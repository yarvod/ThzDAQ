"""A model's server for the tests: OpenAI-compatible chat/completions on
localhost that answers what a test scripted, streamed as servers stream
(server-sent events) or whole. It keeps what it was asked."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional

# What vLLM answers to tools when started without --enable-auto-tool-choice
NO_TOOLS = (
    '"auto" tool choice requires --enable-auto-tool-choice and '
    "--tool-call-parser to be set"
)


def says(text: str) -> Dict[str, Any]:
    """A reply in words."""
    return {"content": text}


def calls(*called: tuple) -> Dict[str, Any]:
    """A reply that calls tools: (name, arguments as a dict or as text)."""
    return {
        "tool_calls": [
            {
                "id": f"call_{name}_{index}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": given if isinstance(given, str) else json.dumps(given),
                },
            }
            for index, (name, given) in enumerate(called)
        ]
    }


class ModelServer:
    def __init__(self, replies: Optional[List[Dict[str, Any]]] = None):
        self.replies = list(replies or [])
        self.asked: List[Dict[str, Any]] = []  # the bodies of the requests
        self.keys: List[Optional[str]] = []  # the Authorization of each
        self.takes_tools = True
        self.status = 200  # another: refuse every request with it
        self.stream = True  # a streamed request is answered streamed
        self.held = threading.Event()  # cleared: the answer waits for it
        self.held.set()
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                server.asked.append(body)
                server.keys.append(self.headers.get("Authorization"))
                server.held.wait(10)
                if server.status != 200:
                    self._json(server.status, {"error": {"message": "nope"}})
                elif body.get("tools") and not server.takes_tools:
                    self._json(400, {"object": "error", "message": NO_TOOLS})
                elif body.get("stream") and server.stream:
                    self._stream(server.next())
                else:
                    self._json(200, {"choices": [{"message": server.next()}]})

            def _json(self, status: int, found: Dict[str, Any]) -> None:
                data = json.dumps(found).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _stream(self, reply: Dict[str, Any]) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                try:
                    for delta in pieces(reply):
                        chunk = {"choices": [{"index": 0, "delta": delta}]}
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                        self.wfile.flush()
                    self.wfile.write(b"data: [DONE]\n\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the client stopped listening: a stopped turn

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def next(self) -> Dict[str, Any]:
        return self.replies.pop(0) if self.replies else says("done")

    def close(self) -> None:
        self.held.set()
        self.httpd.shutdown()
        self.httpd.server_close()


def pieces(reply: Dict[str, Any]):
    """A reply in the pieces a server streams it in: its text a few letters
    at a time, a tool call's name first and its arguments in two halves."""
    text = reply.get("content") or ""
    for start in range(0, len(text), 5):
        yield {"content": text[start : start + 5]}
    for index, call in enumerate(reply.get("tool_calls") or ()):
        function = call["function"]
        half = len(function["arguments"]) // 2
        yield {"tool_calls": [{"index": index, "id": call["id"], "type": "function",
                               "function": {"name": function["name"], "arguments": ""}}]}  # fmt: skip
        for part in (function["arguments"][:half], function["arguments"][half:]):
            yield {"tool_calls": [{"index": index, "function": {"arguments": part}}]}
