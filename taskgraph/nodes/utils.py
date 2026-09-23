"""Built-in utility nodes."""

from taskgraph.core.model import BoolProperty, PortSpec, ProcessNode, TextProperty
from taskgraph.core.registry import register_node


@register_node
class FormatText(ProcessNode):
    """Format one or more incoming values into a text string.

    Attributes:
        template: Python format string applied to incoming values.
        uppercase: Whether to convert the formatted text to uppercase.
    """

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
        """Apply the configured format string to incoming values.

        Args:
            inputs: Values received from upstream attribute connections. The
                ``"value"`` key may contain one value or a list of values.

        Returns:
            dict[str, str]: Formatted text keyed by ``"text"``.

        Raises:
            KeyError: If the required ``"value"`` input is missing.
            IndexError: If the template references an unavailable positional value.
            KeyError: If the template references an unavailable named value.
        """
        values = inputs["value"]
        if not isinstance(values, list):
            values = [values]
        first_value = values[0] if values else ""
        text = self.template.format(*values, value=first_value, values=values)
        return {"text": text.upper() if self.uppercase else text}
