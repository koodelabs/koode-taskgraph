from taskgraph.ui.plugins import TaskGraphGuiPlugin


class Plugin(TaskGraphGuiPlugin):
    plugin_id = "examples.command_validate_graph"
    name = "Validate Graph Command"
    version = "1.0.0"

    def setup(self) -> None:
        self.commands.register(
            f"{self.plugin_id}.validate_graph",
            label="Command API: Validate Current Graph",
            callback=self.validate_graph,
        )
        self.ui.menus.add_command(
            "Examples/Commands",
            f"{self.plugin_id}.validate_graph",
        )

    def validate_graph(self) -> None:
        graph = self.graph.model
        node_count = len(graph.nodes)
        connection_count = len(graph.connections)
        missing_dependencies = [
            connection for connection in graph.connections
            if connection.kind == "attribute"
            and not self.graph.has_dependency_path(
                connection.source_node,
                connection.target_node,
            )
        ]

        if missing_dependencies:
            message = (
                "Graph validation failed: "
                f"{len(missing_dependencies)} attribute connection(s) do not "
                "have a dependency path."
            )
        else:
            message = (
                "Graph validation passed: "
                f"{node_count} node(s), {connection_count} connection(s)."
            )

        self.ui.status.show_message(message)
        self.api.console.appendPlainText(message)
