from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from meligpt.api.app import create_app
from meligpt.auth.secrets import Credentials, save_credentials


@pytest.fixture
def client(settings) -> TestClient:
    settings.auto_refresh_enabled = False
    save_credentials(
        settings.resolved_secrets_path(), Credentials(access_token="tok", cookie_header="c=1")
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def _drain_sse(response) -> str:
    return response.text


def test_chat_with_unknown_model_returns_400(client: TestClient) -> None:
    response = client.post("/v1/chat", json={"message": "oi", "model": "does-not-exist"})
    assert response.status_code == 400
    assert response.json()["code"] == "model_not_found"


def test_chat_with_unknown_endpoint_returns_400(client: TestClient) -> None:
    response = client.post("/v1/chat", json={"message": "oi", "endpoint": "does-not-exist"})
    assert response.status_code == 400
    assert response.json()["code"] == "provider_not_found"


def test_chat_with_valid_model_streams_normally(client: TestClient, monkeypatch) -> None:
    import meligpt.clients.meligpt_http as client_module

    captured: dict = {}

    async def fake_stream(self, *, prompt, message_id, credentials, model_info=None):
        captured["model_info"] = model_info
        yield {
            "event": "on_message_delta",
            "data": {"delta": {"content": [{"type": "text", "text": "ok"}]}},
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)

    response = client.post("/v1/chat", json={"message": "oi", "model": "gemini-3.6-flash"})
    assert response.status_code == 200
    assert captured["model_info"].id == "gemini-3.6-flash"


def test_chat_without_model_or_endpoint_uses_default(client: TestClient, monkeypatch) -> None:
    import meligpt.clients.meligpt_http as client_module

    captured: dict = {}

    async def fake_stream(self, *, prompt, message_id, credentials, model_info=None):
        captured["model_info"] = model_info
        yield {
            "event": "on_message_delta",
            "data": {"delta": {"content": [{"type": "text", "text": "ok"}]}},
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)

    response = client.post("/v1/chat", json={"message": "oi"})
    assert response.status_code == 200
    assert captured["model_info"] is None


def test_chat_emits_generated_image_event_when_media_link_present(
    client: TestClient, monkeypatch
) -> None:
    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module

    async def fake_stream(self, *, prompt, message_id, credentials, model_info=None):
        yield {
            "event": "on_message_delta",
            "data": {
                "delta": {
                    "content": [
                        {
                            "type": "text",
                            "text": "veja: /api/media/u1/image_x.png",
                        }
                    ]
                }
            },
        }

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        return b"IMGBYTES"

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)
    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    response = client.post("/v1/chat", json={"message": "gere uma imagem"})
    assert response.status_code == 200
    body = response.text
    assert "event: generated_image" in body
    assert "/generated-images/image_x.png" in body
