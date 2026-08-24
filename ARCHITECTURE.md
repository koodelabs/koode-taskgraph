# Koode TaskGraph Architecture

This is a simple overview of how TaskGraph is put together.

Think of the app as three main parts:

```text
+------------------+      +------------------+      +------------------+
| Nodes            | ---> | Graph            | ---> | Executor         |
| What can run     |      | How nodes connect|      | Runs the graph   |
+------------------+      +------------------+      +------------------+
          ^
          |
+------------------+
| GUI              |
| Lets user edit   |
+------------------+
```

## Node Architecture

A node is a small Python class.

It says:

- what the node is called
- what inputs it accepts
- what outputs it produces
- what editable settings it has
- what happens when it runs

### Node definition

A node definition looks like this:

```python
@register_node
class HelloNode(ProcessNode):
    type_id = "custom.hello"
    title = "Hello"
    category = "Custom"

    outputs = (
        PortSpec("message", "string"),
    )

    properties = (
        TextProperty("name", "Name", "World"),
    )

    def process(self, inputs):
        return {
            "message": f"Hello {self.name}",
        }
```

Simple meaning:

```text
+------------------------------+
| HelloNode                    |
|------------------------------|
| type_id    = custom.hello    |
| title      = Hello           |
| output     = message         |
| property   = name            |
| process()  = creates output  |
+------------------------------+
```

`@register_node` makes the node available to the app.

```text
Python class
    |
    v
@register_node
    |
    v
Node list / node registry
    |
    v
User can create this node
```

### Node Creation

When the user adds a node, the app does this:

```text
User adds node
    |
    v
Find node class by type_id
    |
    v
Create node instance
    |
    v
Add node to graph
    |
    v
Draw node in GUI
```

Example:

```text
type_id = "custom.hello"
    |
    v
HelloNode class
    |
    v
HelloNode instance
```

The class is the template.

The instance is the real node placed in the graph.

### Node Properties

Properties are editable settings on a node.

Example:

```python
properties = (
    TextProperty("name", "Name", "World"),
    BoolProperty("shout", "Shout", False),
)
```

Simple meaning:

```text
+------------------------------+
| Property                     |
|------------------------------|
| name       internal key      |
| label      text shown in UI  |
| default    starting value    |
| widget     Qt editor widget  |
+------------------------------+
```

For example:

```python
TextProperty("name", "Name", "World")
```

means:

```text
Internal name:  name
UI label:       Name
Default value:  World
Qt widget:      QLineEdit
```

Property flow:

```text
Node defines properties
    |
    v
Node instance stores values
    |
    v
User selects node
    |
    v
Properties panel asks each property to create its widget
    |
    v
User edits widget
    |
    v
node.values is updated
```

The actual values live on the node:

```python
node.values = {
    "name": "World",
    "shout": False,
}
```

Inside `process()`, you can read them like normal attributes:

```python
self.name
self.shout
```

That is just a simple way to read from `node.values`.

### Ports

Ports are connection points.

There are two types:

```text
+----------------------+      +----------------------+
| Dependency ports     |      | Attribute ports      |
|----------------------|      |----------------------|
| Control run order    |      | Pass values/data     |
| Do not pass values   |      | Do not control order |
+----------------------+      +----------------------+
```

Dependency connection:

```text
[ Node A ] ---- must run before ----> [ Node B ]
```

Attribute connection:

```text
[ Node A output ] ---- value ----> [ Node B input ]
```

A normal input/output port is defined with `PortSpec`:

```python
inputs = (
    PortSpec("text", "string", required=True),
)

outputs = (
    PortSpec("result", "string"),
)
```

Simple meaning:

```text
PortSpec("text", "string")

Port name: text
Data type: string
```

### Node Execution

Execution is based on dependency connections.

If the graph is:

```text
[ A ] ---> [ B ] ---> [ C ]
```

then the executor runs:

```text
A first
B second
C third
```

When a node runs, the executor calls:

```python
node.process(inputs)
```

The node returns a dictionary:

```python
return {
    "message": "Hello World",
}
```

That dictionary becomes the node outputs.

Execution flow:

```text
GraphExecutor starts
    |
    v
Find nodes with no dependency parent
    |
    v
Run ready nodes
    |
    v
Collect returned outputs
    |
    v
Unlock downstream nodes
    |
    v
Continue until graph is finished
```

Parallel branches can run at the same time:

```text
        +--> [ B ] --+
        |            |
[ A ] --+            +--> [ D ]
        |            |
        +--> [ C ] --+
```

`B` and `C` can run in parallel after `A` finishes.

If a node is disabled:

```text
[ A ] ---> [ disabled B ] ---> [ C ]
```

`B.process()` is skipped, but the dependency chain continues.

## GUI

The GUI is the Qt application the user sees.

It has:

- graph canvas
- node list
- properties panel
- execution log
- menus
- plugin-added UI

### Core GUI architecture

Simple GUI structure:

```text
+----------------------------------+
| MainWindow                       |
|----------------------------------|
| Menus                            |
| Node list dock                   |
| Properties dock                  |
| Execution log dock               |
| Graph canvas                     |
+----------------+-----------------+
                 |
                 v
+----------------------------------+
| GraphScene                       |
|----------------------------------|
| Owns graph model                 |
| Draws nodes                      |
| Draws connections                |
| Draws backdrops                  |
+----------------+-----------------+
                 |
                 v
+----------------------------------+
| Graph model                      |
|----------------------------------|
| nodes                            |
| connections                      |
| positions                        |
| backdrops                        |
+----------------------------------+
```

When the user selects a node:

```text
User clicks node
    |
    v
GraphScene detects selection
    |
    v
PropertyEditor.set_node(node)
    |
    v
Properties panel is rebuilt
```

When the user edits a property:

```text
User edits widget
    |
    v
Property writes new value
    |
    v
node.values changes
    |
    v
Graph is marked dirty
```

When the user runs the graph:

```text
User clicks Run
    |
    v
MainWindow starts worker thread
    |
    v
GraphExecutor runs graph
    |
    v
GUI receives progress updates
    |
    v
Nodes show running / finished / failed state
```

The graph runs outside the main GUI thread, so the app stays responsive.

### GUI Plugins

GUI plugins let another developer add UI features without changing the main
source code.

GUI plugins can add:

- menu commands
- submenus
- shortcuts
- dock panels
- graph-building tools

GUI plugins are different from custom nodes:

```text
+----------------------+      +----------------------+
| Custom node          |      | GUI plugin           |
|----------------------|      |----------------------|
| Adds process logic   |      | Adds UI behavior     |
| Runs in graph        |      | Extends app menus/UI |
+----------------------+      +----------------------+
```

A GUI plugin has a `Plugin` class:

```python
from taskgraph.ui.plugins import TaskGraphGuiPlugin


class Plugin(TaskGraphGuiPlugin):
    plugin_id = "example.plugin"
    name = "Example Plugin"

    def setup(self):
        self.commands.register(
            "example.say_hello",
            "Say Hello",
            self.say_hello,
        )
        self.ui.menus.add_command(
            "Examples",
            "example.say_hello",
        )

    def say_hello(self):
        self.ui.status.show_message("Hello from plugin")
```

Plugin load flow:

```text
Plugin folder
    |
    v
Python plugin file
    |
    v
Find class Plugin
    |
    v
Create Plugin(api)
    |
    v
Call plugin.setup()
    |
    v
Plugin adds menus/docks/actions
```

Plugin API:

```text
+-----------------------------+
| self.commands               |
| register and run commands   |
+-----------------------------+
| self.ui                     |
| add menus, docks, status    |
+-----------------------------+
| self.graph                  |
| create nodes, connect nodes |
+-----------------------------+
```

Example graph-building plugin flow:

```text
User clicks plugin menu
    |
    v
Plugin command runs
    |
    v
Plugin creates nodes
    |
    v
Plugin connects nodes
    |
    v
Graph canvas updates
```

Use custom nodes when you need new processing behavior.

Use GUI plugins when you need new application UI behavior.
