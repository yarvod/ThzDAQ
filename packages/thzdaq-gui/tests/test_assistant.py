"""The assistant without Qt: a conversation with a model's server on localhost
(model_server) and the simulated bench, called as the assistant; the system
prompt; the providers' Test; the keys."""

import threading
import time

import pytest
from lab_helpers import Window
from model_server import NO_TOOLS, calls, says
from thzdaq_api import catalog, guides
from thzdaq_api.devices import ReadDevice
from thzdaq_api.events import ApprovalRequested
from thzdaq_api.origins import ASSISTANT, ASSISTANT_CLIENT
from thzdaq_api.tools import Reach, tools
from thzdaq_gui.assistant.conversation import STOPPED, Conversation, Outcome
from thzdaq_gui.assistant.keys import SERVICE, Keys
from thzdaq_gui.assistant.prompt import system_prompt
from thzdaq_gui.assistant.provider import Client, Provider, ProviderError

BIAS = {"ref": "sis_bias_1", "key": "voltage_set", "value": "1 mV"}


class Heard:
    """What a turn told, in order."""

    def __init__(self):
        self.told = []

    def text(self, piece):
        self.told.append(("text", piece))

    def called(self, call):
        self.told.append(("called", call.name))

    def progress(self, call, done, total):
        self.told.append(("progress", done, total))

    def answered(self, call, text, failed):
        self.told.append(("answered", text, failed))

    def words(self) -> str:
        return "".join(t[1] for t in self.told if t[0] == "text")

    def answers(self):
        return [(t[1], t[2]) for t in self.told if t[0] == "answered"]


@pytest.fixture
def reach(connect):
    reach = Reach(connect(True, ASSISTANT, ASSISTANT_CLIENT))
    yield reach
    reach.close()


@pytest.fixture
def window(connect):
    """A person in the window: hears what waits and answers it."""
    window = Window(connect(True))
    yield window
    window.stop()


@pytest.fixture
def client(model):
    return Client(Provider("local", model.url, "qwen"), "secret")


def talk(conversation, client, reach, text="hello", heard=None, prompt=None):
    heard = heard or Heard()
    turn = conversation.begin()
    outcome = conversation.say(
        turn, text, client, tools(lambda: None), reach,
        prompt or (lambda reach: "the system prompt"), heard,
    )  # fmt: skip
    return outcome, heard


def roles(conversation):
    return [m["role"] for m in conversation.messages]


def test_the_model_is_offered_the_catalogs_tools(model, client, reach):
    talk(Conversation(), client, reach)
    (asked,) = model.asked
    offered = {t["function"]["name"]: t["function"] for t in asked["tools"]}
    assert set(offered) == {t.name for t in tools(lambda: None)}
    read = offered["read_device"]
    assert read["parameters"] == catalog.tool_schema(ReadDevice)
    assert read["description"] == catalog.description(ReadDevice)
    assert asked["model"] == "qwen" and asked["stream"] is True
    assert asked["messages"][0] == {"role": "system", "content": "the system prompt"}
    assert model.keys == ["Bearer secret"]


def test_tool_calls_go_to_the_bench_and_their_answers_to_the_model(
    model, client, reach
):
    model.replies = [
        calls(("list_devices", {}), ("read_device", {"ref": "sis_bias_1"})),
        says("sis_bias_1 is at 0 V."),
    ]
    conversation = Conversation()
    outcome, heard = talk(conversation, client, reach, "what is the bias?")
    assert outcome == (Outcome.ANSWERED, "")
    assert heard.words() == "sis_bias_1 is at 0 V."
    assert roles(conversation) == ["user", "assistant", "tool", "tool", "assistant"]
    devices, read = conversation.messages[2:4]
    assert "sis_bias_1: " in devices["content"] and devices["tool_call_id"]
    assert read["content"].startswith("sis_bias_1: ")
    # The model is asked again with what the tools answered
    assert model.asked[1]["messages"][-2:] == conversation.messages[2:4]
    assert [t[0] for t in heard.told[:4]] == ["called", "answered"] * 2


def test_what_it_changes_waits_for_the_person_whose_no_it_reads(
    model, client, reach, window
):
    model.replies = [calls(("set_quantity", BIAS)), says("I will not.")]
    done = {}
    turn = threading.Thread(
        target=lambda: done.update(result=talk(Conversation(), client, reach))
    )
    turn.start()
    approval = window.asked()
    assert approval.origin == ASSISTANT
    window.answer(allowed=False, text="pump it first")
    turn.join(5)
    (_, heard) = done["result"]
    ((told, failed),) = heard.answers()
    assert failed and told.startswith("denied: ") and "pump it first" in told
    assert "pump it first" in model.asked[1]["messages"][-1]["content"]


def test_a_wrong_call_is_told_to_the_model_which_goes_on(model, client, reach):
    model.replies = [
        calls(
            ("make_coffee", {}),
            ("read_device", "{not json"),
            ("read_device", {"ref": "nothing_1"}),
            ("read_device", {"reference": "sis_bias_1"}),
        ),
        says("Sorry."),
    ]
    conversation = Conversation()
    outcome, heard = talk(conversation, client, reach)
    assert outcome[0] == Outcome.ANSWERED
    told = [text for text, failed in heard.answers() if failed]
    assert len(told) == 4
    assert told[0].startswith("unknown_operation: No tool 'make_coffee'")
    assert "not JSON" in told[1]
    assert told[2].startswith("not_found: ") and "nothing_1" in told[2]
    assert told[3].startswith("invalid_arguments")


def test_a_turn_ends_after_its_steps(model, client, reach):
    model.replies = [calls(("list_devices", {}))] * 5
    conversation = Conversation(max_steps=3)
    outcome, _ = talk(conversation, client, reach)
    assert outcome == (Outcome.STEPS, "")
    assert len(model.asked) == 3
    assert roles(conversation)[-1] == "tool"  # whole: every call answered


def test_stop_ends_the_turn_at_once_and_leaves_whole_messages(
    model, client, reach, window
):
    model.replies = [calls(("set_quantity", BIAS))]
    conversation = Conversation()
    heard = Heard()
    done = {}
    turn = threading.Thread(
        target=lambda: done.update(
            result=talk(conversation, client, reach, heard=heard)
        )
    )
    turn.start()
    window.asked()  # the call waits for the person
    conversation.stop()
    assert roles(conversation) == ["user", "assistant", "tool"]
    assert conversation.messages[-1]["content"] == STOPPED
    # Another turn runs while the stopped one still waits in its thread
    model.replies = [says("Stopped, as you asked.")]
    assert talk(conversation, client, reach)[0][0] == Outcome.ANSWERED
    window.answer(allowed=True)
    turn.join(5)
    assert done["result"][0] == (Outcome.STOPPED, "")
    # The stopped turn added and told nothing once stopped
    assert roles(conversation) == ["user", "assistant", "tool", "user", "assistant"]
    assert heard.answers() == []


def test_stop_cuts_a_reply_while_it_streams(model, client, reach):
    model.replies = [says("a long answer " * 50)]
    conversation = Conversation()
    heard = Heard()

    class Stopping(Heard):
        def text(self, piece):
            heard.text(piece)
            conversation.stop()

    outcome, _ = talk(conversation, client, reach, heard=Stopping())
    assert outcome == (Outcome.STOPPED, "")
    assert len(heard.told) == 1 and roles(conversation) == ["user"]


def test_a_server_that_fails_ends_the_turn_with_its_words(model, client, reach):
    model.status = 500
    outcome, _ = talk(Conversation(), client, reach)
    assert outcome == (Outcome.FAILED, "the server refused (500): nope")
    model.status = 401
    assert "the key was refused (401)" in talk(Conversation(), client, reach)[0][1]
    gone = Client(Provider("gone", "http://127.0.0.1:9/v1", "qwen"), None)
    outcome = talk(Conversation(), gone, reach)[0]
    assert outcome[0] == Outcome.FAILED and "does not answer" in outcome[1]


def test_a_reply_that_comes_whole_is_read_too(model, client, reach):
    model.stream = False
    model.replies = [calls(("list_devices", {})), says("Two biases.")]
    conversation = Conversation()
    outcome, heard = talk(conversation, client, reach)
    assert outcome[0] == Outcome.ANSWERED and heard.words() == "Two biases."


def test_the_prompt_is_made_once_and_again_when_the_bench_changed(model, client, reach):
    made = []

    def prompt(reach):
        made.append(time.monotonic())
        return f"prompt {len(made)}"

    conversation = Conversation()
    talk(conversation, client, reach, prompt=prompt)
    talk(conversation, client, reach, prompt=prompt)
    conversation.forget_bench()
    talk(conversation, client, reach, prompt=prompt)
    assert len(made) == 2
    assert model.asked[2]["messages"][0]["content"] == "prompt 2"


def test_the_prompt_tells_the_rules_the_bench_and_its_procedures(reach):
    prompt = system_prompt(reach)
    assert prompt.startswith("# ThzDAQ: the assistant in the window")
    assert guides.section(guides.AGENTS, guides.RULES) in prompt
    assert guides.section(guides.AGENTS, guides.OWN_MEASUREMENT) in prompt
    assert "simulated" in prompt and "sis_bias_1: " in prompt
    assert "\nsis.current_vs_voltage: SIS I-V curve. " in prompt
    assert "Slots: bias." in prompt
    assert "Connections:" in prompt


def test_test_says_whether_the_server_takes_tools(model, client):
    model.replies = [calls(("ping", {}))]
    assert client.test() == "qwen answers and calls tools"
    assert model.asked[-1]["stream"] is False
    model.replies = [says("pong")]
    assert "did not call the test tool" in client.test()
    model.takes_tools = False
    with pytest.raises(ProviderError) as refused:
        client.test()
    assert str(refused.value) == f"the server refused (400): {NO_TOOLS}"


def test_keys_live_in_the_keyring(keys):
    kept = Keys()
    kept.set("local", "secret")
    assert keys.kept[(SERVICE, "local")] == "secret"
    assert Keys().get("local") == "secret" and kept.kept()
    kept.set("local", "")
    assert Keys().get("local") is None
    kept.forget("local")  # none kept: nothing to say


def test_without_a_keyring_a_key_lives_while_the_program_runs():
    import keyring
    from keyring.backends.fail import Keyring as Fail

    before = keyring.get_keyring()
    keyring.set_keyring(Fail())
    try:
        kept = Keys()
        kept.set("local", "secret")
        assert kept.get("local") == "secret" and not kept.kept()
        assert "No recommended backend" in kept.problem
    finally:
        keyring.set_keyring(before)


def test_wait_measurement_tells_its_progress(model, client, reach, window):
    model.replies = [
        calls(
            (
                "start_measurement",
                {
                    "procedure": "sis.current_vs_voltage",
                    "devices": {"bias": "sis_bias_1"},
                    "typed": {"voltage": "0:1:5", "settle_time": "0.05",
                              "first_point_delay": "0"},
                },
            )
        ),
        calls(("wait_measurement", {"id": 1, "timeout": 30})),
        says("Done."),
    ]  # fmt: skip
    done = {}
    turn = threading.Thread(
        target=lambda: done.update(result=talk(Conversation(), client, reach))
    )
    turn.start()
    window.answer(allowed=True)
    turn.join(30)
    outcome, heard = done["result"]
    assert outcome[0] == Outcome.ANSWERED
    started, waited = heard.answers()
    assert started[0].startswith("#1 SIS I-V curve") and not started[1]
    assert "completed" in waited[0] and "table iv" in waited[0]
    assert any(t[0] == "progress" for t in heard.told)
    assert ApprovalRequested in {type(e.body) for e in window.heard}
