"""A real HTTP server on 127.0.0.1 that plays an OpenAI-compatible LLM server in tests.

It runs in the test process on an ephemeral port, records every request, and answers with
whatever the test's responder returns, so the client is exercised over a real socket without
a model and without mocking the HTTP layer.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MODEL = "test-model"


@dataclass(frozen=True, slots=True)
class RecordedRequest:
    method: str
    path: str
    body: Any
    """The parsed JSON body, or ``None`` when the request had none."""


@dataclass(frozen=True, slots=True)
class Reply:
    status: int = 200
    body: object = None
    """Sent as JSON, or as-is when it is ``bytes``."""
    delay_seconds: float = 0.0
    drop_connection: bool = False
    """Close the connection without answering, as a crashing or restarting server would."""


type Responder = Callable[[RecordedRequest], Reply]


def chat_reply(content: str | None, *, finish_reason: str = "stop") -> Reply:
    """A chat completion whose single choice says ``content``."""
    return Reply(
        body={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ],
        }
    )


def _default_responder(request: RecordedRequest) -> Reply:
    if request.method == "GET" and request.path == "/v1/models":
        return Reply(body={"object": "list", "data": [{"id": MODEL, "object": "model"}]})
    return Reply(status=404, body={"error": {"message": "no responder set for this test"}})


class FakeLLMServer:
    def __init__(self) -> None:
        self.requests: list[RecordedRequest] = []
        self.responder: Responder = _default_responder
        self._lock = threading.Lock()
        self._release = threading.Event()
        self._httpd = _QuietServer(("127.0.0.1", 0), self._handler_class())
        # A short poll interval keeps stop() fast; the default makes every test wait half a second.
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._httpd.server_address[1]}/v1"

    @property
    def chat_requests(self) -> list[RecordedRequest]:
        with self._lock:
            return [r for r in self.requests if r.path == "/v1/chat/completions"]

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._release.set()  # wake handlers still sleeping out a delay
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join()

    def sleep(self, seconds: float) -> None:
        """Wait ``seconds``, or less if the server is stopping."""
        self._release.wait(seconds)

    def dispatch(self, request: RecordedRequest) -> Reply:
        """Record ``request`` and return the current responder's reply to it."""
        with self._lock:
            self.requests.append(request)
            responder = self.responder
        return responder(request)

    def _handler_class(self) -> type[BaseHTTPRequestHandler]:
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:
                self._handle()

            def do_POST(self) -> None:
                self._handle()

            def _handle(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                reply = server.dispatch(RecordedRequest(self.command, self.path, body))
                if reply.delay_seconds:
                    server.sleep(reply.delay_seconds)
                if reply.drop_connection:
                    self.close_connection = True
                    return
                payload = (
                    reply.body if isinstance(reply.body, bytes) else json.dumps(reply.body).encode()
                )
                self.send_response(reply.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        return Handler


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        # A client that gave up (a timeout test) makes the late reply fail; that's expected.
        pass


@contextmanager
def running_fake_llm() -> Generator[FakeLLMServer]:
    server = FakeLLMServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()


def unused_local_url() -> str:
    """An address on 127.0.0.1 where nothing is listening, like a server that isn't running."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"
