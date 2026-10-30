"""What waits for a person in the daemon: an agent's operation to allow, or its
question. The window shows each one and answers it; the first person to answer
(here or in another window) closes it everywhere."""

from typing import Dict, Optional

from PySide6.QtCore import QObject, Signal
from thzdaq_api.approvals import AnswerApproval, Approval, ListApprovals
from thzdaq_api.events import ApprovalAnswered, ApprovalRequested

LANE = "approvals"  # its calls do not wait behind a device


class ApprovalsModel(QObject):
    asked = Signal(object)  # Approval, waiting for an answer
    closed = Signal(int)  # its id: answered, here or elsewhere, or timed out
    failed = Signal(int, str)  # its id, why the answer was refused

    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.session = session
        self.pending: Dict[int, Approval] = {}
        session.bridge.approval_requested.connect(self._requested)
        session.bridge.approval_answered.connect(self._answered)
        session.station_changed.connect(self.refresh)  # another lab, or a resync
        self.refresh()

    def refresh(self) -> None:
        """What waits now in the lab the window works with."""
        for id in list(self.pending):
            self._close(id)
        for approval in self.session.call(ListApprovals()):
            self._add(approval)

    def answer(
        self,
        id: int,
        allowed: bool,
        text: str = "",
        value: Optional[str] = None,
        choice: Optional[str] = None,
        confirm: str = "",
    ) -> None:
        lab, call = self.session.lab, AnswerApproval(
            id=id, allowed=allowed, text=text, value=value, choice=choice,
            confirm=confirm,
        )  # fmt: skip
        self.session.calls.submit(
            lambda: lab.call(call),
            None,
            lambda error: self.failed.emit(id, str(error)),
            "approvals",
            key=LANE,
        )

    def _requested(self, body: ApprovalRequested) -> None:
        self._add(body.approval)

    def _answered(self, body: ApprovalAnswered) -> None:
        self._close(body.id)

    def _add(self, approval: Approval) -> None:
        if approval.id not in self.pending:
            self.pending[approval.id] = approval
            self.asked.emit(approval)

    def _close(self, id: int) -> None:
        if self.pending.pop(id, None) is not None:
            self.closed.emit(id)
