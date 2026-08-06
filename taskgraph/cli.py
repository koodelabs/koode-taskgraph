"""Headless command-line runner for TaskGraph files."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
from threading import Event

from taskgraph.core.executor import (
    VALID_WORKER_COUNTS,
    GraphExecutionCancelled,
    GraphExecutionError,
    execute_graph,
)
from taskgraph.core.registry import load_custom_node_directory
from taskgraph.core.serialization import load_graph
from taskgraph.nodes import load_builtin_nodes


def worker_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("worker count must be an integer") from exc
    if count not in VALID_WORKER_COUNTS:
        raise argparse.ArgumentTypeError(
            "worker count must be 1 or an even number from 2 through 32"
        )
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="koode-taskgraph-cli",
        description="Execute a TaskGraph file without starting the Qt UI.",
    )
    parser.add_argument(
        "--file", "-f", required=True, type=Path,
        help="path to a .taskgraph or compatible JSON graph file",
    )
    parser.add_argument(
        "--workers", "-w", type=worker_count, default=4,
        help="parallel workers: 1 or an even number from 2 through 32 (default: 4)",
    )
    parser.add_argument(
        "--node-path", action="append", default=[], metavar="DIRECTORY",
        help="custom node directory; may be passed more than once",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="suppress progress messages and print only the final status",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="print the execution result as JSON",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    graph_path = args.file.expanduser()
    if not graph_path.is_file():
        print(f"koode-taskgraph-cli: graph file not found: {graph_path}", file=sys.stderr)
        return 2

    try:
        load_builtin_nodes()
        environment_paths = [
            path
            for path in os.environ.get("TASKGRAPH_NODE_PATH", "").split(os.pathsep)
            if path
        ]
        for location in dict.fromkeys([*environment_paths, *args.node_path]):
            load_custom_node_directory(location)
        graph = load_graph(graph_path)
    except Exception as exc:
        print(f"koode-taskgraph-cli: could not load graph: {exc}", file=sys.stderr)
        return 2

    cancel_event = Event()
    previous_handler = signal.getsignal(signal.SIGINT)

    def request_cancel(_signum, _frame) -> None:
        if not cancel_event.is_set():
            print("Cancellation requested…", file=sys.stderr)
            cancel_event.set()

    signal.signal(signal.SIGINT, request_cancel)
    event_stream = sys.stderr if args.json else sys.stdout
    emit = None if args.quiet else lambda message: print(message, file=event_stream)
    try:
        result = execute_graph(
            graph,
            on_event=emit,
            max_workers=args.workers,
            cancel_event=cancel_event,
        )
    except GraphExecutionCancelled as exc:
        print(f"koode-taskgraph-cli: {exc}", file=sys.stderr)
        return 130
    except GraphExecutionError as exc:
        print(f"koode-taskgraph-cli: execution failed:\n{exc}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGINT, previous_handler)

    if args.json:
        print(json.dumps({
            "order": result.order,
            "outputs": result.outputs,
        }, indent=2, default=repr))
    else:
        print(f"Completed {len(result.order)} node(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
