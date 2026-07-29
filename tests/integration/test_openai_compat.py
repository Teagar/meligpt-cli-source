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


def test_openai_chat_completions_sends_full_transcript_for_memory(
    client: TestClient, monkeypatch
) -> None:
    """Regressão do bug relatado: o chat "esquecia" a mensagem anterior
    porque só a última era enviada. Agora a conversa inteira vira o
    prompt, dando memória sem precisar de estado no servidor.
    """

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
    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "primeira" in prompt
    assert "segunda pergunta" in prompt
    assert "seja útil" in prompt


def test_openai_chat_completions_single_turn_stays_simple(client: TestClient, monkeypatch) -> None:
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
        json={"model": "meligpt", "messages": [{"role": "user", "content": "Ola"}]},
    )
    assert captured_prompts == ["Ola"]


def test_openai_endpoint_mirrors_web_search_tool_call(client: TestClient, monkeypatch) -> None:
    """Prova que a ferramenta WebSearch (e por extensão qualquer
    ferramenta espelhada) funciona de ponta a ponta através do endpoint
    usado pelo OpenClaude, não só da CLI.
    """

    import meligpt.clients.meligpt_http as client_module
    import meligpt.tools.research.web_search as web_search_module
    from meligpt.clients.web_search import SearchResult

    async def fake_stream(self, *, prompt, message_id, credentials):
        yield {
            "event": "on_message_delta",
            "data": {"delta": {"content": [{"type": "text", "text": "Pesquisando..."}]}},
        }
        yield {
            "event": "on_run_step_completed",
            "data": {
                "result": {
                    "type": "tool_call",
                    "tool_call": {
                        "id": "1",
                        "name": "WebSearch",
                        "arguments": '{"query": "python asyncio"}',
                    },
                }
            },
        }

    async def fake_search(query, settings_arg, *, transport=None):
        return [SearchResult(title="Asyncio Docs", url="https://x", snippet="resumo")]

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)
    monkeypatch.setattr(web_search_module, "search_web", fake_search)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "meligpt", "messages": [{"role": "user", "content": "pesquise asyncio"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "Pesquisando..." in content
    assert "Asyncio Docs" in content
    assert "https://x" in content
