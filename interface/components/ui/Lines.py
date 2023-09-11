from PyQt6 import QtWidgets


class HLine(QtWidgets.QFrame):
    """
    a horizontal separation line\n
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setMinimumWidth(1)
        self.setFixedHeight(20)
        self.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Minimum
        )
        return


class VLine(QtWidgets.QFrame):
    """
    a vertical separation line\n
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedWidth(20)
        self.setMinimumHeight(1)
        self.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        self.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Minimum, QtWidgets.QSizePolicy.Policy.Preferred
        )
        return
