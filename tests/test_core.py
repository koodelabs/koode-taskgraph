from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
import shlex
import sys
import tempfile
from threading import Barrier, Event, Timer
from time import monotonic, sleep
import unittest

from taskgraph.cli import main as cli_main
from taskgraph.core.executor import (
    GraphExecutionCancelled,
    GraphExecutionError,
    execute_graph,
)
from taskgraph.core.model import Backdrop, Connection, Graph, PortSpec, ProcessNode
from taskgraph.core.registry import create_node, load_custom_node_directory
from taskgraph.core.serialization import load_graph, save_graph
from taskgraph.nodes import load_builtin_nodes


def sample_graph() -> Graph:
    graph = Graph()
    number = create_node("input.number", values={"number": 3.0})
    formatter = create_node("text.format", values={"template": "Value: {value}"})
    graph.add_node(number, (10, 20))
    graph.add_node(formatter, (300, 20))
    graph.connect(Connection(number.id, "dependency", formatter.id, "dependency", "dependency"))
    graph.connect(Connection(number.id, "number", formatter.id, "value"))
    return graph


class CoreTests(unittest.TestCase):
    def setUp(self):
        load_builtin_nodes()

    def test_all_process_nodes_inherit_dependency_port_contract(self):
        node = create_node("input.number")
        self.assertEqual(
            node.dependency_input,
            PortSpec("dependency", "dependency", multiple=True),
        )
        self.assertEqual(
            node.dependency_output,
            PortSpec("dependency", "dependency", multiple=True),
        )

    def test_custom_nodes_load_from_external_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            node_directory = Path(directory)
            module = node_directory / "external_nodes.py"
            module.write_text(
                "\n".join([
                    "from taskgraph.core.model import ProcessNode",
                    "from taskgraph.core.registry import register_node",
                    "",
                    "@register_node",
                    "class ExternalTestNode(ProcessNode):",
                    '    type_id = "tests.external_location"',
                    '    title = "External Location Node"',
                    '    category = "External Tests"',
                    "",
                    "    def process(self, inputs):",
                    '        return {"loaded": True}',
                ]),
                encoding="utf-8",
            )
            self.assertEqual(load_custom_node_directory(node_directory), [module.resolve()])
            self.assertEqual(load_custom_node_directory(node_directory), [])
            node = create_node("tests.external_location")
            self.assertEqual(node.process({}), {"loaded": True})

    def test_custom_node_example_loads_and_processes_text(self):
        node_directory = Path(__file__).resolve().parents[1] / "examples" / "custom_nodes"
        loaded = load_custom_node_directory(node_directory)
        self.assertEqual(loaded, [node_directory / "text_cleanup.py"])
        node = create_node(
            "examples.clean_text",
            values={
                "fallback_text": "  daily    production   report  ",
                "case_mode": "Title Case",
            },
        )
        self.assertEqual(
            node.process({}),
            {"text": "Daily Production Report"},
        )

    def test_dependency_execution(self):
        graph = sample_graph()
        result = execute_graph(graph)
        formatter = next(
            node for node in graph.nodes.values() if node.type_id == "text.format"
        )
        self.assertEqual(result.outputs[formatter.id]["text"], "Value: 3.0")
        self.assertEqual(result.order[-1], formatter.id)

    def test_format_text_accepts_multiple_input_values(self):
        graph = Graph()
        first = create_node("input.text", values={"text": "hello"})
        second = create_node("input.text", values={"text": "world"})
        formatter = create_node(
            "text.format",
            values={"template": "{0} {1}"},
        )
        graph.add_node(first)
        graph.add_node(second)
        graph.add_node(formatter)
        graph.connect(Connection(
            first.id, "dependency", formatter.id, "dependency", "dependency"
        ))
        graph.connect(Connection(
            second.id, "dependency", formatter.id, "dependency", "dependency"
        ))
        graph.connect(Connection(first.id, "text", formatter.id, "value"))
        graph.connect(Connection(second.id, "text", formatter.id, "value"))

        result = execute_graph(graph)

        self.assertEqual(result.outputs[formatter.id]["text"], "hello world")

    def test_round_trip(self):
        graph = sample_graph()
        graph.add_backdrop(Backdrop(
            title="Input stage",
            note="These nodes prepare the source data.",
            color="#336699",
            position=(-40, -60),
            size=(720, 360),
        ))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "graph.taskgraph"
            save_graph(graph, path)
            restored = load_graph(path)
        self.assertEqual(restored.to_dict(), graph.to_dict())

    def test_headless_cli_executes_saved_graph_as_json(self):
        graph = sample_graph()
        formatter = next(
            node for node in graph.nodes.values()
            if node.type_id == "text.format"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cli.taskgraph"
            save_graph(graph, path)
            stdout = StringIO()
            stderr = StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli_main([
                    "--file", str(path), "--workers", "2", "--json",
                ])
        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["outputs"][formatter.id]["text"], "Value: 3.0")
        self.assertIn("Running Number", stderr.getvalue())

    def test_headless_cli_loads_custom_nodes_from_environment(self):
        with tempfile.TemporaryDirectory() as directory:
            node_directory = Path(directory) / "nodes"
            node_directory.mkdir()
            module = node_directory / "cli_env_nodes.py"
            module.write_text(
                "\n".join([
                    "from taskgraph.core.model import ProcessNode",
                    "from taskgraph.core.registry import register_node",
                    "",
                    "@register_node",
                    "class CliEnvironmentNode(ProcessNode):",
                    '    type_id = "tests.cli_environment_node"',
                    '    title = "CLI Environment Node"',
                    '    category = "Tests"',
                    "",
                    "    def process(self, inputs):",
                    '        return {"text": "loaded from env"}',
                ]),
                encoding="utf-8",
            )
            graph_path = Path(directory) / "custom_env.taskgraph"
            graph_path.write_text(
                json.dumps({
                    "version": 1,
                    "nodes": [{
                        "id": "custom-node",
                        "type": "tests.cli_environment_node",
                        "values": {},
                        "disabled": False,
                        "name": None,
                        "position": [0, 0],
                    }],
                    "connections": [],
                    "backdrops": [],
                }),
                encoding="utf-8",
            )
            previous = os.environ.get("TASKGRAPH_CUSTOM_NODES")
            os.environ["TASKGRAPH_CUSTOM_NODES"] = str(node_directory)
            stdout = StringIO()
            stderr = StringIO()
            try:
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    exit_code = cli_main(["--file", str(graph_path), "--json"])
            finally:
                if previous is None:
                    os.environ.pop("TASKGRAPH_CUSTOM_NODES", None)
                else:
                    os.environ["TASKGRAPH_CUSTOM_NODES"] = previous

        self.assertEqual(exit_code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["outputs"]["custom-node"],
            {"text": "loaded from env"},
        )

    def test_headless_cli_reports_missing_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.taskgraph"
            stderr = StringIO()
            with redirect_stderr(stderr):
                exit_code = cli_main(["--file", str(missing)])
        self.assertEqual(exit_code, 2)
        self.assertIn("graph file not found", stderr.getvalue())

    def test_cycle_is_rejected(self):
        graph = Graph()
        first = create_node("text.format")
        second = create_node("text.format")
        graph.add_node(first)
        graph.add_node(second)
        graph.connect(Connection(
            first.id, "dependency", second.id, "dependency", "dependency"
        ))
        graph.connect(Connection(
            second.id, "dependency", first.id, "dependency", "dependency"
        ))
        with self.assertRaisesRegex(GraphExecutionError, "cycle"):
            execute_graph(graph)

    def test_fixed_dependency_connection_controls_order_without_transferring_data(self):
        graph = Graph()
        first = create_node("input.number", values={"number": 1})
        second = create_node("input.number", values={"number": 2})
        graph.add_node(first)
        graph.add_node(second)
        graph.connect(Connection(
            first.id, "dependency", second.id, "dependency", "dependency"
        ))
        result = execute_graph(graph)
        self.assertEqual(result.order, [first.id, second.id])
        self.assertEqual(result.outputs[second.id], {"number": 2})

    def test_attribute_connection_requires_dependency_path(self):
        graph = Graph()
        source = create_node("input.number")
        target = create_node("text.format")
        graph.add_node(source)
        graph.add_node(target)
        graph.connect(Connection(source.id, "number", target.id, "value"))
        with self.assertRaisesRegex(
            GraphExecutionError, "requires a dependency path"
        ):
            execute_graph(graph)

    def test_disabled_node_is_persisted_and_skipped(self):
        graph = Graph()
        node = create_node("input.number", disabled=True)
        graph.add_node(node)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "disabled.taskgraph"
            save_graph(graph, path)
            restored = load_graph(path)
        restored_node = restored.nodes[node.id]
        self.assertIs(restored_node.disabled, True)
        result = execute_graph(restored)
        self.assertEqual(result.outputs[node.id], {})

    def test_custom_node_name_is_persisted_and_used_in_execution_log(self):
        graph = Graph()
        node = create_node("input.number", name="Starting Amount")
        graph.add_node(node)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "named.taskgraph"
            save_graph(graph, path)
            restored = load_graph(path)
        messages = []
        execute_graph(restored, messages.append)
        self.assertEqual(restored.nodes[node.id].display_name, "Starting Amount")
        self.assertTrue(
            any("Running Starting Amount" in message for message in messages)
        )

    def test_independent_nodes_execute_in_parallel(self):
        barrier = Barrier(4)

        class ParallelNode(ProcessNode):
            def process(self, inputs):
                barrier.wait(timeout=2)
                return {"finished": True}

        graph = Graph()
        for _index in range(4):
            graph.add_node(ParallelNode())
        result = execute_graph(graph, max_workers=4)
        self.assertEqual(len(result.order), 4)
        self.assertTrue(
            all(output == {"finished": True} for output in result.outputs.values())
        )

    def test_worker_count_accepts_one_or_even_values_up_to_thirty_two(self):
        for count in (1, 2, 4, 16, 32):
            execute_graph(Graph(), max_workers=count)
        for count in (0, 3, 17, 33):
            with self.assertRaisesRegex(ValueError, "even number"):
                execute_graph(Graph(), max_workers=count)

    def test_command_node_captures_output_and_reports_execution_states(self):
        graph = Graph()
        command = shlex.join([sys.executable, "-c", "print('command-ok')"])
        node = create_node(
            "system.command",
            values={"command": command, "shell": False},
            name="Test Command",
        )
        graph.add_node(node)
        states = []
        result = execute_graph(
            graph,
            on_node_state=lambda node_id, state: states.append((node_id, state)),
        )
        self.assertEqual(result.outputs[node.id]["stdout"].strip(), "command-ok")
        self.assertEqual(result.outputs[node.id]["return_code"], 0)
        self.assertEqual(states, [(node.id, "running"), (node.id, "finished")])

    def test_failure_blocks_only_downstream_branch(self):
        executed = []

        class FailingNode(ProcessNode):
            def process(self, inputs):
                raise RuntimeError("intentional failure")

        class IndependentNode(ProcessNode):
            def process(self, inputs):
                sleep(0.03)
                executed.append("independent")
                return {}

        class DownstreamNode(ProcessNode):
            def process(self, inputs):
                executed.append("downstream")
                return {}

        graph = Graph()
        failing = FailingNode(name="Failing branch")
        downstream = DownstreamNode(name="Blocked child")
        independent = IndependentNode(name="Independent branch")
        for node in (failing, downstream, independent):
            graph.add_node(node)
        graph.connect(Connection(
            failing.id, "dependency", downstream.id, "dependency", "dependency"
        ))
        states = {}
        with self.assertRaisesRegex(GraphExecutionError, "intentional failure"):
            execute_graph(
                graph,
                max_workers=2,
                on_node_state=lambda node_id, state: states.__setitem__(node_id, state),
            )
        self.assertEqual(executed, ["independent"])
        self.assertEqual(states[failing.id], "failed")
        self.assertEqual(states[downstream.id], "blocked")
        self.assertEqual(states[independent.id], "finished")

    def test_cancellation_terminates_command_and_cancels_pending_nodes(self):
        graph = Graph()
        command = shlex.join([
            sys.executable, "-c", "import time; time.sleep(10)",
        ])
        running = create_node(
            "system.command",
            values={"command": command, "shell": False},
            name="Long command",
        )
        pending = create_node("input.number", name="Pending child")
        graph.add_node(running)
        graph.add_node(pending)
        graph.connect(Connection(
            running.id, "dependency", pending.id, "dependency", "dependency"
        ))
        cancel_event = Event()
        Timer(0.15, cancel_event.set).start()
        states = {}
        started = monotonic()
        with self.assertRaisesRegex(GraphExecutionCancelled, "cancelled"):
            execute_graph(
                graph,
                max_workers=2,
                cancel_event=cancel_event,
                on_node_state=lambda node_id, state: states.__setitem__(node_id, state),
            )
        self.assertLess(monotonic() - started, 2)
        self.assertEqual(states[running.id], "cancelled")
        self.assertEqual(states[pending.id], "cancelled")


if __name__ == "__main__":
    unittest.main()
