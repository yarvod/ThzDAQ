"""The model servers of the assistant: a list, the form of the chosen one (name,
URL, model, key, temperature) and Test, which asks the server whether it
answers and takes tools. A view of ProvidersModel: Save hands it the form."""

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thzdaq_gui import theme
from thzdaq_gui.assistant.provider import Provider
from thzdaq_gui.models.assistant import ProvidersModel

TITLE = "Assistant: model servers"
NEW = "New server"
NO_TEMPERATURE = -0.1  # the spin box's special value: the server's own


class ProvidersDialog(QDialog):
    def __init__(self, providers: ProvidersModel, parent=None):
        super().__init__(parent)
        self.providers = providers
        self.setWindowTitle(TITLE)
        self.resize(640, 360)
        self.editing: Optional[str] = None  # the name of the one in the form

        self.list = QListWidget()
        self.list.currentTextChanged.connect(self.show_provider)
        add = QPushButton(theme.icon("plus"), "Add")
        add.clicked.connect(self.add)
        self.removeButton = QPushButton(theme.icon("delete-outline"), "Remove")
        self.removeButton.clicked.connect(self.remove)
        left = QVBoxLayout()
        left.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(self.removeButton)
        left.addLayout(buttons)

        self.name = QLineEdit()
        self.url = QLineEdit()
        self.url.setPlaceholderText("http://localhost:8000/v1")
        self.model = QLineEdit()
        self.model.setPlaceholderText("as the server lists it (GET /v1/models)")
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("none for a local server")
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(NO_TEMPERATURE, 2.0)
        self.temperature.setSingleStep(0.1)
        self.temperature.setDecimals(2)
        self.temperature.setSpecialValueText("the server's own")
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("URL", self.url)
        form.addRow("Model", self.model)
        form.addRow("Key", self.key)
        form.addRow("Temperature", self.temperature)
        self.keptLabel = QLabel()
        self.keptLabel.setProperty("role", "muted")
        self.keptLabel.setWordWrap(True)
        form.addRow(self.keptLabel)
        self.testButton = QPushButton(theme.icon("lan-check"), "Test")
        self.testButton.setToolTip("Ask the server whether it answers and takes tools")
        self.testButton.clicked.connect(self.test)
        self.saveButton = QPushButton(theme.icon("content-save-outline"), "Save")
        self.saveButton.clicked.connect(self.save)
        actions = QHBoxLayout()
        actions.addWidget(self.testButton)
        actions.addWidget(self.saveButton)
        actions.addStretch()
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        right = QVBoxLayout()
        right.addLayout(form)
        right.addLayout(actions)
        right.addWidget(self.result)
        right.addStretch()
        self.form = QWidget()
        self.form.setLayout(right)

        body = QHBoxLayout()
        body.addLayout(left, 1)
        body.addWidget(self.form, 2)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(close)

        providers.tested.connect(self.show_test)
        self.fill_list()

    def fill_list(self, current: Optional[str] = None) -> None:
        chosen = self.providers.chosen()
        names = [p.name for p in self.providers.all()]
        self.list.clear()
        self.list.addItems(names)
        current = current or (chosen.name if chosen else None)
        if current in names:
            self.list.setCurrentRow(names.index(current))
        else:
            self.show_provider("")

    def show_provider(self, name: str) -> None:
        found = self.providers.get(name) if name else None
        self.editing = found.name if found else None
        self.form.setEnabled(found is not None or self.list.count() == 0)
        self.removeButton.setEnabled(found is not None)
        self.name.setText(found.name if found else "")
        self.url.setText(found.url if found else "")
        self.model.setText(found.model if found else "")
        self.key.setText((self.providers.key(found.name) or "") if found else "")
        temperature = found.temperature if found else None
        self.temperature.setValue(
            NO_TEMPERATURE if temperature is None else temperature
        )
        keys = self.providers.keys
        self.keptLabel.setText(
            "" if keys.kept() else
            f"The system keeps no keys here ({keys.problem}): a key lasts until "
            "the program closes."
        )  # fmt: skip
        self.result.clear()

    def add(self) -> None:
        self.list.clearSelection()
        self.list.setCurrentRow(-1)
        self.show_provider("")
        self.form.setEnabled(True)
        self.name.setText(NEW)
        self.name.setFocus()
        self.name.selectAll()

    def remove(self) -> None:
        if self.editing is not None:
            self.providers.remove(self.editing)
            self.fill_list()

    def provider(self) -> Provider:
        """What the form holds."""
        temperature = self.temperature.value()
        return Provider(
            self.name.text().strip(),
            self.url.text().strip(),
            self.model.text().strip(),
            None if temperature <= NO_TEMPERATURE else temperature,
        )

    def missing(self, provider: Provider) -> str:
        """What the form lacks; empty when it is whole."""
        lacks = [
            label
            for label, value in (
                ("a name", provider.name),
                ("a URL", provider.url),
                ("a model", provider.model),
            )
            if not value
        ]
        taken = provider.name != self.editing and self.providers.get(provider.name)
        if taken:
            lacks.append("another name (this one is taken)")
        return ", ".join(lacks)

    def save(self) -> None:
        provider = self.provider()
        lacks = self.missing(provider)
        if lacks:
            self.show_result(False, f"Give it {lacks}.")
            return
        self.providers.save(provider, self.key.text().strip(), self.editing)
        self.fill_list(provider.name)
        self.show_result(True, "Saved.")

    def test(self) -> None:
        provider = self.provider()
        lacks = self.missing(provider)
        if lacks:
            self.show_result(False, f"Give it {lacks}.")
            return
        self.testButton.setEnabled(False)
        self.result.setStyleSheet("")
        self.result.setText(f"Asking {provider.url}…")
        self.providers.test(provider, self.key.text().strip())

    def show_test(self, name: str, works: bool, text: str) -> None:
        self.testButton.setEnabled(True)
        if name == self.name.text().strip():
            self.show_result(works, text)

    def show_result(self, good: bool, text: str) -> None:
        self.result.setStyleSheet(f"color: {theme.GOOD if good else theme.BAD};")
        self.result.setText(text)
