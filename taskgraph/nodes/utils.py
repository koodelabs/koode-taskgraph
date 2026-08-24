from taskgraph.core.model import BoolProperty, PortSpec, ProcessNode, TextProperty
from taskgraph.core.registry import register_node


@register_node
class FormatText(ProcessNode):
    type_id = "text.format"
    title = "Format Text"
    category = "Utils"
    color = "#6f4a8e"
    inputs = (PortSpec("value", "any", required=True, multiple=True),)
    outputs = (PortSpec("text", "text"),)
    properties = (
        TextProperty("template", "Template", "Result: {0}"),
        BoolProperty("uppercase", "Uppercase", False),
    )

    def process(self, inputs):
        values = inputs["value"]
        if not isinstance(values, list):
            values = [values]
        first_value = values[0] if values else ""
        text = self.template.format(*values, value=first_value, values=values)
        return {"text": text.upper() if self.uppercase else text}
