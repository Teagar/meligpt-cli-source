"""Regressão end-to-end usando respostas SSE REAIS de gerações de imagem
bem-sucedidas, capturadas via HAR (`tudo.har`) pelo usuário em
2026-08-15, e salvas em ``tests/fixtures/image_generation_sse_*.txt``.

Isso existe porque, na primeira leva de modelos de imagem "dedicados"
adicionados ao catálogo, os ids de dois deles estavam errados — só
detectável com dados reais:

1. "Nano Banana" não é `nano-banana` — o id real, visto no payload da
   requisição bem-sucedida, é `gemini-2.5-flash-image`.
2. "Imagen 3.0 Generate" não é `imagen-3.0-generate` — falta o sufixo de
   versão real, `imagen-3.0-generate-002`.

Os outros três (`gpt-image-1-mini`, `gpt-image-1.5`, `gpt-image-2`) já
batiam com o id inferido por convenção, mas agora têm HAR confirmando de
qualquer forma.

Diferente do vídeo (`<videoplayer url="..."/>`), a resposta final de
imagem vem como markdown padrão: ``![...](/api/media/...)`` — mas a
extração de mídia (`meligpt.media.extract_media_references`) já era
genérica o bastante (regex de caminho, não de sintaxe) pra funcionar sem
mudança nenhuma.
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

# (id do modelo, arquivo de fixture, rota HTTP esperada, filename esperado)
CONFIRMED_IMAGE_CASES = [
    (
        "gemini-2.5-flash-image",
        "image_generation_sse_gemini_flash_image.txt",
        "/api/ask/google",
        "downloaded_d6a534f4-4294-47ba-89eb-393af8a132ed.png",
    ),
    (
        "gpt-image-1-mini",
        "image_generation_sse_gpt_image_1_mini.txt",
        "/api/ask/openAI",
        "gpt_image_1_419eea46-dcdb-4a1a-a872-08212b1a36ea.png",
    ),
    (
        "imagen-3.0-generate-002",
        "image_generation_sse_imagen_3.txt",
        "/api/ask/google",
        "imagen_e9729bdf-60ed-413b-8733-15b5985d3012.png",
    ),
    (
        "gpt-image-2",
        "image_generation_sse_gpt_image_2.txt",
        "/api/ask/openAI",
        "gpt_image_1_b49bf5a4-3961-4f55-9679-b645ce956b01.png",
    ),
    (
        "gpt-image-1.5",
        "image_generation_sse_gpt_image_1_5.txt",
        "/api/ask/openAI",
        "gpt_image_1_ed46f6a2-03dd-42f4-8b1a-fc9974d53489.png",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model_id,fixture_name,expected_route,expected_filename", CONFIRMED_IMAGE_CASES
)
async def test_real_image_generation_sse_end_to_end(
    settings, monkeypatch, model_id, fixture_name, expected_route, expected_filename
) -> None:
    """Confirma, pra cada um dos 5 modelos de imagem confirmados do
    catálogo, que a resposta SSE real (capturada por HAR de uma geração
    bem-sucedida) flui corretamente pelo pipeline inteiro: parsing SSE ->
    extração do link de mídia -> download -> salvamento local."""

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
        return b"REALIMAGEBYTES"

    import meligpt.chat.service as service_module

    monkeypatch.setattr(service_module, "download_media", fake_download_media)

    model = next(m for m in FALLBACK_MODELS if m.id == model_id)
    assert model.type == "image"
    assert model.confirmed is True

    registry = build_default_registry()
    events = [
        e
        async for e in run_chat(
            prompt="Crie uma imagem de um RPG 32 bit em 45 graus",
            settings=settings,
            registry=registry,
            discovery_enabled=False,
            model_info=model,
        )
    ]

    generated = [e for e in events if isinstance(e, GeneratedMedia)]
    assert len(generated) == 1
    assert generated[0].media_type == "image"

    saved_path = settings.resolved_media_dir() / expected_filename
    assert saved_path.read_bytes() == b"REALIMAGEBYTES"


def test_nano_banana_and_imagen_ids_confirmed_by_har() -> None:
    """Regressão dos dois ids que a convenção de nomenclatura errou —
    ver docstring do módulo."""

    by_name = {m.name: m for m in FALLBACK_MODELS}
    assert by_name["Nano Banana"].id == "gemini-2.5-flash-image"
    assert by_name["Imagen 3.0 Generate"].id == "imagen-3.0-generate-002"
