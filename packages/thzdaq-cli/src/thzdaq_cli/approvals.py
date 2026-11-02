"""thzdaq approvals [answer|watch]: what waits for a person in the daemon (an
agent's operation, or its question) and the answers. watch asks the person at
this terminal about each one as it comes, as the window's dialog does; the
first answer, here or in a window, closes it everywhere. Only people answer:
the daemon refuses an agent's shell, and --yes answers nothing here."""

import sys
from typing import Optional

from thzdaq_api.approvals import AnswerApproval, Approval, ListApprovals
from thzdaq_api.errors import ErrorCode, LabError
from thzdaq_api.events import ApprovalAnswered, ApprovalRequested
from thzdaq_api.origins import ANSWERING_CLI, agent

from thzdaq_cli import show
from thzdaq_cli.client import FAILED, OK, Client, origin
from thzdaq_cli.measurements import Heard


def add(commands) -> None:
    group = commands.add_parser(
        "approvals", help="what waits for a person: list it, answer it, watch"
    )
    group.set_defaults(run=list_approvals)
    actions = group.add_subparsers(dest="action", metavar="ACTION")
    answer = actions.add_parser("answer", help="allow what waits, or not")
    answer.add_argument("id", type=int)
    verdict = answer.add_mutually_exclusive_group(required=True)
    verdict.add_argument(
        "--allow", action="store_true", help="allow it; answer a question"
    )
    verdict.add_argument("--deny", action="store_true", help="refuse it")
    answer.add_argument(
        "--value", help='allow it with another value, in its unit ("2.2 mV")'
    )
    answer.add_argument(
        "--text", default="", help="words for the agent: why not, what instead"
    )
    answer.add_argument(
        "--confirm", default="", metavar="REF",
        help="the device a dangerous step asks to type",
    )  # fmt: skip
    answer.add_argument("--choice", help="one of a question's options")
    answer.set_defaults(run=answer_approval)
    actions.add_parser(
        "watch", help="ask about each one in this terminal as it comes (Ctrl+C ends)"
    ).set_defaults(run=watch_approvals, kind=ANSWERING_CLI)


def list_approvals(args, client: Client) -> int:
    found = client.call(ListApprovals())
    client.out(
        found, lambda a: "\n\n".join(show.approval(i) for i in a) or "nothing waits"
    )
    return OK


def answer_approval(args, client: Client) -> int:
    client.call(
        AnswerApproval(
            id=args.id, allowed=args.allow, text=args.text, value=args.value,
            choice=args.choice, confirm=args.confirm,
        )
    )  # fmt: skip
    print(f"#{args.id} {'allowed' if args.allow else 'denied'}")
    return OK


def watch_approvals(args, client: Client) -> int:
    if agent(origin()):
        print("thzdaq: an agent's shell does not answer for a person", file=sys.stderr)
        return FAILED
    if not sys.stdin.isatty():
        print(
            "thzdaq: watch asks in a terminal; without one: approvals answer",
            file=sys.stderr,
        )
        return FAILED
    heard = Heard(client.lab)  # from now on a person answers here
    print("answering for agents here; Ctrl+C ends", file=sys.stderr)
    try:
        seen = set()
        for approval in client.call(ListApprovals()):
            seen.add(approval.id)
            ask(client, approval)
        for body in heard.bodies():
            if isinstance(body, ApprovalRequested) and body.approval.id not in seen:
                seen.add(body.approval.id)
                ask(client, body.approval)
            elif isinstance(body, ApprovalAnswered):
                print(show.answer(body.id, body.answer))
    except (KeyboardInterrupt, EOFError):
        print(file=sys.stderr)
        return OK
    finally:
        heard.stop()


def ask(client: Client, approval: Approval) -> None:
    """Until the daemon takes the answer, or it was answered elsewhere."""
    if approval.id not in {a.id for a in client.call(ListApprovals())}:
        return  # answered in a window, or nobody did in time
    print()
    print(show.approval(approval))
    while True:
        answer = questioned(approval) if not approval.operation else decided(approval)
        try:
            client.call(answer)
            return
        except LabError as e:
            if e.code != ErrorCode.INVALID_ARGUMENTS:
                print(f"thzdaq: {e}", file=sys.stderr)
                return
            print(f"thzdaq: {e}: again", file=sys.stderr)


def decided(approval: Approval) -> AnswerApproval:
    """An operation: allow it (another value, the device typed for a dangerous
    step) or not, with words for the agent."""
    if input("allow? [y/N] ").strip().lower() not in ("y", "yes"):
        words = input("why not, what instead (Enter: nothing): ").strip()
        return AnswerApproval(id=approval.id, allowed=False, text=words)
    value: Optional[str] = None
    if approval.value is not None:
        typed = input(f"value [{approval.value}]: ").strip()
        value = typed if typed and typed != approval.value else None
    confirm = ""
    if approval.confirm:
        confirm = input(f"type {approval.confirm} to allow it: ").strip()
    words = input("words for the agent (Enter: none): ").strip()
    return AnswerApproval(
        id=approval.id, allowed=True, text=words, value=value, confirm=confirm
    )


def questioned(approval: Approval) -> AnswerApproval:
    """A question: one of its options, words, or both; nothing declines it."""
    choice: Optional[str] = None
    if approval.options:
        for number, option in enumerate(approval.options, 1):
            print(f"  {number}) {option}")
        typed = input(f"choice [1-{len(approval.options)}, Enter: none]: ").strip()
        if typed.isdigit() and 1 <= int(typed) <= len(approval.options):
            choice = approval.options[int(typed) - 1]
        elif typed:
            choice = typed  # an option typed as it is; the daemon checks it
    words = input("answer (Enter: none): ").strip()
    given = choice is not None or bool(words)
    return AnswerApproval(id=approval.id, allowed=given, text=words, choice=choice)
