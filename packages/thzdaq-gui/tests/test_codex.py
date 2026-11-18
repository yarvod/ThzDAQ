"""Codex as a mode of the assistant's dock, over ACP (offscreen), against a
fake ACP agent (fake_acp.py, the SDK's agent side on stdio) started as the
adapter's command: no Codex, npm or network."""

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from thzdaq_api import host
from thzdaq_gui.assistant.codex import ADAPTER, TITLE, WORKSPACE_WRITE
from thzdaq_gui.docks.assistant import AssistantWidget, PermissionCard
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
from PySide6.QtWidgets import QAbstractItemView

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
    assert assistant.items[-1].text.endswith(
        " s · 1 step · 100 in · 20 out (5 thinking)"
    )
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
    assert (asked.asked.title, asked.asked.detail) == ("Run ls", "command: ls -la")
    assert [(o.id, o.name, o.allows) for o in asked.asked.options] == [
        ("yes", "Allow", True), ("no", "Reject", False),
    ]  # fmt: skip
    (card,) = widget.findChildren(PermissionCard)
    assert not card.choices.isHidden() and card.state.isHidden()
    card.buttons["yes"].click()
    assert asked.state is State.DONE and asked.chosen == "yes"
    assert card.choices.isHidden() and card.state.text() == "Answered: Allow"
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


def test_the_model_chooser_offers_codexs_models_and_efforts(
    assistant, agent, codex_settings, wait
):
    fake = agent()
    widget = AssistantWidget(assistant)
    assert assistant.models() == () and widget.modelBox.count() == 0
    assistant.send("hello")
    wait(lambda: not assistant.busy())
    box = widget.modelBox
    shown = [box.itemText(i) for i in range(box.count())]
    assert shown == ["A · Low", "A · High", "B"]
    assert box.currentText() == "A · Low"
    box.activated.emit(2)  # B, as the person picks it
    wait(lambda: assistant.chosen_model() == "reasoning_effort=medium")
    assert [box.itemText(i) for i in range(box.count())] == ["A", "B · Medium"]
    assert box.currentText() == "B · Medium"
    assert codex_settings.chosen() == ("model=gpt-b",)
    assistant.new_chat()
    assistant.send("again")
    wait(lambda: not assistant.busy())
    set_after = [
        (p["sessionId"], p["configId"], p["value"])
        for p in fake.sent("session/set_config_option")
    ]
    assert set_after == [
        ("new-1", "mode", WORKSPACE_WRITE),
        ("new-1", "model", "gpt-b"),
        ("new-2", "mode", WORKSPACE_WRITE),
        ("new-2", "model", "gpt-b"),  # the person's choice, for a new chat too
    ]
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
