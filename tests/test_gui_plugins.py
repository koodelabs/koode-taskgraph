from pathlib import Path
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qtpy.QtWidgets import QApplication, QLineEdit, QWidget

from taskgraph.nodes import load_builtin_nodes
from taskgraph.core.model import Graph, NodeProperty, ProcessNode
from taskgraph.ui.main_window import MainWindow
from taskgraph.ui.properties import PropertyEditor
from taskgraph.ui.plugins import load_gui_plugin_directory

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

    def test_gui_plugin_can_add_menu_action_and_build_nodes(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin_directory = Path(directory)
            plugin = plugin_directory / "graph_builder.py"
            plugin.write_text(
                "\n".join([
                    "def register_taskgraph_plugin(api):",
                    "    def build_graph():",
                    "        text = api.create_node(",
                    "            'input.text',",
                    "            values={'text': 'hello'},",
                    "            name='Message',",
                    "            position=(10, 20),",
                    "        )",
                    "        formatter = api.create_node(",
                    "            'text.format',",
                    "            values={'template': 'Output: {value}'},",
                    "            name='Formatter',",
                    "            position=(260, 20),",
                    "        )",
                    "        api.connect_dependency(text, formatter)",
                    "        api.connect_attribute(text, 'text', formatter, 'value')",
                    "        api.add_backdrop(",
                    "            title='Plugin Notes',",
                    "            note='Created by a GUI plugin.',",
                    "            position=(0, -120),",
                    "            size=(420, 160),",
                    "        )",
                    "    api.add_menu_action('Tools', 'Build Sample Graph', build_graph)",
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

    def test_example_print_plugins(self):
        plugin_directory = PROJECT_ROOT / "examples" / "gui_plugins"
        loaded = load_gui_plugin_directory(plugin_directory, self.window)
        self.assertIn(plugin_directory / "hello_world_print.py", loaded)
        self.assertIn(plugin_directory / "bingooo_print.py", loaded)

        self._trigger_example_and_assert_graph(
            action_text="Create Hello World Print Graph",
            node_names=["Hello World Text", "Print Hello World"],
            text_value="hello world",
        )
        self.window.scene.set_graph(Graph())
        self.window.dirty = False
        self._trigger_example_and_assert_graph(
            action_text="Create Bingooo Print Graph",
            node_names=["Bingooo Text", "Print Bingooo"],
            text_value="Bingooo!!",
        )

    def _trigger_example_and_assert_graph(self, action_text, node_names, text_value):
        examples_menu = self.window.menus["examples"]
        actions = [
            action for action in examples_menu.actions()
            if action.text() == action_text
        ]
        self.assertEqual(len(actions), 1)
        actions[0].trigger()

        nodes = list(self.window.scene.graph.nodes.values())
        self.assertEqual([node.display_name for node in nodes], node_names)
        self.assertEqual(nodes[0].type_id, "input.text")
        self.assertEqual(nodes[0].values["text"], text_value)
        self.assertEqual(nodes[1].type_id, "output.print")
        self.assertEqual(len(self.window.scene.graph.connections), 2)
        self.assertEqual(
            {connection.kind for connection in self.window.scene.graph.connections},
            {"attribute", "dependency"},
        )


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


if __name__ == "__main__":
    unittest.main()
