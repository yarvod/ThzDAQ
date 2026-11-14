"""A model's server as the assistant speaks to it: an OpenAI-compatible
chat/completions (vLLM, Ollama, LM Studio, OpenAI and the like), with tools.

A reply streams (server-sent events): its text as it comes, the tool calls
it makes once they are whole. A server that answers whole (plain JSON) is
read so too. test() checks that the server answers and takes tools: vLLM
refuses them without --enable-auto-tool-choice and a tool call parser.
"""

import ipaddress
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence
from urllib.parse import urlsplit

import requests

CONNECT_S = 10.0
READ_S = 180.0  # a local model may think long before its first word
TEST_TOOL = "ping"
JSON_TYPE = "application/json"
DONE = "[DONE]"

Message = Dict[str, Any]  # a message of the chat as the server takes it


@dataclass(frozen=True)
class Provider:
    """Where the model is and which one: the URL up to /v1 (its
    chat/completions is asked), the model's name as the server knows it, and
    its temperature (None: the server's own). The key is kept apart (keys.py)."""

    name: str
    url: str
    model: str
    temperature: Optional[float] = None

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


@dataclass
class Reply:
    """What the model said in one step: text, tool calls, or both."""

    text: str = ""
    calls: List[ToolCall] = field(default_factory=list)

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
    ) -> Reply:
        """The model's next step; heard(text) gets its text as it comes (what
        it raises stops the reply)."""
        body: Dict[str, Any] = {
            "model": self.provider.model,
            "messages": list(messages),
            "stream": stream,
        }
        if tools:
            body["tools"] = list(tools)
            body["tool_choice"] = "auto"
        if self.provider.temperature is not None:
            body["temperature"] = self.provider.temperature
        response = self._ask(body, stream)
        with response:
            if response.headers.get("content-type", "").startswith(JSON_TYPE):
                reply = whole(_json(response))
                if reply.text:
                    heard(reply.text)
                return reply
            return streamed(_events(response), heard)

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

    def _ask(self, body: Dict[str, Any], stream: bool) -> requests.Response:
        headers = {"Content-Type": JSON_TYPE}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        try:
            with requests.Session() as session:
                # A server elsewhere through the proxy the person set, if any
                session.trust_env = not self.provider.on_this_machine()
                response = session.post(
                    self.provider.endpoint(),
                    json=body,
                    headers=headers,
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
    return Reply(
        message.get("content") or "",
        [
            ToolCall(
                call.get("id") or f"call_{index}",
                call["function"]["name"],
                call["function"].get("arguments") or "{}",
            )
            for index, call in enumerate(message.get("tool_calls") or ())
        ],
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


def streamed(chunks: Iterator[Mapping[str, Any]], heard: Callable[[str], None]):
    """A reply put together from its chunks: text as it comes, each tool call
    from the pieces of its index."""
    text: List[str] = []
    calls: Dict[int, Dict[str, str]] = {}
    for chunk in chunks:
        if "error" in chunk:
            raise ProviderError(f"the server stopped: {chunk['error']}")
        for choice in chunk.get("choices") or ():
            delta = choice.get("delta") or {}
            if delta.get("content"):
                text.append(delta["content"])
                heard(delta["content"])
            for piece in delta.get("tool_calls") or ():
                call = calls.setdefault(
                    piece.get("index", len(calls)),
                    {"id": "", "name": "", "arguments": ""},
                )
                call["id"] = piece.get("id") or call["id"]
                function = piece.get("function") or {}
                call["name"] += function.get("name") or ""
                call["arguments"] += function.get("arguments") or ""
    return Reply(
        "".join(text),
        [
            ToolCall(
                call["id"] or f"call_{index}", call["name"], call["arguments"] or "{}"
            )
            for index, call in sorted(calls.items())
        ],
    )
