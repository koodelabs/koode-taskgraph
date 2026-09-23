"""Core data model for TaskGraph nodes, ports, connections, and graphs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar
from uuid import uuid4


class NodeCancelled(RuntimeError):
    """Raised by a process node after honoring an execution cancellation.

    The executor treats this as a cooperative cancellation, not a node failure.
    """


@dataclass(frozen=True)
class PortSpec:
    """Describe one input/output port exposed by a process node.

    Attributes:
        name: Internal port name used by connections and process dictionaries.
        data_type: Human-readable data type label shown in the UI.
        required: Whether execution should fail when the input is not provided.
        multiple: Whether the port accepts multiple incoming connections.
    """

    name: str
    data_type: str = "any"
    required: bool = False
    multiple: bool = False


@dataclass(frozen=True)
class NodeProperty:
    """Base description for one user-editable node property.

    Attributes:
        name: Internal property key stored in ``ProcessNode.values``.
        label: User-facing label shown in the Properties panel.
        default: Initial value used when a node is created.
    """

    name: str
    label: str
    default: Any = None

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        """Create a Qt editor widget for this property.

        Args:
            node: Node instance owning the property.
            value: Current property value from ``node.values``.
            on_change: Callback receiving ``(property_name, value)``.
            parent: Optional Qt parent widget.

        Returns:
            QWidget: Editor widget used in the Properties panel.

        Raises:
            NotImplementedError: Always raised by the base property class.
        """
        raise NotImplementedError


class TextProperty(NodeProperty):
    """Single-line text property rendered with a QLineEdit.

    Attributes:
        name: Internal property key.
        label: User-facing property label.
        default: Initial text value.
    """

    def __init__(self, name: str, label: str, default: str = ""):
        """Create a text property definition.

        Args:
            name: Internal property key.
            label: User-facing property label.
            default: Initial text value.

        Returns:
            None.
        """
        super().__init__(name, label, default)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        """Create a QLineEdit and write edits back through on_change.

        Args:
            node: Node instance owning the property.
            value: Current property value.
            on_change: Callback receiving ``(property_name, value)``.
            parent: Optional Qt parent widget.

        Returns:
            QLineEdit: Single-line editor for this property.
        """
        from qtpy.QtWidgets import QLineEdit

        widget = QLineEdit("" if value is None else str(value), parent)
        widget.editingFinished.connect(
            lambda editor=widget: on_change(self.name, editor.text())
        )
        return widget


class MultilineProperty(NodeProperty):
    """Multiline text/code property rendered with the code editor widget.

    Attributes:
        name: Internal property key.
        label: User-facing property label.
        default: Initial multiline text.
    """

    def __init__(self, name: str, label: str, default: str = ""):
        """Create a multiline property definition.

        Args:
            name: Internal property key.
            label: User-facing property label.
            default: Initial multiline text.

        Returns:
            None.
        """
        super().__init__(name, label, default)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        """Create a CodeEditor and write edits back through on_change.

        Args:
            node: Node instance owning the property.
            value: Current property value.
            on_change: Callback receiving ``(property_name, value)``.
            parent: Optional Qt parent widget.

        Returns:
            CodeEditor: Multiline editor for text or code values.
        """
        from taskgraph.ui.code_editor import CodeEditor

        widget = CodeEditor("" if value is None else str(value), parent)
        widget.textChanged.connect(
            lambda editor=widget: on_change(self.name, editor.toPlainText())
        )
        return widget


class BoolProperty(NodeProperty):
    """Boolean property rendered with a QCheckBox.

    Attributes:
        name: Internal property key.
        label: User-facing property label.
        default: Initial checked state.
    """

    def __init__(self, name: str, label: str, default: bool = False):
        """Create a boolean property definition.

        Args:
            name: Internal property key.
            label: User-facing property label.
            default: Initial checked state.

        Returns:
            None.
        """
        super().__init__(name, label, default)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        """Create a QCheckBox and write toggle changes through on_change.

        Args:
            node: Node instance owning the property.
            value: Current property value.
            on_change: Callback receiving ``(property_name, value)``.
            parent: Optional Qt parent widget.

        Returns:
            QCheckBox: Checkbox editor for this property.
        """
        from qtpy.QtWidgets import QCheckBox

        widget = QCheckBox(parent)
        widget.setChecked(bool(value))
        widget.toggled.connect(lambda checked: on_change(self.name, checked))
        return widget


class IntProperty(NodeProperty):
    """Integer property rendered with a QSpinBox.

    Attributes:
        name: Internal property key.
        label: User-facing property label.
        default: Initial integer value.
        minimum: Optional lower bound.
        maximum: Optional upper bound.
    """

    def __init__(
        self,
        name: str,
        label: str,
        default: int = 0,
        minimum: int | None = None,
        maximum: int | None = None,
    ):
        """Create an integer property with optional minimum/maximum bounds.

        Args:
            name: Internal property key.
            label: User-facing property label.
            default: Initial integer value.
            minimum: Optional lower bound.
            maximum: Optional upper bound.

        Returns:
            None.
        """
        super().__init__(name, label, default)
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        """Create a QSpinBox and write value changes through on_change.

        Args:
            node: Node instance owning the property.
            value: Current property value.
            on_change: Callback receiving ``(property_name, value)``.
            parent: Optional Qt parent widget.

        Returns:
            QSpinBox: Integer spin-box editor for this property.
        """
        from qtpy.QtWidgets import QSpinBox

        widget = QSpinBox(parent)
        widget.setRange(
            int(self.minimum if self.minimum is not None else -1_000_000),
            int(self.maximum if self.maximum is not None else 1_000_000),
        )
        widget.setValue(int(value or 0))
        widget.valueChanged.connect(lambda number: on_change(self.name, number))
        return widget


class FloatProperty(NodeProperty):
    """Floating-point property rendered with a QDoubleSpinBox.

    Attributes:
        name: Internal property key.
        label: User-facing property label.
        default: Initial floating-point value.
        minimum: Optional lower bound.
        maximum: Optional upper bound.
    """

    def __init__(
        self,
        name: str,
        label: str,
        default: float = 0.0,
        minimum: float | None = None,
        maximum: float | None = None,
    ):
        """Create a float property with optional minimum/maximum bounds.

        Args:
            name: Internal property key.
            label: User-facing property label.
            default: Initial floating-point value.
            minimum: Optional lower bound.
            maximum: Optional upper bound.

        Returns:
            None.
        """
        super().__init__(name, label, default)
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        """Create a QDoubleSpinBox and write value changes through on_change.

        Args:
            node: Node instance owning the property.
            value: Current property value.
            on_change: Callback receiving ``(property_name, value)``.
            parent: Optional Qt parent widget.

        Returns:
            QDoubleSpinBox: Floating-point spin-box editor for this property.
        """
        from qtpy.QtWidgets import QDoubleSpinBox

        widget = QDoubleSpinBox(parent)
        widget.setDecimals(4)
        widget.setRange(
            self.minimum if self.minimum is not None else -1e12,
            self.maximum if self.maximum is not None else 1e12,
        )
        widget.setValue(float(value or 0))
        widget.valueChanged.connect(lambda number: on_change(self.name, number))
        return widget


class ChoiceProperty(NodeProperty):
    """Choice property rendered with a QComboBox.

    Attributes:
        name: Internal property key.
        label: User-facing property label.
        default: Initial selected value.
        choices: Allowed dropdown values.
    """

    def __init__(
        self,
        name: str,
        label: str,
        choices: tuple[Any, ...],
        default: Any = None,
    ):
        """Create a dropdown property from a fixed list of choices.

        Args:
            name: Internal property key.
            label: User-facing property label.
            choices: Allowed values displayed in the dropdown.
            default: Initial selected value. Defaults to the first choice.

        Returns:
            None.
        """
        if default is None and choices:
            default = choices[0]
        super().__init__(name, label, default)
        object.__setattr__(self, "choices", choices)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        """Create a QComboBox and write selection changes through on_change.

        Args:
            node: Node instance owning the property.
            value: Current property value.
            on_change: Callback receiving ``(property_name, value)``.
            parent: Optional Qt parent widget.

        Returns:
            QComboBox: Dropdown editor for this property.
        """
        from qtpy.QtWidgets import QComboBox

        widget = QComboBox(parent)
        widget.addItems([str(choice) for choice in self.choices])
        if value in self.choices:
            widget.setCurrentIndex(self.choices.index(value))
        widget.currentIndexChanged.connect(
            lambda index: on_change(self.name, self.choices[index])
        )
        return widget


class PathProperty(NodeProperty):
    """Filesystem path property rendered as a line edit plus Browse button.

    Attributes:
        name: Internal property key.
        label: User-facing property label.
        default: Initial path text.
        directory: Whether Browse opens a directory picker instead of file picker.
    """

    def __init__(
        self,
        name: str,
        label: str,
        default: str = "",
        directory: bool = False,
    ):
        """Create a path property.

        Args:
            name: Internal property key stored in ``node.values``.
            label: User-facing label in the Properties panel.
            default: Initial path text.
            directory: When true, Browse opens a directory picker. Otherwise it
                opens a file picker.
        """
        super().__init__(name, label, default)
        object.__setattr__(self, "directory", directory)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        """Create the path text field and Browse button.

        Args:
            node: Node instance owning the property.
            value: Current path text.
            on_change: Callback receiving ``(property_name, value)``.
            parent: Optional Qt parent widget.

        Returns:
            QWidget: Composite widget containing a path line edit and browse button.
        """
        from qtpy.QtWidgets import (
            QFileDialog,
            QHBoxLayout,
            QLineEdit,
            QPushButton,
            QWidget,
        )

        widget = QWidget(parent)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        path = QLineEdit("" if value is None else str(value), widget)
        browse = QPushButton("Browse...", widget)

        def commit_path() -> None:
            """Commit the current line-edit value to the node property.

            Returns:
                None.
            """
            on_change(self.name, path.text())

        def browse_path() -> None:
            """Open the configured file/directory dialog and commit selection.

            Returns:
                None.
            """
            if self.directory:
                selected_path = QFileDialog.getExistingDirectory(
                    widget, f"Select {self.label}", path.text()
                )
            else:
                selected_path, _ = QFileDialog.getOpenFileName(
                    widget, f"Select {self.label}", path.text()
                )
            if selected_path:
                path.setText(selected_path)
                commit_path()

        browse.clicked.connect(browse_path)
        path.editingFinished.connect(commit_path)
        layout.addWidget(path, 1)
        layout.addWidget(browse)
        return widget


class ProcessNode:
    """Base class for all executable graph nodes.

    Attributes:
        id: Unique node id inside the graph.
        disabled: Whether execution should skip this node.
        name: Optional user-facing display name.
        values: Editable property values keyed by property name.
    """

    type_id: ClassVar[str] = "core.process"
    title: ClassVar[str] = "Process"
    category: ClassVar[str] = "General"
    color: ClassVar[str] = "#256b82"
    dependency_input: ClassVar[PortSpec] = PortSpec(
        "dependency", "dependency", multiple=True
    )
    dependency_output: ClassVar[PortSpec] = PortSpec(
        "dependency", "dependency", multiple=True
    )
    inputs: ClassVar[tuple[PortSpec, ...]] = ()
    outputs: ClassVar[tuple[PortSpec, ...]] = ()
    properties: ClassVar[tuple[NodeProperty, ...]] = ()

    def __init__(
        self,
        node_id: str | None = None,
        values: dict[str, Any] | None = None,
        disabled: bool = False,
        name: str | None = None,
    ):
        """Create a process node instance with property defaults and state.

        Args:
            node_id: Optional stable id used when loading a saved graph.
            values: Optional property values keyed by property name.
            disabled: Whether this node should be skipped during execution.
            name: Optional user-facing display name.

        Returns:
            None.
        """
        self.id = node_id or uuid4().hex
        self.disabled = disabled
        self.name = name
        self._cancel_event = None
        self._event_callback = None
        values = values or {}
        self.values = {
            spec.name: values.get(spec.name, spec.default)
            for spec in self.properties
        }

    def __getattr__(self, name: str) -> Any:
        """Expose property values as attributes such as ``self.prefix``.

        Args:
            name: Attribute name requested by Python.

        Returns:
            Any: Stored property value.

        Raises:
            AttributeError: If the requested name is not a node property.
        """
        values = self.__dict__.get("values", {})
        if name in values:
            return values[name]
        raise AttributeError(name)

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Run this node and return output values keyed by output port name.

        Args:
            inputs: Values received from incoming attribute connections.

        Returns:
            dict[str, Any]: Output values keyed by output port name.

        Raises:
            NotImplementedError: Always raised by the base node class.
        """
        raise NotImplementedError

    @property
    def display_name(self) -> str:
        """Return the user-defined node name, falling back to class title.

        Returns:
            str: Display name used in the graph and execution logs.
        """
        return self.name or self.title

    @property
    def cancellation_requested(self) -> bool:
        """Return whether the active graph execution requested cancellation.

        Returns:
            bool: True when the current graph run has requested cancellation.
        """
        return bool(self._cancel_event and self._cancel_event.is_set())

    def emit_event(self, message: str) -> None:
        """Send a live execution message through the active executor logger.

        Args:
            message: Text to show in the active execution log.

        Returns:
            None.
        """
        if self._event_callback:
            self._event_callback(message)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this node instance for a ``.taskgraph`` file.

        Returns:
            dict[str, Any]: JSON-compatible node payload.
        """
        return {
            "id": self.id,
            "type": self.type_id,
            "values": self.values,
            "disabled": self.disabled,
            "name": self.name,
        }


@dataclass(frozen=True)
class Connection:
    """Directed edge between two node ports.

    Attributes:
        source_node: Source node id.
        source_port: Source port name.
        target_node: Target node id.
        target_port: Target port name.
        kind: Connection kind, either ``"attribute"`` or ``"dependency"``.
    """

    source_node: str
    source_port: str
    target_node: str
    target_port: str
    kind: str = "attribute"

    def to_dict(self) -> dict[str, str]:
        """Serialize this connection for a ``.taskgraph`` file.

        Returns:
            dict[str, str]: JSON-compatible connection payload.
        """
        return {
            "source_node": self.source_node,
            "source_port": self.source_port,
            "target_node": self.target_node,
            "target_port": self.target_port,
            "kind": self.kind,
        }


@dataclass
class Backdrop:
    """Resizable note area drawn behind graph nodes.

    Attributes:
        title: Header text shown on the backdrop.
        note: Multiline note text.
        color: Backdrop color string.
        position: Scene position as ``(x, y)``.
        size: Backdrop size as ``(width, height)``.
        id: Unique backdrop id.
    """

    title: str = "Notes"
    note: str = ""
    color: str = "#168c9c"
    position: tuple[float, float] = (0, 0)
    size: tuple[float, float] = (480, 300)
    id: str = field(default_factory=lambda: uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
        """Serialize this backdrop for a ``.taskgraph`` file.

        Returns:
            dict[str, Any]: JSON-compatible backdrop payload.
        """
        return {
            "id": self.id,
            "title": self.title,
            "note": self.note,
            "color": self.color,
            "position": list(self.position),
            "size": list(self.size),
        }


@dataclass
class Graph:
    """In-memory graph containing nodes, connections, positions, and backdrops.

    Attributes:
        nodes: Process nodes keyed by node id.
        positions: Scene positions keyed by node id.
        connections: Directed graph connections.
        backdrops: Backdrop notes keyed by backdrop id.
    """

    nodes: dict[str, ProcessNode] = field(default_factory=dict)
    positions: dict[str, tuple[float, float]] = field(default_factory=dict)
    connections: list[Connection] = field(default_factory=list)
    backdrops: dict[str, Backdrop] = field(default_factory=dict)

    def add_node(self, node: ProcessNode, position: tuple[float, float] = (0, 0)) -> None:
        """Add a node instance to the graph at a scene position.

        Args:
            node: Process node to add.
            position: Initial scene position as ``(x, y)``.

        Returns:
            None.
        """
        self.nodes[node.id] = node
        self.positions[node.id] = position

    def remove_node(self, node_id: str) -> None:
        """Remove a node and all connections attached to it.

        Args:
            node_id: Id of the node to remove.

        Returns:
            None.
        """
        self.nodes.pop(node_id, None)
        self.positions.pop(node_id, None)
        self.connections = [
            edge for edge in self.connections
            if edge.source_node != node_id and edge.target_node != node_id
        ]

    def add_backdrop(self, backdrop: Backdrop) -> None:
        """Add a backdrop note region to the graph.

        Args:
            backdrop: Backdrop model object to add.

        Returns:
            None.
        """
        self.backdrops[backdrop.id] = backdrop

    def remove_backdrop(self, backdrop_id: str) -> None:
        """Remove a backdrop from the graph.

        Args:
            backdrop_id: Id of the backdrop to remove.

        Returns:
            None.
        """
        self.backdrops.pop(backdrop_id, None)

    def connect(self, connection: Connection) -> None:
        """Add a validated connection, replacing existing single-input links.

        Args:
            connection: Directed dependency or attribute connection to add.

        Returns:
            None.

        Raises:
            ValueError: If the connection kind or dependency port names are invalid.
        """
        if connection.kind not in {"attribute", "dependency"}:
            raise ValueError(f"Unknown connection kind: {connection.kind}")
        if connection.kind == "attribute":
            target = self.nodes[connection.target_node]
            target_spec = next(port for port in target.inputs if port.name == connection.target_port)
        else:
            source = self.nodes[connection.source_node]
            target = self.nodes[connection.target_node]
            if connection.source_port != source.dependency_output.name:
                raise ValueError(
                    f"Unknown dependency output: {connection.source_port}"
                )
            if connection.target_port != target.dependency_input.name:
                raise ValueError(
                    f"Unknown dependency input: {connection.target_port}"
                )
            target_spec = target.dependency_input
        if not target_spec.multiple:
            self.connections = [
                edge for edge in self.connections
                if not (
                    edge.target_node == connection.target_node
                    and edge.target_port == connection.target_port
                )
            ]
        if connection not in self.connections:
            self.connections.append(connection)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the full graph into the saved file data structure.

        Returns:
            dict[str, Any]: JSON-compatible graph payload.
        """
        return {
            "version": 1,
            "nodes": [
                {**node.to_dict(), "position": list(self.positions.get(node.id, (0, 0)))}
                for node in self.nodes.values()
            ],
            "connections": [edge.to_dict() for edge in self.connections],
            "backdrops": [
                backdrop.to_dict() for backdrop in self.backdrops.values()
            ],
        }
