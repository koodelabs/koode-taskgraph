"""Dependency-based graph execution engine."""

from __future__ import annotations

from collections import defaultdict, deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable

from taskgraph.core.model import Connection, Graph, NodeCancelled

VALID_WORKER_COUNTS = (1, *range(2, 33, 2))


class GraphExecutionError(RuntimeError):
    """Raised when graph execution fails for validation or node errors.

    This is the public base exception for graph execution failures.
    """

    pass


class GraphExecutionCancelled(GraphExecutionError):
    """Raised when graph execution is cancelled by the caller/user.

    This exception is raised after the executor marks pending nodes cancelled.
    """

    pass


@dataclass
class ExecutionResult:
    """Final graph execution output and executed node order.

    Attributes:
        order: Node ids in the order they finished successfully.
        outputs: Output dictionaries keyed first by node id, then by port name.
    """

    order: list[str]
    outputs: dict[str, dict[str, Any]]


def execute_graph(
    graph: Graph,
    on_event: Callable[[str], None] | None = None,
    max_workers: int = 4,
    on_node_state: Callable[[str, str], None] | None = None,
    cancel_event: Event | None = None,
) -> ExecutionResult:
    """Execute a graph with optional logging, state callbacks, and cancellation.

    Args:
        graph: Graph model to execute.
        on_event: Optional callback for execution log messages.
        max_workers: Number of worker threads to use.
        on_node_state: Optional callback receiving ``(node_id, state)``.
        cancel_event: Optional event used to request cooperative cancellation.

    Returns:
        ExecutionResult: Completed node order and node outputs.

    Raises:
        ValueError: If ``max_workers`` is not an allowed worker count.
        GraphExecutionError: If validation or node execution fails.
        GraphExecutionCancelled: If cancellation is requested during execution.
    """
    return GraphExecutor(
        graph,
        on_event=on_event,
        on_node_state=on_node_state,
        cancel_event=cancel_event,
    ).execute(max_workers=max_workers)


class GraphExecutor:
    """Run graph nodes according to dependency connections.

    Attributes:
        graph: Graph model being executed.
        emit: Callback used for execution log messages.
        set_state: Callback used for node visual state changes.
        cancel_event: Event used to request cooperative cancellation.
        outputs: Completed node outputs keyed by node id.
    """

    def __init__(
        self,
        graph: Graph,
        on_event: Callable[[str], None] | None = None,
        on_node_state: Callable[[str, str], None] | None = None,
        cancel_event: Event | None = None,
    ):
        """Prepare executor state for one graph execution.

        Args:
            graph: Graph model to execute.
            on_event: Optional callback for execution log messages.
            on_node_state: Optional callback receiving ``(node_id, state)``.
            cancel_event: Optional event used to request cancellation.

        Returns:
            None.
        """
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
        """Validate and run the graph, returning node order and outputs.

        Args:
            max_workers: Number of worker threads used for parallel branches.

        Returns:
            ExecutionResult: Completed node order and node outputs.

        Raises:
            ValueError: If ``max_workers`` is not supported.
            GraphExecutionError: If the graph cannot be executed.
            GraphExecutionCancelled: If cancellation is requested.
        """
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
        """Reject unsupported worker counts before starting execution.

        Args:
            max_workers: Requested worker count.

        Returns:
            None.

        Raises:
            ValueError: If the worker count is not 1 or an even number up to 32.
        """
        if max_workers not in VALID_WORKER_COUNTS:
            raise ValueError(
                "max_workers must be 1 or an even number between 2 and 32"
            )

    def _prepare_connections(self) -> None:
        """Split graph connections into dependency and attribute lookup tables.

        Returns:
            None.

        Raises:
            GraphExecutionError: If a connection references a missing node.
        """
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
        """Ensure every value connection also has a dependency path.

        Returns:
            None.

        Raises:
            GraphExecutionError: If an attribute edge has no dependency path.
        """
        for edge in self.attribute_edges:
            if not self._has_dependency_path(edge.source_node, edge.target_node):
                source = self.graph.nodes[edge.source_node]
                target = self.graph.nodes[edge.target_node]
                raise GraphExecutionError(
                    f"Attribute {source.display_name}.{edge.source_port} -> "
                    f"{target.display_name}.{edge.target_port} requires a dependency path"
                )

    def _has_dependency_path(self, source: str, target: str) -> bool:
        """Return whether target is reachable from source through dependencies.

        Args:
            source: Source node id.
            target: Target node id.

        Returns:
            bool: True when a dependency path connects source to target.
        """
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
        """Run ready nodes until there is no queued or running work.

        Args:
            max_workers: Number of worker threads available.

        Returns:
            None.
        """
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
        """Mark pending work cancelled after the cancellation event is set.

        Returns:
            None.
        """
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
        """Submit queued nodes to the thread pool while capacity is available.

        Args:
            pool: Thread pool used to execute node ``process`` methods.
            max_workers: Maximum number of simultaneously running futures.

        Returns:
            None.
        """
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
            node._event_callback = self.emit
            self.running[pool.submit(node.process, node_inputs)] = node_id

    def _inputs_for(self, node_id: str) -> dict[str, Any]:
        """Build the process input dictionary for a ready node.

        Args:
            node_id: Id of the node that is about to run.

        Returns:
            dict[str, Any]: Input values keyed by target input port name.

        Raises:
            GraphExecutionError: If a required upstream output is missing.
        """
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
        """Collect completed node results and update dependency state.

        Args:
            finished: Futures returned by completed node executions.

        Returns:
            None.
        """
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
                node._event_callback = None

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
        """Drain a future result after cancellation without surfacing errors.

        Args:
            future: Future to drain.

        Returns:
            None.
        """
        try:
            future.result()
        except Exception:
            pass

    def _mark_cancelled(self, node_id: str) -> None:
        """Record one node as cancelled and emit its execution state.

        Args:
            node_id: Id of the cancelled node.

        Returns:
            None.
        """
        node = self.graph.nodes[node_id]
        self.terminal.add(node_id)
        self.set_state(node_id, "cancelled")
        self.emit(f"Cancelled {node.display_name}")

    def _complete(self, node_id: str, result: dict[str, Any]) -> None:
        """Store one node result and queue newly unblocked downstream nodes.

        Args:
            node_id: Id of the completed node.
            result: Output dictionary returned by the node.

        Returns:
            None.
        """
        self.outputs[node_id] = result
        self.order.append(node_id)
        self.terminal.add(node_id)
        for target in self.downstream[node_id]:
            self.indegree[target] -= 1
            if self.indegree[target] == 0:
                self.queue.append(target)

    def _fail_branch(self, node_id: str, message: str) -> None:
        """Fail one node and block only nodes that depend on its output.

        Args:
            node_id: Id of the failed node.
            message: Failure message to report.

        Returns:
            None.
        """
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
        """Raise the public cancellation error after all state is marked.

        Returns:
            None.

        Raises:
            GraphExecutionCancelled: If cancellation was requested.
        """
        if not self.cancel_event.is_set():
            return
        for node_id in self.graph.nodes:
            if node_id not in self.terminal:
                self.terminal.add(node_id)
                self.set_state(node_id, "cancelled")
        raise GraphExecutionCancelled("Graph execution cancelled")

    def _raise_if_unresolved_or_failed(self) -> None:
        """Raise a final error for cycles, blocked work, or node failures.

        Returns:
            None.

        Raises:
            GraphExecutionError: If any node failed or unresolved nodes remain.
        """
        unresolved = set(self.graph.nodes) - self.terminal
        if unresolved:
            self.failures.append("The graph contains a cycle and cannot be executed")
            for node_id in unresolved:
                self.set_state(node_id, "blocked")
        if self.failures:
            raise GraphExecutionError("\n".join(self.failures))
