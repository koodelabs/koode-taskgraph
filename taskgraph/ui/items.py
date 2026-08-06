from __future__ import annotations

import math
from typing import TYPE_CHECKING

from qtpy.QtCore import QPointF, QRectF, Qt
from qtpy.QtGui import (
    QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QPolygonF,
)
from qtpy.QtWidgets import QGraphicsItem, QGraphicsObject, QStyle

if TYPE_CHECKING:
    from taskgraph.core.model import Backdrop, Connection, PortSpec, ProcessNode
    from taskgraph.ui.scene import GraphScene


TYPE_COLORS = {
    "any": "#56c7d9", "text": "#61b7ff", "number": "#f0b35b",
    "bool": "#db78e8", "list": "#75d98b", "dependency": "#f2b04f",
}


class PortItem(QGraphicsObject):
    RADIUS = 6.0

    def __init__(
        self, node_item: "NodeItem", spec: "PortSpec", is_output: bool,
        connection_kind: str = "attribute",
    ):
        super().__init__(node_item)
        self.node_item = node_item
        self.spec = spec
        self.is_output = is_output
        self.connection_kind = connection_kind
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CrossCursor)

    def boundingRect(self) -> QRectF:
        r = self.RADIUS + 3
        return QRectF(-r, -r, r * 2, r * 2)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        color = QColor(TYPE_COLORS.get(self.spec.data_type, TYPE_COLORS["any"]))
        if option.state & QStyle.State_MouseOver:
            color = color.lighter(145)
        painter.setPen(QPen(color.lighter(135), 1.5))
        painter.setBrush(QBrush(color.darker(125)))
        painter.drawEllipse(QPointF(0, 0), self.RADIUS, self.RADIUS)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.node_item.graph_scene.begin_connection(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.node_item.graph_scene.update_connection(event.scenePos())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        self.node_item.graph_scene.finish_connection(event.scenePos())
        event.accept()


class BackdropResizeHandle(QGraphicsObject):
    SIZE = 18.0

    def __init__(self, backdrop_item: "BackdropItem"):
        super().__init__(backdrop_item)
        self.backdrop_item = backdrop_item
        self._start_position = QPointF()
        self._start_size = (0.0, 0.0)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setZValue(1)

    def boundingRect(self) -> QRectF:
        return QRectF(-self.SIZE, -self.SIZE, self.SIZE, self.SIZE)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        color = QColor(self.backdrop_item.backdrop.color).lighter(150)
        painter.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(-12, -3), QPointF(-3, -12))
        painter.drawLine(QPointF(-8, -3), QPointF(-3, -8))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.backdrop_item.setSelected(True)
            self._start_position = event.scenePos()
            self._start_size = self.backdrop_item.backdrop.size
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        delta = event.scenePos() - self._start_position
        self.backdrop_item.set_interactive_size(
            self._start_size[0] + delta.x(),
            self._start_size[1] + delta.y(),
        )
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.backdrop_item.graph_scene.node_selected.emit(
                self.backdrop_item.backdrop
            )
            event.accept()
            return
        super().mouseReleaseEvent(event)


class BackdropItem(QGraphicsObject):
    HEADER = 34.0

    def __init__(self, graph_scene: "GraphScene", backdrop: "Backdrop"):
        super().__init__()
        self.graph_scene = graph_scene
        self.backdrop = backdrop
        self._size = backdrop.size
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setZValue(0)
        self.resize_handle = BackdropResizeHandle(self)
        self.resize_handle.setPos(*self._size)

    def boundingRect(self) -> QRectF:
        width, height = self._size
        return QRectF(0, 0, width, height)

    def paint(self, painter: QPainter, option, widget=None) -> None:
        rect = self.boundingRect()
        color = QColor(self.backdrop.color)
        fill = QColor(color)
        fill.setAlpha(42)
        header = QColor(color)
        header.setAlpha(185)
        painter.setPen(QPen(
            color.lighter(145) if self.isSelected() else color,
            2 if self.isSelected() else 1,
        ))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 5, 5)
        painter.fillRect(QRectF(0, 0, rect.width(), self.HEADER), header)
        painter.setPen(QColor("#f2f5f7"))
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(12, 0, rect.width() - 24, self.HEADER),
            Qt.AlignVCenter,
            self.backdrop.title or "Notes",
        )
        painter.setFont(QFont())
        painter.setPen(QColor("#d5dbe3"))
        painter.drawText(
            rect.adjusted(14, self.HEADER + 12, -14, -12),
            Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
            self.backdrop.note,
        )

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            position = self.pos()
            self.backdrop.position = (position.x(), position.y())
            self.graph_scene.graph_changed.emit()
        return super().itemChange(change, value)

    def refresh_geometry(self) -> None:
        if self._size != self.backdrop.size:
            self.prepareGeometryChange()
            self._size = self.backdrop.size
            self.resize_handle.setPos(*self._size)
        self.update()

    def set_interactive_size(self, width: float, height: float) -> None:
        new_size = (max(200.0, width), max(120.0, height))
        if new_size == self._size:
            return
        self.prepareGeometryChange()
        self._size = new_size
        self.backdrop.size = new_size
        self.resize_handle.setPos(*new_size)
        self.update()
        self.graph_scene.graph_changed.emit()


class NodeItem(QGraphicsObject):
    WIDTH = 250.0
    HEADER = 30.0
    ROW = 25.0

    def __init__(self, graph_scene: "GraphScene", node: "ProcessNode"):
        super().__init__()
        self.graph_scene = graph_scene
        self.node = node
        self.input_ports: dict[str, PortItem] = {}
        self.output_ports: dict[str, PortItem] = {}
        row_count = max(len(node.inputs), len(node.outputs), 1)
        self._height = max(104.0, self.HEADER + (row_count + 1) * self.ROW + 18)
        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setCacheMode(QGraphicsItem.DeviceCoordinateCache)
        self.setZValue(2)
        self.dependency_input = PortItem(
            self, node.dependency_input, False, "dependency"
        )
        self.dependency_input.setPos(0, self.HEADER + 17)
        self.dependency_output = PortItem(
            self, node.dependency_output, True, "dependency"
        )
        self.dependency_output.setPos(self.WIDTH, self.HEADER + 17)
        for index, spec in enumerate(node.inputs):
            port = PortItem(self, spec, False)
            port.setPos(0, self.HEADER + 17 + (index + 1) * self.ROW)
            self.input_ports[spec.name] = port
        for index, spec in enumerate(node.outputs):
            port = PortItem(self, spec, True)
            port.setPos(self.WIDTH, self.HEADER + 17 + (index + 1) * self.ROW)
            self.output_ports[spec.name] = port

    def boundingRect(self) -> QRectF:
        return QRectF(-8, -2, self.WIDTH + 16, self._height + 10)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.WIDTH, self._height), 6, 6)
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        body = QRectF(0, 0, self.WIDTH, self._height)
        state = self.graph_scene.execution_states.get(self.node.id, "idle")
        state_colors = {
            "running": QColor("#ffbe3d"),
            "finished": QColor("#45d483"),
            "failed": QColor("#ff5261"),
            "skipped": QColor("#88939d"),
            "blocked": QColor("#b77986"),
            "cancelled": QColor("#9b8eb8"),
        }
        border = state_colors.get(
            state,
            QColor("#64cddd") if self.isSelected() else QColor("#40505d"),
        )
        painter.setPen(QPen(border, 3 if state == "running" else (2 if self.isSelected() else 1)))
        painter.setBrush(QColor("#131b21"))
        painter.drawRoundedRect(body, 6, 6)
        header = QPainterPath()
        header.addRoundedRect(QRectF(0, 0, self.WIDTH, self.HEADER + 5), 6, 6)
        header.addRect(QRectF(0, self.HEADER - 5, self.WIDTH, 10))
        painter.fillPath(header, QColor(self.node.color))
        painter.setPen(QColor("#f2f5f7"))
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(12, 0, self.WIDTH - 58, self.HEADER),
            Qt.AlignVCenter,
            self.node.display_name,
        )
        if state != "idle":
            painter.setPen(Qt.NoPen)
            painter.setBrush(state_colors[state])
            painter.drawEllipse(QPointF(self.WIDTH - 16, self.HEADER / 2), 5, 5)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont(painter.font().family(), 7))
            painter.drawText(
                QRectF(self.WIDTH - 58, 0, 36, self.HEADER),
                Qt.AlignVCenter | Qt.AlignRight,
                state.upper(),
            )
        painter.setFont(QFont())
        painter.setPen(QColor("#b9c3cc"))
        painter.drawText(
            QRectF(12, self.HEADER + 5, self.WIDTH - 24, self.ROW),
            Qt.AlignVCenter,
            "dependency",
        )
        painter.drawText(
            QRectF(12, self.HEADER + 5, self.WIDTH - 24, self.ROW),
            Qt.AlignVCenter | Qt.AlignRight,
            "dependency",
        )
        for index, spec in enumerate(self.node.inputs):
            painter.drawText(
                QRectF(
                    12,
                    self.HEADER + 5 + (index + 1) * self.ROW,
                    self.WIDTH / 2 - 24,
                    self.ROW,
                ),
                Qt.AlignVCenter,
                spec.name,
            )
        for index, spec in enumerate(self.node.outputs):
            painter.drawText(
                QRectF(
                    self.WIDTH / 2,
                    self.HEADER + 5 + (index + 1) * self.ROW,
                    self.WIDTH / 2 - 12,
                    self.ROW,
                ),
                Qt.AlignVCenter | Qt.AlignRight,
                spec.name,
            )
        if self.node.disabled:
            painter.fillRect(body.adjusted(1, 1, -1, -1), QColor(8, 10, 12, 175))
            painter.setPen(QPen(QColor("#ef4d5a"), 2))
            painter.drawLine(body.topLeft() + QPointF(5, 5), body.bottomRight() - QPointF(5, 5))
            painter.drawLine(body.topRight() + QPointF(-5, 5), body.bottomLeft() + QPointF(5, -5))
            painter.setPen(QColor("#ff6673"))
            painter.drawText(body, Qt.AlignCenter, "DISABLED")

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged and self.scene():
            self.graph_scene.node_moved(self)
        return super().itemChange(change, value)


class ConnectionItem(QGraphicsItem):
    def __init__(self, graph_scene: "GraphScene", connection: "Connection" | None = None):
        super().__init__()
        self.graph_scene = graph_scene
        self.connection = connection
        self.start = QPointF()
        self.end = QPointF()
        self.path = QPainterPath()
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setZValue(1)
        self.refresh()

    def boundingRect(self) -> QRectF:
        return self.path.boundingRect().adjusted(-8, -8, 8, 8)

    def shape(self) -> QPainterPath:
        from qtpy.QtGui import QPainterPathStroker
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        return stroker.createStroke(self.path)

    def set_points(self, start: QPointF, end: QPointF) -> None:
        self.prepareGeometryChange()
        self.start, self.end = start, end
        self._update_path()

    def refresh(self) -> None:
        if self.connection and self.connection.source_node in self.graph_scene.node_items:
            source = self.graph_scene.node_items[self.connection.source_node]
            target = self.graph_scene.node_items[self.connection.target_node]
            if self.connection.kind == "dependency":
                source_port = source.dependency_output
                target_port = target.dependency_input
            else:
                source_port = source.output_ports[self.connection.source_port]
                target_port = target.input_ports[self.connection.target_port]
            self.set_points(
                source_port.scenePos(),
                target_port.scenePos(),
            )

    def _update_path(self) -> None:
        self.path = QPainterPath(self.start)
        distance = max(70.0, abs(self.end.x() - self.start.x()) * 0.55)
        direction = 1 if self.end.x() >= self.start.x() else -1
        self.path.cubicTo(
            self.start + QPointF(distance * direction, 0),
            self.end - QPointF(distance * direction, 0),
            self.end,
        )
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self.connection and self.connection.kind == "dependency":
            color = QColor("#ffd166" if self.isSelected() else "#d4922f")
        else:
            color = QColor("#f2b04f" if self.isSelected() else "#4db8c6")
        painter.setPen(QPen(color, 3 if self.isSelected() else 2, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(self.path)
        if self.connection and self.connection.kind == "dependency":
            # Place the arrow inside the curve rather than at the port, where
            # it remains readable even when several connections share a node.
            before = self.path.pointAtPercent(0.54)
            tip = self.path.pointAtPercent(0.58)
            angle = math.atan2(tip.y() - before.y(), tip.x() - before.x())
            direction = QPointF(math.cos(angle), math.sin(angle))
            normal = QPointF(-direction.y(), direction.x())
            arrow_length = 11.0
            arrow_width = 6.0
            base = tip - direction * arrow_length
            arrow = QPolygonF([
                tip,
                base + normal * arrow_width,
                base - normal * arrow_width,
            ])
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawPolygon(arrow)
