"""Codex as a mode of the assistant's dock, over ACP (offscreen), against a
fake ACP agent (fake_acp.py, the SDK's agent side on stdio) started as the
adapter's command: no Codex, npm or network."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import fake_acp
import pytest
from shots import shot
from thzdaq_api import host
from thzdaq_gui.assistant.acp import Offer, Options
from thzdaq_gui.assistant.chat import Change, Choice, Files, Inputs, Run, Used
from thzdaq_gui.assistant.codex import (
    ADAPTER,
    CONFIRM_FULL_ACCESS,
    FULL_ACCESS,
    TITLE,
    WORKSPACE_WRITE,
)
from thzdaq_gui.chat_widgets import MessageView
from thzdaq_gui.docks.assistant import AssistantWidget
from thzdaq_gui.docks.chat_bar import LOADING
from thzdaq_gui.docks.permission import DETAILS, ChangeCard, PermissionCard
from thzdaq_gui.docks.assistant_settings import AssistantSettings
from thzdaq_gui.docks.chat_history import HistoryPage
from thzdaq_gui.models.assistant import (
    ASKING,
    AssistantModel,
    CodexSettingsModel,
    InstructionsModel,
    Kind,
    ProvidersModel,
    State,
    codex_chat,
)
from thzdaq_gui.settings import settings
from PySide6.QtWidgets import QAbstractItemView, QApplication, QMessageBox

FAKE = Path(__file__).with_name("fake_acp.py")
SESSIONS = "codex"  # the settings' group of Codex's keys


class Fake:
    """The fake agent as the settings start it, and what it was sent."""

    def __init__(self, folder: Path, config: Dict[str, Any]):
        self.log = folder / "acp.jsonl"
        self.config = folder / "acp.json"
        self.config.write_text(json.dumps({"log": str(self.log), **config}))
        self.command = f'"{sys.executable}" "{FAKE}" "{self.config}"'

    def sent(self, method: str) -> List[Any]:
        """The params of each request or notification of method it got."""
        if not self.log.exists():
            return []
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return [
            entry["params"]
            for entry in map(json.loads, lines)
            if entry["method"] == method
        ]


@pytest.fixture(autouse=True)
def no_settings(app):
    """Codex's settings and the instructions a test set go with it."""
    yield
    settings().remove(SESSIONS)
    InstructionsModel().set_instructions("")


@pytest.fixture
def codex_settings(app):
    return CodexSettingsModel()


@pytest.fixture
def agent(tmp_path, codex_settings):
    """The fake agent the settings start, configured as a test asks."""

    def made(**config: Any) -> Fake:
        fake = Fake(tmp_path, config)
        codex_settings.save(fake.command, "", WORKSPACE_WRITE)
        return fake

    return made


@pytest.fixture
def assistant(session, codex_settings):
    instructions = InstructionsModel()
    chat = codex_chat(session, codex_settings, instructions)
    assistant = AssistantModel(
        session, ProvidersModel(), instructions, codex_settings, [chat]
    )
    yield assistant
    assistant.close()


def kinds(assistant) -> List[Kind]:
    return [item.kind for item in assistant.items if item.kind is not Kind.STATS]


def last(assistant, kind: Kind):
    return next(item for item in reversed(assistant.items) if item.kind is kind)


def test_a_message_is_answered_in_items_with_the_benchs_server_and_tokens(
    assistant, agent, session, wait
):
    fake = agent()
    InstructionsModel().set_instructions("Answer in Russian")
    assistant.send("hello")
    assert assistant.busy()
    wait(lambda: not assistant.busy())
    assert assistant.mode.title == TITLE
    assert kinds(assistant) == [Kind.PERSON, Kind.THOUGHT, Kind.ANSWER]
    thought, answer = assistant.items[1:3]
    assert thought.text == "Thinking it over" and thought.state is State.DONE
    assert answer.text == "You said: hello"
    # codex-acp's input is what was read fresh: cached reads and writes add
    assert assistant.items[-1].text.endswith(
        " s · 1.0k in (900 cached) · 25 out (5 reasoning)"
    )
    turn = assistant.last_usage
    assert (turn.read, turn.cached, turn.written, turn.reasoning) == (1020, 900, 25, 5)
    assert (assistant.usage.context, assistant.context_limit()) == (1200, 272000)
    (made,) = fake.sent("session/new")
    folder = session.workspace.folder
    started = host.mcp_server(host.cli_command(), True, folder)
    assert made["cwd"] == str(folder)
    assert made["mcpServers"] == [
        {"name": host.MCP_NAME, "command": started[0], "args": started[1:], "env": []}
    ]
    assert made["systemPrompt"] == {
        "mode": "append", "content": [{"type": "text", "text": "Answer in Russian"}]
    }  # fmt: skip
    assert fake.sent("session/set_config_option") == [
        {"sessionId": "new-1", "configId": "mode", "value": WORKSPACE_WRITE}
    ]
    (prompt,) = fake.sent("session/prompt")
    assert prompt["prompt"] == [{"type": "text", "text": "hello"}]
    kept = assistant.mode.chat.current()
    assert (kept.id, kept.title, kept.workspace) == ("new-1", "On hello", folder)


def test_a_turns_tokens_are_those_codex_acp_sums_cached_ones_added():
    """codex-acp's input tokens are those read fresh; what came from the
    cache, and what went into it, were read too."""
    from acp.schema import PromptResponse
    from thzdaq_gui.assistant.acp import used_of

    told = used_of(PromptResponse(stop_reason="end_turn", usage=fake_acp.USAGE))
    assert told == Used(read=1020, written=25, reasoning=5, cached=900)
    assert used_of(PromptResponse(stop_reason="end_turn")) is None


def test_without_instructions_no_system_prompt_goes(assistant, agent, wait):
    fake = agent()
    assistant.send("hello")
    wait(lambda: not assistant.busy())
    (made,) = fake.sent("session/new")
    assert "systemPrompt" not in made


def test_a_tool_call_is_a_card_with_its_answer(assistant, agent, wait):
    agent()
    assistant.send("tool please")
    wait(lambda: not assistant.busy())
    assert kinds(assistant) == [Kind.PERSON, Kind.CALL, Kind.ANSWER]
    call = assistant.items[1]
    assert (call.name, call.arguments) == ("Read sis_bias_1", {"ref": "sis_bias_1"})
    assert call.text == "0 V" and call.state is State.DONE
    assert call.summary() == "Read sis_bias_1 sis_bias_1 → done"
    assert assistant.items[2].text == "It reads 0 V."


def test_every_piece_comes_before_the_turn_ends(assistant, agent, wait):
    agent()
    assistant.send("many 300")
    wait(lambda: not assistant.busy())
    assert last(assistant, Kind.ANSWER).text == "x" * 300


def test_stop_cancels_the_turn_and_the_next_goes_after_it(assistant, agent, wait):
    fake = agent()
    assistant.send("wait")
    wait(lambda: any(item.kind is Kind.ANSWER for item in assistant.items))
    assistant.stop()
    assert not assistant.busy() and last(assistant, Kind.NOTE).text == "Stopped."
    wait(lambda: fake.sent("session/cancel"))
    assert fake.sent("session/cancel") == [{"sessionId": "new-1"}]
    assistant.send("again")
    wait(lambda: not assistant.busy())
    assert last(assistant, Kind.ANSWER).text == "You said: again"
    assert [item.text for item in assistant.items if item.kind is Kind.ANSWER] == [
        "Waiting",
        "You said: again",
    ]  # what the stopped turn told after Stop is dropped


def test_a_question_is_a_card_whose_answer_goes_back_to_codex(assistant, agent, wait):
    fake = agent()
    widget = AssistantWidget(assistant)
    assistant.send("permission")
    wait(lambda: any(item.kind is Kind.PERMISSION for item in assistant.items))
    asked = last(assistant, Kind.PERMISSION)
    assert asked.state is State.RUNNING and assistant.phase == ASKING
    # the title repeats the command: what a command does is said instead
    assert asked.asked.title == "Run a command"
    assert asked.asked.parts == (Run("ls -la", "/work"),)
    assert [(o.id, o.name, o.allows) for o in asked.asked.options] == [
        ("yes", "Yes, proceed", True),
        ("no", "No, and tell Codex what to do differently", False),
    ]
    (card,) = widget.findChildren(PermissionCard)
    assert not card.choices.isHidden() and card.state.isHidden()
    card.buttons["yes"].click()
    assert asked.state is State.DONE and asked.chosen == "yes"
    assert card.choices.isHidden() and card.state.text() == "Answered: Yes, proceed"
    wait(lambda: not assistant.busy())
    assert fake.sent("answered") == ["yes"]
    assert last(assistant, Kind.ANSWER).text == "chose yes"
    card.buttons["no"].click()  # answered once
    assert asked.chosen == "yes"
    widget.close()


def test_a_stopped_turn_answers_its_question_cancelled(assistant, agent, wait):
    fake = agent()
    widget = AssistantWidget(assistant)
    assistant.send("permission")
    wait(lambda: any(item.kind is Kind.PERMISSION for item in assistant.items))
    assistant.stop()
    asked = last(assistant, Kind.PERMISSION)
    assert asked.state is State.STOPPED and asked.chosen is None
    (card,) = widget.findChildren(PermissionCard)
    assert card.choices.isHidden()
    assert card.state.text() == "Not answered: the turn ended first"
    wait(lambda: fake.sent("answered"))
    assert fake.sent("answered") == ["cancelled"]
    widget.close()


def test_what_is_sent_during_a_turn_goes_as_the_next_turn(assistant, agent, wait):
    fake = agent()
    assistant.send("permission")
    wait(lambda: any(item.kind is Kind.PERMISSION for item in assistant.items))
    assistant.send("next one")
    queued = last(assistant, Kind.PERSON)
    assert queued.queued
    assistant.answer(assistant.items.index(last(assistant, Kind.PERMISSION)), "no")
    wait(lambda: not assistant.busy())
    assert not queued.queued and not queued.unsent
    prompts = [p["prompt"][0]["text"] for p in fake.sent("session/prompt")]
    assert prompts == ["permission", "next one"]
    assert [item.text for item in assistant.items if item.kind is Kind.ANSWER] == [
        "chose no", "You said: next one",
    ]  # fmt: skip


@pytest.mark.parametrize(
    "config, told",
    [
        (
            {"version": "2.6.3"},
            f"Found {ADAPTER} 2.6.3; this program needs {ADAPTER} 2.7.0 or newer,"
            " older than 3.0.0.",
        ),
        ({"name": "other-agent", "version": "2.7.0"}, "Found other-agent 2.7.0;"),
        (
            {"protocol": 2},
            "The adapter speaks ACP version 2; this program speaks version 1.",
        ),
        ({"login": True}, "Codex is not signed in: run `codex login` in a terminal"),
    ],
)
def test_an_adapter_that_does_not_work_is_told_in_a_note(
    assistant, agent, wait, config, told
):
    agent(**config)
    assistant.send("hello")
    wait(lambda: not assistant.busy())
    note = last(assistant, Kind.NOTE).text
    assert note.startswith(told), note


def test_a_missing_adapter_says_where_to_set_its_command(
    assistant, codex_settings, wait
):
    codex_settings.save("no-such-acp-adapter --stdio", "", WORKSPACE_WRITE)
    assistant.send("hello")
    wait(lambda: not assistant.busy())
    note = last(assistant, Kind.NOTE).text
    assert note == (
        "The adapter did not start (no-such-acp-adapter: not found)."
        " Set its command in Settings → Codex (the gear above)."
    )


def test_the_tab_shown_makes_a_session_whose_models_and_efforts_are_apart(
    assistant, agent, codex_settings, wait
):
    fake = agent()
    assert assistant.models() == ()
    widget = AssistantWidget(assistant)  # Codex's tab shown: it gets ready
    picker = widget.modelPicker
    wait(lambda: picker.whole() == "A · Low")
    assert len(fake.sent("session/new")) == 1 and fake.sent("session/prompt") == []
    assert not assistant.finding_models()
    rows = picker.popup.rows
    assert [(row.text(), row.tip) for row in rows.values()] == [
        ("A", "model A"), ("B", "model B"),
    ]  # fmt: skip
    efforts = picker.popup.efforts.buttons
    assert list(efforts) == ["reasoning_effort=low", "reasoning_effort=high"]
    efforts["reasoning_effort=high"].click()
    wait(lambda: picker.whole() == "A · High")
    rows["model=gpt-b"].click()  # B, as the person picks it
    wait(lambda: [e.id for e in assistant.efforts()] == ["reasoning_effort=medium"])
    assert picker.whole() == "B · Medium"
    assert codex_settings.chosen() == ("reasoning_effort=high", "model=gpt-b")
    assistant.new_chat()
    assistant.send("again")
    wait(lambda: not assistant.busy())
    set_after = [
        (p["sessionId"], p["configId"], p["value"])
        for p in fake.sent("session/set_config_option")
    ]
    assert set_after == [
        ("new-1", "mode", WORKSPACE_WRITE),
        ("new-1", "reasoning_effort", "high"),
        ("new-1", "model", "gpt-b"),
        ("new-2", "mode", WORKSPACE_WRITE),  # the person's choices, in their order,
        ("new-2", "reasoning_effort", "high"),  # for a new chat too
        ("new-2", "model", "gpt-b"),
    ]
    assert [p["prompt"][0]["text"] for p in fake.sent("session/prompt")] == ["again"]
    widget.close()


def test_models_known_last_show_at_once_and_the_sessions_correct_them(
    session, agent, codex_settings, tmp_path, wait
):
    gate = tmp_path / "gate"
    agent(gate=str(gate))  # the adapter answers nothing until the gate opens
    old = (Choice("model=old", "Old", "gone since"), Choice("model=gpt-a", "A"))
    codex_settings.keep(Options(models=Offer("model", old, "model=old")))
    instructions = InstructionsModel()
    chat = codex_chat(session, codex_settings, instructions)
    assistant = AssistantModel(
        session, ProvidersModel(), instructions, codex_settings, [chat]
    )
    widget = AssistantWidget(assistant)
    picker = widget.modelPicker
    assert picker.whole() == "Old" and assistant.finding_models()
    assert not picker.popup.loading.isHidden()  # the real ones are on their way
    assert widget.policyPicker.whole() == "Workspace access"  # before any session
    gate.touch()
    wait(lambda: not assistant.finding_models())
    assert [m.title for m in assistant.models()] == ["A", "B"]
    assert picker.whole() == "A · Low" and picker.popup.loading.isHidden()
    assert codex_settings.known().models.choices == tuple(assistant.models())
    assistant.close()
    widget.close()


def test_what_a_session_tells_reaches_the_model_and_its_picker_together(
    session, agent, codex_settings, tmp_path, app
):
    """The adapter's thread tells new options while the window is busy: the
    view model shows them only as the window hears of them, with its picker,
    never one before the other (a slow runner once saw them apart)."""
    import threading

    agent(gate=str(tmp_path / "gate"))  # the adapter tells nothing of its own
    instructions = InstructionsModel()
    chat = codex_chat(session, codex_settings, instructions)
    assistant = AssistantModel(
        session, ProvidersModel(), instructions, codex_settings, [chat]
    )
    widget = AssistantWidget(assistant)
    picker = widget.modelPicker
    app.processEvents()
    before = (tuple(assistant.models()), picker.whole())
    told = Options(models=Offer("model", (Choice("model=gpt-z", "Z"),), "model=gpt-z"))
    thread = threading.Thread(target=chat.configured, args=(told,))
    thread.start()
    thread.join()
    assert (tuple(assistant.models()), picker.whole()) == before  # not heard yet
    app.processEvents()
    assert [m.title for m in assistant.models()] == ["Z"] and picker.whole() == "Z"
    assert not assistant.finding_models()
    assistant.close()
    widget.close()


def test_without_models_known_the_picker_says_they_load(
    assistant, agent, tmp_path, wait
):
    gate = tmp_path / "gate"
    agent(gate=str(gate))
    widget = AssistantWidget(assistant)
    assert widget.modelPicker.whole() == LOADING
    gate.touch()
    wait(lambda: widget.modelPicker.whole() == "A · Low")
    widget.close()


def test_the_mode_changes_at_once_a_turn_running_too_and_full_access_asks_first(
    assistant, agent, wait, monkeypatch
):
    fake = agent()
    widget = AssistantWidget(assistant)
    wait(lambda: widget.modelPicker.whole() == "A · Low")
    picker = widget.policyPicker
    assert not picker.isHidden() and picker.whole() == "Workspace access"
    rows = picker.popup.rows
    assert [(row.text(), row.tip) for row in rows.values()] == [
        (name, about) for _, name, about in fake_acp.MODES
    ]
    sets = lambda: [  # noqa: E731
        (p["configId"], p["value"]) for p in fake.sent("session/set_config_option")
    ]
    assistant.send("permission")  # Codex waits for the person's answer
    wait(lambda: any(item.kind is Kind.PERMISSION for item in assistant.items))
    rows["mode=read-only"].click()
    QApplication.processEvents()
    assert picker.whole() == "Read-only"  # at once
    wait(lambda: ("mode", "read-only") in sets())
    assert assistant.busy()  # set while the turn runs, not after it
    assistant.stop()
    asked: List[str] = []
    answer = QMessageBox.No
    monkeypatch.setattr(
        QMessageBox, "question", lambda *given: asked.append(given[2]) or answer
    )
    picker.click()
    picker.popup.rows[f"mode={FULL_ACCESS}"].click()
    assert asked == [CONFIRM_FULL_ACCESS]
    assert assistant.chosen_policy() == "mode=read-only"  # refused: unchanged
    answer = QMessageBox.Yes
    picker.click()
    picker.popup.rows[f"mode={FULL_ACCESS}"].click()
    assert assistant.chosen_policy() == f"mode={FULL_ACCESS}"
    wait(lambda: ("mode", FULL_ACCESS) in sets() and picker.whole() == "Full access")
    assistant.send("permission")  # full access: Codex asks nothing
    answered = lambda: [  # noqa: E731
        item.text for item in assistant.items if item.kind is Kind.ANSWER
    ]
    wait(lambda: answered() == ["ran it without asking"])
    assert sum(item.kind is Kind.PERMISSION for item in assistant.items) == 1
    shot(widget, "codex_mode_full_access")
    picker.click()
    shot(picker.popup, "codex_mode_popup")
    picker.popup.hide()
    widget.close()


def test_a_new_chat_starts_in_the_settings_mode_again(assistant, agent, wait):
    fake = agent()
    assistant.choose_policy("mode=read-only")  # before the session: it is made so
    assistant.send("hello")
    wait(lambda: not assistant.busy())
    assistant.new_chat()
    assert assistant.chosen_policy() == f"mode={WORKSPACE_WRITE}"
    assistant.send("again")
    wait(lambda: not assistant.busy())
    modes = [
        (p["sessionId"], p["value"])
        for p in fake.sent("session/set_config_option")
        if p["configId"] == "mode"
    ]
    assert modes == [("new-1", "read-only"), ("new-2", WORKSPACE_WRITE)]


def card_texts(card: PermissionCard) -> List[str]:
    """What the card shows of what is asked, folded parts unfolded."""
    for fold in card.findChildren(ChangeCard):
        fold.set_expanded(True)
    return [view.text() for view in card.details.findChildren(MessageView)]


@pytest.mark.parametrize("how", ["long", "edit", "mcp"])
def test_a_permission_card_shows_what_is_asked_within_a_narrow_dock(
    assistant, agent, wait, app, how
):
    agent()
    widget = AssistantWidget(assistant)
    widget.resize(320, 640)
    widget.show()
    assistant.send(f"permission {how}")
    wait(lambda: any(item.kind is Kind.PERMISSION for item in assistant.items))
    asked = last(assistant, Kind.PERMISSION).asked
    (card,) = widget.findChildren(PermissionCard)
    texts = card_texts(card)
    for _ in range(3):  # the layout follows the heights
        QApplication.processEvents()
    if how == "long":
        assert asked.title == "Run a command"
        assert asked.parts == (Run(fake_acp.LONG, "/work"),)
        assert texts == [fake_acp.LONG]
        assert len(card.buttons) == 5
    elif how == "edit":  # its diff came with the call's start, as codex-acp sends
        assert asked.title == "Edit files"
        sweep, notes = asked.parts
        assert isinstance(sweep, Change) and sweep.path == "/work/scripts/sweep.py"
        assert sweep.counted() == (1, 2) and notes.counted() == (3, 0)
        diff = texts[0].splitlines()
        assert "+line seven" in diff and "-line 7" in diff and "-line 30" in diff
        assert not any(isinstance(part, Files) for part in asked.parts)
    else:  # an MCP tool's call, named by its id alone
        assert asked.title == "thzdaq: set_quantity"
        assert asked.parts == (
            Inputs((("ref", "sis_bias_1"), ("key", "voltage_set"), ("value", "2 mV"))),
        )
        assert texts == ["ref: sis_bias_1\nkey: voltage_set\nvalue: 2 mV"]
    messages = widget.scroll.widget()
    assert messages.minimumSizeHint().width() <= 320
    assert not widget.scroll.horizontalScrollBar().isVisible()
    assert card.width() <= 320 and card.details.height() <= DETAILS
    for button in card.buttons.values():  # in rows, none past the card
        assert button.geometry().right() < card.choices.width()
    rows = {button.y() for button in card.buttons.values()}
    assert len(rows) >= (3 if how == "long" else 2)
    shot(widget, f"codex_permission_{how}")
    card.buttons["no"].click()
    wait(lambda: not assistant.busy())
    widget.close()


def test_history_lists_codexs_chats_and_opens_one_to_go_on(
    assistant, agent, session, wait
):
    folder = str(session.workspace.folder)
    fake = agent(
        sessions=[
            {"sessionId": "s1", "cwd": folder, "title": "Old", "updatedAt": "2026-11-01T10:00:00Z"},
            {"sessionId": "s2", "cwd": folder, "title": "Newer", "updatedAt": "2026-11-02T10:00:00Z"},
            {"sessionId": "s3", "cwd": "/elsewhere", "title": "Other"},
        ],
        history={
            "s1": [
                ["user", "hello"], ["thought", "hm"], ["agent", "hi there"],
                ["tool", "t1", "Read x", {"ref": "x"}, "1 V"],
                ["user", "again"], ["agent", "yes"],
            ]
        },
    )  # fmt: skip
    assistant.find_chats()
    wait(lambda: assistant.chats())
    assert [(c.id, c.title) for c in assistant.chats()] == [
        ("s2", "Newer"),
        ("s1", "Old"),
    ]
    assert [c.id for c in assistant.chats("ol")] == ["s1"]
    assistant.open_chat("s1")
    wait(lambda: assistant.items)
    assert kinds(assistant) == [
        Kind.PERSON, Kind.THOUGHT, Kind.ANSWER, Kind.CALL, Kind.PERSON, Kind.ANSWER,
    ]  # fmt: skip
    texts = [item.text for item in assistant.items if item.kind is not Kind.STATS]
    assert texts == ["hello", "hm", "hi there", "1 V", "again", "yes"]
    assert assistant.current_chat() == "s1" and not assistant.busy()
    assistant.send("more")
    wait(lambda: not assistant.busy())
    assert [p["sessionId"] for p in fake.sent("session/prompt")] == ["s1"]
    assert fake.sent("session/new") == []
    assert last(assistant, Kind.ANSWER).text == "You said: more"


def test_a_chat_is_renamed_when_codex_takes_titles_else_rename_is_hidden(
    assistant, agent, session, wait
):
    folder = str(session.workspace.folder)
    listed = [{"sessionId": "s1", "cwd": folder, "title": "Old"}]
    fake = agent(sessions=listed)
    page = HistoryPage(assistant)
    assistant.find_chats()
    wait(lambda: assistant.chats())
    assert assistant.renames()
    assert page.list.editTriggers() == QAbstractItemView.EditKeyPressed
    assistant.rename_chat("s1", "  Bias sweep ")
    assert assistant.chats()[0].title == "Bias sweep"
    wait(lambda: fake.sent("session/set_title"))
    assert fake.sent("session/set_title") == [
        {"sessionId": "s1", "title": "Bias sweep"}
    ]
    page.close()


def test_rename_is_hidden_when_codex_takes_no_titles(assistant, agent, session, wait):
    folder = str(session.workspace.folder)
    agent(titles=False, sessions=[{"sessionId": "s1", "cwd": folder, "title": "Old"}])
    page = HistoryPage(assistant)
    assistant.find_chats()
    wait(lambda: assistant.chats())
    assert not assistant.renames()
    assert page.list.editTriggers() == QAbstractItemView.NoEditTriggers
    page.close()


def test_an_adapter_that_ends_is_told_and_started_again_for_the_chat(
    assistant, agent, wait
):
    fake = agent()
    assistant.send("hello")
    wait(lambda: not assistant.busy())
    assistant.send("die")
    wait(lambda: not assistant.busy())
    note = last(assistant, Kind.NOTE).text
    assert (
        note == "The adapter ended (exit code 3).\n\nboom: the fake adapter fell over"
    )
    assistant.send("again")
    wait(lambda: not assistant.busy())
    assert last(assistant, Kind.ANSWER).text == "You said: again"
    assert len(fake.sent("initialize")) == 2  # a new process
    assert [p["sessionId"] for p in fake.sent("session/resume")] == ["new-1"]
    assert len(fake.sent("session/new")) == 1


def test_new_instructions_resume_the_chat_with_them(assistant, agent, wait):
    fake = agent()
    assistant.send("hello")
    wait(lambda: not assistant.busy())
    InstructionsModel().set_instructions("Be brief")
    assistant.send("again")
    wait(lambda: not assistant.busy())
    (resumed,) = fake.sent("session/resume")
    assert resumed["sessionId"] == "new-1"
    assert resumed["systemPrompt"]["content"] == [{"type": "text", "text": "Be brief"}]
    assert len(fake.sent("session/new")) == 1


def test_the_gui_thread_never_waits_for_the_adapter(
    assistant, agent, tmp_path, app, wait
):
    """The adapter answers nothing until the gate opens: everything the window
    asks of Codex meanwhile has returned, the window goes on."""
    gate = tmp_path / "gate"
    fake = agent(gate=str(gate))
    assistant.send("hello")
    assistant.find_chats()
    assistant.choose_model("model=gpt-b")
    assert assistant.busy() and kinds(assistant) == [Kind.PERSON]
    wait(lambda: fake.sent("initialize"))  # it got initialize, it does not answer
    app.processEvents()
    assert not gate.exists() and kinds(assistant) == [Kind.PERSON]
    gate.touch()
    wait(lambda: not assistant.busy())
    assert last(assistant, Kind.ANSWER).text == "You said: hello"


def test_the_settings_test_reports_the_adapter_found(
    providers_model, agent, codex_settings, wait
):
    fake = agent()
    dialog = AssistantSettings(providers_model, InstructionsModel(), codex_settings)
    page = dialog.codex
    assert page.command.text() == fake.command
    page.testButton.click()
    assert not page.testButton.isEnabled()
    wait(lambda: page.testButton.isEnabled(), 15)
    assert page.result.text() == (f"Codex ({ADAPTER} 2.7.0), ACP version 1")
    old = agent(version="3.1.0")
    page.command.setText(old.command)
    page.testButton.click()
    wait(lambda: page.testButton.isEnabled(), 15)
    assert page.result.text().startswith(f"Found {ADAPTER} 3.1.0;")
    page.mode.setCurrentIndex(page.mode.findData("read-only"))
    page.command.setText("")
    page.saveButton.click()
    assert codex_settings.mode() == "read-only"
    assert codex_settings.command() == f"npx -y {ADAPTER}"  # empty: the default
    dialog.close()


@pytest.fixture
def providers_model(app):
    return ProvidersModel()


def test_the_images_codex_sends_are_shown_as_images(assistant, agent, tmp_path, wait):
    """As codex-acp 2.7.0 sends them: an image in its message, an image
    generation's tool call with the image (its bytes again in the raw output,
    never shown as words), an image looked at named by its path (read), and
    a generation whose bytes Codex kept, its file in the raw output."""
    from model_server import png

    looked_at, saved = tmp_path / "screen.png", tmp_path / "kept.png"
    looked_at.write_bytes(png(8, 5))
    saved.write_bytes(png(2, 2))
    agent(picture=str(looked_at), saved=str(saved))
    assistant.send("image please")
    wait(lambda: not assistant.busy())
    assert kinds(assistant) == [
        Kind.PERSON, Kind.IMAGE, Kind.CALL, Kind.IMAGE, Kind.CALL, Kind.IMAGE,
        Kind.CALL, Kind.IMAGE, Kind.ANSWER,
    ]  # fmt: skip
    images = [i.image for i in assistant.items if i.kind is Kind.IMAGE]
    assert [(i.data, i.mime, i.name) for i in images] == [
        (fake_acp.SAID_IMAGE, "image/png", ""),
        (fake_acp.MADE, "image/png", "square.png"),
        (looked_at.read_bytes(), "image/png", "screen.png"),
        (saved.read_bytes(), "image/png", "kept.png"),
    ]
    made = assistant.items[2]
    assert made.name == "Image generation" and made.state is State.DONE
    assert made.text == f"Revised prompt: {fake_acp.REVISED}"  # no base64
    assert assistant.items[4].name == f"View Image {looked_at}"
    assert last(assistant, Kind.ANSWER).text == "Here they are."


def test_a_loaded_chat_shows_its_images_again(
    assistant, agent, session, tmp_path, wait
):
    import base64

    from model_server import png

    saved = tmp_path / "kept.png"
    saved.write_bytes(png(3, 3))
    folder = str(session.workspace.folder)
    encoded = base64.b64encode(png(4, 1)).decode()
    agent(
        sessions=[{"sessionId": "s1", "cwd": folder, "title": "Drawn"}],
        history={
            "s1": [
                ["user", "draw"], ["image", encoded],
                ["generated", "g1", str(saved)], ["agent", "done"],
            ]
        },
    )  # fmt: skip
    assistant.find_chats()
    wait(lambda: assistant.chats())
    assistant.open_chat("s1")
    wait(lambda: assistant.items)
    assert kinds(assistant) == [
        Kind.PERSON,
        Kind.IMAGE,
        Kind.CALL,
        Kind.IMAGE,
        Kind.ANSWER,
    ]
    images = [i.image.data for i in assistant.items if i.kind is Kind.IMAGE]
    assert images == [png(4, 1), png(3, 3)]
