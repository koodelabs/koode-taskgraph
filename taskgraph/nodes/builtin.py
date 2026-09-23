"""Built-in input/value nodes."""

import json

from taskgraph.core.model import (
    FloatProperty,
    MultilineProperty,
    PathProperty,
    PortSpec,
    ProcessNode,
    TextProperty,
)
from taskgraph.core.registry import register_node


@register_node
class StringValue(ProcessNode):
    """Output a user-provided string value.

    Attributes:
        string: Configured string value.
    """

    type_id = "input.string"
    title = "String"
    category = "Inputs"
    color = "#087f8c"
    outputs = (PortSpec("string", "string"),)
    properties = (TextProperty("string", "String", "Hello graph"),)

    def process(self, inputs):
        """Return the configured string.

        Args:
            inputs: Incoming values from connected upstream nodes. This node
                does not use them.

        Returns:
            dict[str, str]: The string value keyed by ``"string"``.
        """
        return {"string": self.string}


@register_node
class NumberValue(ProcessNode):
    """Output a user-provided numeric value.

    Attributes:
        number: Configured numeric value.
    """

    type_id = "input.number"
    title = "Number"
    category = "Inputs"
    color = "#087f8c"
    outputs = (PortSpec("number", "number"),)
    properties = (FloatProperty("number", "Number", 1.0),)

    def process(self, inputs):
        """Return the configured number.

        Args:
            inputs: Incoming values from connected upstream nodes. This node
                does not use them.

        Returns:
            dict[str, float]: The number value keyed by ``"number"``.
        """
        return {"number": self.number}


@register_node
class PathValue(ProcessNode):
    """Output a user-provided file path.

    Attributes:
        path: Configured file or directory path string.
    """

    type_id = "input.path"
    title = "Path"
    category = "Inputs"
    color = "#087f8c"
    outputs = (PortSpec("path", "string"),)
    properties = (
        PathProperty("path", "Path", ""),
    )

    def process(self, inputs):
        """Return the configured path string.

        Args:
            inputs: Incoming values from connected upstream nodes. This node
                does not use them.

        Returns:
            dict[str, str]: The selected path keyed by ``"path"``.
        """
        return {"path": self.path}


@register_node
class ListValue(ProcessNode):
    """Output a Python list parsed from JSON text.

    Attributes:
        items: JSON text expected to contain a list.
    """

    type_id = "input.list"
    title = "List"
    category = "Inputs"
    color = "#087f8c"
    outputs = (PortSpec("list", "list"),)
    properties = (
        MultilineProperty(
            "items",
            "Items (JSON List)",
            "[\n    \"item 1\",\n    \"item 2\"\n]",
        ),
    )

    def process(self, inputs):
        """Parse the configured JSON text and return a list.

        Args:
            inputs: Incoming values from connected upstream nodes. This node
                does not use them.

        Returns:
            dict[str, list]: Parsed list keyed by ``"list"``.

        Raises:
            ValueError: If the configured JSON value is not a list.
            json.JSONDecodeError: If the configured text is not valid JSON.
        """
        value = json.loads(self.items)
        if not isinstance(value, list):
            raise ValueError("List node value must be a JSON list")
        return {"list": value}


@register_node
class DictValue(ProcessNode):
    """Output a Python dictionary parsed from JSON text.

    Attributes:
        items: JSON text expected to contain an object.
    """

    type_id = "input.dict"
    title = "Dict"
    category = "Inputs"
    color = "#087f8c"
    outputs = (PortSpec("dict", "dict"),)
    properties = (
        MultilineProperty(
            "items",
            "Items (JSON Dict)",
            "{\n    \"key\": \"value\"\n}",
        ),
    )

    def process(self, inputs):
        """Parse the configured JSON text and return a dictionary.

        Args:
            inputs: Incoming values from connected upstream nodes. This node
                does not use them.

        Returns:
            dict[str, dict]: Parsed dictionary keyed by ``"dict"``.

        Raises:
            ValueError: If the configured JSON value is not an object.
            json.JSONDecodeError: If the configured text is not valid JSON.
        """
        value = json.loads(self.items)
        if not isinstance(value, dict):
            raise ValueError("Dict node value must be a JSON object")
        return {"dict": value}
