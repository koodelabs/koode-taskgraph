def register_taskgraph_plugin(api):
    def build_bingooo_print_graph():
        text = api.create_node(
            "input.text",
            name="Bingooo Text",
            values={"text": "Bingooo!!"},
            position=(0, 0),
        )
        printer = api.create_node(
            "output.print",
            name="Print Bingooo",
            position=(300, 0),
        )
        api.connect_dependency(text, printer)
        api.connect_attribute(text, "text", printer, "value")

    api.add_menu_action(
        "Examples",
        "Create Bingooo Print Graph",
        build_bingooo_print_graph,
    )
