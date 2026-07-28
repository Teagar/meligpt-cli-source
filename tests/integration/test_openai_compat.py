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


async def _fake_stream_chat(self, *, prompt, message_id, credentials):
    yield {
        "event": "on_message_delta",
        "data": {"delta": {"content": [{"type": "text", "text": "resposta"}]}},
    }


def test_openai_chat_completions_non_streaming(client: TestClient, monkeypatch) -> None:
    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", _fake_stream_chat)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "meligpt", "messages": [{"role": "user", "content": "oi"}]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["choices"][0]["message"]["content"] == "resposta"
    assert body["choices"][0]["finish_reason"] == "stop"


def test_openai_models_list(client: TestClient) -> None:
    response = client.get("/v1/models")
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "gpt-5.6-sol"


def test_openai_chat_completions_uses_last_user_message(client: TestClient, monkeypatch) -> None:
    import meligpt.clients.meligpt_http as client_module

    captured_prompts = []

    async def capturing_stream(self, *, prompt, message_id, credentials):
        captured_prompts.append(prompt)
        yield {
            "event": "on_message_delta",
            "data": {"delta": {"content": [{"type": "text", "text": "ok"}]}},
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", capturing_stream)

    client.post(
        "/v1/chat/completions",
        json={
            "model": "meligpt",
            "messages": [
                {"role": "system", "content": "seja útil"},
                {"role": "user", "content": "primeira"},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": "segunda pergunta"},
            ],
        },
    )
    assert captured_prompts == ["segunda pergunta"]
