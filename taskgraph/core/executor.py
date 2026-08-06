from __future__ import annotations

from collections import defaultdict, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from threading import Event
from typing import Any, Callable

from taskgraph.core.model import Graph, NodeCancelled

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
    if max_workers not in VALID_WORKER_COUNTS:
        raise ValueError(
            "max_workers must be 1 or an even number between 2 and 32"
        )
    emit = on_event or (lambda _message: None)
    set_state = on_node_state or (lambda _node_id, _state: None)
    cancel_event = cancel_event or Event()
    indegree = {node_id: 0 for node_id in graph.nodes}
    downstream: dict[str, list[str]] = defaultdict(list)
    incoming = defaultdict(list)

    attribute_edges = []
    for edge in graph.connections:
        if edge.source_node not in graph.nodes or edge.target_node not in graph.nodes:
            raise GraphExecutionError("A connection references a missing node")
        if edge.kind == "dependency":
            indegree[edge.target_node] += 1
            downstream[edge.source_node].append(edge.target_node)
        else:
            attribute_edges.append(edge)
            incoming[edge.target_node].append(edge)

    def has_dependency_path(source: str, target: str) -> bool:
        pending = [source]
        visited = set()
        while pending:
            current = pending.pop()
            if current == target:
                return True
            if current not in visited:
                visited.add(current)
                pending.extend(downstream[current])
        return False

    for edge in attribute_edges:
        if not has_dependency_path(edge.source_node, edge.target_node):
            source = graph.nodes[edge.source_node]
            target = graph.nodes[edge.target_node]
            raise GraphExecutionError(
                f"Attribute {source.display_name}.{edge.source_port} → "
                f"{target.display_name}.{edge.target_port} requires a dependency path"
            )

    queue = deque(node_id for node_id, degree in indegree.items() if degree == 0)
    order: list[str] = []
    outputs: dict[str, dict[str, Any]] = {}
    terminal: set[str] = set()
    failures: list[str] = []

    def inputs_for(node_id: str) -> dict[str, Any]:
        node = graph.nodes[node_id]
        node_inputs: dict[str, Any] = {}
        for edge in incoming[node_id]:
            source_outputs = outputs.get(edge.source_node, {})
            if edge.source_port not in source_outputs:
                source = graph.nodes[edge.source_node]
                raise GraphExecutionError(
                    f"{node.display_name}: input '{edge.target_port}' is unavailable "
                    f"because {source.display_name} did not produce '{edge.source_port}'"
                )
            value = source_outputs[edge.source_port]
            port = next(spec for spec in node.inputs if spec.name == edge.target_port)
            if port.multiple:
                node_inputs.setdefault(edge.target_port, []).append(value)
            else:
                node_inputs[edge.target_port] = value

        missing = [port.name for port in node.inputs if port.required and port.name not in node_inputs]
        if missing:
            raise GraphExecutionError(
                f"{node.display_name}: missing required input(s): {', '.join(missing)}"
            )
        return node_inputs

    def complete(node_id: str, result: dict[str, Any]) -> None:
        outputs[node_id] = result
        order.append(node_id)
        terminal.add(node_id)
        for target in downstream[node_id]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    def fail_branch(node_id: str, message: str) -> None:
        """Fail one node and block only nodes that depend on its output."""
        if node_id in terminal:
            return
        terminal.add(node_id)
        failures.append(message)
        set_state(node_id, "failed")
        emit(f"Failure: {message}")
        pending = deque(downstream[node_id])
        while pending:
            blocked_id = pending.popleft()
            if blocked_id in terminal:
                continue
            terminal.add(blocked_id)
            set_state(blocked_id, "blocked")
            emit(
                f"Blocked {graph.nodes[blocked_id].display_name}: "
                "an upstream dependency failed"
            )
            pending.extend(downstream[blocked_id])

    running = {}
    cancellation_applied = False
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="taskgraph") as pool:
        while queue or running:
            if cancel_event.is_set() and not cancellation_applied:
                cancellation_applied = True
                emit("Cancellation requested…")
                running_ids = set(running.values())
                for future in running:
                    future.cancel()
                for node_id in graph.nodes:
                    if node_id not in terminal and node_id not in running_ids:
                        terminal.add(node_id)
                        set_state(node_id, "cancelled")
                queue.clear()

            while queue and len(running) < max_workers:
                node_id = queue.popleft()
                if node_id in terminal:
                    continue
                node = graph.nodes[node_id]
                if node.disabled:
                    emit(f"Skipped disabled node: {node.display_name}")
                    set_state(node_id, "skipped")
                    complete(node_id, {})
                    continue
                try:
                    node_inputs = inputs_for(node_id)
                except GraphExecutionError as exc:
                    fail_branch(node_id, str(exc))
                    continue
                emit(f"Running {node.display_name}")
                set_state(node_id, "running")
                node._cancel_event = cancel_event
                running[pool.submit(node.process, node_inputs)] = node_id

            if not running:
                continue

            finished, _pending = wait(running, return_when=FIRST_COMPLETED)
            for future in finished:
                node_id = running.pop(future)
                node = graph.nodes[node_id]
                if cancel_event.is_set():
                    try:
                        future.result()
                    except Exception:
                        pass
                    terminal.add(node_id)
                    set_state(node_id, "cancelled")
                    emit(f"Cancelled {node.display_name}")
                    node._cancel_event = None
                    continue
                try:
                    result = future.result()
                except NodeCancelled:
                    terminal.add(node_id)
                    set_state(node_id, "cancelled")
                    emit(f"Cancelled {node.display_name}")
                    node._cancel_event = None
                    continue
                except Exception as exc:
                    fail_branch(node_id, f"{node.display_name} failed: {exc}")
                    node._cancel_event = None
                    continue
                if not isinstance(result, dict):
                    fail_branch(
                        node_id,
                        f"{node.display_name} must return a dictionary",
                    )
                    node._cancel_event = None
                    continue
                complete(node_id, result)
                set_state(node_id, "finished")
                emit(f"Finished {node.display_name}: {result}")
                node._cancel_event = None

    if cancel_event.is_set():
        # A running cooperative node may notice cancellation and finish before
        # the scheduler reaches the next loop iteration. Ensure descendants
        # that never entered the ready queue still receive a cancelled state.
        for node_id in graph.nodes:
            if node_id not in terminal:
                terminal.add(node_id)
                set_state(node_id, "cancelled")
        raise GraphExecutionCancelled("Graph execution cancelled")
    unresolved = set(graph.nodes) - terminal
    if unresolved:
        failures.append("The graph contains a cycle and cannot be executed")
        for node_id in unresolved:
            set_state(node_id, "blocked")
    if failures:
        raise GraphExecutionError("\n".join(failures))
    return ExecutionResult(order, outputs)
