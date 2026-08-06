import json
from pathlib import Path

from taskgraph.core.model import Backdrop, Connection, Graph
from taskgraph.core.registry import create_node


def save_graph(graph: Graph, path: str | Path) -> None:
    Path(path).write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")


def load_graph(path: str | Path) -> Graph:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError(f"Unsupported graph version: {data.get('version')}")
    graph = Graph()
    for item in data.get("nodes", []):
        node = create_node(
            item["type"], item["id"], item.get("values"),
            disabled=item.get("disabled", False),
            name=item.get("name"),
        )
        graph.add_node(node, tuple(item.get("position", (0, 0))))
    for item in data.get("connections", []):
        graph.connect(Connection(**item))
    for item in data.get("backdrops", []):
        graph.add_backdrop(Backdrop(
            id=item["id"],
            title=item.get("title", "Notes"),
            note=item.get("note", ""),
            color=item.get("color", "#168c9c"),
            position=tuple(item.get("position", (0, 0))),
            size=tuple(item.get("size", (480, 300))),
        ))
    return graph
