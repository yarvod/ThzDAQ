import sys

from PyQt6.QtWidgets import QApplication

from interface.index import App

if __name__ == "__main__":
    app = QApplication(sys.argv)
    ex = App()
    sys.exit(app.exec())
