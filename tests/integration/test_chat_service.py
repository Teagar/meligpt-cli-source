from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.auth.secrets import Credentials, save_credentials
from meligpt.chat.service import (
    AmbiguousDiscoveryError,
    ChatFinished,
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
