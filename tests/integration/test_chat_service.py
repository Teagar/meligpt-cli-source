from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.auth.secrets import Credentials, save_credentials
from meligpt.chat.service import (
    AmbiguousDiscoveryError,
    ChatFinished,
    GeneratedMedia,
    MirroredToolResult,
    TextChunk,
    WarningMessage,
    run_chat,
)
from meligpt.tools.registry import build_default_registry


async def _fake_stream_chat(self, *, prompt, message_id, credentials):
    yield {
        "event": "on_message_delta",
        "data": {"delta": {"content": [{"type": "text", "text": "olá"}]}},
    }
    yield {
        "event": "on_run_step_completed",
        "data": {
            "result": {
                "type": "tool_call",
                "tool_call": {
                    "id": "1",
                    "name": "write_file",
                    "args": {"file_path": "/saida.txt", "content": "conteudo"},
                },
            }
        },
    }


async def _fake_stream_chat_string_args(self, *, prompt, message_id, credentials):
    """Reproduz o formato observado na prática: `arguments` como STRING
    JSON (estilo Assistants API), não como dict já parseado. Antes da
    correção isso fazia o write_file falhar com 'file_path inválido'
    mesmo o modelo tendo mandado tudo certo.
    """

    yield {
        "event": "on_run_step_completed",
        "data": {
            "result": {
                "type": "tool_call",
                "tool_call": {
                    "id": "1",
                    "name": "write_file",
                    "arguments": (
                        '{"file_path": "/index.js", '
                        '"content": "console.log(\\"Hello, World!\\");\\n"}'
                    ),
                },
            }
        },
    }


async def _fake_stream_unmirrored(self, *, prompt, message_id, credentials):
    yield {
        "event": "on_run_step_completed",
        "data": {
            "result": {
                "type": "tool_call",
                "tool_call": {"id": "1", "name": "ImageGeneration", "args": {"prompt": "x"}},
            }
        },
    }


async def _fake_stream_final_message_only(self, *, prompt, message_id, credentials):
    """Sem deltas — só o texto final em `responseMessage`."""

    yield {
        "event": "on_message",
        "data": {"responseMessage": {"text": "resposta completa sem deltas"}},
    }


async def _fake_stream_delta_then_final_message(self, *, prompt, message_id, credentials):
    """Backend manda deltas E um resumo final — não deve duplicar o texto."""

    yield {
        "event": "on_message_delta",
        "data": {"delta": {"content": [{"type": "text", "text": "olá"}]}},
    }
    yield {
        "event": "on_message",
        "data": {"responseMessage": {"text": "olá"}},
    }


async def _fake_stream_with_generated_image(self, *, prompt, message_id, credentials):
    yield {
        "event": "on_message_delta",
        "data": {
            "delta": {
                "content": [
                    {
                        "type": "text",
                        "text": ("aqui está: /api/media/69a6d3ab29b848ccb550efbf/image_abc123.png"),
                    }
                ]
            }
        },
    }


@pytest.fixture(autouse=True)
def _credentials(settings) -> None:
    save_credentials(
        settings.resolved_secrets_path(), Credentials(access_token="tok", cookie_header="c=1")
    )


@pytest.mark.asyncio
async def test_run_chat_streams_text_and_mirrors_write_file(
    files_root: Path, settings, monkeypatch
) -> None:
    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", _fake_stream_chat)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="olá", settings=settings, registry=registry, discovery_enabled=False
        )
    ]

    text_events = [e for e in events if isinstance(e, TextChunk)]
    assert "".join(e.text for e in text_events) == "olá"

    mirrored = [e for e in events if isinstance(e, MirroredToolResult)]
    assert mirrored[0].name == "write_file"
    assert mirrored[0].success is True
    assert (files_root / "saida.txt").read_text() == "conteudo"

    finished = [e for e in events if isinstance(e, ChatFinished)][0]
    assert finished.had_text is True


@pytest.mark.asyncio
async def test_run_chat_warns_on_unmirrored_tool(settings, monkeypatch) -> None:
    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", _fake_stream_unmirrored)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="pesquise algo", settings=settings, registry=registry, discovery_enabled=False
        )
    ]

    warnings = [e for e in events if isinstance(e, WarningMessage)]
    assert any("ImageGeneration" in w.message for w in warnings)


@pytest.mark.asyncio
async def test_run_chat_uses_final_message_when_no_deltas(settings, monkeypatch) -> None:
    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", _fake_stream_final_message_only)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="oi", settings=settings, registry=registry, discovery_enabled=False
        )
    ]

    chunks = [e.text for e in events if isinstance(e, TextChunk)]
    assert chunks == ["resposta completa sem deltas"]
    finished = next(e for e in events if isinstance(e, ChatFinished))
    assert finished.had_text is True


@pytest.mark.asyncio
async def test_run_chat_ignores_final_message_when_deltas_already_seen(
    settings, monkeypatch
) -> None:
    """Evita duplicar: se já vieram deltas de texto, o resumo final em
    `responseMessage` (mesmo texto ou não) é ignorado."""

    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(
        client_module.MeliGPTClient, "stream_chat", _fake_stream_delta_then_final_message
    )

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="oi", settings=settings, registry=registry, discovery_enabled=False
        )
    ]

    chunks = [e.text for e in events if isinstance(e, TextChunk)]
    assert chunks == ["olá"]


@pytest.mark.asyncio
async def test_run_chat_ambiguous_directory_raises(files_root: Path, settings) -> None:
    for parent in ("x", "y"):
        d = files_root / parent / "thiago"
        d.mkdir(parents=True)

    with pytest.raises(AmbiguousDiscoveryError):
        async for _ in run_chat(
            prompt="qual o conteúdo da pasta thiago?",
            settings=settings,
            registry=build_default_registry(),
        ):
            pass


@pytest.mark.asyncio
async def test_run_chat_mirrors_write_file_with_string_arguments(
    files_root: Path, settings, monkeypatch
) -> None:
    """Regressão do bug real: `tool_call.arguments` como string JSON
    devia continuar sendo aplicado (não descartado como {}).
    """

    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", _fake_stream_chat_string_args)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="crie um hello world no index.js",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
        )
    ]

    mirrored = [e for e in events if isinstance(e, MirroredToolResult)]
    assert mirrored[0].name == "write_file"
    assert mirrored[0].success is True, mirrored[0].message
    assert (files_root / "index.js").read_text() == 'console.log("Hello, World!");\n'


async def _fake_stream_write_file_bad_args(self, *, prompt, message_id, credentials):
    yield {
        "event": "on_run_step_completed",
        "data": {
            "result": {
                "type": "tool_call",
                "tool_call": {
                    "id": "1",
                    "name": "write_file",
                    "arguments": '{"unexpected_key": "index.js", "content": "x"}',
                },
            }
        },
    }


@pytest.mark.asyncio
async def test_run_chat_shows_raw_arguments_when_mirrored_tool_fails(settings, monkeypatch) -> None:
    """Regressão: quando uma ferramenta espelhada falha, a mensagem deve
    trazer os argumentos brutos recebidos — é o que permite diagnosticar
    formatos inesperados do MeliGPT sem acesso direto ao backend.
    """

    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(
        client_module.MeliGPTClient, "stream_chat", _fake_stream_write_file_bad_args
    )

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="crie um arquivo",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
        )
    ]

    mirrored = [e for e in events if isinstance(e, MirroredToolResult)][0]
    assert mirrored.success is False
    assert "unexpected_key" in mirrored.message
    assert "args brutos" in mirrored.message


async def _fake_stream_duplicate_completed_event(self, *, prompt, message_id, credentials):
    """Reproduz EXATAMENTE o formato real observado via HAR: o MeliGPT
    emite `on_run_step_completed` duas vezes para a mesma tool call — a
    primeira com `args` completo, a segunda (evento de "fechamento") sem
    esse campo. Antes da correção, a segunda ocorrência sobrescrevia a
    primeira no dicionário de tool calls e `write_file` sempre recebia
    argumentos vazios, mesmo o modelo remoto tendo mandado tudo certo.
    """

    tool_call_id = "toolu_bdrk_01EQEaWKMg3actmw2n8UekCm"

    yield {
        "event": "on_run_step_completed",
        "data": {
            "result": {
                "id": "step_uVnJRG-ygbaFNwR6kSRXm",
                "index": 1,
                "type": "tool_call",
                "tool_call": {
                    "args": (
                        '{"content":"console.log(\\"Hello, World!\\");\\n","file_path":"/index.js"}'
                    ),
                    "name": "write_file",
                    "id": tool_call_id,
                    "output": "Successfully wrote to '/index.js'",
                    "progress": 1,
                },
            }
        },
    }
    yield {
        "event": "on_message_delta",
        "data": {
            "id": "step_ms6gq2bm_syn",
            "delta": {"content": [{"type": "text", "text": "Arquivo criado com sucesso!"}]},
        },
    }
    # Segunda ocorrência: mesmo id, SEM o campo "args" — exatamente como no HAR real.
    yield {
        "event": "on_run_step_completed",
        "data": {
            "result": {
                "id": "step_uVnJRG-ygbaFNwR6kSRXm",
                "index": 1,
                "type": "tool_call",
                "tool_call": {
                    "name": "write_file",
                    "id": tool_call_id,
                    "output": "Successfully wrote to '/index.js'",
                    "progress": 1,
                },
            }
        },
    }


@pytest.mark.asyncio
async def test_run_chat_survives_duplicate_completed_event_without_args(
    files_root: Path, settings, monkeypatch
) -> None:
    """Regressão do bug real relatado (confirmado via HAR do MeliGPT com
    modelo Claude/bedrock): write_file deve ser executado com os
    argumentos reais, não apagados pelo evento de fechamento duplicado.
    """

    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(
        client_module.MeliGPTClient, "stream_chat", _fake_stream_duplicate_completed_event
    )

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="Use a ferramenta write_file e crie um index.js com um hello world",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
        )
    ]

    mirrored = [e for e in events if isinstance(e, MirroredToolResult)]
    assert len(mirrored) == 1
    assert mirrored[0].name == "write_file"
    assert mirrored[0].success is True, mirrored[0].message
    assert (files_root / "index.js").read_text() == 'console.log("Hello, World!");\n'


@pytest.mark.asyncio
async def test_run_chat_forwards_model_info_to_client(settings, monkeypatch) -> None:
    from meligpt.catalog import FALLBACK_MODELS

    received: dict = {}

    async def fake_stream_chat(self, *, prompt, message_id, credentials, model_info=None):
        received["model_info"] = model_info
        yield {
            "event": "on_message_delta",
            "data": {"delta": {"content": [{"type": "text", "text": "ok"}]}},
        }

    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", fake_stream_chat)

    chosen_model = next(m for m in FALLBACK_MODELS if m.id == "gemini-3.6-flash")
    registry = build_default_registry()
    async for _ in run_chat(
        prompt="oi",
        settings=settings,
        registry=registry,
        discovery_enabled=False,
        model_info=chosen_model,
    ):
        pass

    assert received["model_info"] is chosen_model


@pytest.mark.asyncio
async def test_run_chat_downloads_and_saves_generated_image(
    files_root: Path, settings, monkeypatch
) -> None:
    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(
        client_module.MeliGPTClient, "stream_chat", _fake_stream_with_generated_image
    )

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        assert path == "/api/media/69a6d3ab29b848ccb550efbf/image_abc123.png"
        return b"FAKEPNGBYTES"

    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="gere uma imagem de um gato",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
        )
    ]

    generated = [e for e in events if isinstance(e, GeneratedMedia)]
    assert len(generated) == 1
    expected_path = str(settings.resolved_media_dir() / "image_abc123.png")
    assert generated[0].virtual_path == expected_path

    saved_path = settings.resolved_media_dir() / "image_abc123.png"
    assert saved_path.read_bytes() == b"FAKEPNGBYTES"


@pytest.mark.asyncio
async def test_run_chat_downloads_generated_image_with_full_filesystem_access(
    tmp_path: Path, monkeypatch
) -> None:
    """Regressão exata do bug reportado em 2026-08-10: com
    `MELIGPT_FILES_DIR=/` (acesso total, o modo usado para deixar o
    OpenClaude editar/criar arquivos reais), baixar uma imagem gerada
    falhava com "não foi possível criar diretório intermediário:
    generated-images/..." porque a pasta de mídia tentava se criar sob a
    raiz real do filesystem. `resolved_media_dir()` deve ficar sob
    `config_dir`, então isso tem que funcionar mesmo com `files_dir=/`.
    """

    from meligpt.config import Settings

    settings = Settings(
        config_dir=tmp_path / "config",
        files_dir=Path("/"),
        allow_full_filesystem_access=True,
        secrets_path=tmp_path / "config" / "secrets.env",
    )
    save_credentials(
        settings.resolved_secrets_path(), Credentials(access_token="tok", cookie_header="c=1")
    )

    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(
        client_module.MeliGPTClient, "stream_chat", _fake_stream_with_generated_image
    )

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        return b"FAKEPNGBYTES"

    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="gere uma imagem de um gato",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
        )
    ]

    warnings = [e for e in events if isinstance(e, WarningMessage)]
    assert not [w for w in warnings if "falha ao salvar imagem gerada" in w.message], warnings

    generated = [e for e in events if isinstance(e, GeneratedMedia)]
    assert len(generated) == 1
    saved_path = tmp_path / "config" / "generated-images" / "image_abc123.png"
    assert saved_path.read_bytes() == b"FAKEPNGBYTES"


@pytest.mark.asyncio
async def test_run_chat_warns_but_continues_when_image_download_fails(
    settings, monkeypatch
) -> None:
    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module
    from meligpt.exceptions import UpstreamError

    monkeypatch.setattr(
        client_module.MeliGPTClient, "stream_chat", _fake_stream_with_generated_image
    )

    async def failing_download_media(settings_, credentials_, path, *, transport=None):
        raise UpstreamError("boom")

    monkeypatch.setattr(service_module, "download_media", failing_download_media)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="gere uma imagem de um gato",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
        )
    ]

    assert not [e for e in events if isinstance(e, GeneratedMedia)]
    warnings = [e for e in events if isinstance(e, WarningMessage)]
    assert any("falha ao baixar mídia gerada" in w.message for w in warnings)
    # o texto da resposta ainda deve ter sido entregue normalmente
    finished = next(e for e in events if isinstance(e, ChatFinished))
    assert finished.had_text is True


@pytest.mark.asyncio
async def test_run_chat_without_media_link_yields_no_generated_image(settings, monkeypatch) -> None:
    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(client_module.MeliGPTClient, "stream_chat", _fake_stream_chat)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="oi", settings=settings, registry=registry, discovery_enabled=False
        )
    ]

    assert not [e for e in events if isinstance(e, GeneratedMedia)]


async def _fake_stream_with_generated_video(self, *, prompt, message_id, credentials):
    yield {
        "event": "on_message_delta",
        "data": {
            "delta": {
                "content": [
                    {
                        "type": "text",
                        "text": "aqui está: /api/media/u1/video_abc123.mp4",
                    }
                ]
            }
        },
    }


@pytest.mark.asyncio
async def test_run_chat_classifies_video_media_type(settings, monkeypatch) -> None:
    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(
        client_module.MeliGPTClient, "stream_chat", _fake_stream_with_generated_video
    )

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        return b"FAKEVIDEOBYTES"

    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="gere um vídeo",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
        )
    ]

    generated = [e for e in events if isinstance(e, GeneratedMedia)]
    assert len(generated) == 1
    assert generated[0].media_type == "video"
    saved_path = settings.resolved_media_dir() / "video_abc123.mp4"
    assert saved_path.read_bytes() == b"FAKEVIDEOBYTES"


@pytest.mark.asyncio
async def test_run_chat_classifies_image_media_type(settings, monkeypatch) -> None:
    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(
        client_module.MeliGPTClient, "stream_chat", _fake_stream_with_generated_image
    )

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        return b"FAKEPNGBYTES"

    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="gere uma imagem",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
        )
    ]

    generated = [e for e in events if isinstance(e, GeneratedMedia)]
    assert len(generated) == 1
    assert generated[0].media_type == "image"


@pytest.mark.asyncio
async def test_run_chat_saves_to_custom_media_dir(files_root: Path, settings, monkeypatch) -> None:
    """`media_dir` explícito manda o download pra dentro da sandbox de
    arquivos (mesmo mapeamento de `write_file`), em vez do destino padrão
    (`Settings.resolved_media_dir()`, sob `config_dir`)."""

    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(
        client_module.MeliGPTClient, "stream_chat", _fake_stream_with_generated_image
    )

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        return b"FAKEPNGBYTES"

    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="gere uma imagem",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
            media_dir="minhas-imagens",
        )
    ]

    generated = [e for e in events if isinstance(e, GeneratedMedia)]
    assert len(generated) == 1
    expected = files_root / "minhas-imagens" / "image_abc123.png"
    assert generated[0].virtual_path == str(expected)
    assert expected.read_bytes() == b"FAKEPNGBYTES"

    # não deve ter tocado no destino padrão
    assert not settings.resolved_media_dir().exists()


@pytest.mark.asyncio
async def test_run_chat_custom_media_dir_absolute_path_in_full_access_mode(
    tmp_path: Path, monkeypatch
) -> None:
    """Em modo de acesso total (`files_dir=/`), um `media_dir` absoluto
    grava exatamente nesse caminho real — mesma semântica de `write_file`."""

    from meligpt.config import Settings

    target_dir = tmp_path / "onde-eu-quiser"
    target_dir.mkdir()

    settings = Settings(
        config_dir=tmp_path / "config",
        files_dir=Path("/"),
        allow_full_filesystem_access=True,
        secrets_path=tmp_path / "config" / "secrets.env",
    )
    save_credentials(
        settings.resolved_secrets_path(), Credentials(access_token="tok", cookie_header="c=1")
    )

    import meligpt.chat.service as service_module
    import meligpt.clients.meligpt_http as client_module

    monkeypatch.setattr(
        client_module.MeliGPTClient, "stream_chat", _fake_stream_with_generated_image
    )

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        return b"FAKEPNGBYTES"

    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="gere uma imagem",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
            media_dir=str(target_dir),
        )
    ]

    generated = [e for e in events if isinstance(e, GeneratedMedia)]
    assert len(generated) == 1
    saved_path = target_dir / "image_abc123.png"
    assert saved_path.read_bytes() == b"FAKEPNGBYTES"
