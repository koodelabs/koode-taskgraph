"""GUI plugin API and loader."""

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
from qtpy.QtWidgets import QDockWidget, QMenu, QWidget

from taskgraph.core.model import Backdrop, Connection, ProcessNode
from taskgraph.core.registry import create_node

PLUGIN_CLASS = "Plugin"
_LOADED_GUI_PLUGINS: dict[Path, ModuleType] = {}
_LOADED_GUI_PLUGIN_INSTANCES: dict[Path, "TaskGraphGuiPlugin"] = {}


class TaskGraphPluginApiError(RuntimeError):
    """Raised when a plugin uses the public API incorrectly.

    Plugin authors should treat this as a recoverable API usage error.
    """


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
        """Store the API object passed by the plugin loader.

        Args:
            api: Root plugin API for the loaded plugin module.

        Returns:
            None.
        """
        self.api = api

    @property
    def commands(self) -> "TaskGraphCommandApi":
        """Return the command registration API.

        Returns:
            TaskGraphCommandApi: API used to register and trigger commands.
        """
        return self.api.commands

    @property
    def ui(self) -> "TaskGraphUiApi":
        """Return the UI extension API.

        Returns:
            TaskGraphUiApi: API used to add menus, docks, and status messages.
        """
        return self.api.ui

    @property
    def graph(self) -> "TaskGraphGraphApi":
        """Return the graph authoring API.

        Returns:
            TaskGraphGraphApi: API used to create nodes and connections.
        """
        return self.api.graph

    def setup(self) -> None:
        """Register plugin commands, menus, docks, or event hooks.

        Returns:
            None.
        """


class TaskGraphCommand:
    """Registered plugin command that can be exposed in menus or shortcuts.

    Attributes:
        id: Plugin-local command id.
        label: User-facing command label.
        callback: Callable executed when the command runs.
        shortcut: Optional keyboard shortcut.
    """

    def __init__(
        self,
        command_id: str,
        label: str,
        callback: Callable,
        shortcut: str | QKeySequence | None = None,
    ):
        """Create a command descriptor for a plugin callback.

        Args:
            command_id: Plugin-local command id.
            label: User-facing command label.
            callback: Callable executed when the command runs.
            shortcut: Optional keyboard shortcut.

        Returns:
            None.
        """
        self.id = command_id
        self.label = label
        self.callback = callback
        self.shortcut = shortcut


class TaskGraphCommandApi:
    """Command registry for plugin-owned actions.

    Attributes:
        root: Root API object for the plugin.
    """

    def __init__(self, root: "TaskGraphPluginApi"):
        """Create an empty command registry for one plugin.

        Args:
            root: Root API object for the plugin.

        Returns:
            None.
        """
        self.root = root
        self._commands: dict[str, TaskGraphCommand] = {}

    def register(
        self,
        command_id: str,
        label: str,
        callback: Callable,
        shortcut: str | QKeySequence | None = None,
    ) -> TaskGraphCommand:
        """Register a plugin command by id.

        Args:
            command_id: Plugin-local command id.
            label: User-facing command label.
            callback: Callable executed when the command runs.
            shortcut: Optional keyboard shortcut.

        Returns:
            TaskGraphCommand: Registered command descriptor.

        Raises:
            TaskGraphPluginApiError: If the command id is already registered.
        """
        if command_id in self._commands:
            raise TaskGraphPluginApiError(
                f"Plugin command is already registered: {command_id}"
            )
        command = TaskGraphCommand(command_id, label, callback, shortcut)
        self._commands[command_id] = command
        return command

    def get(self, command_id: str) -> TaskGraphCommand:
        """Return a previously registered plugin command.

        Args:
            command_id: Plugin-local command id.

        Returns:
            TaskGraphCommand: Registered command descriptor.

        Raises:
            TaskGraphPluginApiError: If the command id is unknown.
        """
        try:
            return self._commands[command_id]
        except KeyError as exc:
            raise TaskGraphPluginApiError(
                f"Plugin command is not registered: {command_id}"
            ) from exc

    def trigger(self, command_id: str) -> None:
        """Execute a registered plugin command.

        Args:
            command_id: Plugin-local command id.

        Returns:
            None.

        Raises:
            TaskGraphPluginApiError: If the command id is unknown.
        """
        command = self.get(command_id)
        self.root._trigger_callback(command.callback, False)


class TaskGraphMenuApi:
    """Menu helpers exposed to GUI plugins.

    Attributes:
        root: Root API object for the plugin.
    """

    def __init__(self, root: "TaskGraphPluginApi"):
        """Create menu helpers for one plugin.

        Args:
            root: Root API object for the plugin.

        Returns:
            None.
        """
        self.root = root

    def add_action(
        self,
        menu: str,
        label: str,
        callback: Callable,
        shortcut: str | QKeySequence | None = None,
    ) -> QAction:
        """Create a QAction and insert it into a menu path.

        Args:
            menu: Slash-separated menu path, for example ``"Tools/Build"``.
            label: User-facing action label.
            callback: Callable executed when the action is triggered.
            shortcut: Optional keyboard shortcut.

        Returns:
            QAction: Created Qt action.

        Raises:
            TaskGraphPluginApiError: If the menu path is empty.
        """
        action = QAction(label, self.root.window)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            self.root.window.addAction(action)
        action.triggered.connect(
            lambda checked=False: self.root._trigger_callback(callback, checked)
        )
        qt_menu = self._menu_for_path(menu)
        qt_menu.addAction(action)
        self.root.window.plugin_actions.append(action)
        return action

    def add_command(self, menu: str, command_id: str) -> QAction:
        """Add a registered command to a menu path.

        Args:
            menu: Slash-separated menu path.
            command_id: Plugin-local command id to expose.

        Returns:
            QAction: Created Qt action.

        Raises:
            TaskGraphPluginApiError: If the command id is unknown.
        """
        command = self.root.commands.get(command_id)
        return self.add_action(
            menu,
            command.label,
            command.callback,
            command.shortcut,
        )

    def _menu_for_path(self, menu: str):
        """Return or create a menu/submenu for a slash-separated path.

        Args:
            menu: Slash-separated menu path.

        Returns:
            QMenu: Final menu in the path.

        Raises:
            TaskGraphPluginApiError: If the path is empty.
        """
        parts = [part.strip() for part in menu.split("/") if part.strip()]
        if not parts:
            raise TaskGraphPluginApiError("Plugin menu path cannot be empty")
        current = self.root.window.menu_for_plugin(parts[0])
        path_parts = [parts[0]]
        for part in parts[1:]:
            path_parts.append(part)
            current = self._submenu(current, part, "/".join(path_parts))
        return current

    def _submenu(self, parent_menu, title: str, path: str):
        """Return or create a submenu under a parent QMenu.

        Args:
            parent_menu: Parent Qt menu.
            title: Submenu title.
            path: Full normalized menu path.

        Returns:
            QMenu: Existing or newly created submenu.
        """
        key = self.root.window._plugin_menu_key(path)
        if key in self.root.window.menus:
            return self.root.window.menus[key]
        normalized = title.replace("&", "").strip().lower()
        for action in parent_menu.actions():
            submenu = action.menu()
            if submenu and submenu.title().replace("&", "").strip().lower() == normalized:
                self.root.window.menus[key] = submenu
                return submenu
        submenu = QMenu(title, parent_menu)
        parent_menu.addMenu(submenu)
        self.root.window.menus[key] = submenu
        self.root.window.plugin_menus.append(submenu)
        return submenu


class TaskGraphDockApi:
    """Dock panel helpers exposed to GUI plugins.

    Attributes:
        root: Root API object for the plugin.
    """

    def __init__(self, root: "TaskGraphPluginApi"):
        """Create dock helpers for one plugin.

        Args:
            root: Root API object for the plugin.

        Returns:
            None.
        """
        self.root = root

    def add(
        self,
        title: str,
        widget: QWidget,
        area: Qt.DockWidgetArea = Qt.RightDockWidgetArea,
    ) -> QDockWidget:
        """Add a plugin-owned dock widget to the main window.

        Args:
            title: Dock title shown in the UI.
            widget: Widget placed inside the dock.
            area: Qt dock area where the dock should be inserted.

        Returns:
            QDockWidget: Created dock widget.
        """
        return self.root.window.add_plugin_dock(title, widget, area)


class TaskGraphStatusApi:
    """Status-bar helpers exposed to GUI plugins.

    Attributes:
        root: Root API object for the plugin.
    """

    def __init__(self, root: "TaskGraphPluginApi"):
        """Create status-bar helpers for one plugin.

        Args:
            root: Root API object for the plugin.

        Returns:
            None.
        """
        self.root = root

    def show_message(self, message: str, timeout_ms: int = 6000) -> None:
        """Show a temporary message in the main window status bar.

        Args:
            message: Text to display.
            timeout_ms: Display duration in milliseconds.

        Returns:
            None.
        """
        self.root.window.statusBar().showMessage(message, timeout_ms)


class TaskGraphUiApi:
    """GUI-specific plugin API namespace.

    Attributes:
        menus: Menu helper API.
        docks: Dock helper API.
        status: Status-bar helper API.
    """

    def __init__(self, root: "TaskGraphPluginApi"):
        """Create UI helper namespaces for one plugin.

        Args:
            root: Root API object for the plugin.

        Returns:
            None.
        """
        self.menus = TaskGraphMenuApi(root)
        self.docks = TaskGraphDockApi(root)
        self.status = TaskGraphStatusApi(root)


class TaskGraphGraphApi:
    """Graph authoring API namespace for plugins.

    Attributes:
        root: Root API object for the plugin.
    """

    def __init__(self, root: "TaskGraphPluginApi"):
        """Create graph helpers for one plugin.

        Args:
            root: Root API object for the plugin.

        Returns:
            None.
        """
        self.root = root

    @property
    def model(self):
        """Return the underlying graph model.

        Returns:
            Graph: Current graph model edited by the main window.
        """
        return self.root.window.scene.graph

    def create_node(
        self,
        type_id: str,
        values: dict | None = None,
        name: str | None = None,
        position: tuple[float, float] = (0, 0),
        disabled: bool = False,
    ) -> ProcessNode:
        """Create and draw a node in the current graph.

        Args:
            type_id: Registered node type id.
            values: Optional property values keyed by property name.
            name: Optional user-facing node name.
            position: Scene position as ``(x, y)``.
            disabled: Whether the node should start disabled.

        Returns:
            ProcessNode: Created node model.
        """
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
        """Connect two nodes with dependency/order ports.

        Args:
            source: Source node or source node id.
            target: Target node or target node id.

        Returns:
            Connection: Created dependency connection.

        Raises:
            KeyError: If a provided node id is not in the graph.
        """
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
        """Connect one source output port to one target input port.

        Args:
            source: Source node or source node id.
            source_port: Source output port name.
            target: Target node or target node id.
            target_port: Target input port name.

        Returns:
            Connection: Created attribute connection.

        Raises:
            KeyError: If a provided node id is not in the graph.
        """
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
        """Create a backdrop note region in the current graph.

        Args:
            title: Backdrop title.
            note: Backdrop note text.
            color: Backdrop color string.
            position: Scene position as ``(x, y)``.
            size: Backdrop size as ``(width, height)``.

        Returns:
            Backdrop: Created backdrop model.
        """
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
        """Return process nodes currently selected in the scene.

        Returns:
            list[ProcessNode]: Selected process node models.
        """
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
        """Return whether target is downstream of source by dependencies.

        Args:
            source: Source node or source node id.
            target: Target node or target node id.

        Returns:
            bool: True when a dependency path connects source to target.
        """
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

    def _add_connection(self, connection: Connection) -> None:
        """Add a connection to the model and redraw the scene.

        Args:
            connection: Connection model to add.

        Returns:
            None.
        """
        self.model.connect(connection)
        self.root.scene.rebuild()
        self.root.scene.graph_changed.emit()

    def _node(self, node: ProcessNode | str) -> ProcessNode:
        """Resolve a node object or node id into a node object.

        Args:
            node: Process node object or node id.

        Returns:
            ProcessNode: Resolved node model.

        Raises:
            KeyError: If the node id is not present in the graph.
        """
        if isinstance(node, ProcessNode):
            return node
        return self.model.nodes[node]


class TaskGraphPluginApi:
    """Root plugin API passed to TaskGraphGuiPlugin subclasses.

    Attributes:
        window: Main window receiving plugin changes.
        plugin_path: Filesystem path of the loaded plugin module.
        commands: Command registration API.
        ui: UI extension API.
        graph: Graph authoring API.
    """

    def __init__(self, window, plugin_path: Path):
        """Create the root API object for one loaded plugin file.

        Args:
            window: Main window receiving plugin UI additions.
            plugin_path: Filesystem path of the plugin module.

        Returns:
            None.
        """
        self.window = window
        self.plugin_path = plugin_path
        self.commands = TaskGraphCommandApi(self)
        self.ui = TaskGraphUiApi(self)
        self.graph = TaskGraphGraphApi(self)

    @property
    def scene(self):
        """Return the current graph scene.

        Returns:
            GraphScene: Current graph scene.
        """
        return self.window.scene

    @property
    def console(self):
        """Return the execution console widget.

        Returns:
            QPlainTextEdit: Execution console widget.
        """
        return self.window.console

    def _trigger_callback(self, callback: Callable, checked: bool) -> None:
        """Call plugin callbacks with or without the QAction checked value.

        Args:
            callback: Plugin callback to execute.
            checked: QAction checked state.

        Returns:
            None.
        """
        signature = inspect.signature(callback)
        if len(signature.parameters) == 0:
            callback()
        else:
            callback(checked)


def load_gui_plugin_directory(directory: str | Path, window) -> list[Path]:
    """Load GUI plugins from a directory.

    Args:
        directory: Folder containing GUI plugin ``.py`` files.
        window: Main window that receives plugin extensions.

    Returns:
        list[Path]: Plugin module paths loaded during this call.

    Raises:
        ValueError: If the directory does not exist.
        TypeError: If a plugin module defines an invalid ``Plugin`` class.
        ImportError: If a plugin module cannot be imported.
        Exception: Re-raises errors raised by plugin setup.
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
        if plugin is None:
            continue
        try:
            plugin.setup()
            _LOADED_GUI_PLUGIN_INSTANCES[path] = plugin
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
    """Create a plugin instance from a loaded module if it defines Plugin.

    Args:
        module: Imported plugin module.
        api: Root API object passed to the plugin class.
        path: Filesystem path of the plugin module.

    Returns:
        TaskGraphGuiPlugin | None: Plugin instance, or None if no plugin class exists.

    Raises:
        TypeError: If ``Plugin`` is not a valid ``TaskGraphGuiPlugin`` subclass.
    """
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
    """Import one plugin file under an isolated generated module name.

    Args:
        path: Plugin file to import.
        location: Directory temporarily added to ``sys.path`` for imports.

    Returns:
        ModuleType: Imported plugin module.

    Raises:
        ImportError: If the module spec or loader cannot be created.
        Exception: Re-raises import-time errors from the plugin module.
    """
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
