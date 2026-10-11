import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

SAMPLES = Path(__file__).resolve().parent.parent / "docs" / "api" / "samples"


def load_sample(name: str):
    return json.loads((SAMPLES / f"{name}.json").read_text())


@pytest.fixture
def event():
    """A real event with embedded production (Primetime) and venue (Studio Kino)."""
    return copy.deepcopy(load_sample("event-with-embeds"))


@pytest.fixture
def venue_data():
    return copy.deepcopy(load_sample("venues-list-response")["_embedded"]["venues"][0])


def make_event(base: dict, event_id: str, start: str, **changes) -> dict:
    """Copy of `base` with a new id/startDate and optional top-level overrides."""
    ev = copy.deepcopy(base)
    ev["id"] = event_id
    ev["startDate"] = start
    ev.update(changes)
    return ev


@dataclass
class Recorded:
    method: str
    path: str
    query: dict[str, str]
    headers: dict[str, str]
    json: Any = None
    form: dict[str, str] | None = None


@dataclass
class FakeApi:
    """A real local HTTP server with canned responses, standing in for api.cineville.de and cineville.de.

    Responses for the same (method, path) are served in the order they were added; the last one repeats.
    A response can be a callable taking the Recorded request and returning (status, payload).
    """

    url: str = ""
    responses: dict[tuple[str, str], list] = field(default_factory=dict)
    requests: list[Recorded] = field(default_factory=list)

    def add(self, method: str, path: str, payload: Any = None, *, status: int = 200,
            body: str | None = None, handler: Callable[[Recorded], tuple[int, Any]] | None = None) -> None:
        self.responses.setdefault((method, path), []).append((status, payload, body, handler))

    def sent(self, method: str, path: str) -> list[Recorded]:
        return [r for r in self.requests if r.method == method and r.path == path]

    async def dispatch(self, request: web.Request) -> web.StreamResponse:
        rec = Recorded(request.method, request.path, dict(request.query), dict(request.headers))
        if request.content_type == "application/json":
            rec.json = await request.json()
        elif request.content_type == "application/x-www-form-urlencoded":
            rec.form = dict(await request.post())
        self.requests.append(rec)
        queue = self.responses.get((request.method, request.path))
        if not queue:
            return web.json_response({"error": "no canned response"}, status=404)
        status, payload, body, handler = queue.pop(0) if len(queue) > 1 else queue[0]
        if handler:
            status, payload = handler(rec)
        if body is not None:
            return web.Response(status=status, text=body, content_type="text/html")
        return web.json_response(payload, status=status)


@pytest.fixture
async def fake_api(socket_enabled):
    """socket_enabled: the HA test harness blocks sockets; the fake server only listens on 127.0.0.1."""
    api = FakeApi()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", api.dispatch)
    server = TestServer(app)
    await server.start_server()
    api.url = str(server.make_url("")).rstrip("/")
    yield api
    await server.close()


@pytest.fixture
async def session(socket_enabled):
    async with aiohttp.ClientSession() as s:
        yield s


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load custom_components/cineville in every test."""
    yield
