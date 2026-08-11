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


def test_openai_models_list_filters_by_provider(client: TestClient) -> None:
    response = client.get("/v1/models", params={"provider": "google"})
    assert response.status_code == 200
    ids = {m["id"] for m in response.json()["data"]}
    assert ids == {"gemini-3.6-flash", "veo-3.1-generate-001", "veo-3.1-fast-generate-001"}


def test_openai_models_list_filters_by_endpoint(client: TestClient) -> None:
    response = client.get("/v1/models", params={"endpoint": "bedrock"})
    assert response.status_code == 200
    ids = [m["id"] for m in response.json()["data"]]
    assert ids == ["claude-5-sonnet"]


def test_openai_get_model_by_id(client: TestClient) -> None:
    response = client.get("/v1/models/claude-5-sonnet")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "anthropic"
    assert body["endpoint"] == "bedrock"
    assert body["route"] == "/api/ask/generic"


def test_openai_get_model_unknown_id_returns_404(client: TestClient) -> None:
    response = client.get("/v1/models/does-not-exist")
    assert response.status_code == 404


def test_openai_list_providers(client: TestClient) -> None:
    response = client.get("/v1/providers")
    assert response.status_code == 200
    providers = {p["id"]: p["route"] for p in response.json()["data"]}
    assert providers["openAI"] == "/api/ask/openAI"
    assert providers["bedrock"] == "/api/ask/generic"


def test_openai_chat_completions_accepts_non_chat_model(client: TestClient, monkeypatch) -> None:
    """Regressão do bug reportado via OpenClaude em 2026-08-10: modelos
    de vídeo/imagem PRECISAM funcionar aqui, porque `/v1/chat/completions`
    é o único endpoint que clientes OpenAI-compatible (OpenClaude) falam
    — bloquear por tipo os deixava inacessíveis na prática."""

    import meligpt.api.openai_compat as openai_compat_module
    import meligpt.clients.meligpt_http as client_module
    from meligpt.catalog import ModelInfo

    image_model = ModelInfo(
        id="image-gen-1",
        name="Image Gen 1",
        provider="custom",
        route="/api/ask/generic",
        payload_endpoint="custom",
        type="image",
    )

    async def fake_get(self, model_id):
        return image_model if model_id == "image-gen-1" else None

    async def fake_stream(self, *, prompt, message_id, credentials, model_info=None):
        yield {
            "event": "on_message_delta",
            "data": {"delta": {"content": [{"type": "text", "text": "ok"}]}},
        }

    monkeypatch.setattr(openai_compat_module.ModelCatalog, "get", fake_get)
    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "image-gen-1", "messages": [{"role": "user", "content": "oi"}]},
    )
    assert response.status_code == 200


def test_openai_chat_completions_generates_video_end_to_end(
    client: TestClient, settings, monkeypatch
) -> None:
    """Reprodução exata do fluxo reportado: OpenClaude com `/model sora-2`
    pedindo um vídeo via `/v1/chat/completions`."""

    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module

    captured: dict = {}

    async def fake_stream(self, *, prompt, message_id, credentials, model_info=None):
        captured["model_info"] = model_info
        yield {
            "event": "on_message_delta",
            "data": {
                "delta": {
                    "content": [
                        {
                            "type": "text",
                            "text": "pronto: /api/media/u1/video_goku_vs_naruto.mp4",
                        }
                    ]
                }
            },
        }

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        return b"VIDEOBYTES"

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)
    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "sora-2",
            "messages": [
                {"role": "user", "content": "Crie um video com audio do goku vs o naruto"}
            ],
        },
    )
    assert response.status_code == 200
    assert captured["model_info"].id == "sora-2"
    content = response.json()["choices"][0]["message"]["content"]
    assert "![vídeo gerado]" in content
    assert "video_goku_vs_naruto.mp4" in content

    saved = settings.resolved_media_dir() / "video_goku_vs_naruto.mp4"
    assert saved.read_bytes() == b"VIDEOBYTES"


def test_openai_chat_completions_selects_model_route(client: TestClient, monkeypatch) -> None:
    """`model` batendo com o catálogo troca a rota/endpoint/model reais
    enviados ao MeliGPT."""

    import meligpt.clients.meligpt_http as client_module

    captured: dict = {}

    async def capturing_stream(self, *, prompt, message_id, credentials, model_info=None):
        captured["model_info"] = model_info
        yield {
            "event": "on_message_delta",
            "data": {"delta": {"content": [{"type": "text", "text": "ok"}]}},
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", capturing_stream)

    client.post(
        "/v1/chat/completions",
        json={
            "model": "gemini-3.6-flash",
            "messages": [{"role": "user", "content": "oi"}],
        },
    )
    assert captured["model_info"] is not None
    assert captured["model_info"].id == "gemini-3.6-flash"


def test_openai_chat_completions_unknown_model_label_uses_default(
    client: TestClient, monkeypatch
) -> None:
    """`model="meligpt"` (rótulo genérico do OpenClaude) não bate com
    nenhum id do catálogo — deve preservar o comportamento antigo
    (Settings.model / resolved_endpoint()), não falhar."""

    import meligpt.clients.meligpt_http as client_module

    captured: dict = {}

    async def capturing_stream(self, *, prompt, message_id, credentials, model_info=None):
        captured["model_info"] = model_info
        yield {
            "event": "on_message_delta",
            "data": {"delta": {"content": [{"type": "text", "text": "ok"}]}},
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", capturing_stream)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "meligpt", "messages": [{"role": "user", "content": "oi"}]},
    )
    assert response.status_code == 200
    assert captured["model_info"] is None


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


def test_openai_chat_completions_embeds_generated_image_markdown(
    client: TestClient, monkeypatch
) -> None:
    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module

    async def fake_stream(self, *, prompt, message_id, credentials, model_info=None):
        yield {
            "event": "on_message_delta",
            "data": {
                "delta": {
                    "content": [{"type": "text", "text": "pronto: /api/media/u1/image_gato.png"}]
                }
            },
        }

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        return b"IMGBYTES"

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)
    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "meligpt", "messages": [{"role": "user", "content": "gere um gato"}]},
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "/generated-images/image_gato.png" in content
    assert "![imagem gerada](" in content


def test_openai_chat_completions_streaming_embeds_generated_image_markdown(
    client: TestClient, monkeypatch
) -> None:
    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module

    async def fake_stream(self, *, prompt, message_id, credentials, model_info=None):
        yield {
            "event": "on_message_delta",
            "data": {
                "delta": {
                    "content": [{"type": "text", "text": "pronto: /api/media/u1/image_gato.png"}]
                }
            },
        }

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        return b"IMGBYTES"

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)
    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "meligpt",
            "messages": [{"role": "user", "content": "gere um gato"}],
            "stream": True,
        },
    )
    assert response.status_code == 200
    assert "/generated-images/image_gato.png" in response.text
