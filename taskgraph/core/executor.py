from __future__ import annotations

from collections import defaultdict, deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable

from taskgraph.core.model import Connection, Graph, NodeCancelled

VALID_WORKER_COUNTS = (1, *range(2, 33, 2))


class GraphExecutionError(RuntimeError):
    pass


class GraphExecutionCancelled(GraphExecutionError):
    pass


@dataclass
class ExecutionResult:
    order: list[str]
    outputs: dict[str, dict[str, Any]]


def execute_graph(
    graph: Graph,
    on_event: Callable[[str], None] | None = None,
    max_workers: int = 4,
    on_node_state: Callable[[str, str], None] | None = None,
    cancel_event: Event | None = None,
) -> ExecutionResult:
    return GraphExecutor(
        graph,
        on_event=on_event,
        on_node_state=on_node_state,
        cancel_event=cancel_event,
    ).execute(max_workers=max_workers)


class GraphExecutor:
    def __init__(
        self,
        graph: Graph,
        on_event: Callable[[str], None] | None = None,
        on_node_state: Callable[[str, str], None] | None = None,
        cancel_event: Event | None = None,
    ):
        self.graph = graph
        self.emit = on_event or (lambda _message: None)
        self.set_state = on_node_state or (lambda _node_id, _state: None)
        self.cancel_event = cancel_event or Event()
        self.indegree = {node_id: 0 for node_id in graph.nodes}
        self.downstream: dict[str, list[str]] = defaultdict(list)
        self.incoming: dict[str, list[Connection]] = defaultdict(list)
        self.attribute_edges: list[Connection] = []
        self.queue: deque[str] = deque()
        self.order: list[str] = []
        self.outputs: dict[str, dict[str, Any]] = {}
        self.terminal: set[str] = set()
        self.failures: list[str] = []
        self.running: dict[Future[dict[str, Any]], str] = {}
        self.cancellation_applied = False

    def execute(self, max_workers: int = 4) -> ExecutionResult:
        self._validate_worker_count(max_workers)
        self._prepare_connections()
        self._validate_attribute_dependencies()
        self.queue = deque(
            node_id for node_id, degree in self.indegree.items()
            if degree == 0
        )
        self._run(max_workers)
        self._raise_if_cancelled()
        self._raise_if_unresolved_or_failed()
        return ExecutionResult(self.order, self.outputs)

    @staticmethod
    def _validate_worker_count(max_workers: int) -> None:
        if max_workers not in VALID_WORKER_COUNTS:
            raise ValueError(
                "max_workers must be 1 or an even number between 2 and 32"
            )

    def _prepare_connections(self) -> None:
        for edge in self.graph.connections:
            if (
                edge.source_node not in self.graph.nodes
                or edge.target_node not in self.graph.nodes
            ):
                raise GraphExecutionError("A connection references a missing node")
            if edge.kind == "dependency":
                self.indegree[edge.target_node] += 1
                self.downstream[edge.source_node].append(edge.target_node)
            else:
                self.attribute_edges.append(edge)
                self.incoming[edge.target_node].append(edge)

    def _validate_attribute_dependencies(self) -> None:
        for edge in self.attribute_edges:
            if not self._has_dependency_path(edge.source_node, edge.target_node):
                source = self.graph.nodes[edge.source_node]
                target = self.graph.nodes[edge.target_node]
                raise GraphExecutionError(
                    f"Attribute {source.display_name}.{edge.source_port} -> "
                    f"{target.display_name}.{edge.target_port} requires a dependency path"
                )

    def _has_dependency_path(self, source: str, target: str) -> bool:
        pending = [source]
        visited = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current not in visited:
                visited.add(current)
                pending.extend(self.downstream[current])
        return False

    def _run(self, max_workers: int) -> None:
        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="taskgraph",
        ) as pool:
            while self.queue or self.running:
                self._apply_cancellation_if_requested()
                self._submit_ready_nodes(pool, max_workers)
                if not self.running:
                    continue
                finished, _pending = wait(
                    self.running,
                    return_when=FIRST_COMPLETED,
                )
                self._handle_finished_futures(finished)

    def _apply_cancellation_if_requested(self) -> None:
        if not self.cancel_event.is_set() or self.cancellation_applied:
            return
        self.cancellation_applied = True
        self.emit("Cancellation requested...")
        running_ids = set(self.running.values())
        for future in self.running:
            future.cancel()
        for node_id in self.graph.nodes:
            if node_id not in self.terminal and node_id not in running_ids:
                self.terminal.add(node_id)
                self.set_state(node_id, "cancelled")
        self.queue.clear()

    def _submit_ready_nodes(
        self,
        pool: ThreadPoolExecutor,
        max_workers: int,
    ) -> None:
        while self.queue and len(self.running) < max_workers:
            node_id = self.queue.popleft()
            if node_id in self.terminal:
                continue
            node = self.graph.nodes[node_id]
            if node.disabled:
                self.emit(f"Skipped disabled node: {node.display_name}")
                self.set_state(node_id, "skipped")
                self._complete(node_id, {})
                continue
            try:
                node_inputs = self._inputs_for(node_id)
            except GraphExecutionError as exc:
                self._fail_branch(node_id, str(exc))
                continue
            self.emit(f"Running {node.display_name}")
            self.set_state(node_id, "running")
            node._cancel_event = self.cancel_event
            self.running[pool.submit(node.process, node_inputs)] = node_id

    def _inputs_for(self, node_id: str) -> dict[str, Any]:
        node = self.graph.nodes[node_id]
        node_inputs: dict[str, Any] = {}
        for edge in self.incoming[node_id]:
            source_outputs = self.outputs.get(edge.source_node, {})
            if edge.source_port not in source_outputs:
                source = self.graph.nodes[edge.source_node]
                raise GraphExecutionError(
                    f"{node.display_name}: input '{edge.target_port}' is unavailable "
                    f"because {source.display_name} did not produce '{edge.source_port}'"
                )
            value = source_outputs[edge.source_port]
            port = next(
                spec for spec in node.inputs
                if spec.name == edge.target_port
            )
            if port.multiple:
                node_inputs.setdefault(edge.target_port, []).append(value)
            else:
                node_inputs[edge.target_port] = value

        missing = [
            port.name for port in node.inputs
            if port.required and port.name not in node_inputs
        ]
        if missing:
            raise GraphExecutionError(
                f"{node.display_name}: missing required input(s): {', '.join(missing)}"
            )
        return node_inputs

    def _handle_finished_futures(
        self,
        finished: set[Future[dict[str, Any]]],
    ) -> None:
        for future in finished:
            node_id = self.running.pop(future)
            node = self.graph.nodes[node_id]
            try:
                if self.cancel_event.is_set():
                    self._discard_cancelled_future(future)
                    self._mark_cancelled(node_id)
                    continue
                result = future.result()
            except NodeCancelled:
                self._mark_cancelled(node_id)
                continue
            except Exception as exc:
                self._fail_branch(node_id, f"{node.display_name} failed: {exc}")
                continue
            finally:
                node._cancel_event = None

            if not isinstance(result, dict):
                self._fail_branch(
                    node_id,
                    f"{node.display_name} must return a dictionary",
                )
                continue
            self._complete(node_id, result)
            self.set_state(node_id, "finished")
            self.emit(f"Finished {node.display_name}: {result}")

    @staticmethod
    def _discard_cancelled_future(future: Future[dict[str, Any]]) -> None:
        try:
            future.result()
        except Exception:
            pass

    def _mark_cancelled(self, node_id: str) -> None:
        node = self.graph.nodes[node_id]
        self.terminal.add(node_id)
        self.set_state(node_id, "cancelled")
        self.emit(f"Cancelled {node.display_name}")

    def _complete(self, node_id: str, result: dict[str, Any]) -> None:
        self.outputs[node_id] = result
        self.order.append(node_id)
        self.terminal.add(node_id)
        for target in self.downstream[node_id]:
            self.indegree[target] -= 1
            if self.indegree[target] == 0:
                self.queue.append(target)

    def _fail_branch(self, node_id: str, message: str) -> None:
        """Fail one node and block only nodes that depend on its output."""
        if node_id in self.terminal:
            return
        self.terminal.add(node_id)
        self.failures.append(message)
        self.set_state(node_id, "failed")
        self.emit(f"Failure: {message}")
        pending = deque(self.downstream[node_id])
        while pending:
            blocked_id = pending.popleft()
            if blocked_id in self.terminal:
                continue
            self.terminal.add(blocked_id)
            self.set_state(blocked_id, "blocked")
            self.emit(
                f"Blocked {self.graph.nodes[blocked_id].display_name}: "
                "an upstream dependency failed"
            )
            pending.extend(self.downstream[blocked_id])

    def _raise_if_cancelled(self) -> None:
        if not self.cancel_event.is_set():
            return
        for node_id in self.graph.nodes:
            if node_id not in self.terminal:
                self.terminal.add(node_id)
                self.set_state(node_id, "cancelled")
        raise GraphExecutionCancelled("Graph execution cancelled")

    def _raise_if_unresolved_or_failed(self) -> None:
        unresolved = set(self.graph.nodes) - self.terminal
        if unresolved:
            self.failures.append("The graph contains a cycle and cannot be executed")
            for node_id in unresolved:
                self.set_state(node_id, "blocked")
        if self.failures:
            raise GraphExecutionError("\n".join(self.failures))
