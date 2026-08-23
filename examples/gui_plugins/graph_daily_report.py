from taskgraph.ui.plugins import TaskGraphGuiPlugin


class Plugin(TaskGraphGuiPlugin):
    plugin_id = "examples.graph_daily_report"
    name = "Daily Report Graph Builder"
    version = "1.0.0"

    def setup(self) -> None:
        self.commands.register(
            f"{self.plugin_id}.build_daily_report",
            label="Graph API: Build Daily Report Graph",
            callback=self.build_daily_report,
        )
        self.ui.menus.add_command(
            "Examples/Graph Builders",
            f"{self.plugin_id}.build_daily_report",
        )

    def build_daily_report(self) -> None:
        title = self.graph.create_node(
            "input.text",
            name="Report Title",
            values={"text": "Daily Production Report"},
            position=(0, 0),
        )
        status = self.graph.create_node(
            "input.text",
            name="Report Status",
            values={"text": "All scheduled tasks completed."},
            position=(0, 140),
        )
        formatter = self.graph.create_node(
            "text.format",
            name="Format Report",
            values={"template": "{0}\n\nStatus: {1}"},
            position=(330, 60),
        )
        printer = self.graph.create_node(
            "output.print",
            name="Print Report",
            position=(660, 60),
        )

        self.graph.connect_dependency(title, formatter)
        self.graph.connect_dependency(status, formatter)
        self.graph.connect_dependency(formatter, printer)
        self.graph.connect_attribute(title, "text", formatter, "value")
        self.graph.connect_attribute(status, "text", formatter, "value")
        self.graph.connect_attribute(formatter, "text", printer, "value")
        self.graph.add_backdrop(
            title="Daily Report Template",
            note=(
                "Practical graph API example: build a reusable report graph "
                "from input nodes, a formatter node, and a print node."
            ),
            position=(-40, -110),
            size=(940, 360),
        )
