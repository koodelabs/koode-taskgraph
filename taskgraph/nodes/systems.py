"""Built-in system/process nodes."""

import json
import os
from queue import Empty, Queue
import shlex
import signal
import subprocess
import sys
from threading import Thread
import time

from taskgraph.core.model import (
    BoolProperty,
    IntProperty,
    MultilineProperty,
    NodeCancelled,
    PortSpec,
    ProcessNode,
    TextProperty,
)
from taskgraph.core.registry import register_node


PYTHON_SCRIPT_WRAPPER = r"""
import contextlib
import io
import json
import sys
import traceback

payload = json.loads(sys.stdin.read())
namespace = {}
captured_stdout = io.StringIO()

try:
    with contextlib.redirect_stdout(captured_stdout):
        exec(payload["code"], namespace)
        process = namespace.get("process")
        if not callable(process):
            raise RuntimeError("Python Script must define callable process(inputs)")
        outputs = process(payload["inputs"])
    if not isinstance(outputs, dict):
        raise RuntimeError("process(inputs) must return a dict")
    print(json.dumps({
        "outputs": outputs,
        "stdout": captured_stdout.getvalue(),
    }))
except Exception:
    print(captured_stdout.getvalue(), end="")
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
"""


@register_node
class PrintValue(ProcessNode):
    """Print an incoming value to stdout.

    Attributes:
        prefix: Text prepended to the printed value.
    """

    type_id = "output.print"
    title = "Print"
    category = "System"
    color = "#a33a4b"
    inputs = (PortSpec("value", "any", required=True),)
    properties = (TextProperty("prefix", "Prefix", ""),)

    def process(self, inputs):
        """Print the input value with the configured prefix.

        Args:
            inputs: Incoming values from upstream attribute connections. Requires
                a ``"value"`` key.

        Returns:
            dict[str, object]: Empty output dictionary.

        Raises:
            KeyError: If the required ``"value"`` input is missing.
        """
        value = f"{self.prefix}{inputs['value']}"
        print(value)
        return {}


@register_node
class PythonScript(ProcessNode):
    """Run user-provided Python code in a subprocess.

    Attributes:
        code: Python source code expected to define ``process(inputs)``.
        timeout: Maximum runtime in seconds.
    """

    type_id = "system.python_script"
    title = "Python Script"
    category = "System"
    color = "#325d88"
    inputs = (PortSpec("value", "any", multiple=True),)
    outputs = (
        PortSpec("result", "any"),
        PortSpec("stdout", "text"),
        PortSpec("stderr", "text"),
    )
    properties = (
        MultilineProperty(
            "code",
            "Code",
            (
                "def process(inputs):\n"
                "    values = inputs.get(\"values\", [])\n"
                "    return {\"result\": values}\n"
            ),
        ),
        IntProperty("timeout", "Timeout (seconds)", 300, minimum=1, maximum=86400),
    )

    def process(self, inputs):
        """Execute the configured script and return its declared outputs.

        Args:
            inputs: Incoming values from upstream attribute connections. Multiple
                values on the ``"value"`` port are normalized to ``"values"``.

        Returns:
            dict[str, object]: Script outputs plus ``stdout`` and ``stderr`` keys.

        Raises:
            RuntimeError: If inputs cannot be serialized, the script fails,
                times out, or does not return a dictionary.
            NodeCancelled: If graph cancellation is requested while running.
        """
        values = inputs.get("value", [])
        if not isinstance(values, list):
            values = [values]
        script_inputs = dict(inputs)
        script_inputs["value"] = values
        script_inputs["values"] = values
        try:
            payload = json.dumps({
                "code": self.code,
                "inputs": script_inputs,
            })
        except TypeError as exc:
            raise RuntimeError(
                "Python Script inputs must be JSON serializable"
            ) from exc
        popen_options = {}
        if os.name == "posix":
            popen_options["start_new_session"] = True
        elif os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            [sys.executable, "-c", PYTHON_SCRIPT_WRAPPER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **popen_options,
        )
        assert process.stdin is not None
        process.stdin.write(payload)
        process.stdin.close()
        process.stdin = None
        stdout, stderr = self._communicate(process)
        if process.returncode:
            detail = stderr.strip() or stdout.strip()
            raise RuntimeError(
                "Python Script failed" + (f": {detail}" if detail else "")
            )
        try:
            envelope = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Python Script did not produce valid JSON output"
            ) from exc
        outputs = envelope.get("outputs", {})
        if not isinstance(outputs, dict):
            raise RuntimeError("Python Script returned invalid outputs")
        outputs = dict(outputs)
        outputs["stdout"] = envelope.get("stdout", "")
        outputs["stderr"] = stderr
        outputs.setdefault("result", None)
        return outputs

    def _communicate(self, process):
        """Wait for the subprocess while enforcing timeout and cancellation.

        Args:
            process: Running Python script subprocess.

        Returns:
            tuple[str, str]: Captured stdout and stderr text.

        Raises:
            RuntimeError: If the subprocess exceeds the configured timeout.
            NodeCancelled: If graph cancellation is requested.
        """
        deadline = time.monotonic() + self.timeout
        while True:
            if self.cancellation_requested:
                self._terminate_process(process)
                process.communicate()
                raise NodeCancelled("Python Script cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._terminate_process(process)
                process.communicate()
                raise RuntimeError(
                    f"Python Script timed out after {self.timeout} seconds"
                )
            try:
                return process.communicate(timeout=min(0.1, remaining))
            except subprocess.TimeoutExpired:
                continue

    @staticmethod
    def _terminate_process(process):
        """Terminate a subprocess or process group as forcefully as needed.

        Args:
            process: Subprocess to terminate.

        Returns:
            None.
        """
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=0.5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if process.poll() is None:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()


@register_node
class RunCommand(ProcessNode):
    """Execute a shell command or argument list in a subprocess.

    Attributes:
        command: Command text to execute when no command input is connected.
        working_directory: Optional process working directory.
        shell: Whether to execute through the system shell.
        timeout: Maximum runtime in seconds.
        fail_on_error: Whether a non-zero return code raises an error.
    """

    type_id = "system.command"
    title = "Run Command"
    category = "System"
    color = "#566b32"
    inputs = (PortSpec("command", "text"),)
    outputs = (
        PortSpec("stdout", "text"),
        PortSpec("stderr", "text"),
        PortSpec("return_code", "number"),
    )
    properties = (
        TextProperty("command", "Command", "echo Hello from TaskGraph"),
        TextProperty("working_directory", "Working Directory", ""),
        BoolProperty("shell", "Use Shell", True),
        IntProperty("timeout", "Timeout (seconds)", 300, minimum=1, maximum=86400),
        BoolProperty("fail_on_error", "Fail on Non-zero Exit", True),
    )

    def process(self, inputs):
        """Run the configured command and return stdout, stderr, and exit code.

        Args:
            inputs: Incoming values from upstream attribute connections. The
                optional ``"command"`` key overrides the command property.

        Returns:
            dict[str, object]: Captured ``stdout``, ``stderr``, and
            ``return_code`` values.

        Raises:
            ValueError: If no command text is provided.
            RuntimeError: If the command times out or exits non-zero while
                ``fail_on_error`` is enabled.
            NodeCancelled: If graph cancellation is requested while running.
        """
        command = str(inputs.get("command", self.command)).strip()
        if not command:
            raise ValueError("Command cannot be empty")
        args = command if self.shell else shlex.split(command)
        popen_options = {}
        if os.name == "posix":
            popen_options["start_new_session"] = True
        elif os.name == "nt":
            popen_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        process = subprocess.Popen(
            args,
            cwd=self.working_directory.strip() or None,
            shell=self.shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            **popen_options,
        )
        stdout, stderr = self._collect_output(process)
        if self.fail_on_error and process.returncode:
            detail = stderr.strip() or stdout.strip()
            raise RuntimeError(
                f"command exited with code {process.returncode}"
                + (f": {detail}" if detail else "")
            )
        return {
            "stdout": stdout,
            "stderr": stderr,
            "return_code": process.returncode,
        }

    def _collect_output(self, process):
        """Collect process output while emitting stdout/stderr lines live.

        Args:
            process: Running command subprocess.

        Returns:
            tuple[str, str]: Full captured stdout and stderr text.

        Raises:
            RuntimeError: If the command exceeds the configured timeout.
            NodeCancelled: If graph cancellation is requested.
        """
        output_queue = Queue()
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        readers = [
            Thread(
                target=self._read_stream,
                args=(process.stdout, "stdout", output_queue),
                daemon=True,
            ),
            Thread(
                target=self._read_stream,
                args=(process.stderr, "stderr", output_queue),
                daemon=True,
            ),
        ]
        for reader in readers:
            reader.start()

        deadline = time.monotonic() + self.timeout
        while True:
            self._drain_output_queue(output_queue, stdout_parts, stderr_parts)
            if self.cancellation_requested:
                self._terminate_process(process)
                self._finish_readers(readers, output_queue, stdout_parts, stderr_parts)
                raise NodeCancelled("Command cancelled")
            if process.poll() is not None:
                self._finish_readers(readers, output_queue, stdout_parts, stderr_parts)
                return "".join(stdout_parts), "".join(stderr_parts)
            if time.monotonic() >= deadline:
                self._terminate_process(process)
                self._finish_readers(readers, output_queue, stdout_parts, stderr_parts)
                raise RuntimeError(f"command timed out after {self.timeout} seconds")
            time.sleep(0.05)

    @staticmethod
    def _read_stream(stream, stream_name, output_queue) -> None:
        """Read one subprocess stream and push chunks into a shared queue.

        Args:
            stream: File-like stdout or stderr stream from ``subprocess.Popen``.
            stream_name: Label used to identify the stream, usually ``stdout``
                or ``stderr``.
            output_queue: Queue receiving ``(stream_name, text)`` tuples.

        Returns:
            None.
        """
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                output_queue.put((stream_name, line))
        finally:
            stream.close()

    def _drain_output_queue(
        self,
        output_queue,
        stdout_parts: list[str],
        stderr_parts: list[str],
    ) -> None:
        """Move queued subprocess output into capture buffers and live logs.

        Args:
            output_queue: Queue containing stream output tuples.
            stdout_parts: Mutable list collecting stdout chunks.
            stderr_parts: Mutable list collecting stderr chunks.

        Returns:
            None.
        """
        while True:
            try:
                stream_name, text = output_queue.get_nowait()
            except Empty:
                return
            if stream_name == "stdout":
                stdout_parts.append(text)
            else:
                stderr_parts.append(text)
            self.emit_event(f"{self.display_name} {stream_name}: {text.rstrip()}")

    def _finish_readers(
        self,
        readers: list[Thread],
        output_queue,
        stdout_parts: list[str],
        stderr_parts: list[str],
    ) -> None:
        """Wait briefly for output readers and drain any remaining output.

        Args:
            readers: Reader threads attached to subprocess streams.
            output_queue: Queue containing stream output tuples.
            stdout_parts: Mutable list collecting stdout chunks.
            stderr_parts: Mutable list collecting stderr chunks.

        Returns:
            None.
        """
        for reader in readers:
            reader.join(timeout=0.5)
        self._drain_output_queue(output_queue, stdout_parts, stderr_parts)

    @staticmethod
    def _terminate_process(process):
        """Terminate a command subprocess or process group.

        Args:
            process: Subprocess to terminate.

        Returns:
            None.
        """
        if process.poll() is not None:
            return
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
            process.wait(timeout=0.5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if process.poll() is None:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
