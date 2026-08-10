from __future__ import annotations

import httpx
import pytest

from meligpt.auth.secrets import Credentials
from meligpt.clients.meligpt_http import MeliGPTClient
from meligpt.exceptions import (
    UpstreamError,
    UpstreamForbiddenError,
    UpstreamHTTPError,
    UpstreamTimeoutError,
)

CREDS = Credentials(access_token="tok", cookie_header="c=1")


def _sse_body(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


async def _collect(client: MeliGPTClient, credentials=CREDS):
    events = []
    async for event in client.stream_chat(prompt="oi", message_id="m1", credentials=credentials):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_stream_full_response(settings, monkeypatch) -> None:
    body = _sse_body(
        'data: {"event": "on_message_delta", "data": {"delta": {"content": [{"type": "text", "text": "oi"}]}}}',
        "data: [DONE]",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    events = await _collect(client)
    assert events[0]["data"]["delta"]["content"][0]["text"] == "oi"


@pytest.mark.asyncio
async def test_stream_partial_then_done(settings, monkeypatch) -> None:
    body = _sse_body(
        'data: {"event": "on_message_delta", "data": {"delta": {"content": [{"type": "text", "text": "a"}]}}}',
        "",
        'data: {"event": "on_message_delta", "data": {"delta": {"content": [{"type": "text", "text": "b"}]}}}',
        "data: [DONE]",
        'data: {"event": "on_message_delta", "data": {"delta": {"content": [{"type": "text", "text": "nunca deveria aparecer"}]}}}',
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    events = await _collect(client)
    texts = [e["data"]["delta"]["content"][0]["text"] for e in events]
    assert texts == ["a", "b"]


@pytest.mark.asyncio
async def test_stream_401_raises_upstream_http_error(settings, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"content-type": "application/json"}, content=b"{}")

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamHTTPError) as exc_info:
        await _collect(client)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_stream_403_raises_forbidden(settings, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"content-type": "application/json"}, content=b"{}")

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamForbiddenError):
        await _collect(client)


@pytest.mark.asyncio
async def test_stream_unexpected_content_type_raises(settings, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html></html>")

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamError):
        await _collect(client)


@pytest.mark.asyncio
async def test_stream_timeout_raises_upstream_timeout(settings, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout simulado")

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamTimeoutError):
        await _collect(client)


@pytest.mark.asyncio
async def test_credentials_never_appear_in_error_message(settings, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, headers={"content-type": "text/plain"}, content=b"boom")

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    secret_creds = Credentials(access_token="SUPER_SECRETO", cookie_header="COOKIE_SECRETO")
    with pytest.raises(UpstreamHTTPError) as exc_info:
        await _collect(client, credentials=secret_creds)

    assert "SUPER_SECRETO" not in str(exc_info.value)
    assert "COOKIE_SECRETO" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_model_info_overrides_route_model_and_payload_endpoint(settings) -> None:
    import json as json_module

    from meligpt.catalog import FALLBACK_MODELS

    claude = next(m for m in FALLBACK_MODELS if m.id == "claude-5-sonnet")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json_module.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n",
        )

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    async for _ in client.stream_chat(
        prompt="oi", message_id="m1", credentials=CREDS, model_info=claude
    ):
        pass

    assert captured["path"] == "/api/ask/generic"
    assert captured["payload"]["model"] == "claude-5-sonnet"
    assert captured["payload"]["endpoint"] == "bedrock"


@pytest.mark.asyncio
async def test_without_model_info_uses_default_settings(settings) -> None:
    import json as json_module

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json_module.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n",
        )

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    async for _ in client.stream_chat(prompt="oi", message_id="m1", credentials=CREDS):
        pass

    assert captured["path"] == "/api/ask/openAI"
    assert captured["payload"]["model"] == settings.model
    assert captured["payload"]["endpoint"] == "openAI"
