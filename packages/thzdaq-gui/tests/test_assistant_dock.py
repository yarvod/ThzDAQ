"""The assistant in the window (offscreen): its model servers, the chat's view
model on the simulated bench with a model's server on localhost, the dock
and the dialog of the servers."""

import os
from pathlib import Path

import pytest
from lab_helpers import Window
from model_server import calls, says
from thzdaq_gui.assistant.keys import SERVICE
from thzdaq_gui.assistant.provider import Provider
from thzdaq_gui.models.assistant import (
    NO_PROVIDER,
    AssistantModel,
    Kind,
    ProvidersModel,
    State,
)

BIAS = {"ref": "sis_bias_1", "key": "voltage_set", "value": "1 mV"}
# Pictures of the dock for a person to look at, when asked for (a folder)
SHOTS = os.environ.get("THZDAQ_SHOTS")


def shot(widget, name: str) -> None:
    if SHOTS:
        widget.grab().save(str(Path(SHOTS) / f"{name}.png"))


@pytest.fixture(autouse=True)
def no_servers(app):
    """The settings outlive a test: the servers a test added go with it."""
    yield
    providers = ProvidersModel()
    for provider in providers.all():
        providers.remove(provider.name)


@pytest.fixture
def providers(model):
    providers = ProvidersModel()
    providers.save(Provider("local", model.url, "qwen"), "secret")
    return providers


@pytest.fixture
def assistant(session, providers):
    assistant = AssistantModel(session, providers)
    yield assistant
    assistant.close()


@pytest.fixture
def person(connect):
    """A person answering in another window of the same daemon."""
    window = Window(connect(True))
    yield window
    window.stop()


def kinds(assistant):
    return [item.kind for item in assistant.items]


def test_servers_are_kept_with_their_keys_in_the_keyring(providers, keys, model):
    again = ProvidersModel()
    assert again.all() == (Provider("local", model.url, "qwen"),)
    assert again.chosen().name == "local" and again.key("local") == "secret"
    again.save(Provider("vllm", model.url, "qwen", 0.2), "other", was="local")
    assert keys.kept == {(SERVICE, "vllm"): "other"}
    assert ProvidersModel().chosen() == Provider("vllm", model.url, "qwen", 0.2)
    again.remove("vllm")
    assert ProvidersModel().all() == () and not keys.kept


def test_test_is_told_from_its_thread(providers, model, wait):
    heard = []
    providers.tested.connect(lambda *told: heard.append(told))
    model.replies = [calls(("ping", {}))]
    providers.test(providers.chosen(), "secret")
    wait(lambda: heard)
    assert heard == [("local", True, "qwen answers and calls tools")]


def test_a_message_is_answered_with_the_benchs_tools(assistant, model, wait):
    model.replies = [
        calls(("read_device", {"ref": "sis_bias_1"})),
        says("The bias is **0 V**."),
    ]
    busy = []
    assistant.busy_changed.connect(busy.append)
    assistant.send("what is the bias?")
    wait(lambda: busy == [True, False])
    assert kinds(assistant) == [Kind.PERSON, Kind.CALL, Kind.ANSWER]
    card = assistant.items[1]
    assert card.state == State.DONE and card.text.startswith("sis_bias_1: ")
    assert card.summary() == "read_device sis_bias_1 → done"
    assert assistant.items[2].text == "The bias is **0 V**."


def test_a_refusal_shows_on_its_card(assistant, model, person, wait):
    model.replies = [calls(("set_quantity", BIAS)), says("As you say.")]
    assistant.send("set 1 mV")
    person.asked()
    person.answer(allowed=False, text="not yet")
    wait(lambda: not assistant.busy())
    card = assistant.items[1]
    assert card.state == State.REFUSED and "not yet" in card.text
    assert card.summary() == "set_quantity sis_bias_1 voltage_set 1 mV → refused"


def test_stop_ends_the_turn_while_a_call_waits(assistant, model, person, wait):
    model.replies = [calls(("set_quantity", BIAS))]
    assistant.send("set 1 mV")
    person.asked()  # the call waits for the person
    wait(lambda: Kind.CALL in kinds(assistant))
    assistant.stop()
    assert not assistant.busy()
    assert assistant.items[1].state == State.STOPPED
    assert assistant.items[-1].text == "Stopped."
    person.answer(allowed=False)  # the stopped call ends; nothing more is told
    model.replies = [says("Ready.")]
    assistant.send("and now?")
    wait(lambda: not assistant.busy())
    assert assistant.items[-1].text == "Ready."
    messages = assistant.conversation.messages
    assert [m["role"] for m in messages] == [
        "user", "assistant", "tool", "user", "assistant",
    ]  # fmt: skip


def test_without_a_server_it_says_to_add_one(session, app):
    assistant = AssistantModel(session, ProvidersModel())
    assistant.send("hello")
    assert assistant.items[-1].text == NO_PROVIDER and not assistant.busy()


def test_a_new_chat_forgets_the_conversation(assistant, model, wait):
    assistant.send("hello")
    wait(lambda: not assistant.busy())
    cleared = []
    assistant.cleared.connect(lambda: cleared.append(True))
    assistant.new_chat()
    assert cleared and not assistant.items
    assert not assistant.conversation.messages


def test_another_profile_is_told_to_the_model_at_the_next_turn(
    assistant, session, model, wait
):
    assistant.send("hello")
    wait(lambda: not assistant.busy())
    session.config_changed.emit()
    assistant.send("again")
    wait(lambda: not assistant.busy())
    first, again = (asked["messages"][0]["content"] for asked in model.asked)
    assert first == again  # made anew: the same bench, the same prompt
    assert assistant.conversation.system == first


def test_the_dock_shows_messages_and_folded_cards(assistant, model, person, wait):
    from thzdaq_gui.docks.assistant import AssistantWidget, CallCard

    model.replies = [
        calls(
            ("list_devices", {}),
            ("set_quantity", {**BIAS, "value": "20 mV"}),
        ),
        says(
            "There are two SIS biases. You refused **20 mV** on `sis_bias_1`: "
            "nothing was set. Shall I take an I-V curve first?"
        ),
    ]
    widget = AssistantWidget(assistant)
    widget.resize(440, 520)
    widget.show()
    widget.input.setPlainText("set sis_bias_1 to 20 mV")
    widget.send_or_stop()
    person.asked()
    person.answer(allowed=False, text="too high for this junction")
    wait(lambda: not assistant.busy())
    cards = widget.findChildren(CallCard)
    assert [card.title() for card in cards] == [
        "list_devices → done",
        "set_quantity sis_bias_1 voltage_set 20 mV → refused",
    ]
    assert not any(card.expanded() for card in cards)
    cards[1].set_expanded(True)
    assert "too high for this junction" in cards[1].answer.text()
    assert widget.input.toPlainText() == ""
    assert widget.providerBox.currentText() == "local"
    shot(widget, "assistant_dock")
    widget.close()


def test_the_dialog_saves_a_server_and_tests_it(providers, model, wait):
    from thzdaq_gui.docks.providers import ProvidersDialog

    dialog = ProvidersDialog(providers)
    dialog.show()
    assert dialog.list.count() == 1 and dialog.key.text() == "secret"
    dialog.add()
    dialog.url.setText(model.url)
    dialog.model.setText("qwen")
    dialog.save()
    assert "a name" not in dialog.result.text()  # "New server" is a name
    assert [p.name for p in providers.all()] == ["local", "New server"]
    dialog.name.setText("local")
    dialog.save()
    assert "taken" in dialog.result.text()
    dialog.name.setText("vllm")
    dialog.key.setText("")
    model.takes_tools = False
    dialog.test()
    wait(lambda: dialog.testButton.isEnabled())
    assert "requires --enable-auto-tool-choice" in dialog.result.text()
    model.takes_tools = True
    model.replies = [calls(("ping", {}))]
    dialog.test()
    wait(lambda: dialog.testButton.isEnabled())
    assert dialog.result.text() == "qwen answers and calls tools"
    shot(dialog, "assistant_providers")
    dialog.close()


def test_a_cards_line_cuts_a_long_argument():
    from thzdaq_gui.models.assistant import Item

    script = '"""P-V"""\nfrom thzdaq import connect\n' + "x = 1\n" * 50
    card = Item(
        Kind.CALL, name="write_custom", arguments={"script": "pv", "text": script}
    )
    line = card.summary()
    assert line.startswith('write_custom pv """P-V""" from thzdaq import connect')
    assert line.endswith("… → done") and len(line) < 90
