"""The safe state from the toolbar: every value the profile names for it (its
safety section) set by the daemon in its order, in steps where the limits ask.
A device a running measurement sweeps is left as it is unless the person goes
on anyway; how each value went is shown."""

from typing import Sequence

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox
from thzdaq_api.devices import SafeState, SafeValue

from thzdaq_gui import profile as fmt
from thzdaq_gui import theme
from thzdaq_gui.wording import SAFE_STATE as TITLE


class SafeStateAction(QAction):
    def __init__(self, session, parent):
        super().__init__(theme.icon("shield-alert-outline"), TITLE, parent)
        self.session = session
        self.setToolTip("Set every device to the safe state of the profile")
        self.triggered.connect(self.ask)

    def values(self) -> int:
        safety = self.session.profile().profile.get(fmt.SAFETY) or {}
        return sum(
            len(values) for values in (safety.get(fmt.SAFE_STATE) or {}).values()
        )

    def ask(self) -> None:
        count = self.values()
        if not count:
            QMessageBox.information(
                self.parent(),
                TITLE,
                "The profile names no safe state: give its values in Setup, Safety.",
            )
            return
        answer = QMessageBox.question(
            self.parent(),
            TITLE,
            f"Set the {count} value(s) of the safe state now? Devices that running "
            "measurements sweep are left as they are.",
        )
        if answer == QMessageBox.Yes:
            self.run(share=False)

    def run(self, share: bool) -> None:
        lab, operation = self.session.lab, SafeState(share=share)
        self.setEnabled(False)
        self.session.calls.submit(
            lambda: lab.call(operation), self.done, self.failed, TITLE, key=TITLE
        )

    def done(self, values: Sequence[SafeValue]) -> None:
        self.setEnabled(True)
        lines = "\n".join(
            f"{v.ref} {v.key} → {v.value}: {v.error or 'set'}" for v in values
        )
        missed = sum(1 for v in values if v.error)
        if not missed:
            QMessageBox.information(self.parent(), TITLE, lines)
            return
        answer = QMessageBox.question(
            self.parent(),
            TITLE,
            f"{lines}\n\n{missed} value(s) were not set. Set them anyway, also on "
            "devices that measurements sweep?",
        )
        if answer == QMessageBox.Yes:
            self.run(share=True)

    def failed(self, error: BaseException) -> None:
        self.setEnabled(True)
        QMessageBox.critical(self.parent(), TITLE, str(error))
