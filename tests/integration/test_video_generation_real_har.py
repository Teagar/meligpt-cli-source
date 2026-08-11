"""Regressão end-to-end usando respostas SSE REAIS de gerações de vídeo
bem-sucedidas, capturadas via HAR pelo usuário em 2026-08-10/11 e salvas
em ``tests/fixtures/video_generation_sse_*.txt``.

Isso existe porque as primeiras tentativas de suporte a vídeo (mesma
janela de datas) tinham bugs reais, só visíveis com dados reais:

1. ``_build_payload`` não mandava o campo ``"examples"``, presente em
   toda requisição real observada.
2. Os ids de modelo Veo inferidos (``veo-3.1-generate``,
   ``veo-3.1-fast-generate``) estavam errados — o real tem sufixo
   ``-001``.
3. O id de HappyHorse inferido (``happyhorse-1.0``) também estava
   errado — o real tem sufixo ``-t2v`` (``happyhorse-1.0-t2v``).

Os 4 modelos de vídeo do catálogo (`sora-2`, `veo-3.1-generate-001`,
`veo-3.1-fast-generate-001`, `happyhorse-1.0-t2v`) têm HAR de uma geração
bem-sucedida cada — todos confirmam o mesmo formato de resposta: o texto
final vem como uma tag ``<videoplayer url="...">`` (não markdown), e o
evento SSE de nível de transporte é ``event: message`` com um payload
``{"final": true, ...}`` — bem diferente de ``on_message_delta``/
``on_run_step_completed`` usados por texto/imagem.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from meligpt.auth.secrets import Credentials, save_credentials
from meligpt.catalog import FALLBACK_MODELS
from meligpt.chat.service import GeneratedMedia, run_chat
from meligpt.tools.registry import build_default_registry

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

# (id do modelo, arquivo de fixture, rota HTTP esperada, filename esperado do .mp4)
CONFIRMED_VIDEO_CASES = [
    (
        "veo-3.1-fast-generate-001",
        "video_generation_sse_veo_fast.txt",
        "/api/ask/google",
        "7412cc65-26d8-47db-9e8c-50390720446c.mp4",
    ),
    (
        "veo-3.1-generate-001",
        "video_generation_sse_veo_generate.txt",
        "/api/ask/google",
        "a8039ddd-6e9d-471f-b894-1562558a5553.mp4",
    ),
    (
        "sora-2",
        "video_generation_sse_sora2.txt",
        "/api/ask/openAI",
        "72978916-ef72-4bda-b3e1-9db375541656.mp4",
    ),
    (
        "happyhorse-1.0-t2v",
        "video_generation_sse_happyhorse.txt",
        "/api/ask/generic",
        "090b5bff-a186-4d67-a190-a1e2b46eb2a3.mp4",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_id,fixture_name,expected_route,expected_filename", CONFIRMED_VIDEO_CASES
)
async def test_real_video_generation_sse_end_to_end(
    settings, monkeypatch, model_id, fixture_name, expected_route, expected_filename
) -> None:
    """Confirma, pra cada um dos 4 modelos de vídeo do catálogo, que a
    resposta SSE real (capturada por HAR de uma geração bem-sucedida)
    flui corretamente pelo pipeline inteiro: parsing SSE -> extração do
    link de mídia -> download -> salvamento local."""

    save_credentials(
        settings.resolved_secrets_path(), Credentials(access_token="tok", cookie_header="c=1")
    )

    raw_sse = (FIXTURES_DIR / fixture_name).read_bytes()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == expected_route
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=raw_sse)

    import meligpt.clients.meligpt_http as client_module

    original_init = client_module.MeliGPTClient.__init__

    def patched_init(self, settings_, *, transport=None):
        original_init(self, settings_, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(client_module.MeliGPTClient, "__init__", patched_init)

    async def fake_download_media(settings_, credentials_, path, *, transport=None):
        assert path.endswith(f"/{expected_filename}")
        return b"REALVIDEOBYTES"

    import meligpt.chat.service as service_module

    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    model = next(m for m in FALLBACK_MODELS if m.id == model_id)
    assert model.type == "video"

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="Crie um video de uma bola quicando",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
            model_info=model,
        )
    ]

    generated = [e for e in events if isinstance(e, GeneratedMedia)]
    assert len(generated) == 1
    assert generated[0].media_type == "video"

    saved_path = settings.resolved_media_dir() / expected_filename
    assert saved_path.read_bytes() == b"REALVIDEOBYTES"


def test_payload_includes_examples_field_confirmed_by_har() -> None:
    """Regressão do bug #1: `examples` some do payload real capturado por
    HAR quebrava geração de vídeo (e possivelmente outros fluxos)."""

    from meligpt.clients.meligpt_http import _build_payload

    payload = _build_payload("oi", "msg-1", "veo-3.1-fast-generate-001", payload_endpoint="google")
    assert payload["examples"] == [{"input": {"content": ""}, "output": {"content": ""}}]
