from PyQt6.QtWidgets import QGroupBox


class ExpandableGroupBox(QGroupBox):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_height = self.maximumHeight()
        self.setCheckable(True)

        self.toggled.connect(self.on_pressed)

    def on_pressed(self, checked):
        if checked:
            self.setFixedHeight(self.max_height)
        else:
            self.setFixedHeight(45)
