from __future__ import annotations

from qtpy.QtCore import Signal
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QLabel,
    QLineEdit, QScrollArea, QSizePolicy, QSpinBox, QTextEdit, QWidget,
)

from taskgraph.core.model import Backdrop


class PropertyEditor(QScrollArea):
    property_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumWidth(250)
        self._node = None
        self._body = QWidget()
        self._layout = QFormLayout(self._body)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self.setWidget(self._body)
        self.set_node(None)

    def _clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def set_node(self, node) -> None:
        self._node = node
        self._clear()
        if node is None:
            self._layout.addRow(
                QLabel("Select a node or backdrop to edit its properties.")
            )
            return
        if isinstance(node, Backdrop):
            self._set_backdrop(node)
            return
        title = QLabel(f"<b>{node.title}</b><br><small>{node.type_id}</small>")
        self._layout.addRow(title)
        name_editor = QLineEdit(node.name or "")
        name_editor.setPlaceholderText(node.title)
        name_editor.editingFinished.connect(
            lambda editor=name_editor: self._set_name(editor.text())
        )
        self._layout.addRow("Node Name", name_editor)
        for spec in node.properties:
            widget = self._make_editor(spec, node.values.get(spec.name))
            self._layout.addRow(spec.label, widget)

    def _set_backdrop(self, backdrop: Backdrop) -> None:
        self._layout.addRow(QLabel("<b>Backdrop</b><br><small>Graph notes</small>"))
        title = QLineEdit(backdrop.title)
        title.editingFinished.connect(
            lambda editor=title: self._set_backdrop_value(
                "title", editor.text().strip() or "Notes"
            )
        )
        self._layout.addRow("Title", title)

        notes = QTextEdit(backdrop.note)
        notes.setObjectName("notesEditor")
        notes.setAcceptRichText(False)
        notes.setLineWrapMode(QTextEdit.WidgetWidth)
        notes.setMinimumHeight(140)
        notes.setMaximumHeight(220)
        notes.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        notes.textChanged.connect(
            lambda editor=notes: self._set_backdrop_value(
                "note", editor.toPlainText()
            )
        )
        # A widget-only QFormLayout row spans both columns, giving multiline
        # notes the full width of the Properties panel.
        self._layout.addRow(QLabel("Notes"))
        self._layout.addRow(notes)

        color = QLineEdit(backdrop.color)
        color.editingFinished.connect(
            lambda editor=color: self._set_backdrop_color(editor.text())
        )
        self._layout.addRow("Color", color)

        width = QSpinBox()
        width.setRange(200, 3000)
        width.setValue(int(backdrop.size[0]))
        width.valueChanged.connect(
            lambda value: self._set_backdrop_size(width=value)
        )
        self._layout.addRow("Width", width)

        height = QSpinBox()
        height.setRange(120, 3000)
        height.setValue(int(backdrop.size[1]))
        height.valueChanged.connect(
            lambda value: self._set_backdrop_size(height=value)
        )
        self._layout.addRow("Height", height)

    def _make_editor(self, spec, value):
        if spec.kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(value))
            widget.toggled.connect(lambda checked, s=spec: self._set(s.name, checked))
        elif spec.kind == "int":
            widget = QSpinBox()
            widget.setRange(int(spec.minimum if spec.minimum is not None else -1_000_000),
                            int(spec.maximum if spec.maximum is not None else 1_000_000))
            widget.setValue(int(value or 0))
            widget.valueChanged.connect(lambda number, s=spec: self._set(s.name, number))
        elif spec.kind == "float":
            widget = QDoubleSpinBox()
            widget.setDecimals(4)
            widget.setRange(spec.minimum if spec.minimum is not None else -1e12,
                            spec.maximum if spec.maximum is not None else 1e12)
            widget.setValue(float(value or 0))
            widget.valueChanged.connect(lambda number, s=spec: self._set(s.name, number))
        elif spec.kind == "choice":
            widget = QComboBox()
            widget.addItems([str(choice) for choice in spec.choices])
            if value in spec.choices:
                widget.setCurrentIndex(spec.choices.index(value))
            widget.currentIndexChanged.connect(
                lambda index, s=spec: self._set(s.name, s.choices[index])
            )
        else:
            widget = QLineEdit("" if value is None else str(value))
            widget.editingFinished.connect(lambda w=widget, s=spec: self._set(s.name, w.text()))
        return widget

    def _set(self, name, value) -> None:
        if self._node:
            self._node.values[name] = value
            self.property_changed.emit()

    def _set_name(self, value: str) -> None:
        if self._node:
            self._node.name = value.strip() or None
            self.property_changed.emit()

    def _set_backdrop_value(self, name: str, value) -> None:
        if isinstance(self._node, Backdrop):
            setattr(self._node, name, value)
            self.property_changed.emit()

    def _set_backdrop_color(self, value: str) -> None:
        if isinstance(self._node, Backdrop) and QColor(value).isValid():
            self._node.color = value
            self.property_changed.emit()

    def _set_backdrop_size(
        self, width: int | None = None, height: int | None = None
    ) -> None:
        if isinstance(self._node, Backdrop):
            current_width, current_height = self._node.size
            self._node.size = (
                width if width is not None else current_width,
                height if height is not None else current_height,
            )
            self.property_changed.emit()
