"""Node type registry and custom-node module loading."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from typing import TypeVar

from taskgraph.core.model import ProcessNode

T = TypeVar("T", bound=type[ProcessNode])
_NODE_TYPES: dict[str, type[ProcessNode]] = {}
_LOADED_CUSTOM_MODULES: set[Path] = set()


def register_node(node_class: T) -> T:
    """Register a ``ProcessNode`` subclass by its unique ``type_id``.

    Args:
        node_class: Node class to add to the global registry.

    Returns:
        T: The same class, allowing use as a decorator.

    Raises:
        ValueError: If the class does not define a unique type id.
    """
    if not node_class.type_id or node_class.type_id == ProcessNode.type_id:
        raise ValueError(f"{node_class.__name__} must define a unique type_id")
    if node_class.type_id in _NODE_TYPES:
        raise ValueError(f"Duplicate node type: {node_class.type_id}")
    _NODE_TYPES[node_class.type_id] = node_class
    return node_class


def node_class(type_id: str) -> type[ProcessNode]:
    """Return the registered node class for a type id.

    Args:
        type_id: Registered node type id.

    Returns:
        type[ProcessNode]: Node class registered for the type id.

    Raises:
        ValueError: If no node class has been registered for ``type_id``.
    """
    try:
        return _NODE_TYPES[type_id]
    except KeyError as exc:
        raise ValueError(f"Unknown node type: {type_id}") from exc


def create_node(
    type_id: str,
    node_id: str | None = None,
    values: dict | None = None,
    disabled: bool = False,
    name: str | None = None,
) -> ProcessNode:
    """Instantiate a registered node type.

    Args:
        type_id: Registered node type id.
        node_id: Optional stable id used when loading saved graphs.
        values: Optional property values keyed by property name.
        disabled: Whether the node starts disabled.
        name: Optional user-facing node name.

    Returns:
        ProcessNode: New node instance.
    """
    return node_class(type_id)(
        node_id=node_id, values=values, disabled=disabled, name=name
    )


def nodes_by_category() -> dict[str, list[type[ProcessNode]]]:
    """Return registered node classes grouped and sorted by category.

    Returns:
        dict[str, list[type[ProcessNode]]]: Registered node classes keyed by category.
    """
    result: dict[str, list[type[ProcessNode]]] = defaultdict(list)
    for cls in _NODE_TYPES.values():
        result[cls.category].append(cls)
    return {
        category: sorted(classes, key=lambda cls: cls.title.lower())
        for category, classes in sorted(result.items())
    }


def load_custom_node_directory(directory: str | Path) -> list[Path]:
    """Import standalone custom-node modules from an arbitrary directory.

    Args:
        directory: Folder containing custom ``.py`` node modules.

    Returns:
        list[Path]: Module paths imported during this call.

    Raises:
        ValueError: If ``directory`` does not exist.
        ImportError: If a module cannot be loaded.
        Exception: Re-raises exceptions from imported custom node modules.
    """
    location = Path(directory).expanduser().resolve()
    if not location.is_dir():
        raise ValueError(f"Custom node location does not exist: {location}")

    loaded = []
    for path in sorted(location.glob("*.py")):
        if path.name.startswith("_") or path in _LOADED_CUSTOM_MODULES:
            continue
        module_name = (
            "_taskgraph_custom_"
            + sha256(str(path).encode("utf-8")).hexdigest()[:20]
        )
        spec = spec_from_file_location(module_name, path)
        if not spec or not spec.loader:
            raise ImportError(f"Could not load custom node module: {path}")
        module = module_from_spec(spec)
        registered_before = set(_NODE_TYPES)
        sys.modules[module_name] = module
        sys.path.insert(0, str(location))
        try:
            spec.loader.exec_module(module)
        except Exception:
            for type_id in set(_NODE_TYPES) - registered_before:
                _NODE_TYPES.pop(type_id, None)
            sys.modules.pop(module_name, None)
            raise
        finally:
            try:
                sys.path.remove(str(location))
            except ValueError:
                pass
        _LOADED_CUSTOM_MODULES.add(path)
        loaded.append(path)
    return loaded
