from pathlib import Path
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtCore import QSettings
from qtpy.QtWidgets import QApplication, QLineEdit, QWidget

from taskgraph.nodes import load_builtin_nodes
from taskgraph.core.model import Connection, Graph, NodeProperty, ProcessNode
from taskgraph.core.registry import create_node
from taskgraph.ui import main_window as main_window_module
from taskgraph.ui.main_window import MainWindow, NodePalette
from taskgraph.ui.properties import PropertyEditor
from taskgraph.ui.plugins import load_gui_plugin_directory
from taskgraph.ui.scene import GraphScene

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class GuiPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        load_builtin_nodes()
        self.window = MainWindow()

    def tearDown(self):
        self.window.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def test_oop_gui_plugin_can_add_menu_action_and_build_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin_directory = Path(directory)
            plugin = plugin_directory / "graph_builder.py"
            plugin.write_text(
                "\n".join([
                    "from taskgraph.ui.plugins import TaskGraphGuiPlugin",
                    "",
                    "",
                    "class Plugin(TaskGraphGuiPlugin):",
                    "    plugin_id = 'tests.graph_builder'",
                    "    name = 'Graph Builder'",
                    "",
                    "    def setup(self):",
                    "        self.commands.register(",
                    "            f'{self.plugin_id}.build_sample_graph',",
                    "            label='Build Sample Graph',",
                    "            callback=self.build_graph,",
                    "        )",
                    "        self.ui.menus.add_command(",
                    "            'Tools',",
                    "            f'{self.plugin_id}.build_sample_graph',",
                    "        )",
                    "",
                    "    def build_graph(self):",
                    "        text = self.graph.create_node(",
                    "            'input.text',",
                    "            values={'text': 'hello'},",
                    "            name='Message',",
                    "            position=(10, 20),",
                    "        )",
                    "        formatter = self.graph.create_node(",
                    "            'text.format',",
                    "            values={'template': 'Output: {value}'},",
                    "            name='Formatter',",
                    "            position=(260, 20),",
                    "        )",
                    "        self.graph.connect_dependency(text, formatter)",
                    "        self.graph.connect_attribute(",
                    "            text, 'text', formatter, 'value'",
                    "        )",
                    "        self.graph.add_backdrop(",
                    "            title='Plugin Notes',",
                    "            note='Created by a GUI plugin.',",
                    "            position=(0, -120),",
                    "            size=(420, 160),",
                    "        )",
                ]),
                encoding="utf-8",
            )

            self.assertEqual(
                load_gui_plugin_directory(plugin_directory, self.window),
                [plugin.resolve()],
            )

        tools_menu = self.window.menus["tools"]
        actions = [action for action in tools_menu.actions() if action.text() == "Build Sample Graph"]
        self.assertEqual(len(actions), 1)
        actions[0].trigger()

        nodes = list(self.window.scene.graph.nodes.values())
        self.assertEqual([node.display_name for node in nodes], ["Message", "Formatter"])
        self.assertEqual(nodes[0].values["text"], "hello")
        self.assertEqual(nodes[1].values["template"], "Output: {value}")
        self.assertEqual(len(self.window.scene.graph.connections), 2)
        self.assertEqual(
            {connection.kind for connection in self.window.scene.graph.connections},
            {"attribute", "dependency"},
        )
        backdrops = list(self.window.scene.graph.backdrops.values())
        self.assertEqual(len(backdrops), 1)
        self.assertEqual(backdrops[0].title, "Plugin Notes")

    def test_gui_plugin_legacy_flat_api_still_works(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin_directory = Path(directory)
            plugin = plugin_directory / "legacy_graph_builder.py"
            plugin.write_text(
                "\n".join([
                    "def register_taskgraph_plugin(api):",
                    "    def build_graph():",
                    "        text = api.create_node(",
                    "            'input.text', values={'text': 'legacy'}",
                    "        )",
                    "        printer = api.create_node('output.print')",
                    "        api.connect_dependency(text, printer)",
                    "        api.connect_attribute(text, 'text', printer, 'value')",
                    "    api.add_menu_action(",
                    "        'Tools', 'Build Legacy Graph', build_graph",
                    "    )",
                ]),
                encoding="utf-8",
            )

            self.assertEqual(
                load_gui_plugin_directory(plugin_directory, self.window),
                [plugin.resolve()],
            )

        tools_menu = self.window.menus["tools"]
        actions = [
            action for action in tools_menu.actions()
            if action.text() == "Build Legacy Graph"
        ]
        self.assertEqual(len(actions), 1)
        actions[0].trigger()

        nodes = list(self.window.scene.graph.nodes.values())
        self.assertEqual([node.type_id for node in nodes], [
            "input.text",
            "output.print",
        ])
        self.assertEqual(nodes[0].values["text"], "legacy")
        self.assertEqual(len(self.window.scene.graph.connections), 2)

    def test_add_gui_plugin_location_does_not_persist_for_auto_load(self):
        settings = QSettings()
        settings.remove("plugins/custom_locations")
        with tempfile.TemporaryDirectory() as directory:
            plugin_directory = Path(directory)
            plugin = plugin_directory / "session_plugin.py"
            plugin.write_text(
                "\n".join([
                    "from taskgraph.ui.plugins import TaskGraphGuiPlugin",
                    "",
                    "class Plugin(TaskGraphGuiPlugin):",
                    "    plugin_id = 'tests.session_plugin'",
                    "",
                    "    def setup(self):",
                    "        self.commands.register(",
                    "            f'{self.plugin_id}.noop',",
                    "            label='Session Plugin Action',",
                    "            callback=lambda: None,",
                    "        )",
                    "        self.ui.menus.add_command(",
                    "            'Tools', f'{self.plugin_id}.noop'",
                    "        )",
                ]),
                encoding="utf-8",
            )
            original_picker = main_window_module.QFileDialog.getExistingDirectory
            main_window_module.QFileDialog.getExistingDirectory = staticmethod(
                lambda *_args, **_kwargs: str(plugin_directory)
            )
            try:
                self.window.add_gui_plugin_location()
            finally:
                main_window_module.QFileDialog.getExistingDirectory = original_picker

        self.assertIsNone(settings.value("plugins/custom_locations", None))
        tools_menu = self.window.menus["tools"]
        self.assertIn(
            "Session Plugin Action",
            [action.text() for action in tools_menu.actions()],
        )

    def test_separate_api_example_plugins_are_practical(self):
        plugin_directory = PROJECT_ROOT / "examples" / "gui_plugins"
        loaded = load_gui_plugin_directory(plugin_directory, self.window)
        self.assertEqual(loaded, [
            plugin_directory / "command_validate_graph.py",
            plugin_directory / "graph_daily_report.py",
            plugin_directory / "ui_project_notes.py",
        ])

        examples_menu = self.window.menus["examples"]
        action_labels = [action.text() for action in examples_menu.actions()]
        self.assertEqual(action_labels, [
            "Command API: Validate Current Graph",
            "Graph API: Build Daily Report Graph",
            "UI API: Open Project Notes Panel",
        ])

        self._trigger_example_action("Command API: Validate Current Graph")
        self.assertEqual(
            self.window.statusBar().currentMessage(),
            "Graph validation passed: 0 node(s), 0 connection(s).",
        )
        self.assertIn(
            "Graph validation passed: 0 node(s), 0 connection(s).",
            self.window.console.toPlainText(),
        )

        self._trigger_example_action("UI API: Open Project Notes Panel")
        self.assertEqual(self.window.plugin_docks[-1].windowTitle(), "Project Notes")
        self.assertEqual(
            self.window.statusBar().currentMessage(),
            "Opened the Project Notes plugin panel",
        )

        self._trigger_example_and_assert_graph(
            action_text="Graph API: Build Daily Report Graph",
            node_names=[
                "Report Title",
                "Report Status",
                "Format Report",
                "Print Report",
            ],
            text_value="Daily Production Report",
        )

    def _trigger_example_action(self, action_text):
        examples_menu = self.window.menus["examples"]
        actions = [
            action for action in examples_menu.actions()
            if action.text() == action_text
        ]
        self.assertEqual(len(actions), 1)
        actions[0].trigger()

    def _trigger_example_and_assert_graph(self, action_text, node_names, text_value):
        self._trigger_example_action(action_text)

        nodes = list(self.window.scene.graph.nodes.values())
        self.assertEqual([node.display_name for node in nodes], node_names)
        self.assertEqual(nodes[0].type_id, "input.text")
        self.assertEqual(nodes[0].values["text"], text_value)
        self.assertEqual(nodes[-1].type_id, "output.print")
        self.assertEqual(len(self.window.scene.graph.connections), 6)
        self.assertEqual(
            {connection.kind for connection in self.window.scene.graph.connections},
            {"attribute", "dependency"},
        )
        self.assertEqual(len(self.window.scene.graph.backdrops), 1)


class PropertyEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_file_property_uses_browse_widget_and_stores_text_path(self):
        class FileNode(ProcessNode):
            title = "File Node"
            type_id = "tests.file_node"
            properties = (
                NodeProperty("source_file", "Source File", "file", ""),
            )

        node = FileNode()
        editor = PropertyEditor()
        editor.set_node(node)

        file_widgets = [
            widget for widget in editor.findChildren(QWidget)
            if widget.findChild(QLineEdit)
        ]
        path_editor = file_widgets[-1].findChild(QLineEdit)
        path_editor.setText("/tmp/example.txt")
        path_editor.editingFinished.emit()

        self.assertEqual(node.values["source_file"], "/tmp/example.txt")


class ConnectionItemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        load_builtin_nodes()

    def test_multi_input_attribute_connections_report_visible_indices(self):
        graph = Graph()
        first = create_node("input.text", values={"text": "first"})
        second = create_node("input.text", values={"text": "second"})
        formatter = create_node("text.format")
        graph.add_node(first)
        graph.add_node(second)
        graph.add_node(formatter)
        graph.connect(Connection(first.id, "text", formatter.id, "value"))
        graph.connect(Connection(second.id, "text", formatter.id, "value"))

        scene = GraphScene(graph)

        attribute_items = [
            item for item in scene.connection_items
            if item.connection and item.connection.kind == "attribute"
        ]
        self.assertEqual(
            [item.multi_input_index() for item in attribute_items],
            [0, 1],
        )


class NodePaletteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        load_builtin_nodes()
        self.palette = NodePalette()

    def tearDown(self):
        self.palette.deleteLater()
        self.app.processEvents()

    def visible_nodes(self):
        result = []
        for category_index in range(self.palette.tree.topLevelItemCount()):
            category = self.palette.tree.topLevelItem(category_index)
            for child_index in range(category.childCount()):
                result.append(category.child(child_index).text(0))
        return result

    def visible_categories(self):
        return [
            self.palette.tree.topLevelItem(index).text(0)
            for index in range(self.palette.tree.topLevelItemCount())
        ]

    def test_node_palette_filters_by_title_type_id_and_category(self):
        self.assertIn("Format Text", self.visible_nodes())

        self.palette.search.setText("print")
        self.assertEqual(self.visible_nodes(), ["Print"])

        self.palette.search.setText("system.command")
        self.assertEqual(self.visible_nodes(), ["Run Command"])

        self.palette.search.setText("inputs")
        self.assertEqual(self.visible_categories(), ["Inputs"])
        self.assertEqual(self.visible_nodes(), ["Number", "Text"])


if __name__ == "__main__":
    unittest.main()
