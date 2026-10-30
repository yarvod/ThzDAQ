"""Operations on what waits for a person: list it, answer it, ask a question."""

from typing import Tuple

from thzdaq_api import approvals as api

from thzdaq_core.application.approvals import Approvals
from thzdaq_core.application.handlers import Handler


class ListApprovals(Handler[api.ListApprovals, Tuple[api.Approval, ...]]):
    operation = api.ListApprovals

    def __init__(self, approvals: Approvals):
        self.approvals = approvals

    def handle(self, args, origin):
        return self.approvals.pending()


class AnswerApproval(Handler[api.AnswerApproval, None]):
    operation = api.AnswerApproval

    def __init__(self, approvals: Approvals):
        self.approvals = approvals

    def handle(self, args, origin):
        answer = api.Answer(args.allowed, args.text, args.value, args.choice, origin)
        self.approvals.answer(args.id, answer, args.confirm)


class AskUser(Handler[api.AskUser, api.UserAnswer]):
    operation = api.AskUser

    def __init__(self, approvals: Approvals):
        self.approvals = approvals

    def handle(self, args, origin):
        return self.approvals.question(
            args.question, args.options, origin, args.timeout
        )


class WaitAnswer(Handler[api.WaitAnswer, api.UserAnswer]):
    operation = api.WaitAnswer

    def __init__(self, approvals: Approvals):
        self.approvals = approvals

    def handle(self, args, origin):
        return self.approvals.wait(args.id, args.timeout)
