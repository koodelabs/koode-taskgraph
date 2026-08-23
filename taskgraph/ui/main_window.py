from __future__ import annotations

from pathlib import Path
from threading import Event

from qtpy.QtCore import (
    QByteArray, QMimeData, QObject, QPointF, QSettings, QThread, Qt, Signal, Slot,
)
from qtpy.QtGui import QAction, QActionGroup, QDrag, QKeySequence, QShortcut
from qtpy.QtWidgets import (
    QAbstractItemView, QDockWidget, QFileDialog, QMainWindow, QMessageBox,
    QLineEdit, QPlainTextEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from taskgraph.core.executor import (
    VALID_WORKER_COUNTS,
    GraphExecutionCancelled,
    GraphExecutionError,
    execute_graph,
)
from taskgraph.core.model import Graph
from taskgraph.core.registry import (
    create_node,
    load_custom_node_directory,
    nodes_by_category,
)
from taskgraph.core.serialization import load_graph, save_graph
from taskgraph.ui.plugins import load_gui_plugin_directory
from taskgraph.ui.properties import PropertyEditor
from taskgraph.ui.scene import GraphScene, GraphView
from taskgraph.ui.theme import APP_STYLESHEET


class GraphExecutionWorker(QObject):
    event = Signal(str)
    node_state = Signal(str, str)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal(str)

    def __init__(self, graph, worker_count):
        super().__init__()
        self.graph = graph
        self.worker_count = worker_count
        self.cancel_event = Event()

    def request_cancel(self) -> None:
        self.cancel_event.set()

    @Slot()
    def run(self) -> None:
        try:
            result = execute_graph(
                self.graph,
                self.event.emit,
                max_workers=self.worker_count,
                on_node_state=self.node_state.emit,
                cancel_event=self.cancel_event,
            )
        except GraphExecutionCancelled as exc:
            self.cancelled.emit(str(exc))
        except GraphExecutionError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:
            self.failed.emit(f"Unexpected execution error: {exc}")
        else:
            self.completed.emit(result)


class NodePaletteTree(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def startDrag(self, supported_actions) -> None:
        item = self.currentItem()
        type_id = item.data(0, Qt.UserRole) if item else None
        if not type_id:
            return
        mime = QMimeData()
        mime.setData("application/x-taskgraph-node", QByteArray(type_id.encode()))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class NodePalette(QWidget):
    itemDoubleClicked = Signal(object, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search nodes...")
        self.tree = NodePaletteTree()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(self.search)
        layout.addWidget(self.tree, 1)
        self.search.textChanged.connect(self.reload)
        self.tree.itemDoubleClicked.connect(self.itemDoubleClicked.emit)
        self.reload()

    def reload(self) -> None:
        query = self.search.text().strip().lower()
        self.tree.clear()
        for category, classes in nodes_by_category().items():
            matches_category = query and query in category.lower()
            children = [
                cls for cls in classes
                if (
                    not query
                    or matches_category
                    or query in cls.title.lower()
                    or query in cls.type_id.lower()
                )
            ]
            if not children:
                continue
            parent = QTreeWidgetItem([category])
            parent.setFlags(parent.flags() & ~Qt.ItemIsDragEnabled)
            self.tree.addTopLevelItem(parent)
            for cls in children:
                child = QTreeWidgetItem([cls.title])
                child.setData(0, Qt.UserRole, cls.type_id)
                child.setToolTip(0, cls.type_id)
                parent.addChild(child)
            parent.setExpanded(True)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TaskGraph — Untitled")
        self.resize(1400, 850)
        self.setStyleSheet(APP_STYLESHEET)
        self.current_path: Path | None = None
        self.dirty = False
        self.execution_thread: QThread | None = None
        self.execution_worker: GraphExecutionWorker | None = None
        self.plugin_actions: list[QAction] = []
        self.plugin_menus = []
        self.plugin_docks: list[QDockWidget] = []
        saved_workers = QSettings().value("execution/max_workers", 4, type=int)
        self.worker_count = min(
            VALID_WORKER_COUNTS,
            key=lambda count: abs(count - saved_workers),
        )

        self.scene = GraphScene()
        self.view = GraphView(self.scene)
        self.setCentralWidget(self.view)
        self.palette = NodePalette()
        self.properties = PropertyEditor()
        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(1000)
        self.console.setContextMenuPolicy(Qt.CustomContextMenu)

        self.docks = {
            "Nodes": self._add_dock("Nodes", self.palette, Qt.LeftDockWidgetArea),
            "Properties": self._add_dock("Properties", self.properties, Qt.RightDockWidgetArea),
            "Execution": self._add_dock("Execution", self.console, Qt.BottomDockWidgetArea),
        }
        self._create_actions()

        self.palette.itemDoubleClicked.connect(self._palette_double_clicked)
        self.view.node_type_dropped.connect(self.add_node)
        self.scene.node_selected.connect(self.properties.set_node)
        self.scene.graph_changed.connect(self._mark_dirty)
        self.properties.property_changed.connect(self._mark_dirty)
        self.properties.property_changed.connect(self.scene.refresh_nodes)
        self.statusBar().showMessage("Drag nodes onto the canvas. Connect output ports to input ports.")

    def _add_dock(self, title, widget, area) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"{title.lower()}Dock")
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _create_actions(self) -> None:
        self.actions: dict[str, QAction] = {}

        def make_action(key, text, shortcut, callback):
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(callback)
            self.addAction(action)
            self.actions[key] = action
            return action

        make_action("new", "&New", QKeySequence.New, self.new_graph)
        make_action("open", "&Open…", QKeySequence.Open, self.open_graph)
        make_action("save", "&Save", QKeySequence.Save, self.save_graph)
        make_action("save_as", "Save &As…", QKeySequence.SaveAs, self.save_graph_as)
        make_action("quit", "&Quit TaskGraph", QKeySequence.Quit, self.close)
        make_action("run", "&Run Graph", "Ctrl+R", self.run_graph)
        cancel = make_action(
            "cancel", "&Cancel Execution", QKeySequence(Qt.Key_Escape),
            self.cancel_execution,
        )
        cancel.setEnabled(False)
        make_action(
            "clear_log", "Clear Execution &Log", None, self.console.clear,
        )
        make_action(
            "add_node_location", "Add Custom Node &Location…", None,
            self.add_custom_node_location,
        )
        make_action(
            "add_gui_plugin_location", "Add GUI Plugin &Location…", None,
            self.add_gui_plugin_location,
        )
        make_action("frame", "&Frame All", "F", self.frame_all)
        auto_arrange = make_action(
            "auto_arrange", "&Auto Arrange Nodes", "Shift+A",
            self.auto_arrange_nodes,
        )
        # A single-letter shortcut belongs to the canvas, not property text
        # fields where Shift+A should continue to type an uppercase letter.
        self.removeAction(auto_arrange)
        auto_arrange.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        self.view.addAction(auto_arrange)
        make_action(
            "add_backdrop", "Add &Backdrop", None, self.add_backdrop,
        )
        make_action(
            "toggle_disabled", "Toggle &Disabled", None,
            self.scene.toggle_selected_disabled,
        )
        copy_nodes = QAction("&Copy Nodes", self.view)
        copy_nodes.setShortcut(QKeySequence.Copy)
        copy_nodes.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        copy_nodes.triggered.connect(self.scene.copy_selected)
        self.view.addAction(copy_nodes)
        self.actions["copy"] = copy_nodes
        paste_nodes = QAction("&Paste Nodes", self.view)
        paste_nodes.setShortcut(QKeySequence.Paste)
        paste_nodes.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        paste_nodes.triggered.connect(self.scene.paste_clipboard)
        self.view.addAction(paste_nodes)
        self.actions["paste"] = paste_nodes

        delete = make_action("delete", "Delete Selected", None, self.scene.delete_selected)
        # macOS keyboards normally expose Backspace as the key labelled
        # "delete", while Windows/Linux commonly use forward Delete.
        delete.setShortcuts([
            QKeySequence(Qt.Key_Backspace),
            QKeySequence(Qt.Key_Delete),
        ])
        delete.setShortcutContext(Qt.ApplicationShortcut)

        self.menus = {}
        file_menu = self.menuBar().addMenu("&File")
        self.menus["file"] = file_menu
        file_menu.addActions([
            self.actions["new"], self.actions["open"],
        ])
        file_menu.addSeparator()
        file_menu.addActions([
            self.actions["save"], self.actions["save_as"],
        ])
        file_menu.addSeparator()
        file_menu.addAction(self.actions["quit"])

        edit_menu = self.menuBar().addMenu("&Edit")
        self.menus["edit"] = edit_menu
        edit_menu.addActions([self.actions["copy"], self.actions["paste"]])
        edit_menu.addSeparator()
        edit_menu.addAction(self.actions["delete"])
        edit_menu.addAction(self.actions["toggle_disabled"])

        # Scope the single-letter shortcut to the canvas so typing in the
        # property editor can never disable a node accidentally.
        self.disable_shortcut = QShortcut(QKeySequence("D"), self.view)
        self.disable_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.disable_shortcut.activated.connect(self.scene.toggle_selected_disabled)

        nodes_menu = self.menuBar().addMenu("&Nodes")
        self.menus["nodes"] = nodes_menu
        nodes_menu.addAction(self.actions["add_node_location"])

        plugins_menu = self.menuBar().addMenu("&Plugins")
        self.menus["plugins"] = plugins_menu
        plugins_menu.addAction(self.actions["add_gui_plugin_location"])

        graph_menu = self.menuBar().addMenu("&Graph")
        self.menus["graph"] = graph_menu
        graph_menu.addAction(self.actions["run"])
        graph_menu.addAction(self.actions["cancel"])
        graph_menu.addAction(self.actions["clear_log"])
        workers_menu = graph_menu.addMenu("&Worker Count")
        self.menus["workers"] = workers_menu
        self.worker_actions = QActionGroup(self)
        self.worker_actions.setExclusive(True)
        for count in VALID_WORKER_COUNTS:
            label = f"{count} Worker" if count == 1 else f"{count} Workers"
            action = QAction(label, self, checkable=True)
            action.setChecked(count == self.worker_count)
            action.triggered.connect(
                lambda checked=False, value=count: self.set_worker_count(value)
            )
            self.worker_actions.addAction(action)
            workers_menu.addAction(action)
        graph_menu.addSeparator()
        graph_menu.addAction(self.actions["add_backdrop"])
        graph_menu.addAction(self.actions["auto_arrange"])
        graph_menu.addAction(self.actions["frame"])

        view_menu = self.menuBar().addMenu("&View")
        self.menus["view"] = view_menu
        for dock in self.docks.values():
            # Qt keeps this check state synchronized when a dock is closed,
            # hidden, floated, or restored.
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        show_all = QAction("Show All Panels", self)
        self.actions["show_all_panels"] = show_all
        show_all.triggered.connect(self.show_all_panels)
        view_menu.addAction(show_all)
        self.console.customContextMenuRequested.connect(
            self._show_console_context_menu
        )

    def menu_for_plugin(self, name: str):
        key = self._plugin_menu_key(name)
        if key in self.menus:
            return self.menus[key]
        menu = self.menuBar().addMenu(name)
        self.menus[key] = menu
        return menu

    def add_plugin_dock(
        self,
        title: str,
        widget,
        area: Qt.DockWidgetArea = Qt.RightDockWidgetArea,
    ) -> QDockWidget:
        dock = self._add_dock(title, widget, area)
        self.plugin_docks.append(dock)
        self.menus["view"].insertAction(
            self.actions["show_all_panels"],
            dock.toggleViewAction(),
        )
        return dock

    @staticmethod
    def _plugin_menu_key(name: str) -> str:
        return name.replace("&", "").strip().lower()

    def _show_console_context_menu(self, position) -> None:
        menu = self.console.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction(self.actions["clear_log"])
        menu.exec(self.console.viewport().mapToGlobal(position))
        menu.deleteLater()

    def show_all_panels(self) -> None:
        for dock in self.docks.values():
            dock.show()
            dock.raise_()

    def add_custom_node_location(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Add Custom Node Location"
        )
        if not directory:
            return
        try:
            loaded = load_custom_node_directory(directory)
        except Exception as exc:
            QMessageBox.critical(
                self, "Custom node loading failed", f"{directory}\n\n{exc}"
            )
            return
        settings = QSettings()
        locations = settings.value("nodes/custom_locations", [])
        if isinstance(locations, str):
            locations = [locations]
        if directory not in locations:
            locations.append(directory)
            settings.setValue("nodes/custom_locations", locations)
        self.palette.reload()
        self.statusBar().showMessage(
            f"Loaded {len(loaded)} custom node module(s) from {directory}",
            6000,
        )

    def add_gui_plugin_location(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Add GUI Plugin Location"
        )
        if not directory:
            return
        try:
            loaded = load_gui_plugin_directory(directory, self)
        except Exception as exc:
            QMessageBox.critical(
                self, "GUI plugin loading failed", f"{directory}\n\n{exc}"
            )
            return
        self.palette.reload()
        self.statusBar().showMessage(
            (
                f"Loaded {len(loaded)} GUI plugin module(s) from {directory} "
                "for this session"
            ),
            6000,
        )

    def set_worker_count(self, count: int) -> None:
        self.worker_count = min(
            VALID_WORKER_COUNTS,
            key=lambda valid: abs(valid - count),
        )
        QSettings().setValue("execution/max_workers", self.worker_count)
        self.statusBar().showMessage(
            f"Graph execution will use {self.worker_count} worker(s)", 4000
        )

    def _palette_double_clicked(self, item, column) -> None:
        type_id = item.data(0, Qt.UserRole)
        if type_id:
            center = self.view.mapToScene(self.view.viewport().rect().center())
            self.add_node(type_id, center)

    def add_node(self, type_id: str, position: QPointF) -> None:
        try:
            self.scene.add_process_node(create_node(type_id), position)
        except Exception as exc:
            QMessageBox.warning(self, "Could not add node", str(exc))

    def add_backdrop(self) -> None:
        position = self.view.mapToScene(self.view.viewport().rect().center())
        self.scene.add_backdrop(position - QPointF(240, 150))

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._update_title()

    def _update_title(self) -> None:
        name = self.current_path.name if self.current_path else "Untitled"
        self.setWindowTitle(f"TaskGraph — {name}{' *' if self.dirty else ''}")

    def _confirm_discard(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(
            self, "Unsaved graph", "Discard unsaved changes?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def new_graph(self) -> None:
        if not self._confirm_discard():
            return
        self.scene.set_graph(Graph())
        self.current_path = None
        self.dirty = False
        self.console.clear()
        self._update_title()

    def open_graph(self) -> None:
        if not self._confirm_discard():
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Open graph", "", "TaskGraph (*.taskgraph *.json)")
        if not filename:
            return
        try:
            self.scene.set_graph(load_graph(filename))
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        self.current_path = Path(filename)
        self.dirty = False
        self._update_title()
        self.frame_all()

    def save_graph(self) -> bool:
        if not self.current_path:
            return self.save_graph_as()
        try:
            save_graph(self.scene.graph, self.current_path)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self.dirty = False
        self._update_title()
        self.statusBar().showMessage(f"Saved {self.current_path}", 4000)
        return True

    def save_graph_as(self) -> bool:
        filename, _ = QFileDialog.getSaveFileName(self, "Save graph", "", "TaskGraph (*.taskgraph)")
        if not filename:
            return False
        path = Path(filename)
        if not path.suffix:
            path = path.with_suffix(".taskgraph")
        self.current_path = path
        return self.save_graph()

    def run_graph(self) -> None:
        if self.execution_thread and self.execution_thread.isRunning():
            return
        self.console.clear()
        self.console.appendPlainText("Running graph…")
        self.scene.reset_execution_states()
        self.actions["run"].setEnabled(False)
        self.actions["cancel"].setEnabled(True)
        self.view.setInteractive(False)
        self.palette.setEnabled(False)
        self.properties.setEnabled(False)
        for key in (
            "new", "open", "paste", "delete", "toggle_disabled",
            "auto_arrange", "add_backdrop",
        ):
            self.actions[key].setEnabled(False)

        thread = QThread(self)
        worker = GraphExecutionWorker(self.scene.graph, self.worker_count)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.event.connect(self.console.appendPlainText)
        worker.node_state.connect(self._set_node_execution_state)
        worker.completed.connect(self._execution_completed)
        worker.failed.connect(self._execution_failed)
        worker.cancelled.connect(self._execution_cancelled)
        worker.completed.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.completed.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        thread.finished.connect(self._execution_thread_finished)
        self.execution_thread = thread
        self.execution_worker = worker
        self.statusBar().showMessage(
            f"Running graph with {self.worker_count} worker(s)…"
        )
        thread.start()

    def _execution_completed(self, result) -> None:
        self.console.appendPlainText(f"\nCompleted {len(result.order)} node(s).")
        self.statusBar().showMessage("Graph execution completed", 5000)

    def _execution_failed(self, message: str) -> None:
        self.console.appendPlainText(f"\nERROR: {message}")
        self.statusBar().showMessage("Graph execution failed", 5000)

    def _execution_cancelled(self, message: str) -> None:
        self.console.appendPlainText(f"\nCANCELLED: {message}")
        self.statusBar().showMessage("Graph execution cancelled", 5000)

    def cancel_execution(self) -> None:
        if not self.execution_worker:
            return
        self.actions["cancel"].setEnabled(False)
        self.execution_worker.request_cancel()
        self.statusBar().showMessage("Cancelling all running processes…")

    def _execution_thread_finished(self) -> None:
        if self.execution_thread:
            self.execution_thread.deleteLater()
        self.execution_thread = None
        self.execution_worker = None
        self.actions["run"].setEnabled(True)
        self.actions["cancel"].setEnabled(False)
        self.view.setInteractive(True)
        self.palette.setEnabled(True)
        self.properties.setEnabled(True)
        for key in (
            "new", "open", "paste", "delete", "toggle_disabled",
            "auto_arrange", "add_backdrop",
        ):
            self.actions[key].setEnabled(True)

    def _set_node_execution_state(self, node_id: str, state: str) -> None:
        self.scene.set_execution_state(node_id, state)
        if state == "running":
            # Render immediately so even the final node's running state reaches
            # the viewport before a very fast completion signal is handled.
            self.view.viewport().repaint()

    def frame_all(self) -> None:
        rect = self.scene.itemsBoundingRect()
        if rect.isValid() and not rect.isEmpty():
            self.view.fitInView(rect.adjusted(-80, -80, 80, 80), Qt.KeepAspectRatio)

    def auto_arrange_nodes(self) -> None:
        self.scene.auto_arrange()
        self.frame_all()
        self.statusBar().showMessage("Nodes arranged by dependency order", 4000)

    def closeEvent(self, event) -> None:
        if self.execution_thread and self.execution_thread.isRunning():
            self.statusBar().showMessage(
                "Wait for graph execution to finish before closing", 5000
            )
            event.ignore()
            return
        event.accept() if self._confirm_discard() else event.ignore()
