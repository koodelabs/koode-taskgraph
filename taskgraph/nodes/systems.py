import json
import os
import shlex
import signal
import subprocess
import sys
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
    type_id = "output.print"
    title = "Print"
    category = "System"
    color = "#a33a4b"
    inputs = (PortSpec("value", "any", required=True),)
    properties = (TextProperty("prefix", "Prefix", ""),)

    def process(self, inputs):
        value = f"{self.prefix}{inputs['value']}"
        print(value)
        return {}


@register_node
class PythonScript(ProcessNode):
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
        IntProperty("timeout", "Timeout (seconds)", 60, minimum=1, maximum=86400),
        BoolProperty("fail_on_error", "Fail on Non-zero Exit", True),
    )

    def process(self, inputs):
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
        deadline = time.monotonic() + self.timeout
        while True:
            if self.cancellation_requested:
                self._terminate_process(process)
                process.communicate()
                raise NodeCancelled("Command cancelled")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._terminate_process(process)
                process.communicate()
                raise RuntimeError(f"command timed out after {self.timeout} seconds")
            try:
                stdout, stderr = process.communicate(timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
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

    @staticmethod
    def _terminate_process(process):
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
