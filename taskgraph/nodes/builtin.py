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
    type_id = "input.string"
    title = "String"
    category = "Inputs"
    color = "#087f8c"
    outputs = (PortSpec("string", "string"),)
    properties = (TextProperty("string", "String", "Hello graph"),)

    def process(self, inputs):
        return {"string": self.string}


@register_node
class NumberValue(ProcessNode):
    type_id = "input.number"
    title = "Number"
    category = "Inputs"
    color = "#087f8c"
    outputs = (PortSpec("number", "number"),)
    properties = (FloatProperty("number", "Number", 1.0),)

    def process(self, inputs):
        return {"number": self.number}


@register_node
class PathValue(ProcessNode):
    type_id = "input.path"
    title = "Path"
    category = "Inputs"
    color = "#087f8c"
    outputs = (PortSpec("path", "string"),)
    properties = (
        PathProperty("path", "Path", ""),
    )

    def process(self, inputs):
        return {"path": self.path}


@register_node
class ListValue(ProcessNode):
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
        value = json.loads(self.items)
        if not isinstance(value, list):
            raise ValueError("List node value must be a JSON list")
        return {"list": value}


@register_node
class DictValue(ProcessNode):
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
        value = json.loads(self.items)
        if not isinstance(value, dict):
            raise ValueError("Dict node value must be a JSON object")
        return {"dict": value}
