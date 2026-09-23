"""Graph scene and view classes for editing node graphs in Qt."""

from __future__ import annotations

import json
from collections import defaultdict, deque

from qtpy.QtCore import QPointF, QRectF, Qt, Signal
from qtpy.QtGui import QColor, QPainter, QPen
from qtpy.QtWidgets import QApplication, QGraphicsScene, QGraphicsView

from taskgraph.core.model import Backdrop, Connection, Graph
from taskgraph.core.registry import create_node
from taskgraph.ui.items import BackdropItem, ConnectionItem, NodeItem, PortItem

CLIPBOARD_MIME = "application/x-taskgraph-nodes"


class GraphScene(QGraphicsScene):
    """QGraphicsScene that keeps graphics items synchronized with a Graph.

    Attributes:
        graph: Graph model being edited.
        node_items: Node graphics items keyed by node id.
        connection_items: Graphics items for graph connections.
        execution_states: Current visual execution states keyed by node id.
    """

    node_selected = Signal(object)
    graph_changed = Signal()

    def __init__(self, graph: Graph | None = None, parent=None):
        """Create a scene for an existing graph or a new empty graph.

        Args:
            graph: Optional graph model to display.
            parent: Optional Qt parent object.

        Returns:
            None.
        """
        super().__init__(parent)
        self.setSceneRect(-5000, -5000, 10000, 10000)
        self.graph = graph or Graph()
        self.backdrop_items: dict[str, BackdropItem] = {}
        self.node_items: dict[str, NodeItem] = {}
        self.connection_items: list[ConnectionItem] = []
        self._drag_item: ConnectionItem | None = None
        self._drag_port: PortItem | None = None
        self._paste_offset = 0
        self.execution_states: dict[str, str] = {}
        self.selectionChanged.connect(self._selection_changed)
        self.rebuild()

    def rebuild(self) -> None:
        """Recreate all graphics items from the current graph model.

        Returns:
            None.
        """
        self.clear()
        self.backdrop_items.clear()
        self.node_items.clear()
        self.connection_items.clear()
        for backdrop in self.graph.backdrops.values():
            item = BackdropItem(self, backdrop)
            item.setPos(QPointF(*backdrop.position))
            self.addItem(item)
            self.backdrop_items[backdrop.id] = item
        for node in self.graph.nodes.values():
            item = NodeItem(self, node)
            item.setPos(QPointF(*self.graph.positions.get(node.id, (0, 0))))
            self.addItem(item)
            self.node_items[node.id] = item
        for connection in self.graph.connections:
            item = ConnectionItem(self, connection)
            self.addItem(item)
            self.connection_items.append(item)

    def set_graph(self, graph: Graph) -> None:
        """Replace the current graph model and redraw the scene.

        Args:
            graph: New graph model to display and edit.

        Returns:
            None.
        """
        self.graph = graph
        self.rebuild()
        self.graph_changed.emit()

    def add_process_node(self, node, position: QPointF) -> NodeItem:
        """Add a process node to the graph and scene at a position.

        Args:
            node: Process node model to add.
            position: Scene position where the node should be placed.

        Returns:
            NodeItem: Graphics item created for the node.
        """
        self.graph.add_node(node, (position.x(), position.y()))
        item = NodeItem(self, node)
        item.setPos(position)
        self.addItem(item)
        self.node_items[node.id] = item
        item.setSelected(True)
        self.graph_changed.emit()
        return item

    def add_backdrop(self, position: QPointF) -> BackdropItem:
        """Add a new backdrop to the graph and scene.

        Args:
            position: Scene position where the backdrop should be placed.

        Returns:
            BackdropItem: Graphics item created for the backdrop.
        """
        backdrop = Backdrop(position=(position.x(), position.y()))
        self.graph.add_backdrop(backdrop)
        item = BackdropItem(self, backdrop)
        item.setPos(position)
        self.addItem(item)
        self.backdrop_items[backdrop.id] = item
        self.clearSelection()
        item.setSelected(True)
        self.graph_changed.emit()
        return item

    def node_moved(self, item: NodeItem) -> None:
        """Persist a moved node's position and refresh attached edges.

        Args:
            item: Node graphics item that moved.

        Returns:
            None.
        """
        pos = item.pos()
        self.graph.positions[item.node.id] = (pos.x(), pos.y())
        for edge in self.connection_items:
            if edge.connection and item.node.id in (edge.connection.source_node, edge.connection.target_node):
                edge.refresh()
        self.graph_changed.emit()

    def begin_connection(self, port: PortItem) -> None:
        """Start drawing a temporary connection from a port.

        Args:
            port: Port item where the drag starts.

        Returns:
            None.
        """
        self.cancel_connection()
        self._drag_port = port
        self._drag_item = ConnectionItem(self)
        self.addItem(self._drag_item)
        self._drag_item.set_points(port.scenePos(), port.scenePos())

    def update_connection(self, position: QPointF) -> None:
        """Move the temporary connection endpoint while dragging.

        Args:
            position: Current scene position of the drag cursor.

        Returns:
            None.
        """
        if not self._drag_item or not self._drag_port:
            return
        if self._drag_port.is_output:
            self._drag_item.set_points(self._drag_port.scenePos(), position)
        else:
            self._drag_item.set_points(position, self._drag_port.scenePos())

    def finish_connection(self, position: QPointF) -> None:
        """Create a graph connection when the drag ends on a compatible port.

        Args:
            position: Scene position where the drag ended.

        Returns:
            None.
        """
        start = self._drag_port
        targets = [item for item in self.items(position) if isinstance(item, PortItem)]
        target = next((port for port in targets if port is not start), None)
        self.cancel_connection()
        if not start or not target or start.is_output == target.is_output:
            return
        source, destination = (start, target) if start.is_output else (target, start)
        if source.node_item is destination.node_item:
            return
        if source.connection_kind != destination.connection_kind:
            return
        if (
            source.connection_kind == "attribute"
            and
            source.spec.data_type != "any"
            and destination.spec.data_type != "any"
            and source.spec.data_type != destination.spec.data_type
        ):
            return
        connection = Connection(
            source.node_item.node.id, source.spec.name,
            destination.node_item.node.id, destination.spec.name,
            source.connection_kind,
        )
        self.graph.connect(connection)
        self.rebuild()
        self.graph_changed.emit()

    def cancel_connection(self) -> None:
        """Remove any temporary connection currently being dragged.

        Returns:
            None.
        """
        if self._drag_item and self._drag_item.scene():
            self.removeItem(self._drag_item)
        self._drag_item = None
        self._drag_port = None

    def delete_selected(self) -> None:
        """Delete selected nodes, connections, and backdrops.

        Returns:
            None.
        """
        selected = list(self.selectedItems())
        edges = {item.connection for item in selected if isinstance(item, ConnectionItem) and item.connection}
        node_ids = {item.node.id for item in selected if isinstance(item, NodeItem)}
        backdrop_ids = {
            item.backdrop.id for item in selected
            if isinstance(item, BackdropItem)
        }
        if edges:
            self.graph.connections = [edge for edge in self.graph.connections if edge not in edges]
        for node_id in node_ids:
            self.graph.remove_node(node_id)
        for backdrop_id in backdrop_ids:
            self.graph.remove_backdrop(backdrop_id)
        if selected:
            self.rebuild()
            self.node_selected.emit(None)
            self.graph_changed.emit()

    def toggle_selected_disabled(self) -> None:
        """Toggle disabled state for all selected node items.

        Returns:
            None.
        """
        nodes = [item for item in self.selectedItems() if isinstance(item, NodeItem)]
        if not nodes:
            return
        disable = not all(item.node.disabled for item in nodes)
        for item in nodes:
            item.node.disabled = disable
            item.update()
        self.graph_changed.emit()

    def copy_selected(self) -> bool:
        """Copy selected nodes and internal connections to the clipboard.

        Returns:
            bool: True when node data was copied, otherwise False.
        """
        selected_ids = {
            item.node.id for item in self.selectedItems()
            if isinstance(item, NodeItem)
        }
        if not selected_ids:
            return False
        nodes = []
        for node_id in selected_ids:
            node = self.graph.nodes[node_id]
            nodes.append({
                **node.to_dict(),
                "position": list(self.graph.positions.get(node_id, (0, 0))),
            })
        connections = [
            edge.to_dict() for edge in self.graph.connections
            if edge.source_node in selected_ids and edge.target_node in selected_ids
        ]
        payload = json.dumps({
            "format": "taskgraph/nodes",
            "version": 1,
            "nodes": nodes,
            "connections": connections,
        })
        # Replace the clipboard data while also exposing readable JSON for
        # inspection and interoperability.
        from qtpy.QtCore import QMimeData
        new_mime = QMimeData()
        new_mime.setData(CLIPBOARD_MIME, payload.encode("utf-8"))
        new_mime.setText(payload)
        QApplication.clipboard().setMimeData(new_mime)
        self._paste_offset = 0
        return True

    def paste_clipboard(self) -> list[NodeItem]:
        """Paste TaskGraph node clipboard data into the scene.

        Returns:
            list[NodeItem]: Newly pasted node items.
        """
        mime = QApplication.clipboard().mimeData()
        raw = bytes(mime.data(CLIPBOARD_MIME)) if mime.hasFormat(CLIPBOARD_MIME) else b""
        if not raw:
            return []
        try:
            data = json.loads(raw.decode("utf-8"))
            if data.get("format") != "taskgraph/nodes" or data.get("version") != 1:
                return []
            self._paste_offset += 32
            id_map = {}
            created_ids = []
            self.clearSelection()
            for item in data.get("nodes", []):
                node = create_node(
                    item["type"], values=item.get("values"),
                    disabled=item.get("disabled", False),
                    name=item.get("name"),
                )
                id_map[item["id"]] = node.id
                created_ids.append(node.id)
                x, y = item.get("position", (0, 0))
                self.add_process_node(
                    node, QPointF(x + self._paste_offset, y + self._paste_offset)
                )
            for item in data.get("connections", []):
                source = id_map.get(item["source_node"])
                target = id_map.get(item["target_node"])
                if source and target:
                    self.graph.connect(Connection(
                        source, item["source_port"], target, item["target_port"],
                        item.get("kind", "attribute"),
                    ))
            self.rebuild()
            for node_id in created_ids:
                replacement = self.node_items.get(node_id)
                if replacement:
                    replacement.setSelected(True)
            self.graph_changed.emit()
            return [self.node_items[node_id] for node_id in created_ids]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return []

    def _selection_changed(self) -> None:
        """Emit the editable selected node/backdrop for the Properties panel.

        Returns:
            None.
        """
        selected = self.selectedItems()
        editable = next(
            (item.node for item in selected if isinstance(item, NodeItem)),
            None,
        )
        if editable is None:
            editable = next(
                (
                    item.backdrop for item in selected
                    if isinstance(item, BackdropItem)
                ),
                None,
            )
        self.node_selected.emit(editable)

    def refresh_nodes(self) -> None:
        """Refresh visual node and backdrop items after model edits.

        Returns:
            None.
        """
        for item in self.node_items.values():
            item.update()
        for item in self.backdrop_items.values():
            item.refresh_geometry()

    def reset_execution_states(self) -> None:
        """Clear all visual execution states from node items.

        Returns:
            None.
        """
        self.execution_states.clear()
        self.refresh_nodes()

    def set_execution_state(self, node_id: str, state: str) -> None:
        """Set the visual execution state for one node.

        Args:
            node_id: Node id whose state should be updated.
            state: Execution state name, such as ``running`` or ``failed``.

        Returns:
            None.
        """
        self.execution_states[node_id] = state
        item = self.node_items.get(node_id)
        if item:
            item.update()

    def auto_arrange(self) -> None:
        """Lay out the dependency graph from left to right in execution layers.

        Returns:
            None.
        """
        if not self.graph.nodes:
            return
        indegree = {node_id: 0 for node_id in self.graph.nodes}
        downstream = defaultdict(list)
        for edge in self.graph.connections:
            if (
                edge.kind == "dependency"
                and edge.source_node in indegree
                and edge.target_node in indegree
            ):
                indegree[edge.target_node] += 1
                downstream[edge.source_node].append(edge.target_node)

        levels = {node_id: 0 for node_id, degree in indegree.items() if degree == 0}
        queue = deque(sorted(
            levels,
            key=lambda node_id: (
                self.graph.positions.get(node_id, (0, 0))[1],
                self.graph.nodes[node_id].display_name.lower(),
            ),
        ))
        while queue:
            node_id = queue.popleft()
            for target in downstream[node_id]:
                levels[target] = max(levels.get(target, 0), levels[node_id] + 1)
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)

        # Cyclic nodes cannot be topologically layered. Keep the operation
        # useful by placing them together in a final column.
        if len(levels) != len(self.graph.nodes):
            last_level = max(levels.values(), default=-1) + 1
            for node_id in self.graph.nodes:
                levels.setdefault(node_id, last_level)

        columns = defaultdict(list)
        for node_id, level in levels.items():
            columns[level].append(node_id)
        max_rows = max(len(nodes) for nodes in columns.values())
        horizontal_spacing = 300.0
        vertical_spacing = 160.0
        for level in sorted(columns):
            nodes = sorted(
                columns[level],
                key=lambda node_id: (
                    self.graph.positions.get(node_id, (0, 0))[1],
                    self.graph.nodes[node_id].display_name.lower(),
                ),
            )
            vertical_offset = (max_rows - len(nodes)) * vertical_spacing / 2
            for row, node_id in enumerate(nodes):
                position = QPointF(
                    level * horizontal_spacing,
                    vertical_offset + row * vertical_spacing,
                )
                self.graph.positions[node_id] = (position.x(), position.y())
                self.node_items[node_id].setPos(position)

        for connection in self.connection_items:
            connection.refresh()
        self.graph_changed.emit()


class GraphView(QGraphicsView):
    """Graphics view for zooming, panning, and dropping node types.

    Attributes:
        node_type_dropped: Signal emitted when a palette node is dropped.
    """

    node_type_dropped = Signal(str, QPointF)

    def __init__(self, scene: GraphScene, parent=None):
        """Create the interactive graph viewport.

        Args:
            scene: Graph scene displayed by the view.
            parent: Optional Qt parent widget.

        Returns:
            None.
        """
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setAcceptDrops(True)
        self.setBackgroundBrush(QColor("#1a1f24"))
        self._panning = False
        self._pan_start = None

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        """Draw the dark grid background.

        Args:
            painter: Qt painter used for drawing.
            rect: Visible scene rectangle to repaint.

        Returns:
            None.
        """
        painter.fillRect(rect, QColor("#1a1f24"))
        left = int(rect.left()) - int(rect.left()) % 24
        top = int(rect.top()) - int(rect.top()) % 24
        painter.setPen(QPen(QColor("#242b31"), 1))
        x = left
        while x < rect.right():
            painter.drawLine(x, rect.top(), x, rect.bottom())
            x += 24
        y = top
        while y < rect.bottom():
            painter.drawLine(rect.left(), y, rect.right(), y)
            y += 24
        painter.setPen(QPen(QColor("#2c353d"), 1))
        x = left - left % 120
        while x < rect.right():
            painter.drawLine(x, rect.top(), x, rect.bottom())
            x += 120
        y = top - top % 120
        while y < rect.bottom():
            painter.drawLine(rect.left(), y, rect.right(), y)
            y += 120

    def wheelEvent(self, event) -> None:
        """Zoom the view around the mouse pointer.

        Args:
            event: Qt wheel event.

        Returns:
            None.
        """
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        current = self.transform().m11()
        if 0.2 < current * factor < 4.0:
            self.scale(factor, factor)

    def mousePressEvent(self, event) -> None:
        """Start middle-mouse panning or delegate normal selection.

        Args:
            event: Qt mouse press event.

        Returns:
            None.
        """
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """Pan while middle mouse is held.

        Args:
            event: Qt mouse move event.

        Returns:
            None.
        """
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        """Stop panning on middle mouse release.

        Args:
            event: Qt mouse release event.

        Returns:
            None.
        """
        if event.button() == Qt.MiddleButton:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event) -> None:
        """Accept node type drags from the node palette.

        Args:
            event: Qt drag-enter event.

        Returns:
            None.
        """
        if event.mimeData().hasFormat("application/x-taskgraph-node"):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        """Keep accepting node type drags over the viewport.

        Args:
            event: Qt drag-move event.

        Returns:
            None.
        """
        event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        """Emit a node creation request at the drop position.

        Args:
            event: Qt drop event containing a node type id.

        Returns:
            None.
        """
        type_id = bytes(event.mimeData().data("application/x-taskgraph-node")).decode()
        self.node_type_dropped.emit(type_id, self.mapToScene(event.position().toPoint()))
        event.acceptProposedAction()
