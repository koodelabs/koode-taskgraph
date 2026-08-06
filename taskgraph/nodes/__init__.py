"""Node discovery.

Every Python module placed in this package is imported at startup, so extending
the application only requires adding a module containing registered nodes.
"""

from importlib import import_module
from pkgutil import iter_modules


def load_builtin_nodes() -> None:
    for module in iter_modules(__path__, f"{__name__}."):
        if not module.name.rsplit(".", 1)[-1].startswith("_"):
            import_module(module.name)
