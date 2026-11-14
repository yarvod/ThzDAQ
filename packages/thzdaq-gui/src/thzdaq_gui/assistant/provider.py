"""A model's server as the assistant speaks to it: an OpenAI-compatible
chat/completions (vLLM, Ollama, LM Studio, OpenAI and the like), with tools.

A reply streams (server-sent events): its text as it comes, the tool calls
it makes once they are whole. A server that answers whole (plain JSON) is
read so too. What a reasoning model thinks before it answers comes apart from
its text: in reasoning_content or reasoning (vLLM, DeepSeek, Ollama, LM
Studio), or within <think>…</think> at the start of its text (Qwen and the
like on a server without a reasoning parser). How many tokens a step took
comes last (stream_options.include_usage). test() checks that the server
answers and takes tools: vLLM refuses them without
--enable-auto-tool-choice and a tool call parser; context() asks the
server how long a conversation its model takes, when it tells it.
"""

import ipaddress
import json
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)
from urllib.parse import urlsplit

import requests

CONNECT_S = 10.0
READ_S = 180.0  # a local model may think long before its first word
TEST_TOOL = "ping"
JSON_TYPE = "application/json"
DONE = "[DONE]"
THINK, THOUGHT = "<think>", "</think>"
REASONING = ("reasoning_content", "reasoning")  # where servers put thoughts
# How servers tell their model's context in GET /models: vLLM, OpenRouter and
# others, LM Studio
CONTEXT_KEYS = ("max_model_len", "context_length", "max_context_length")

Message = Dict[str, Any]  # a message of the chat as the server takes it


@dataclass(frozen=True)
class Provider:
    """Where the model is and which one: the URL up to /v1 (its
    chat/completions is asked), the model's name as the server knows it, and
    its temperature (None: the server's own) and the context it takes in
    tokens (None: not known). The key is kept apart (keys.py)."""

    name: str
    url: str
    model: str
    temperature: Optional[float] = None
    context: Optional[int] = None  # tokens the model takes; None: not known

    def endpoint(self) -> str:
        return self.url.rstrip("/") + "/chat/completions"

    def on_this_machine(self) -> bool:
        """Whether the server runs on this computer (a loopback address or
        localhost): it is asked directly, never through the person's proxy,
        which is for servers elsewhere and has no way to this one's loopback."""
        host = urlsplit(self.url).hostname or ""
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return host == "localhost" or host.endswith(".localhost")


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON as the model wrote it

    def message(self) -> Message:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass(frozen=True)
class Usage:
    """Tokens of one step: what the model read (the whole conversation so
    far) and what it wrote, its thoughts among them."""

    prompt: int = 0
    completion: int = 0
    reasoning: int = 0

    @staticmethod
    def of(found: Any) -> Optional["Usage"]:
        """As a server tells it; None when it does not."""
        if not isinstance(found, Mapping):
            return None
        details = found.get("completion_tokens_details") or {}
        return Usage(
            int(found.get("prompt_tokens") or 0),
            int(found.get("completion_tokens") or 0),
            int(details.get("reasoning_tokens") or 0),
        )


@dataclass
class Reply:
    """What the model said in one step: text, tool calls, or both; what it
    thought first, and the tokens it took when the server tells them."""

    text: str = ""
    calls: List[ToolCall] = field(default_factory=list)
    reasoning: str = ""
    usage: Optional[Usage] = None

    def message(self) -> Message:
        """As the conversation keeps it for the next step."""
        found: Message = {"role": "assistant", "content": self.text or None}
        if self.calls:
            found["tool_calls"] = [call.message() for call in self.calls]
        return found


class ProviderError(Exception):
    """The server did not answer, or refused: what it said."""


def tool(name: str, description: str, schema: Mapping[str, Any]) -> Dict[str, Any]:
    """A tool as chat/completions takes it."""
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": schema},
    }


class Client:
    """Asks one provider's server."""

    def __init__(self, provider: Provider, key: Optional[str]):
        self.provider = provider
        self.key = key

    def complete(
        self,
        messages: Sequence[Message],
        tools: Sequence[Dict[str, Any]],
        heard: Callable[[str], None],
        stream: bool = True,
        thought: Callable[[str], None] = lambda piece: None,
    ) -> Reply:
        """The model's next step; heard(text) gets its text as it comes,
        thought(text) what it thinks (what either raises stops the reply)."""
        body: Dict[str, Any] = {
            "model": self.provider.model,
            "messages": list(messages),
            "stream": stream,
        }
        if stream:
            body["stream_options"] = {"include_usage": True}
        if tools:
            body["tools"] = list(tools)
            body["tool_choice"] = "auto"
        if self.provider.temperature is not None:
            body["temperature"] = self.provider.temperature
        response = self._ask(body, stream)
        with response:
            if response.headers.get("content-type", "").startswith(JSON_TYPE):
                reply = whole(_json(response))
                if reply.reasoning:
                    thought(reply.reasoning)
                if reply.text:
                    heard(reply.text)
                return reply
            return streamed(_events(response), heard, thought)

    def context(self) -> Optional[int]:
        """The tokens its model takes, as the server's GET /models tells
        them; None when it does not (Ollama, OpenAI) or does not answer."""
        try:
            with self._session() as session:
                response = session.get(
                    self.provider.url.rstrip("/") + "/models",
                    headers=self._headers(),
                    timeout=(CONNECT_S, CONNECT_S),
                )
            found = response.json() if response.status_code == 200 else {}
        except (requests.RequestException, ValueError):
            return None
        listed = found.get("data") if isinstance(found, dict) else None
        for model in listed if isinstance(listed, list) else ():
            if isinstance(model, dict) and model.get("id") == self.provider.model:
                for key in CONTEXT_KEYS:
                    if isinstance(model.get(key), int):
                        return model[key]
        return None

    def test(self) -> str:
        """Whether the server answers and takes tools, in a line; ProviderError
        says what is wrong."""
        ping = tool(TEST_TOOL, "Answers pong: call it when asked to.", {
            "type": "object", "properties": {},
        })  # fmt: skip
        reply = self.complete(
            [{"role": "user", "content": f"Call the tool {TEST_TOOL}."}],
            [ping],
            lambda text: None,
            stream=False,
        )
        if any(call.name == TEST_TOOL for call in reply.calls):
            return f"{self.provider.model} answers and calls tools"
        return (
            f"{self.provider.model} answers and the server takes tools, but the "
            "model did not call the test tool: it may use tools poorly"
        )

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": JSON_TYPE}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        return headers

    def _session(self) -> requests.Session:
        session = requests.Session()
        # A server elsewhere through the proxy the person set, if any
        session.trust_env = not self.provider.on_this_machine()
        return session

    def _ask(self, body: Dict[str, Any], stream: bool) -> requests.Response:
        try:
            with self._session() as session:
                response = session.post(
                    self.provider.endpoint(),
                    json=body,
                    headers=self._headers(),
                    stream=stream,
                    timeout=(CONNECT_S, READ_S),
                )
        except requests.RequestException as e:
            raise ProviderError(f"{self.provider.url} does not answer: {e}") from None
        if response.status_code != 200:
            with response:
                raise ProviderError(refusal(response))
        return response


def refusal(response: requests.Response) -> str:
    """What a server that refused says, in a line."""
    try:
        found = response.json()
    except ValueError:
        found = None
    error = found.get("error", found) if isinstance(found, dict) else None
    message = error.get("message") if isinstance(error, dict) else error
    told = str(message or response.text or response.reason).strip()
    if response.status_code in (401, 403):
        return f"the key was refused ({response.status_code}): {told}"
    return f"the server refused ({response.status_code}): {told}"


def _json(response: requests.Response) -> Dict[str, Any]:
    try:
        return response.json()
    except ValueError:
        raise ProviderError("the server answered something that is not JSON") from None


def whole(found: Mapping[str, Any]) -> Reply:
    """A reply that came at once."""
    try:
        message = found["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError(f"the server answered no message: {found}") from None
    split = Thinking()
    text, thought = split.split(message.get("content") or "")
    rest, more = split.end()
    reasoning = "".join(message.get(key) or "" for key in REASONING)
    return Reply(
        text + rest,
        [
            ToolCall(
                call.get("id") or f"call_{index}",
                call["function"]["name"],
                call["function"].get("arguments") or "{}",
            )
            for index, call in enumerate(message.get("tool_calls") or ())
        ],
        reasoning + thought + more,
        Usage.of(found.get("usage")),
    )


def _events(response: requests.Response) -> Iterator[Dict[str, Any]]:
    """The chunks of a streamed reply (data: lines), up to [DONE]."""
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        data = line[len("data:") :].strip()
        if data == DONE:
            return
        try:
            yield json.loads(data)
        except ValueError:
            raise ProviderError(f"the server streamed what is not JSON: {data}")


class Thinking:
    """Splits a model's text into its thoughts and its answer: what stands
    within <think>…</think> at its start is thought. The text comes in pieces,
    a tag maybe cut between two: the end of a piece that may start a tag
    waits for the next one."""

    def __init__(self):
        self._inside = False
        self._started = False  # the text began: a <think> later is words
        self._held = ""

    def split(self, piece: str) -> Tuple[str, str]:
        """(the answer's part, the thought's part) of piece."""
        held, self._held = self._held + piece, ""
        answer, thought = "", ""
        while held:
            if self._inside:
                at = held.find(THOUGHT)
                if at < 0:
                    keep = _tail(held, THOUGHT)
                    thought += held[: len(held) - keep]
                    self._held = held[len(held) - keep :]
                    break
                thought += held[:at]
                held = held[at + len(THOUGHT) :].lstrip("\n")
                self._inside, self._started = False, True
                continue
            if not self._started:
                stripped = held.lstrip()
                if stripped.startswith(THINK):
                    held, self._inside = stripped[len(THINK) :], True
                    continue
                if THINK.startswith(stripped):  # perhaps a tag, cut
                    self._held = held
                    break
                self._started = True
            answer += held
            break
        return answer, thought

    def end(self) -> Tuple[str, str]:
        """What was held when the text ends: within a tag never closed it is
        thought, else words."""
        held, self._held = self._held, ""
        return ("", held) if self._inside else (held, "")


def _tail(text: str, tag: str) -> int:
    """How many letters at the end of text may start tag."""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if tag.startswith(text[-size:]):
            return size
    return 0


def streamed(
    chunks: Iterator[Mapping[str, Any]],
    heard: Callable[[str], None],
    thought: Callable[[str], None] = lambda piece: None,
) -> Reply:
    """A reply put together from its chunks: text and thoughts as they come,
    each tool call from the pieces of its index, the tokens from the last."""
    text: List[str] = []
    reasoning: List[str] = []
    calls: Dict[int, Dict[str, str]] = {}
    usage: Optional[Usage] = None
    split = Thinking()

    def words(answered: str, thinking: str) -> None:
        if thinking:
            reasoning.append(thinking)
            thought(thinking)
        if answered:
            text.append(answered)
            heard(answered)

    for chunk in chunks:
        if "error" in chunk:
            raise ProviderError(f"the server stopped: {chunk['error']}")
        usage = Usage.of(chunk.get("usage")) or usage
        for choice in chunk.get("choices") or ():
            delta = choice.get("delta") or {}
            for key in REASONING:
                if delta.get(key):
                    reasoning.append(delta[key])
                    thought(delta[key])
            if delta.get("content"):
                words(*split.split(delta["content"]))
            for piece in delta.get("tool_calls") or ():
                call = calls.setdefault(
                    piece.get("index", len(calls)),
                    {"id": "", "name": "", "arguments": ""},
                )
                call["id"] = piece.get("id") or call["id"]
                function = piece.get("function") or {}
                call["name"] += function.get("name") or ""
                call["arguments"] += function.get("arguments") or ""
    words(*split.end())
    return Reply(
        "".join(text),
        [
            ToolCall(
                call["id"] or f"call_{index}", call["name"], call["arguments"] or "{}"
            )
            for index, call in sorted(calls.items())
        ],
        "".join(reasoning),
        usage,
    )
