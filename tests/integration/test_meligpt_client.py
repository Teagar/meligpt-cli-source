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
async def test_stream_empty_content_type_includes_body_preview(settings, monkeypatch) -> None:
    """Regressão de um caso real (modelos de imagem dedicados como
    `nano-banana`): 200 OK sem Content-Type, corpo às vezes vazio. A
    mensagem de erro precisa trazer o corpo pra dar alguma pista, não só
    'Content-Type vazio'.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={}, content=b'{"error":"endpoint nao suportado"}')

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamError) as exc_info:
        await _collect(client)
    assert "endpoint nao suportado" in str(exc_info.value)


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


# --- fork_conversation ------------------------------------------------
#
# Payload/semântica confirmados por HAR real (`forks.har`, 2026-08-13) —
# ver `meligpt.clients.meligpt_http.ForkOption`.


@pytest.mark.asyncio
async def test_fork_conversation_sends_expected_payload(settings, monkeypatch) -> None:
    import json as json_module

    from meligpt.clients.meligpt_http import ForkOption

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["payload"] = json_module.loads(request.content)
        captured["accept"] = request.headers.get("accept")
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "conversation": {"conversationId": "new-conv-id", "title": "bifurcada"},
                "messages": [{"messageId": "m1"}, {"messageId": "m2"}],
            },
        )

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    result = await client.fork_conversation(
        conversation_id="conv-1",
        message_id="msg-1",
        credentials=CREDS,
        option=ForkOption.INCLUDE_RELATED_BRANCHES,
    )

    assert captured["path"] == "/api/convos/fork"
    assert captured["accept"] == "application/json"
    assert captured["payload"] == {
        "messageId": "msg-1",
        "conversationId": "conv-1",
        "option": "includeBranches",
        "splitAtTarget": False,
        "latestMessageId": "msg-1",
    }
    assert result["conversation"]["conversationId"] == "new-conv-id"


@pytest.mark.asyncio
async def test_fork_conversation_default_option_is_empty_string(settings, monkeypatch) -> None:
    """'Incluir todos para/de aqui' é o padrão do MeliGPT/LibreChat e é
    mandado como string vazia no payload — confirmado por HAR real."""

    import json as json_module

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json_module.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"conversation": {"conversationId": "c"}, "messages": []},
        )

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    await client.fork_conversation(conversation_id="conv-1", message_id="msg-1", credentials=CREDS)

    assert captured["payload"]["option"] == ""


@pytest.mark.asyncio
async def test_fork_conversation_visible_only_option(settings, monkeypatch) -> None:
    import json as json_module

    from meligpt.clients.meligpt_http import ForkOption

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json_module.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"conversation": {"conversationId": "c"}, "messages": []},
        )

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    await client.fork_conversation(
        conversation_id="conv-1",
        message_id="msg-1",
        credentials=CREDS,
        option=ForkOption.VISIBLE_ONLY,
    )

    assert captured["payload"]["option"] == "directPath"


@pytest.mark.asyncio
async def test_fork_conversation_401_raises_upstream_http_error(settings, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"content-type": "application/json"}, content=b"{}")

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamHTTPError) as exc_info:
        await client.fork_conversation(
            conversation_id="conv-1", message_id="msg-1", credentials=CREDS
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_fork_conversation_403_raises_forbidden(settings, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"content-type": "application/json"}, content=b"{}")

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamForbiddenError):
        await client.fork_conversation(
            conversation_id="conv-1", message_id="msg-1", credentials=CREDS
        )


@pytest.mark.asyncio
async def test_fork_conversation_timeout_raises_upstream_timeout(settings, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout simulado")

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamTimeoutError):
        await client.fork_conversation(
            conversation_id="conv-1", message_id="msg-1", credentials=CREDS
        )
