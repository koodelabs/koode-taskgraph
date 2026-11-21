"""Right-side Properties panel for nodes and backdrops."""

from __future__ import annotations

from qtpy.QtCore import Signal
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QSpinBox, QTextEdit, QWidget,
)

from taskgraph.core.model import Backdrop, CustomProperties
from taskgraph.ui.code_editor import CodeEditor


class PropertyEditor(QScrollArea):
    """Render editable controls for the current node or backdrop selection.

    Attributes:
        property_changed: Signal emitted after a property edit updates the model.
    """

    property_changed = Signal()

    def __init__(self, parent=None):
        """Create an empty property panel.

        Args:
            parent: Optional Qt parent widget.

        Returns:
            None.
        """
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setMinimumWidth(250)
        self._node = None
        self._body = QWidget()
        self._layout = QFormLayout(self._body)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.setWidget(self._body)
        self.set_node(None)

    def _clear(self) -> None:
        """Remove all editor rows from the current panel body.

        Returns:
            None.
        """
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def set_node(self, node) -> None:
        """Display editors for a node, backdrop, or empty selection.

        Args:
            node: Selected ``ProcessNode``, selected ``Backdrop``, or ``None``.

        Returns:
            None.
        """
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
            widget = spec.create_editor(
                node,
                node.values.get(spec.name),
                self._set,
                self._body,
            )
            if isinstance(widget, CodeEditor):
                self._layout.addRow(QLabel(spec.label))
                self._layout.addRow(widget)
            else:
                self._layout.addRow(spec.label, widget)
        self._add_custom_properties_section()

    def _add_custom_properties_section(self) -> None:
        """Render the user-defined key/value property section.

        Returns:
            None.
        """
        header = QWidget(self._body)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 12, 0, 0)
        header_layout.addWidget(QLabel("<b>Custom Properties</b>"), 1)
        add_button = QPushButton("Add")
        add_button.setObjectName("addCustomPropertyButton")
        add_button.clicked.connect(self._add_custom_property)
        header_layout.addWidget(add_button)
        self._layout.addRow(header)

        for key, value in self._node.custom_properties.items():
            self._add_custom_property_row(key, value)

    def _add_custom_property_row(self, key: str, value) -> None:
        """Render one editable custom-property row.

        Args:
            key: Current custom-property key.
            value: Current custom-property value.

        Returns:
            None.
        """
        row = QWidget(self._body)
        row.setObjectName("customPropertyRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        key_editor = QLineEdit(key)
        key_editor.setObjectName("customPropertyKey")
        key_editor.setProperty("customPropertyKeyName", key)
        key_editor.setPlaceholderText("key")
        key_editor.setToolTip(
            "Use a Python identifier, for example: department or frame_start"
        )
        key_editor.editingFinished.connect(
            lambda editor=key_editor: self._rename_custom_property(editor)
        )

        value_editor = QLineEdit(str(value))
        value_editor.setObjectName("customPropertyValue")
        value_editor.setPlaceholderText("value")
        value_editor.editingFinished.connect(
            lambda key_widget=key_editor, editor=value_editor:
            self._set_custom_property(
                key_widget.property("customPropertyKeyName"), editor.text()
            )
        )

        remove_button = QPushButton("Remove")
        remove_button.setObjectName("removeCustomPropertyButton")
        remove_button.clicked.connect(
            lambda _checked=False, key_widget=key_editor:
            self._remove_custom_property(
                key_widget.property("customPropertyKeyName")
            )
        )

        layout.addWidget(key_editor, 1)
        layout.addWidget(value_editor, 2)
        layout.addWidget(remove_button)
        self._layout.addRow(row)

    def _add_custom_property(self) -> None:
        """Add a uniquely named empty custom property to the selected node.

        Returns:
            None.
        """
        if not self._node or isinstance(self._node, Backdrop):
            return
        base = "property"
        key = base
        suffix = 2
        while key in self._node.custom_properties:
            key = f"{base}_{suffix}"
            suffix += 1
        self._node.custom_properties.add(key)
        node = self._node
        self.set_node(node)
        key_editors = self.findChildren(QLineEdit, "customPropertyKey")
        if key_editors:
            key_editors[-1].setFocus()
            key_editors[-1].selectAll()
        self.property_changed.emit()

    def _rename_custom_property(self, editor: QLineEdit) -> None:
        """Rename a custom property when its new key is valid.

        Args:
            editor: Key editor containing the old and candidate key names.

        Returns:
            None.
        """
        if not self._node or isinstance(self._node, Backdrop):
            return
        old_key = editor.property("customPropertyKeyName")
        new_key = editor.text().strip()
        if old_key == new_key:
            return
        if (
            not CustomProperties.is_valid_key(new_key)
            or new_key in self._node.custom_properties
        ):
            editor.setText(old_key)
            return
        self._node.custom_properties.rename(old_key, new_key)
        editor.setText(new_key)
        editor.setProperty("customPropertyKeyName", new_key)
        self.property_changed.emit()

    def _set_custom_property(self, key: str, value: str) -> None:
        """Update a user-defined property value.

        Args:
            key: Existing custom-property key.
            value: New text value.

        Returns:
            None.
        """
        if self._node and key in self._node.custom_properties:
            self._node.custom_properties[key] = value
            self.property_changed.emit()

    def _remove_custom_property(self, key: str) -> None:
        """Remove a user-defined property from the selected node.

        Args:
            key: Existing custom-property key.

        Returns:
            None.
        """
        if self._node and key in self._node.custom_properties:
            self._node.custom_properties.remove(key)
            node = self._node
            self.set_node(node)
            self.property_changed.emit()

    def _set_backdrop(self, backdrop: Backdrop) -> None:
        """Build fixed editors for a selected backdrop.

        Args:
            backdrop: Selected backdrop model.

        Returns:
            None.
        """
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

    def _set(self, name, value) -> None:
        """Write a node property value and notify the graph view.

        Args:
            name: Property key to update.
            value: New property value.

        Returns:
            None.
        """
        if self._node:
            self._node.values[name] = value
            self.property_changed.emit()

    def _set_name(self, value: str) -> None:
        """Update the display name for the selected node.

        Args:
            value: Raw node name text from the editor.

        Returns:
            None.
        """
        if self._node:
            self._node.name = value.strip() or None
            self.property_changed.emit()

    def _set_backdrop_value(self, name: str, value) -> None:
        """Write a simple attribute on the selected backdrop.

        Args:
            name: Backdrop attribute name to update.
            value: New attribute value.

        Returns:
            None.
        """
        if isinstance(self._node, Backdrop):
            setattr(self._node, name, value)
            self.property_changed.emit()

    def _set_backdrop_color(self, value: str) -> None:
        """Update backdrop color when the entered color string is valid.

        Args:
            value: Candidate CSS-style color string.

        Returns:
            None.
        """
        if isinstance(self._node, Backdrop) and QColor(value).isValid():
            self._node.color = value
            self.property_changed.emit()

    def _set_backdrop_size(
        self, width: int | None = None, height: int | None = None
    ) -> None:
        """Update backdrop dimensions from width/height spin boxes.

        Args:
            width: Optional new backdrop width.
            height: Optional new backdrop height.

        Returns:
            None.
        """
        if isinstance(self._node, Backdrop):
            current_width, current_height = self._node.size
            self._node.size = (
                width if width is not None else current_width,
                height if height is not None else current_height,
            )
            self.property_changed.emit()
