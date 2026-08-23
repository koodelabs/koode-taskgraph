import os
import sys

from qtpy.QtCore import QSettings
from qtpy.QtWidgets import QApplication

from taskgraph.core.registry import load_custom_node_directory
from taskgraph.nodes import load_builtin_nodes
from taskgraph.ui.main_window import MainWindow
from taskgraph.ui.plugins import load_gui_plugin_directory


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("TaskGraph")
    app.setOrganizationName("TaskGraph")
    load_builtin_nodes()
    saved_locations = QSettings().value("nodes/custom_locations", [])
    if isinstance(saved_locations, str):
        saved_locations = [saved_locations]
    environment_locations = [
        path for path in os.environ.get("TASKGRAPH_CUSTOM_NODES", "").split(os.pathsep)
        if path
    ]
    load_errors = []
    for location in dict.fromkeys([*saved_locations, *environment_locations]):
        try:
            load_custom_node_directory(location)
        except Exception as exc:
            load_errors.append(f"{location}: {exc}")
    window = MainWindow()
    environment_plugin_locations = [
        path for path in os.environ.get("TASKGRAPH_GUI_PLUGINS", "").split(os.pathsep)
        if path
    ]
    for location in dict.fromkeys(environment_plugin_locations):
        try:
            load_gui_plugin_directory(location, window)
        except Exception as exc:
            load_errors.append(f"{location}: {exc}")
    window.palette.reload()
    if load_errors:
        window.console.appendPlainText(
            "Custom loading errors:\n" + "\n".join(load_errors)
        )
    window.show()
    return app.exec()
