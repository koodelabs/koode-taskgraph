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
    kind: str
    default: Any = None
    choices: tuple[Any, ...] = ()
    minimum: float | None = None
    maximum: float | None = None


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
