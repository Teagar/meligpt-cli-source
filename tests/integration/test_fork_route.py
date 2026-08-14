from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import meligpt.clients.meligpt_http as client_module
from meligpt.api.app import create_app
from meligpt.auth.secrets import Credentials, save_credentials
from meligpt.clients.meligpt_http import ForkOption
from meligpt.exceptions import UpstreamForbiddenError


@pytest.fixture
def client(settings) -> TestClient:
    settings.auto_refresh_enabled = False
    save_credentials(
        settings.resolved_secrets_path(), Credentials(access_token="tok", cookie_header="c=1")
    )
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_fork_route_default_option_sends_empty_string(client: TestClient, monkeypatch) -> None:
    captured: dict = {}

    async def fake_fork(self, *, conversation_id, message_id, credentials, **kwargs):
        captured["conversation_id"] = conversation_id
        captured["message_id"] = message_id
        captured["kwargs"] = kwargs
        return {
            "conversation": {"conversationId": "new-conv", "title": "bifurcada"},
            "messages": [{"messageId": "m1"}],
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "fork_conversation", fake_fork)

    response = client.post(
        "/v1/conversations/fork",
        json={"conversation_id": "conv-1", "message_id": "msg-1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["conversation_id"] == "new-conv"
    assert body["title"] == "bifurcada"
    assert body["message_count"] == 1
    assert captured["conversation_id"] == "conv-1"
    assert captured["message_id"] == "msg-1"
    assert captured["kwargs"]["option"] is ForkOption.INCLUDE_ALL


def test_fork_route_visible_only_option(client: TestClient, monkeypatch) -> None:
    captured: dict = {}

    async def fake_fork(self, *, conversation_id, message_id, credentials, **kwargs):
        captured["kwargs"] = kwargs
        return {"conversation": {"conversationId": "c"}, "messages": []}

    monkeypatch.setattr(client_module.MeliGPTClient, "fork_conversation", fake_fork)

    response = client.post(
        "/v1/conversations/fork",
        json={"conversation_id": "conv-1", "message_id": "msg-1", "option": "directPath"},
    )
    assert response.status_code == 200
    assert captured["kwargs"]["option"] is ForkOption.VISIBLE_ONLY


def test_fork_route_rejects_invalid_option(client: TestClient) -> None:
    response = client.post(
        "/v1/conversations/fork",
        json={"conversation_id": "conv-1", "message_id": "msg-1", "option": "nao-existe"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_fork_option"


def test_fork_route_surfaces_upstream_error(client: TestClient, monkeypatch) -> None:
    async def fake_fork(self, **kwargs):
        raise UpstreamForbiddenError("nao autorizado", status_code=403)

    monkeypatch.setattr(client_module.MeliGPTClient, "fork_conversation", fake_fork)

    response = client.post(
        "/v1/conversations/fork",
        json={"conversation_id": "conv-1", "message_id": "msg-1"},
    )
    assert response.status_code == 502
