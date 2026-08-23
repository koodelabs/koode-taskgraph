import os
import shlex
import signal
import subprocess
import time

from taskgraph.core.model import NodeCancelled, NodeProperty, PortSpec, ProcessNode
from taskgraph.core.registry import register_node


@register_node
class TextValue(ProcessNode):
    type_id = "input.text"
    title = "Text"
    category = "Inputs"
    color = "#087f8c"
    outputs = (PortSpec("text", "text"),)
    properties = (NodeProperty("text", "Text", "text", "Hello graph"),)

    def process(self, inputs):
        return {"text": self.text}


@register_node
class NumberValue(ProcessNode):
    type_id = "input.number"
    title = "Number"
    category = "Inputs"
    color = "#087f8c"
    outputs = (PortSpec("number", "number"),)
    properties = (NodeProperty("number", "Number", "float", 1.0),)

    def process(self, inputs):
        return {"number": self.number}


@register_node
class FormatText(ProcessNode):
    type_id = "text.format"
    title = "Format Text"
    category = "Utils"
    color = "#6f4a8e"
    inputs = (PortSpec("value", "any", required=True, multiple=True),)
    outputs = (PortSpec("text", "text"),)
    properties = (
        NodeProperty("template", "Template", "text", "Result: {0}"),
        NodeProperty("uppercase", "Uppercase", "bool", False),
    )

    def process(self, inputs):
        values = inputs["value"]
        if not isinstance(values, list):
            values = [values]
        first_value = values[0] if values else ""
        text = self.template.format(*values, value=first_value, values=values)
        return {"text": text.upper() if self.uppercase else text}


@register_node
class PrintValue(ProcessNode):
    type_id = "output.print"
    title = "Print"
    category = "System"
    color = "#a33a4b"
    inputs = (PortSpec("value", "any", required=True),)
    properties = (NodeProperty("prefix", "Prefix", "text", ""),)

    def process(self, inputs):
        value = f"{self.prefix}{inputs['value']}"
        print(value)
        return {}


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
        NodeProperty("command", "Command", "text", "echo Hello from TaskGraph"),
        NodeProperty("working_directory", "Working Directory", "text", ""),
        NodeProperty("shell", "Use Shell", "bool", True),
        NodeProperty("timeout", "Timeout (seconds)", "int", 60, minimum=1, maximum=86400),
        NodeProperty("fail_on_error", "Fail on Non-zero Exit", "bool", True),
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
