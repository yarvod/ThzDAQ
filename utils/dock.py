class Dock:
    ex = None

    @classmethod
    def add_widget_to_dock(
        cls,
        name: str,
        widget_class,
        **kwargs,
    ):
        cls.ex.add_dock_widget(name, widget_class, **kwargs)

    @classmethod
    def delete_widget_from_dock(cls, name: str):
        cls.ex.delete_dock_widget(name)

    @classmethod
    def rename_widget_in_dock(cls, name: str, title: str):
        if cls.ex is not None:
            cls.ex.rename_dock_widget(name, title)
