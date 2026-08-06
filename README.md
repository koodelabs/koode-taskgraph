<p align="left">
  <a href="https://buymeacoffee.com/cgarjun">
    <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" height="50" alt="Buy Me A Coffee">
  </a>
</p>

# Koode TaskGraph

TaskGraph is a small, extensible process graph editor built from scratch with
Python, QtPy, and PySide6.

![Koode TaskGraph demo](images/demo-koode-taskgraph.png)

## Run

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install koode-taskgraph
koode-taskgraph
```

For local development from this repository, use `python -m pip install -e .`.

## Headless CLI

Execute a saved graph without starting Qt or opening a window:

```bash
koode-taskgraph-cli --file /path/to/workflow.taskgraph
```

Select the worker count and load external node locations when needed:

```bash
koode-taskgraph-cli \
  --file /path/to/workflow.taskgraph \
  --workers 8 \
  --node-path /path/to/custom_nodes
```

`--node-path` may be repeated. `TASKGRAPH_NODE_PATH` is also supported with
the normal platform path separator. Use `--json` for structured results,
`--quiet` to hide progress messages, and `Ctrl+C` to cancel execution.

Exit codes are `0` for success, `1` for graph execution failure, `2` for
arguments/loading errors, and `130` for cancellation.

Double-click a node type in the left panel to add it. Drag from an output port
on the right of a node to an input port on the left of another node. Select a
node to edit its properties, then click **Run graph**.

## Add a node

Create a module in `taskgraph/nodes/` and define a `ProcessNode` subclass:

```python
from taskgraph.core.model import NodeProperty, PortSpec, ProcessNode
from taskgraph.core.registry import register_node

@register_node
class PrefixText(ProcessNode):
    type_id = "custom.prefix_text"
    title = "Prefix Text"
    category = "Custom"
    inputs = (PortSpec("value", "any"),)
    outputs = (PortSpec("text", "text"),)
    properties = (
        NodeProperty("prefix", "Prefix", "text", "Result: "),
    )

    def process(self, inputs):
        return {"text": f"{self.prefix}{inputs.get('value', '')}"}
```

Modules in `taskgraph/nodes/` are discovered automatically. Custom modules can
also live anywhere on disk:

1. Put one or more standalone `.py` node modules in a directory.
2. Select **Nodes → Add Custom Node Location…** and choose that directory.
3. Restarting TaskGraph reloads the saved location automatically.

Alternatively, set `TASKGRAPH_NODE_PATH` before launching. Separate multiple
directories with the platform path separator (`:` on macOS/Linux and `;` on
Windows):

```bash
TASKGRAPH_NODE_PATH="/path/to/company_nodes:/path/to/my_nodes" koode-taskgraph
```

Files beginning with `_` are ignored. Importing a custom node module executes
its Python code, so only add trusted directories. The editor, property panel,
serialization, and executor require no other changes.

## Add a GUI plugin

GUI plugins can add menus, actions, docks, and graph-building commands without
editing TaskGraph source. Put one or more `.py` files in a plugin directory and
define `register_taskgraph_plugin(api)`:

```python
def register_taskgraph_plugin(api):
    def build_template_graph():
        text = api.create_node(
            "input.text",
            name="Message",
            values={"text": "hello world"},
            position=(0, 0),
        )
        formatter = api.create_node(
            "text.format",
            name="Format Message",
            values={"template": "Output: {value}"},
            position=(280, 0),
        )
        printer = api.create_node(
            "output.print",
            name="Print Result",
            position=(560, 0),
        )
        api.connect_dependency(text, formatter)
        api.connect_attribute(text, "text", formatter, "value")
        api.connect_dependency(formatter, printer)
        api.connect_attribute(formatter, "text", printer, "value")
        api.add_backdrop(
            title="Template Notes",
            note="This graph was created by a GUI plugin.",
            position=(-40, -140),
            size=(720, 180),
        )

    api.add_menu_action("Tools", "Build Template Graph", build_template_graph)
```

Load GUI plugins from **Plugins → Add GUI Plugin Location…**. Restarting
TaskGraph reloads saved plugin locations automatically. Alternatively, set
`TASKGRAPH_PLUGIN_PATH` before launching, using the same platform path
separator rules as `TASKGRAPH_NODE_PATH`.

This repository includes minimal example plugins in `examples/gui_plugins`.
Load that directory, then run **Examples → Create Hello World Print Graph** or
**Examples → Create Bingooo Print Graph**.

GUI plugins are intentionally separate from custom node locations. The
headless CLI loads `TASKGRAPH_NODE_PATH` only, so UI plugin code can safely
import Qt widgets without breaking `koode-taskgraph-cli`.

## Controls

- Standard commands are organized under the **File**, **Edit**, **Nodes**,
  **Graph**, **Plugins**, and **View** menus.
- Drag a node from **Nodes** to the canvas, or double-click it.
- Every node has fixed gold **dependency** input/output ports. These control
  process order but do not transfer values. Gold dependency connections show
  an arrowhead pointing from the upstream node toward the downstream node.
- Declared node inputs and outputs are attribute ports. Attribute connections
  transfer values, but execution order comes only from dependency connections.
  An attribute connection therefore needs a dependency path from its source
  node to its target node.
- Dependency ports connect only to dependency ports; compatible attribute
  ports connect only to attribute ports.
- Select one or more nodes on the canvas and press **D** to toggle them
  disabled. Disabled nodes stay in the dependency chain but their process
  functions are skipped. The same command is available from **Edit**.
- **Copy Nodes** and **Paste Nodes** under **Edit** use the standard platform
  shortcuts. Properties, disabled state, relative positions, and connections
  entirely inside the copied selection are preserved.
- Select a node to edit generated property controls.
- Use **Node Name** at the top of the Properties panel to give each node
  instance a descriptive name. Custom names appear in node headers and
  execution messages and are preserved when saving or copying nodes.
- Select nodes or connections and press **Backspace** or **Delete** to remove
  them. **Edit → Delete Selected** works on every platform too.
- Middle-drag pans, the mouse wheel zooms, and **F** frames the graph.
- **Shift+A** or **Graph → Auto Arrange Nodes** lays out dependency layers
  from left to right and parallel nodes vertically, then frames the result.
- **Graph → Add Backdrop** creates a movable notes region behind the graph.
  Select it to edit its title, notes, color, width, and height in Properties.
  Drag the grip in its bottom-right corner to resize it interactively.
  Backdrops are stored in `.taskgraph` files.
- **Ctrl+R** executes nodes in dependency order.
- Independent dependency branches execute concurrently. Choose between one
  worker or any even worker count from 2 through 32 under
  **Graph → Worker Count**; the setting is remembered.
- Use **Graph → Cancel Execution** or **Esc** to cancel the complete run.
  Pending nodes are cancelled immediately. Running nodes receive a cooperative
  cancellation signal, and built-in command nodes terminate their subprocess
  groups promptly.
- Clear displayed execution messages with **Graph → Clear Execution Log** or
  from the Execution panel's right-click menu.
- Built-in nodes are organized as **System → Run Command/Print**,
  **Utils → Format Text**, and **Inputs → Text/Number**.
- The built-in **System → Run Command** node executes a command and exposes
  stdout, stderr, and return code outputs. It supports an optional working
  directory, shell mode, timeout, and failure on non-zero exit. Shell mode
  executes exactly what the graph author enters, so only run trusted graphs.
- Node headers show live execution state: amber while running, green when
  finished, red on failure, gray when a disabled node is skipped, and muted
  red when a node is blocked by an upstream failure. Cancelled nodes use a
  purple-gray state.
  Execution coordination runs outside the GUI thread so the final running
  node and parallel running nodes remain visible while work is in progress.
- A failed node blocks only its downstream dependency branch. Independent
  parallel branches continue running and report their own final states.
- Closed panels can be restored from **View → Nodes/Properties/Execution**.
  Use **View → Show All Panels** to restore everything at once.

Graph files use readable JSON with the `.taskgraph` extension.

## Architecture

- `core/model.py`: node contract—including inherited dependency port
  specifications—and serializable graph model
- `core/registry.py`: decorator-based built-in and external node discovery
- `core/executor.py`: validation and dependency-ordered execution
- `ui/`: graphics editor, node items, property editor, and main window
- `nodes/`: built-in examples and the extension point for new processes
