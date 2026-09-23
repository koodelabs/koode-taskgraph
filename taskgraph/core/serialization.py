"""Read and write ``.taskgraph`` files."""

import json
from pathlib import Path

from taskgraph.core.model import Backdrop, Connection, Graph
from taskgraph.core.registry import create_node


def save_graph(graph: Graph, path: str | Path) -> None:
    """Write a graph to disk as formatted JSON.

    Args:
        graph: Graph model to serialize.
        path: Destination ``.taskgraph`` or JSON file path.

    Returns:
        None.
    """
    Path(path).write_text(json.dumps(graph.to_dict(), indent=2), encoding="utf-8")


def load_graph(path: str | Path) -> Graph:
    """Load a graph from disk and recreate node/backdrop/connection objects.

    Args:
        path: Source ``.taskgraph`` or JSON file path.

    Returns:
        Graph: Recreated graph model.

    Raises:
        ValueError: If the saved graph version is not supported.
        json.JSONDecodeError: If the file is not valid JSON.
    """
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
