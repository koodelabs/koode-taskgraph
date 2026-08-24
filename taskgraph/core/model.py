from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar
from uuid import uuid4


class NodeCancelled(RuntimeError):
    """Raised by a process node after honoring an execution cancellation."""


@dataclass(frozen=True)
class PortSpec:
    name: str
    data_type: str = "any"
    required: bool = False
    multiple: bool = False


@dataclass(frozen=True)
class NodeProperty:
    name: str
    label: str
    default: Any = None

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        raise NotImplementedError


class TextProperty(NodeProperty):
    def __init__(self, name: str, label: str, default: str = ""):
        super().__init__(name, label, default)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        from qtpy.QtWidgets import QLineEdit

        widget = QLineEdit("" if value is None else str(value), parent)
        widget.editingFinished.connect(
            lambda editor=widget: on_change(self.name, editor.text())
        )
        return widget


class MultilineProperty(NodeProperty):
    def __init__(self, name: str, label: str, default: str = ""):
        super().__init__(name, label, default)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        from taskgraph.ui.code_editor import CodeEditor

        widget = CodeEditor("" if value is None else str(value), parent)
        widget.textChanged.connect(
            lambda editor=widget: on_change(self.name, editor.toPlainText())
        )
        return widget


class BoolProperty(NodeProperty):
    def __init__(self, name: str, label: str, default: bool = False):
        super().__init__(name, label, default)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
        from qtpy.QtWidgets import QCheckBox

        widget = QCheckBox(parent)
        widget.setChecked(bool(value))
        widget.toggled.connect(lambda checked: on_change(self.name, checked))
        return widget


class IntProperty(NodeProperty):
    def __init__(
        self,
        name: str,
        label: str,
        default: int = 0,
        minimum: int | None = None,
        maximum: int | None = None,
    ):
        super().__init__(name, label, default)
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
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
    def __init__(
        self,
        name: str,
        label: str,
        default: float = 0.0,
        minimum: float | None = None,
        maximum: float | None = None,
    ):
        super().__init__(name, label, default)
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
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
    def __init__(
        self,
        name: str,
        label: str,
        choices: tuple[Any, ...],
        default: Any = None,
    ):
        if default is None and choices:
            default = choices[0]
        super().__init__(name, label, default)
        object.__setattr__(self, "choices", choices)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
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
    def __init__(
        self,
        name: str,
        label: str,
        default: str = "",
        directory: bool = False,
    ):
        super().__init__(name, label, default)
        object.__setattr__(self, "directory", directory)

    def create_editor(self, node: ProcessNode, value: Any, on_change, parent=None):
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
            on_change(self.name, path.text())

        def browse_path() -> None:
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
        self.id = node_id or uuid4().hex
        self.disabled = disabled
        self.name = name
        self._cancel_event = None
        values = values or {}
        self.values = {spec.name: values.get(spec.name, spec.default) for spec in self.properties}

    def __getattr__(self, name: str) -> Any:
        values = self.__dict__.get("values", {})
        if name in values:
            return values[name]
        raise AttributeError(name)

    def process(self, inputs: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @property
    def display_name(self) -> str:
        return self.name or self.title

    @property
    def cancellation_requested(self) -> bool:
        return bool(self._cancel_event and self._cancel_event.is_set())

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type_id,
            "values": self.values,
            "disabled": self.disabled,
            "name": self.name,
        }


@dataclass(frozen=True)
class Connection:
    source_node: str
    source_port: str
    target_node: str
    target_port: str
    kind: str = "attribute"

    def to_dict(self) -> dict[str, str]:
        return {
            "source_node": self.source_node,
            "source_port": self.source_port,
            "target_node": self.target_node,
            "target_port": self.target_port,
            "kind": self.kind,
        }


@dataclass
class Backdrop:
    title: str = "Notes"
    note: str = ""
    color: str = "#168c9c"
    position: tuple[float, float] = (0, 0)
    size: tuple[float, float] = (480, 300)
    id: str = field(default_factory=lambda: uuid4().hex)

    def to_dict(self) -> dict[str, Any]:
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
    nodes: dict[str, ProcessNode] = field(default_factory=dict)
    positions: dict[str, tuple[float, float]] = field(default_factory=dict)
    connections: list[Connection] = field(default_factory=list)
    backdrops: dict[str, Backdrop] = field(default_factory=dict)

    def add_node(self, node: ProcessNode, position: tuple[float, float] = (0, 0)) -> None:
        self.nodes[node.id] = node
        self.positions[node.id] = position

    def remove_node(self, node_id: str) -> None:
        self.nodes.pop(node_id, None)
        self.positions.pop(node_id, None)
        self.connections = [
            edge for edge in self.connections
            if edge.source_node != node_id and edge.target_node != node_id
        ]

    def add_backdrop(self, backdrop: Backdrop) -> None:
        self.backdrops[backdrop.id] = backdrop

    def remove_backdrop(self, backdrop_id: str) -> None:
        self.backdrops.pop(backdrop_id, None)

    def connect(self, connection: Connection) -> None:
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
