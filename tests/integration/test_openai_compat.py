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
    """Bootstrap: quando não há sessão MeliGPT cacheada para continuar
    (aqui, a primeira requisição desse `client`/app — o cache de sessão
    está vazio), a conversa inteira ainda vira o prompt, pra não perder
    contexto quando o servidor não tem por onde retomar. Ver
    `test_openai_chat_completions_resumes_conversation_incrementally`
    para o caminho normal (turno a turno, sem reenviar histórico).
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


def test_openai_chat_completions_resumes_conversation_incrementally(
    client: TestClient, monkeypatch
) -> None:
    """Fluxo normal, turno a turno: depois que o primeiro turno confirma um
    conversationId/messageId reais, o segundo turno (histórico completo +
    uma mensagem nova, exatamente como o OpenClaude reenvia) deve mandar
    SÓ a mensagem nova pro MeliGPT, resumindo a MESMA conversa — em vez de
    recriar uma conversa nova a cada chamada.
    """

    import meligpt.clients.meligpt_http as client_module

    captured_calls: list[dict] = []
    turn = {"n": 0}

    async def fake_stream(self, *, prompt, message_id, credentials, **kwargs):
        turn["n"] += 1
        captured_calls.append({"prompt": prompt, **kwargs})
        yield {
            "event": "message",
            "data": {
                "final": True,
                "responseMessage": {
                    "text": f"resposta {turn['n']}",
                    "conversationId": "conv-123",
                    "messageId": f"msg-{turn['n']}",
                },
            },
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)

    first = client.post(
        "/v1/chat/completions",
        json={"model": "meligpt", "messages": [{"role": "user", "content": "primeira"}]},
    )
    assert first.status_code == 200
    first_reply = first.json()["choices"][0]["message"]["content"]
    assert first_reply == "resposta 1"

    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "meligpt",
            "messages": [
                {"role": "user", "content": "primeira"},
                {"role": "assistant", "content": first_reply},
                {"role": "user", "content": "segunda"},
            ],
        },
    )
    assert second.status_code == 200
    assert second.json()["choices"][0]["message"]["content"] == "resposta 2"

    assert len(captured_calls) == 2
    # Primeiro turno: sem sessão pra continuar, conversa nova de verdade.
    assert captured_calls[0].get("conversation_id") is None
    # Segundo turno: retoma a conversa 1, mandando só a mensagem nova —
    # nem o system, nem "primeira", nem "resposta 1" voltam a ser enviados.
    assert captured_calls[1]["prompt"] == "segunda"
    assert captured_calls[1]["conversation_id"] == "conv-123"
    assert captured_calls[1]["parent_message_id"] == "msg-1"


def test_openai_chat_completions_resumes_after_reformatted_history(
    client: TestClient, monkeypatch
) -> None:
    """Regressão do `openclaude --continue`: ao recarregar uma conversa
    salva, o OpenClaude reconstrói `system`/`assistant` do zero (system
    prompt regenerado, anotações de tool call reformatadas) — só o texto
    que o usuário digitou permanece idêntico. A sessão precisa continuar
    sendo reconhecida mesmo assim.
    """

    import meligpt.clients.meligpt_http as client_module

    captured_calls: list[dict] = []
    turn = {"n": 0}

    async def fake_stream(self, *, prompt, message_id, credentials, **kwargs):
        turn["n"] += 1
        captured_calls.append({"prompt": prompt, **kwargs})
        yield {
            "event": "message",
            "data": {
                "final": True,
                "responseMessage": {
                    "text": f"resposta {turn['n']}",
                    "conversationId": "conv-continue",
                    "messageId": f"msg-{turn['n']}",
                },
            },
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)

    first = client.post(
        "/v1/chat/completions",
        json={
            "model": "meligpt",
            "messages": [
                {"role": "system", "content": "Você é um agente. Diretório: /home/user/proj"},
                {"role": "user", "content": "primeira"},
            ],
        },
    )
    assert first.status_code == 200

    # Simula o --continue: mesmo texto do usuário, mas system/assistant
    # completamente diferentes do que teria sido gravado originalmente
    # (o OpenClaude nunca ecoa de volta um `full_text` idêntico ao que
    # recebeu — reformata anotações locais, tool calls, etc.).
    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "meligpt",
            "messages": [
                {
                    "role": "system",
                    "content": "Você é um agente. Diretório: /home/user/proj (recarregado)",
                },
                {"role": "user", "content": "primeira"},
                {"role": "assistant", "content": "[resposta reformatada de forma diferente]"},
                {"role": "user", "content": "segunda"},
            ],
        },
    )
    assert second.status_code == 200
    assert len(captured_calls) == 2
    assert captured_calls[1]["prompt"] == "segunda"
    assert captured_calls[1]["conversation_id"] == "conv-continue"
    assert captured_calls[1]["parent_message_id"] == "msg-1"


def test_openai_chat_completions_resumes_despite_ephemeral_reminder_blocks(
    client: TestClient, monkeypatch
) -> None:
    """Regressão exata do log real reportado: o OpenClaude injeta blocos
    `<system-reminder>`/`<available-deferred-tools>` DENTRO das próprias
    mensagens `user` (não como `system` separado), e o conteúdo desses
    blocos (ex.: `snip_id=...`) muda a cada retomada — mesmo o texto que
    a pessoa digitou sendo idêntico. Sem ignorar esses blocos ao calcular
    a chave, a sessão nunca era reconhecida depois de um `--continue`.
    """

    import meligpt.clients.meligpt_http as client_module

    captured_calls: list[dict] = []
    turn = {"n": 0}

    async def fake_stream(self, *, prompt, message_id, credentials, **kwargs):
        turn["n"] += 1
        captured_calls.append({"prompt": prompt, **kwargs})
        yield {
            "event": "message",
            "data": {
                "final": True,
                "responseMessage": {
                    "text": f"resposta {turn['n']}",
                    "conversationId": "conv-reminder",
                    "messageId": f"msg-{turn['n']}",
                },
            },
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)

    first_user_content = (
        "<available-deferred-tools>\nAskUserQuestion, WebSearch\n</available-deferred-tools>\n\n"
        "Ola\n<system-reminder>snip_id=701tx1; sessão original</system-reminder>"
    )
    first = client.post(
        "/v1/chat/completions",
        json={"model": "meligpt", "messages": [{"role": "user", "content": first_user_content}]},
    )
    assert first.status_code == 200

    # Retomada (--continue): mesmo texto humano ("Ola"), mas o snip_id e o
    # resto do bloco de reminder são regenerados com valores diferentes.
    reloaded_user_content = (
        "<available-deferred-tools>\nAskUserQuestion, WebSearch, Bash\n</available-deferred-tools>\n\n"
        "Ola\n<system-reminder>snip_id=99zzq2; sessão recarregada, outro contexto</system-reminder>"
    )
    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "meligpt",
            "messages": [
                {"role": "user", "content": reloaded_user_content},
                {"role": "assistant", "content": "resposta 1"},
                {
                    "role": "user",
                    "content": "Como você se chama?\n<system-reminder>snip_id=abc123</system-reminder>",
                },
            ],
        },
    )
    assert second.status_code == 200
    assert len(captured_calls) == 2
    assert captured_calls[1]["prompt"] == (
        "Como você se chama?\n<system-reminder>snip_id=abc123</system-reminder>"
    )
    assert captured_calls[1]["conversation_id"] == "conv-reminder"
    assert captured_calls[1]["parent_message_id"] == "msg-1"


def test_openai_chat_completions_video_generation_uses_only_latest_message_when_resuming(
    client: TestClient, monkeypatch
) -> None:
    """Regressão exata do segundo bug relatado: ao continuar uma conversa
    já em andamento, pedir pra gerar vídeo/imagem não pode fazer a geração
    usar a transcrição inteira como prompt — só o pedido atual.
    """

    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module

    captured_prompts: list[str] = []
    turn = {"n": 0}

    async def fake_stream(self, *, prompt, message_id, credentials, **kwargs):
        turn["n"] += 1
        captured_prompts.append(prompt)
        text = "oi, tudo bem?" if turn["n"] == 1 else "pronto: /api/media/u1/video_final.mp4"
        yield {
            "event": "message",
            "data": {
                "final": True,
                "responseMessage": {
                    "text": text,
                    "conversationId": "conv-xyz",
                    "messageId": f"msg-{turn['n']}",
                },
            },
        }

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        return b"VIDEOBYTES"

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)
    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    first = client.post(
        "/v1/chat/completions",
        json={"model": "meligpt", "messages": [{"role": "user", "content": "oi"}]},
    )
    first_reply = first.json()["choices"][0]["message"]["content"]

    second = client.post(
        "/v1/chat/completions",
        json={
            "model": "sora-2",
            "messages": [
                {"role": "user", "content": "oi"},
                {"role": "assistant", "content": first_reply},
                {"role": "user", "content": "gera um video de um gato jogando xadrez"},
            ],
        },
    )
    assert second.status_code == 200
    assert captured_prompts[1] == "gera um video de um gato jogando xadrez"
    content = second.json()["choices"][0]["message"]["content"]
    assert "video_final.mp4" in content


def test_openai_chat_completions_broken_history_falls_back_to_bootstrap(
    client: TestClient, monkeypatch
) -> None:
    """Se o histórico recebido não bate com nenhuma sessão cacheada (ex.:
    o processo reiniciou e perdeu o cache em memória, ou o usuário editou
    uma mensagem antiga), o adaptador não quebra — só degrada de volta
    pro bootstrap (transcrição completa, conversa nova).
    """

    import meligpt.clients.meligpt_http as client_module

    captured_calls: list[dict] = []

    async def fake_stream(self, *, prompt, message_id, credentials, **kwargs):
        captured_calls.append({"prompt": prompt, **kwargs})
        yield {
            "event": "message",
            "data": {"final": True, "responseMessage": {"text": "ok"}},
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "meligpt",
            "messages": [
                {"role": "user", "content": "mensagem nunca vista antes"},
                {"role": "assistant", "content": "resposta nunca vista antes"},
                {"role": "user", "content": "segunda"},
            ],
        },
    )
    assert response.status_code == 200
    assert captured_calls[0].get("conversation_id") is None
    assert "mensagem nunca vista antes" in captured_calls[0]["prompt"]
    assert "segunda" in captured_calls[0]["prompt"]


def test_openai_chat_completions_exposes_meligpt_conversation_id(
    client: TestClient, monkeypatch
) -> None:
    """Extensão fora do padrão OpenAI: o id real da conversa MeliGPT vem
    junto na resposta, pra dar pra usar em `meligpt fork`/`/v1/conversations/fork`
    sem precisar abrir a UI web."""

    import meligpt.clients.meligpt_http as client_module

    async def fake_stream(self, *, prompt, message_id, credentials, **kwargs):
        yield {
            "event": "message",
            "data": {
                "final": True,
                "responseMessage": {
                    "text": "ok",
                    "conversationId": "conv-abc",
                    "messageId": "msg-xyz",
                },
            },
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)

    response = client.post(
        "/v1/chat/completions",
        json={"model": "meligpt", "messages": [{"role": "user", "content": "oi"}]},
    )
    body = response.json()
    assert body["meligpt_conversation_id"] == "conv-abc"
    assert body["meligpt_message_id"] == "msg-xyz"


def test_openai_chat_completions_streaming_exposes_meligpt_conversation_id(
    client: TestClient, monkeypatch
) -> None:
    import meligpt.clients.meligpt_http as client_module

    async def fake_stream(self, *, prompt, message_id, credentials, **kwargs):
        yield {
            "event": "message",
            "data": {
                "final": True,
                "responseMessage": {
                    "text": "ok",
                    "conversationId": "conv-abc",
                    "messageId": "msg-xyz",
                },
            },
        }

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream)

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "meligpt",
            "messages": [{"role": "user", "content": "oi"}],
            "stream": True,
        },
    )
    assert "conv-abc" in response.text
    assert "msg-xyz" in response.text


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
