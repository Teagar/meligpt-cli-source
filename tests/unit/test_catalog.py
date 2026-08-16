from __future__ import annotations

import json

import httpx
import pytest

from meligpt.catalog import (
    FALLBACK_MODELS,
    FALLBACK_PROVIDERS,
    ModelCatalog,
    resolve_model,
)
from meligpt.exceptions import ModelNotFoundError, ProviderNotFoundError


def test_fallback_models_have_gpt_sol_first() -> None:
    assert FALLBACK_MODELS[0].id == "gpt-5.6-sol"
    assert len(FALLBACK_MODELS) == 59
    assert len({m.id for m in FALLBACK_MODELS}) == 59


def test_fallback_models_include_video_models() -> None:
    video_ids = {m.id for m in FALLBACK_MODELS if m.type == "video"}
    assert video_ids == {
        "sora-2",
        "veo-3.1-generate-001",
        "veo-3.1-fast-generate-001",
        "happyhorse-1.0-t2v",
    }


def test_fallback_models_include_image_models() -> None:
    image_ids = {m.id for m in FALLBACK_MODELS if m.type == "image"}
    assert image_ids == {
        "gemini-2.5-flash-image",
        "gemini-3.1-flash-image",
        "gemini-3-pro-image",
        "nano-banana-2",
        "gpt-image-1-mini",
        "gpt-image-1.5",
        "gpt-image-2",
        "imagen-3.0-generate-002",
    }
    # Confirmados por HAR real (2026-08-15, `tudo.har` + `import.har`) —
    # inclusive revelando que "Nano Banana" e "Imagen 3.0 Generate" tinham
    # ids diferentes do que a convenção de nomenclatura sugeria, e um
    # modelo (`gemini-3.1-flash-image`) que nem estava na lista da UI.
    confirmed_image_ids = {m.id for m in FALLBACK_MODELS if m.type == "image" and m.confirmed}
    assert confirmed_image_ids == {
        "gemini-2.5-flash-image",
        "gemini-3.1-flash-image",
        "gpt-image-1-mini",
        "gpt-image-1.5",
        "gpt-image-2",
        "imagen-3.0-generate-002",
    }
    # "Nano Banana 2" e "Gemini 3 Pro Image" continuam sem HAR.
    unconfirmed_image_ids = {m.id for m in FALLBACK_MODELS if m.type == "image" and not m.confirmed}
    assert unconfirmed_image_ids == {"gemini-3-pro-image", "nano-banana-2"}


def test_nano_banana_display_name_maps_to_real_id() -> None:
    """'Nano Banana' na UI do MeliGPT não é um id literal — é
    `gemini-2.5-flash-image` por baixo (confirmado por HAR real)."""

    nano_banana = next(m for m in FALLBACK_MODELS if m.name == "Nano Banana")
    assert nano_banana.id == "gemini-2.5-flash-image"
    assert nano_banana.confirmed is True


def test_fallback_models_confirmed_flag() -> None:
    """18 modelos com HAR real: os 8 chat + 4 vídeo do checkpoint
    original, mais 6 de imagem confirmados em 2026-08-15 (`tudo.har` +
    `import.har`, este último trazendo um modelo extra
    `gemini-3.1-flash-image` que nem estava na lista da UI). Todo o resto
    do catálogo (colado da UI, sem id interno visível) é melhor-esforço.
    """

    confirmed_ids = {m.id for m in FALLBACK_MODELS if m.confirmed}
    assert confirmed_ids == {
        "gpt-5.6-sol",
        "gpt-5.6-luna",
        "claude-5-sonnet",
        "gemini-3.6-flash",
        "glm-5.1",
        "nvidia.nemotron-nano-12b-v2",
        "amazon.nova-pro-v1:0",
        "us.meta.llama4-scout-17b-instruct-v1:0",
        "sora-2",
        "veo-3.1-generate-001",
        "veo-3.1-fast-generate-001",
        "happyhorse-1.0-t2v",
        "gemini-2.5-flash-image",
        "gemini-3.1-flash-image",
        "gpt-image-1-mini",
        "gpt-image-1.5",
        "gpt-image-2",
        "imagen-3.0-generate-002",
    }
    assert sum(1 for m in FALLBACK_MODELS if not m.confirmed) == 41


def test_claude_uses_generic_route_but_bedrock_payload_endpoint() -> None:
    claude = next(m for m in FALLBACK_MODELS if m.id == "claude-5-sonnet")
    assert claude.provider == "anthropic"
    assert claude.payload_endpoint == "bedrock"
    assert claude.route == "/api/ask/generic"


def test_known_route_models_use_dedicated_routes() -> None:
    routes = {m.id: m.route for m in FALLBACK_MODELS}
    assert routes["gpt-5.6-sol"] == "/api/ask/openAI"
    assert routes["gemini-3.6-flash"] == "/api/ask/google"
    assert routes["amazon.nova-pro-v1:0"] == "/api/ask/nova"


@pytest.mark.asyncio
async def test_models_falls_back_to_local_without_models_url(settings) -> None:
    catalog = ModelCatalog(settings)
    models = await catalog.models()
    assert models == list(FALLBACK_MODELS)


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown_id(settings) -> None:
    catalog = ModelCatalog(settings)
    assert await catalog.get("does-not-exist") is None
    assert (await catalog.get("gpt-5.6-sol")).name == "GPT-5.6 Sol"


@pytest.mark.asyncio
async def test_list_models_filters_by_provider_and_endpoint(settings) -> None:
    catalog = ModelCatalog(settings)
    google_models = await catalog.list_models(provider="google")
    assert {m.id for m in google_models} == {
        "gemini-3.6-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-3-pro-image",
        "gemini-2.5-flash-image",
        "gemini-3.1-flash-image",
        "nano-banana-2",
        "imagen-3.0-generate-002",
        "veo-3.1-generate-001",
        "veo-3.1-fast-generate-001",
    }

    bedrock_models = await catalog.list_models(endpoint="bedrock")
    assert {m.id for m in bedrock_models} == {
        "claude-5-sonnet",
        "claude-4.6-sonnet",
        "claude-4.5-sonnet",
        "claude-4.6-opus",
    }


@pytest.mark.asyncio
async def test_list_providers_returns_known_routes(settings) -> None:
    catalog = ModelCatalog(settings)
    providers = await catalog.list_providers()
    assert providers == list(FALLBACK_PROVIDERS)
    assert any(p.id == "openAI" and p.route == "/api/ask/openAI" for p in providers)


@pytest.mark.asyncio
async def test_remote_catalog_is_used_when_configured(settings) -> None:
    remote_payload = {
        "models": [
            {
                "id": "custom-model",
                "name": "Custom Model",
                "provider": "custom-vendor",
                "payload_endpoint": "custom-vendor",
                "type": "chat",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com/models.json"
        return httpx.Response(200, json=remote_payload)

    settings.models_url = "https://example.com/models.json"
    catalog = ModelCatalog(settings, transport=httpx.MockTransport(handler))

    models = await catalog.models()
    assert len(models) == 1
    assert models[0].id == "custom-model"
    # rota derivada via KNOWN_ROUTES (provedor desconhecido -> generic)
    assert models[0].route == "/api/ask/generic"
    # Sem `confirmed` no payload remoto: assume True (fonte é o próprio
    # servidor, não uma convenção de nomenclatura inferida por nós).
    assert models[0].confirmed is True


@pytest.mark.asyncio
async def test_remote_catalog_respects_explicit_confirmed_false(settings) -> None:
    remote_payload = {
        "models": [
            {
                "id": "unverified-model",
                "name": "Unverified Model",
                "provider": "custom-vendor",
                "payload_endpoint": "custom-vendor",
                "type": "chat",
                "confirmed": False,
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=remote_payload)

    settings.models_url = "https://example.com/models.json"
    catalog = ModelCatalog(settings, transport=httpx.MockTransport(handler))

    models = await catalog.models()
    assert models[0].confirmed is False


@pytest.mark.asyncio
async def test_remote_catalog_falls_back_to_local_on_http_error(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    settings.models_url = "https://example.com/models.json"
    catalog = ModelCatalog(settings, transport=httpx.MockTransport(handler))

    models = await catalog.models()
    assert models == list(FALLBACK_MODELS)


@pytest.mark.asyncio
async def test_remote_catalog_falls_back_to_local_on_bad_json(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    settings.models_url = "https://example.com/models.json"
    catalog = ModelCatalog(settings, transport=httpx.MockTransport(handler))

    models = await catalog.models()
    assert models == list(FALLBACK_MODELS)


@pytest.mark.asyncio
async def test_remote_catalog_falls_back_to_local_on_unexpected_shape(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    settings.models_url = "https://example.com/models.json"
    catalog = ModelCatalog(settings, transport=httpx.MockTransport(handler))

    models = await catalog.models()
    assert models == list(FALLBACK_MODELS)


@pytest.mark.asyncio
async def test_remote_catalog_is_cached_within_ttl(settings) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"models": []})

    settings.models_url = "https://example.com/models.json"
    settings.models_cache_seconds = 300.0
    catalog = ModelCatalog(settings, transport=httpx.MockTransport(handler))

    await catalog.models()
    await catalog.models()
    assert call_count == 1


@pytest.mark.asyncio
async def test_remote_catalog_refetches_after_ttl_expires(settings, monkeypatch) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"models": []})

    settings.models_url = "https://example.com/models.json"
    settings.models_cache_seconds = 0.01
    catalog = ModelCatalog(settings, transport=httpx.MockTransport(handler))

    await catalog.models()

    import time

    time.sleep(0.05)
    await catalog.models()
    assert call_count == 2


@pytest.mark.asyncio
async def test_resolve_model_returns_none_without_selection(settings) -> None:
    catalog = ModelCatalog(settings)
    assert await resolve_model(catalog) is None


@pytest.mark.asyncio
async def test_resolve_model_by_id(settings) -> None:
    catalog = ModelCatalog(settings)
    model = await resolve_model(catalog, model_id="gemini-3.6-flash")
    assert model is not None
    assert model.id == "gemini-3.6-flash"


@pytest.mark.asyncio
async def test_resolve_model_unknown_id_raises(settings) -> None:
    catalog = ModelCatalog(settings)
    with pytest.raises(ModelNotFoundError):
        await resolve_model(catalog, model_id="nope")


@pytest.mark.asyncio
async def test_resolve_model_by_provider_picks_first_chat_model(settings) -> None:
    catalog = ModelCatalog(settings)
    model = await resolve_model(catalog, provider="openAI")
    assert model is not None
    assert model.id == "gpt-5.6-sol"


@pytest.mark.asyncio
async def test_resolve_model_unknown_provider_raises(settings) -> None:
    catalog = ModelCatalog(settings)
    with pytest.raises(ProviderNotFoundError):
        await resolve_model(catalog, provider="does-not-exist")


@pytest.mark.asyncio
async def test_resolve_model_mismatched_provider_raises(settings) -> None:
    catalog = ModelCatalog(settings)
    with pytest.raises(ModelNotFoundError):
        await resolve_model(catalog, model_id="gemini-3.6-flash", provider="openAI")


@pytest.mark.asyncio
async def test_resolve_model_rejects_non_chat_type(settings) -> None:
    remote_payload = {
        "models": [
            {
                "id": "image-model",
                "name": "Image Model",
                "provider": "custom",
                "payload_endpoint": "custom",
                "type": "image",
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=remote_payload)

    settings.models_url = "https://example.com/models.json"
    catalog = ModelCatalog(settings, transport=httpx.MockTransport(handler))

    from meligpt.exceptions import ModelTypeNotSupportedError

    with pytest.raises(ModelTypeNotSupportedError):
        await resolve_model(catalog, model_id="image-model")


@pytest.mark.asyncio
async def test_resolve_model_by_id_accepts_video_with_require_type_none(settings) -> None:
    catalog = ModelCatalog(settings)
    model = await resolve_model(catalog, model_id="sora-2", require_type=None)
    assert model is not None
    assert model.id == "sora-2"
    assert model.type == "video"


@pytest.mark.asyncio
async def test_resolve_model_by_id_video_rejected_with_default_require_type(settings) -> None:
    from meligpt.exceptions import ModelTypeNotSupportedError

    catalog = ModelCatalog(settings)
    with pytest.raises(ModelTypeNotSupportedError):
        await resolve_model(catalog, model_id="sora-2")


@pytest.mark.asyncio
async def test_resolve_model_by_provider_with_require_type_none_picks_first(settings) -> None:
    """openAI tem modelos de chat E o Sora 2 (vídeo) — sem restrição de
    tipo, pega o primeiro da lista (chat, por vir primeiro no catálogo)."""

    catalog = ModelCatalog(settings)
    model = await resolve_model(catalog, provider="openAI", require_type=None)
    assert model is not None
    assert model.id == "gpt-5.6-sol"


def test_json_import_smoke() -> None:
    # Garante que os payloads de exemplo usados nos testes acima são JSON válido.
    json.dumps({"models": []})
