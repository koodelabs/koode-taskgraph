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

There are two separate things:

```text
Property definition
    Describes one editable setting.
    Example: TextProperty("name", "Name", "World")

Property value
    The actual value on a specific node.
    Example: node.values["name"] = "World"
```

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
| TextProperty                 |
|------------------------------|
| name       internal key      |
| label      text shown in UI  |
| default    starting value    |
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
```

The property definition does not store the current value.

The node instance stores the current value:

```python
node.values = {
    "name": "World",
    "shout": False,
}
```

When the user selects a node, the Properties panel asks each property to create
its Qt editor widget.

```text
User selects node
    |
    v
PropertyEditor.set_node(node)
    |
    v
Loop over node.properties
    |
    v
property.create_editor(...)
    |
    v
Qt widget is created now
```

#### `create_editor()`

`create_editor()` is the function that turns a property definition into a real
Qt widget.

It lives on each property class.

```text
TextProperty      creates QLineEdit
BoolProperty      creates QCheckBox
IntProperty       creates QSpinBox
FloatProperty     creates QDoubleSpinBox
ChoiceProperty    creates QComboBox
PathProperty      creates path text field + Browse button
MultilineProperty creates CodeEditor
```

The Properties panel calls it here:

```python
widget = spec.create_editor(
    node,
    node.values.get(spec.name),
    self._set,
    self._body,
)
```

Simple meaning:

```text
spec
    The property definition.
    Example: TextProperty("name", "Name", "World")

node
    The selected node instance.

node.values.get(spec.name)
    The current value for this property.
    Example: node.values["name"]

self._set
    Callback used to save changed values back to the node.

self._body
    Parent Qt widget for the editor.
```

The function returns a Qt widget:

```text
create_editor(...)
    |
    v
QLineEdit / QCheckBox / QSpinBox / etc.
```

For example, `TextProperty.create_editor()` creates a `QLineEdit`.

```python
class TextProperty(NodeProperty):
    def create_editor(self, node, value, on_change, parent=None):
        widget = QLineEdit(value, parent)
        widget.editingFinished.connect(
            lambda: on_change(self.name, widget.text())
        )
        return widget
```

Step by step:

```text
1. PropertyEditor is rebuilding the right-side panel.

2. It sees TextProperty("name", "Name", "World").

3. It calls:
       TextProperty.create_editor(...)

4. TextProperty creates:
       QLineEdit

5. TextProperty connects QLineEdit.editingFinished
   to the on_change callback.

6. TextProperty returns the QLineEdit.

7. PropertyEditor places the QLineEdit in the form.
```

`on_change` is not a separate global function. It is the callback passed by
`PropertyEditor`.

```text
PropertyEditor passes self._set as on_change
    |
    v
Property widget calls on_change(name, value)
    |
    v
PropertyEditor._set(name, value)
    |
    v
node.values[name] = value
```

So the responsibility is:

```text
+------------------------------+
| Property class               |
|------------------------------|
| Creates the Qt editor widget |
+---------------+--------------+
                |
                v
+------------------------------+
| PropertyEditor               |
|------------------------------|
| Places widget in the panel   |
| Writes changed values back   |
| into node.values             |
+------------------------------+
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
