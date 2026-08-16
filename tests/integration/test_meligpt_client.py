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


# --- upload_image -------------------------------------------------------
#
# Payload/resposta confirmados por HAR real (`import.har`, 2026-08-15):
# multipart/form-data com file/file_id/width/height/endpoint, resposta
# JSON com fileId/filepath/type/width/height reais (o servidor recalcula
# as dimensões — o que mandamos não precisa ser exato).

_PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
    b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_upload_image_sends_expected_multipart_fields(settings, monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["content_type_header"] = request.headers.get("content-type", "")
        captured["accept"] = request.headers.get("accept")
        body = request.content
        captured["body"] = body
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "message": "File uploaded and processed successfully",
                "fileId": "1c613107-adb1-402f-b14e-4bbdc0a70174",
                "file_id": "1c613107-adb1-402f-b14e-4bbdc0a70174",
                "filepath": "/images/u1/1c613107-...__foto.png",
                "type": "image/png",
                "width": 768,
                "height": 768,
            },
        )

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    result = await client.upload_image(
        file_bytes=_PNG_1X1,
        filename="foto.png",
        content_type="image/png",
        credentials=CREDS,
        payload_endpoint="google",
        temp_file_id="temp-abc",
    )

    assert captured["path"] == "/api/files/images"
    assert captured["accept"] == "application/json"
    assert "multipart/form-data" in captured["content_type_header"]
    body_text = captured["body"].decode("latin-1")
    assert 'name="file_id"' in body_text
    assert "temp-abc" in body_text
    assert 'name="endpoint"' in body_text
    assert "google" in body_text
    assert 'filename="foto.png"' in body_text
    assert result["fileId"] == "1c613107-adb1-402f-b14e-4bbdc0a70174"
    assert result["width"] == 768


@pytest.mark.asyncio
async def test_upload_image_generates_temp_file_id_when_omitted(settings, monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"fileId": "f1", "filepath": "/x", "type": "image/png", "width": 1, "height": 1},
        )

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    await client.upload_image(
        file_bytes=_PNG_1X1,
        filename="foto.png",
        content_type="image/png",
        credentials=CREDS,
        payload_endpoint="openAI",
    )

    body_text = captured["body"].decode("latin-1")
    assert 'name="file_id"' in body_text


@pytest.mark.asyncio
async def test_upload_image_detects_dimensions_when_omitted(settings, monkeypatch) -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"fileId": "f1", "filepath": "/x", "type": "image/png", "width": 1, "height": 1},
        )

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    await client.upload_image(
        file_bytes=_PNG_1X1,
        filename="foto.png",
        content_type="image/png",
        credentials=CREDS,
        payload_endpoint="openAI",
    )

    body_text = captured["body"].decode("latin-1")
    assert 'name="width"' in body_text
    assert "\r\n1\r\n" in body_text  # PNG 1x1: largura e altura detectadas = 1


@pytest.mark.asyncio
async def test_upload_image_401_raises_upstream_http_error(settings, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"content-type": "application/json"}, content=b"{}")

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamHTTPError) as exc_info:
        await client.upload_image(
            file_bytes=_PNG_1X1,
            filename="foto.png",
            content_type="image/png",
            credentials=CREDS,
            payload_endpoint="openAI",
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_upload_image_403_raises_forbidden(settings, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"content-type": "application/json"}, content=b"{}")

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamForbiddenError):
        await client.upload_image(
            file_bytes=_PNG_1X1,
            filename="foto.png",
            content_type="image/png",
            credentials=CREDS,
            payload_endpoint="openAI",
        )


@pytest.mark.asyncio
async def test_upload_image_timeout_raises_upstream_timeout(settings, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timeout simulado")

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    with pytest.raises(UpstreamTimeoutError):
        await client.upload_image(
            file_bytes=_PNG_1X1,
            filename="foto.png",
            content_type="image/png",
            credentials=CREDS,
            payload_endpoint="openAI",
        )


def test_file_entry_from_upload_matches_real_har_shape() -> None:
    from meligpt.clients.meligpt_http import file_entry_from_upload

    # Resposta real de POST /api/files/images (import.har, 2026-08-15).
    upload_response = {
        "message": "File uploaded and processed successfully",
        "_id": "1c613107-adb1-402f-b14e-4bbdc0a70174",
        "bytes": 610559,
        "context": "message_attachment",
        "fileId": "1c613107-adb1-402f-b14e-4bbdc0a70174",
        "file_id": "1c613107-adb1-402f-b14e-4bbdc0a70174",
        "filename": "meligpt-image-2026-08-09-at-85304-pm.png",
        "filepath": "/images/69a6d3ab29b848ccb550efbf/1c613107-...png",
        "height": 768,
        "source": "object_storage",
        "temp_file_id": "c1699687-3c0d-49ff-877a-9c605cca54b9",
        "type": "image/png",
        "width": 768,
    }
    entry = file_entry_from_upload(upload_response)
    assert entry == {
        "file_id": "1c613107-adb1-402f-b14e-4bbdc0a70174",
        "filepath": "/images/69a6d3ab29b848ccb550efbf/1c613107-...png",
        "type": "image/png",
        "height": 768,
        "width": 768,
    }


@pytest.mark.asyncio
async def test_stream_chat_includes_files_when_provided(settings, monkeypatch) -> None:
    import json as json_module

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json_module.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n",
        )

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    files = [
        {
            "file_id": "f1",
            "filepath": "/images/x.png",
            "type": "image/png",
            "height": 10,
            "width": 10,
        }
    ]
    async for _ in client.stream_chat(
        prompt="descreva essa imagem", message_id="m1", credentials=CREDS, files=files
    ):
        pass

    assert captured["payload"]["files"] == files


@pytest.mark.asyncio
async def test_stream_chat_omits_files_key_when_none(settings, monkeypatch) -> None:
    import json as json_module

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json_module.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"data: [DONE]\n",
        )

    client = MeliGPTClient(settings, transport=httpx.MockTransport(handler))
    async for _ in client.stream_chat(prompt="oi", message_id="m1", credentials=CREDS):
        pass

    assert "files" not in captured["payload"]
