from __future__ import annotations

from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import inspect
import sys
from types import ModuleType
from typing import Callable

from qtpy.QtCore import QPointF, Qt
from qtpy.QtGui import QAction, QKeySequence
from qtpy.QtWidgets import QDockWidget, QWidget

from taskgraph.core.model import Backdrop, Connection, ProcessNode
from taskgraph.core.registry import create_node

PLUGIN_ENTRYPOINT = "register_taskgraph_plugin"
_LOADED_GUI_PLUGINS: dict[Path, ModuleType] = {}


class TaskGraphPluginApi:
    """Small GUI-facing API for external TaskGraph plugins."""

    def __init__(self, window, plugin_path: Path):
        self.window = window
        self.plugin_path = plugin_path

    @property
    def scene(self):
        return self.window.scene

    @property
    def graph(self):
        return self.window.scene.graph

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
        action = QAction(text, self.window)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
            self.window.addAction(action)
        action.triggered.connect(
            lambda checked=False: self._trigger_callback(callback, checked)
        )
        qt_menu = self.window.menu_for_plugin(menu)
        qt_menu.addAction(action)
        self.window.plugin_actions.append(action)
        return action

    def add_dock(
        self,
        title: str,
        widget: QWidget,
        area: Qt.DockWidgetArea = Qt.RightDockWidgetArea,
    ) -> QDockWidget:
        dock = self.window.add_plugin_dock(title, widget, area)
        return dock

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
        self.scene.add_process_node(node, QPointF(position[0], position[1]))
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
        self.graph.add_backdrop(backdrop)
        self.scene.rebuild()
        self.scene.graph_changed.emit()
        return backdrop

    def _add_connection(self, connection: Connection) -> None:
        self.graph.connect(connection)
        self.scene.rebuild()
        self.scene.graph_changed.emit()

    def _node(self, node: ProcessNode | str) -> ProcessNode:
        if isinstance(node, ProcessNode):
            return node
        return self.graph.nodes[node]

    def _trigger_callback(self, callback: Callable, checked: bool) -> None:
        signature = inspect.signature(callback)
        if len(signature.parameters) == 0:
            callback()
        else:
            callback(checked)


def load_gui_plugin_directory(directory: str | Path, window) -> list[Path]:
    """Load GUI plugins from a directory and call register_taskgraph_plugin(api)."""
    location = Path(directory).expanduser().resolve()
    if not location.is_dir():
        raise ValueError(f"GUI plugin location does not exist: {location}")

    loaded = []
    for path in sorted(location.glob("*.py")):
        if path.name.startswith("_") or path in _LOADED_GUI_PLUGINS:
            continue
        module = _load_plugin_module(path, location)
        entrypoint = getattr(module, PLUGIN_ENTRYPOINT, None)
        if entrypoint is None:
            continue
        if not callable(entrypoint):
            raise TypeError(f"{path} defines non-callable {PLUGIN_ENTRYPOINT}")
        try:
            entrypoint(TaskGraphPluginApi(window, path))
        except Exception:
            _LOADED_GUI_PLUGINS.pop(path, None)
            sys.modules.pop(module.__name__, None)
            raise
        _LOADED_GUI_PLUGINS[path] = module
        loaded.append(path)
    return loaded


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
