from __future__ import annotations

from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import inspect
import sys
from types import ModuleType
from typing import Callable, ClassVar

from qtpy.QtCore import QPointF, Qt
from qtpy.QtGui import QAction, QKeySequence
from qtpy.QtWidgets import QDockWidget, QWidget

from taskgraph.core.model import Backdrop, Connection, ProcessNode
from taskgraph.core.registry import create_node

PLUGIN_ENTRYPOINT = "register_taskgraph_plugin"
PLUGIN_CLASS = "Plugin"
_LOADED_GUI_PLUGINS: dict[Path, ModuleType] = {}
_LOADED_GUI_PLUGIN_INSTANCES: dict[Path, "TaskGraphGuiPlugin"] = {}


class TaskGraphPluginApiError(RuntimeError):
    """Raised when a plugin uses the public API incorrectly."""


class TaskGraphGuiPlugin:
    """Base class for OOP-style GUI plugins.

    Subclasses should implement ``setup()`` and register commands, menus, docks,
    or other UI integration from there. Command callbacks should be regular
    instance methods, which keeps plugin code testable and avoids nested
    function entrypoints.
    """

    plugin_id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    version: ClassVar[str] = "0.1.0"

    def __init__(self, api: "TaskGraphPluginApi"):
        self.api = api

    @property
    def commands(self) -> "TaskGraphCommandApi":
        return self.api.commands

    @property
    def ui(self) -> "TaskGraphUiApi":
        return self.api.ui

    @property
    def graph(self) -> "TaskGraphGraphApi":
        return self.api.graph

    def setup(self) -> None:
        """Register plugin commands, menus, docks, or event hooks."""


class TaskGraphCommand:
    """Registered plugin command that can be exposed in menus or shortcuts."""

    def __init__(
        self,
        command_id: str,
        label: str,
        callback: Callable,
        shortcut: str | QKeySequence | None = None,
    ):
        self.id = command_id
        self.label = label
        self.callback = callback
        self.shortcut = shortcut


class TaskGraphCommandApi:
    """Command registry for plugin-owned actions."""

    def __init__(self, root: "TaskGraphPluginApi"):
        self.root = root
        self._commands: dict[str, TaskGraphCommand] = {}

    def register(
        self,
        command_id: str,
        label: str,
        callback: Callable,
        shortcut: str | QKeySequence | None = None,
    ) -> TaskGraphCommand:
        if command_id in self._commands:
            raise TaskGraphPluginApiError(
                f"Plugin command is already registered: {command_id}"
            )
        command = TaskGraphCommand(command_id, label, callback, shortcut)
        self._commands[command_id] = command
        return command

    def get(self, command_id: str) -> TaskGraphCommand:
        try:
            return self._commands[command_id]
        except KeyError as exc:
            raise TaskGraphPluginApiError(
                f"Plugin command is not registered: {command_id}"
            ) from exc

    def trigger(self, command_id: str) -> None:
        command = self.get(command_id)
        self.root._trigger_callback(command.callback, False)


class TaskGraphMenuApi:
    """Menu helpers exposed to GUI plugins."""

    def __init__(self, root: "TaskGraphPluginApi"):
        self.root = root

    def add_action(
        self,
        menu: str,
        label: str,
        callback: Callable,
        shortcut: str | QKeySequence | None = None,
    ) -> QAction:
        action = QAction(label, self.root.window)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            self.root.window.addAction(action)
        action.triggered.connect(
            lambda checked=False: self.root._trigger_callback(callback, checked)
        )
        qt_menu = self.root.window.menu_for_plugin(menu)
        qt_menu.addAction(action)
        self.root.window.plugin_actions.append(action)
        return action

    def add_command(self, menu: str, command_id: str) -> QAction:
        command = self.root.commands.get(command_id)
        return self.add_action(
            menu,
            command.label,
            command.callback,
            command.shortcut,
        )


class TaskGraphDockApi:
    """Dock panel helpers exposed to GUI plugins."""

    def __init__(self, root: "TaskGraphPluginApi"):
        self.root = root

    def add(
        self,
        title: str,
        widget: QWidget,
        area: Qt.DockWidgetArea = Qt.RightDockWidgetArea,
    ) -> QDockWidget:
        return self.root.window.add_plugin_dock(title, widget, area)


class TaskGraphStatusApi:
    """Status-bar helpers exposed to GUI plugins."""

    def __init__(self, root: "TaskGraphPluginApi"):
        self.root = root

    def show_message(self, message: str, timeout_ms: int = 6000) -> None:
        self.root.window.statusBar().showMessage(message, timeout_ms)


class TaskGraphUiApi:
    """GUI-specific plugin API namespace."""

    def __init__(self, root: "TaskGraphPluginApi"):
        self.menus = TaskGraphMenuApi(root)
        self.docks = TaskGraphDockApi(root)
        self.status = TaskGraphStatusApi(root)


class TaskGraphGraphApi:
    """Graph authoring API namespace for plugins."""

    def __init__(self, root: "TaskGraphPluginApi"):
        self.root = root

    @property
    def model(self):
        return self.root.window.scene.graph

    def create_node(
        self,
        type_id: str,
        values: dict | None = None,
        name: str | None = None,
        position: tuple[float, float] = (0, 0),
        disabled: bool = False,
    ) -> ProcessNode:
        node = create_node(
            type_id,
            values=values,
            disabled=disabled,
            name=name,
        )
        self.root.scene.add_process_node(node, QPointF(position[0], position[1]))
        return node

    def connect_dependency(
        self,
        source: ProcessNode | str,
        target: ProcessNode | str,
    ) -> Connection:
        source_node = self._node(source)
        target_node = self._node(target)
        connection = Connection(
            source_node.id,
            source_node.dependency_output.name,
            target_node.id,
            target_node.dependency_input.name,
            "dependency",
        )
        self._add_connection(connection)
        return connection

    def connect_attribute(
        self,
        source: ProcessNode | str,
        source_port: str,
        target: ProcessNode | str,
        target_port: str,
    ) -> Connection:
        source_node = self._node(source)
        target_node = self._node(target)
        connection = Connection(
            source_node.id,
            source_port,
            target_node.id,
            target_port,
            "attribute",
        )
        self._add_connection(connection)
        return connection

    def add_backdrop(
        self,
        title: str = "Notes",
        note: str = "",
        color: str = "#168c9c",
        position: tuple[float, float] = (0, 0),
        size: tuple[float, float] = (480, 300),
    ) -> Backdrop:
        backdrop = Backdrop(
            title=title,
            note=note,
            color=color,
            position=position,
            size=size,
        )
        self.model.add_backdrop(backdrop)
        self.root.scene.rebuild()
        self.root.scene.graph_changed.emit()
        return backdrop

    def selected_nodes(self) -> list[ProcessNode]:
        from taskgraph.ui.items import NodeItem

        return [
            item.node for item in self.root.scene.selectedItems()
            if isinstance(item, NodeItem)
        ]

    def has_dependency_path(
        self,
        source: ProcessNode | str,
        target: ProcessNode | str,
    ) -> bool:
        source_id = source.id if isinstance(source, ProcessNode) else source
        target_id = target.id if isinstance(target, ProcessNode) else target
        downstream: dict[str, list[str]] = {}
        for connection in self.model.connections:
            if connection.kind != "dependency":
                continue
            downstream.setdefault(connection.source_node, []).append(
                connection.target_node
            )

        pending = [source_id]
        visited = set()
        while pending:
            current = pending.pop()
            if current == target_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(downstream.get(current, ()))
        return False

    def __getattr__(self, name: str):
        """Compatibility access to the underlying graph model.

        Existing plugins that used ``api.graph.nodes`` still work. New plugins
        should prefer ``api.graph.model`` when they need direct model access.
        """
        return getattr(self.model, name)

    def _add_connection(self, connection: Connection) -> None:
        self.model.connect(connection)
        self.root.scene.rebuild()
        self.root.scene.graph_changed.emit()

    def _node(self, node: ProcessNode | str) -> ProcessNode:
        if isinstance(node, ProcessNode):
            return node
        return self.model.nodes[node]


class TaskGraphPluginApi:
    """Root plugin API passed to register_taskgraph_plugin(plugin)."""

    def __init__(self, window, plugin_path: Path):
        self.window = window
        self.plugin_path = plugin_path
        self.commands = TaskGraphCommandApi(self)
        self.ui = TaskGraphUiApi(self)
        self.graph = TaskGraphGraphApi(self)

    @property
    def scene(self):
        return self.window.scene

    @property
    def console(self):
        return self.window.console

    def add_menu_action(
        self,
        menu: str,
        text: str,
        callback: Callable,
        shortcut: str | QKeySequence | None = None,
    ) -> QAction:
        """Compatibility alias for api.ui.menus.add_action(...)."""
        return self.ui.menus.add_action(menu, text, callback, shortcut)

    def add_dock(
        self,
        title: str,
        widget: QWidget,
        area: Qt.DockWidgetArea = Qt.RightDockWidgetArea,
    ) -> QDockWidget:
        """Compatibility alias for api.ui.docks.add(...)."""
        return self.ui.docks.add(title, widget, area)

    def create_node(
        self,
        type_id: str,
        values: dict | None = None,
        name: str | None = None,
        position: tuple[float, float] = (0, 0),
        disabled: bool = False,
    ) -> ProcessNode:
        """Compatibility alias for api.graph.create_node(...)."""
        return self.graph.create_node(
            type_id,
            values=values,
            name=name,
            position=position,
            disabled=disabled,
        )

    def connect_dependency(
        self,
        source: ProcessNode | str,
        target: ProcessNode | str,
    ) -> Connection:
        """Compatibility alias for api.graph.connect_dependency(...)."""
        return self.graph.connect_dependency(source, target)

    def connect_attribute(
        self,
        source: ProcessNode | str,
        source_port: str,
        target: ProcessNode | str,
        target_port: str,
    ) -> Connection:
        """Compatibility alias for api.graph.connect_attribute(...)."""
        return self.graph.connect_attribute(source, source_port, target, target_port)

    def add_backdrop(
        self,
        title: str = "Notes",
        note: str = "",
        color: str = "#168c9c",
        position: tuple[float, float] = (0, 0),
        size: tuple[float, float] = (480, 300),
    ) -> Backdrop:
        """Compatibility alias for api.graph.add_backdrop(...)."""
        return self.graph.add_backdrop(title, note, color, position, size)

    def _trigger_callback(self, callback: Callable, checked: bool) -> None:
        signature = inspect.signature(callback)
        if len(signature.parameters) == 0:
            callback()
        else:
            callback(checked)


def load_gui_plugin_directory(directory: str | Path, window) -> list[Path]:
    """Load GUI plugins from a directory.

    Preferred plugin modules define ``class Plugin(TaskGraphGuiPlugin)``.
    Legacy modules defining ``register_taskgraph_plugin(api)`` are still
    supported for compatibility.
    """
    location = Path(directory).expanduser().resolve()
    if not location.is_dir():
        raise ValueError(f"GUI plugin location does not exist: {location}")

    loaded = []
    for path in sorted(location.glob("*.py")):
        if path.name.startswith("_") or path in _LOADED_GUI_PLUGINS:
            continue
        module = _load_plugin_module(path, location)
        api = TaskGraphPluginApi(window, path)
        plugin = _create_plugin_instance(module, api, path)
        entrypoint = getattr(module, PLUGIN_ENTRYPOINT, None)
        if plugin is None and entrypoint is None:
            continue
        if plugin is None and not callable(entrypoint):
            raise TypeError(f"{path} defines non-callable {PLUGIN_ENTRYPOINT}")
        try:
            if plugin is not None:
                plugin.setup()
                _LOADED_GUI_PLUGIN_INSTANCES[path] = plugin
            else:
                entrypoint(api)
        except Exception:
            _LOADED_GUI_PLUGINS.pop(path, None)
            _LOADED_GUI_PLUGIN_INSTANCES.pop(path, None)
            sys.modules.pop(module.__name__, None)
            raise
        _LOADED_GUI_PLUGINS[path] = module
        loaded.append(path)
    return loaded


def _create_plugin_instance(
    module: ModuleType,
    api: TaskGraphPluginApi,
    path: Path,
) -> TaskGraphGuiPlugin | None:
    plugin_class = getattr(module, PLUGIN_CLASS, None)
    if plugin_class is None:
        return None
    if not inspect.isclass(plugin_class):
        raise TypeError(f"{path} defines non-class {PLUGIN_CLASS}")
    if not issubclass(plugin_class, TaskGraphGuiPlugin):
        raise TypeError(
            f"{path} {PLUGIN_CLASS} must inherit from TaskGraphGuiPlugin"
        )
    return plugin_class(api)


def _load_plugin_module(path: Path, location: Path) -> ModuleType:
    module_name = (
        "_taskgraph_gui_plugin_"
        + sha256(str(path).encode("utf-8")).hexdigest()[:20]
    )
    spec = spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise ImportError(f"Could not load GUI plugin module: {path}")
    module = module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(location))
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    finally:
        try:
            sys.path.remove(str(location))
        except ValueError:
            pass
    return module
