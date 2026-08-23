import re

from taskgraph.core.model import NodeProperty, PortSpec, ProcessNode
from taskgraph.core.registry import register_node


@register_node
class CleanText(ProcessNode):
    type_id = "examples.clean_text"
    title = "Clean Text"
    category = "Examples"
    color = "#2f6f5e"
    inputs = (PortSpec("text", "text"),)
    outputs = (PortSpec("text", "text"),)
    properties = (
        NodeProperty("fallback_text", "Fallback Text", "text", ""),
        NodeProperty("collapse_whitespace", "Collapse Whitespace", "bool", True),
        NodeProperty(
            "case_mode",
            "Case",
            "choice",
            "Preserve",
            choices=("Preserve", "Uppercase", "Lowercase", "Title Case"),
        ),
    )

    def process(self, inputs):
        text = str(inputs.get("text", self.fallback_text))
        text = text.strip()
        if self.collapse_whitespace:
            text = re.sub(r"\s+", " ", text)
        if self.case_mode == "Uppercase":
            text = text.upper()
        elif self.case_mode == "Lowercase":
            text = text.lower()
        elif self.case_mode == "Title Case":
            text = text.title()
        return {"text": text}
