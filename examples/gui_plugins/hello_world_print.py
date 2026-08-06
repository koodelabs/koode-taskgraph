def register_taskgraph_plugin(api):
    def build_hello_world_print_graph():
        text = api.create_node(
            "input.text",
            name="Hello World Text",
            values={"text": "hello world"},
            position=(0, 0),
        )
        printer = api.create_node(
            "output.print",
            name="Print Hello World",
            position=(300, 0),
        )
        api.connect_dependency(text, printer)
        api.connect_attribute(text, "text", printer, "value")

    api.add_menu_action(
        "Examples",
        "Create Hello World Print Graph",
        build_hello_world_print_graph,
    )
