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
