from qtpy.QtWidgets import QLabel

from taskgraph.ui.plugins import TaskGraphGuiPlugin


class Plugin(TaskGraphGuiPlugin):
    plugin_id = "examples.ui_project_notes"
    name = "Project Notes Panel"
    version = "1.0.0"

    def setup(self) -> None:
        self.commands.register(
            f"{self.plugin_id}.open_notes",
            label="UI API: Open Project Notes Panel",
            callback=self.open_notes_panel,
        )
        self.ui.menus.add_command(
            "Examples",
            f"{self.plugin_id}.open_notes",
        )

    def open_notes_panel(self) -> None:
        label = QLabel(
            "Project Notes\n\n"
            "- Use backdrops to document graph sections.\n"
            "- Use dependency links to control execution order.\n"
            "- Validate the graph before handing it to another user."
        )
        label.setWordWrap(True)
        self.ui.docks.add("Project Notes", label)
        self.ui.status.show_message("Opened the Project Notes plugin panel")
