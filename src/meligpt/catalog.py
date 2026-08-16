"""Catálogo central de modelos multi-provedor.

O MeliGPT (backend LibreChat-like) expõe vários "provedores" lógicos via
rotas HTTP distintas, e cada requisição também carrega um campo
``"endpoint"`` no corpo do payload. Nem sempre esses dois valores
coincidem — o HAR real mostrou, por exemplo, que o Claude usa a rota
``/api/ask/generic`` mas manda ``"endpoint": "bedrock"`` no payload. Por
isso :class:`ModelInfo` guarda ``route`` (a URL HTTP) e ``payload_endpoint``
(o valor do campo ``endpoint`` do JSON) como dois campos separados — nunca
um só.

Este módulo mantém:

- :data:`KNOWN_ROUTES`: mapeamento fixo "endpoint lógico" -> rota HTTP,
  confirmado por HAR para ``openAI``/``google``/``nova`` e assumido (por
  convenção do backend, sem HAR específico) para o restante -> ``generic``.
- :data:`FALLBACK_MODELS`: os modelos confirmados manualmente, usados
  quando nenhum catálogo remoto está configurado ou quando ele falha.
- :class:`ModelCatalog`: carrega o catálogo (remoto opcional via
  ``MELIGPT_MODELS_URL``, com cache e fallback local automático) e
  resolve consultas por id/provider/endpoint/tipo.

Não há evidência de HAR para uma URL de catálogo remoto — por isso ela é
puramente configurável (``MELIGPT_MODELS_URL``), nunca inventada aqui.
"""

from __future__ import annotations

import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from meligpt.config import Settings
from meligpt.exceptions import (
    ModelNotFoundError,
    ModelTypeNotSupportedError,
    ProviderNotFoundError,
)
from meligpt.logging import get_logger, log_with_fields

_logger = get_logger("catalog")

ModelType = Literal["chat", "image", "video"]

DEFAULT_ROUTE = "/api/ask/generic"

#: Mapeamento "endpoint lógico" (valor do campo ``endpoint`` do payload,
#: também usado como id de provedor) -> rota HTTP conhecida. ``openAI``,
#: ``google`` e ``nova`` foram confirmados via HAR real; os demais seguem
#: a convenção observada (tudo que não tem rota dedicada cai em
#: ``/api/ask/generic``) mas não foram exercitados ao vivo.
KNOWN_ROUTES: dict[str, str] = {
    "openAI": "/api/ask/openAI",
    "google": "/api/ask/google",
    "nova": "/api/ask/nova",
    "anthropic": "/api/ask/generic",
    "bedrock": "/api/ask/generic",
    "alibaba": "/api/ask/generic",
    "nvidia": "/api/ask/generic",
    "meta": "/api/ask/generic",
    "grok": "/api/ask/generic",
    "deepseek": "/api/ask/generic",
    "mistral": "/api/ask/generic",
}


class ModelInfo(BaseModel):
    """Uma entrada do catálogo de modelos."""

    model_config = {"frozen": True}

    id: str
    name: str
    provider: str
    """Nome "humano" do provedor/vendor (ex.: ``anthropic``, ``google``)."""

    route: str
    """Caminho HTTP real (ex.: ``/api/ask/generic``)."""

    payload_endpoint: str
    """Valor enviado no campo ``"endpoint"`` do payload JSON — pode ser
    diferente do ``provider`` (ex.: Claude é ``provider="anthropic"`` mas
    ``payload_endpoint="bedrock"``)."""

    type: ModelType = "chat"


class ProviderInfo(BaseModel):
    """Uma entrada de :data:`KNOWN_ROUTES`, exposta via ``GET /v1/providers``."""

    model_config = {"frozen": True}

    id: str
    route: str


def _route_for(payload_endpoint: str) -> str:
    return KNOWN_ROUTES.get(payload_endpoint, DEFAULT_ROUTE)


def _model(
    model_id: str,
    name: str,
    provider: str,
    payload_endpoint: str,
    *,
    type: ModelType = "chat",
) -> ModelInfo:
    return ModelInfo(
        id=model_id,
        name=name,
        provider=provider,
        route=_route_for(payload_endpoint),
        payload_endpoint=payload_endpoint,
        type=type,
    )


#: Os 8 modelos de CHAT confirmados manualmente (ver resumo do checkpoint
#: anterior). ``gpt-5.6-sol`` fica primeiro de propósito: é o default de
#: ``Settings.model`` e o comportamento pré-catálogo de ``GET /v1/models``
#: (usado por integrações existentes, ex. OpenClaude) já esperava vê-lo
#: como primeiro item da lista.
_CHAT_MODELS: tuple[ModelInfo, ...] = (
    _model("gpt-5.6-sol", "GPT-5.6 Sol", "openAI", "openAI"),
    _model("gpt-5.6-luna", "GPT-5.6 Luna", "openAI", "openAI"),
    _model("claude-5-sonnet", "Claude 5 Sonnet", "anthropic", "bedrock"),
    _model("gemini-3.6-flash", "Gemini 3.6 Flash", "google", "google"),
    _model("glm-5.1", "GLM 5.1", "alibaba", "alibaba"),
    _model("nvidia.nemotron-nano-12b-v2", "Nemotron Nano 12B v2", "nvidia", "nvidia"),
    _model("amazon.nova-pro-v1:0", "Amazon Nova Pro v1", "nova", "nova"),
    _model(
        "us.meta.llama4-scout-17b-instruct-v1:0",
        "Llama 4 Scout 17B Instruct",
        "meta",
        "meta",
    ),
)

#: Modelos de VÍDEO — nomes de exibição confirmados pelo usuário (visto no
#: seletor de modelo do MeliGPT em 2026-08-10/11). Confirmação por HAR
#: real (requisições de geração de vídeo bem-sucedidas):
#: - ``veo-3.1-fast-generate-001``, ``veo-3.1-generate-001``, ``sora-2``,
#:   ``happyhorse-1.0-t2v``: CONFIRMADOS — todos os 4 têm HAR de uma
#:   geração bem-sucedida (2026-08-10/11), ver
#:   ``tests/fixtures/video_generation_sse*.txt`` e
#:   ``tests/integration/test_video_generation_real_har.py``.
#: Se algum id parar de bater (o MeliGPT pode trocar de versão), corrija
#: a string aqui — é o único lugar que precisa mudar.
_VIDEO_MODELS: tuple[ModelInfo, ...] = (
    _model("sora-2", "Sora 2", "openAI", "openAI", type="video"),
    _model("veo-3.1-generate-001", "Veo 3.1 Generate", "google", "google", type="video"),
    _model(
        "veo-3.1-fast-generate-001",
        "Veo 3.1 Fast Generate",
        "google",
        "google",
        type="video",
    ),
    _model("happyhorse-1.0-t2v", "HappyHorse 1.0", "alibaba", "alibaba", type="video"),
)

FALLBACK_MODELS: tuple[ModelInfo, ...] = _CHAT_MODELS + _VIDEO_MODELS

FALLBACK_PROVIDERS: tuple[ProviderInfo, ...] = tuple(
    ProviderInfo(id=provider, route=route) for provider, route in KNOWN_ROUTES.items()
)


def _parse_remote_model(entry: dict[str, Any]) -> ModelInfo | None:
    try:
        model_id = entry["id"]
        provider = entry["provider"]
    except (KeyError, TypeError):
        return None

    payload_endpoint = entry.get("payload_endpoint") or provider
    route = entry.get("route") or _route_for(payload_endpoint)
    model_type = entry.get("type", "chat")
    if model_type not in ("chat", "image", "video"):
        model_type = "chat"

    try:
        return ModelInfo(
            id=model_id,
            name=entry.get("name") or model_id,
            provider=provider,
            route=route,
            payload_endpoint=payload_endpoint,
            type=model_type,
        )
    except (TypeError, ValueError):
        return None


class ModelCatalog:
    """Carrega e consulta o catálogo de modelos.

    Uma instância deve ser reaproveitada entre requisições (ver
    ``api/app.py``) para que o cache de 5 minutos do catálogo remoto
    funcione de verdade.
    """

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._cache: list[ModelInfo] | None = None
        self._cache_time: float = 0.0

    async def _fetch_remote(self) -> list[ModelInfo] | None:
        url = self._settings.models_url
        if not url:
            return None

        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=10.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            log_with_fields(
                _logger,
                30,
                "falha ao buscar catálogo remoto de modelos, usando fallback local",
                url=url,
                error=str(exc),
            )
            return None

        raw_models = data.get("models") if isinstance(data, dict) else data
        if not isinstance(raw_models, list):
            log_with_fields(
                _logger,
                30,
                "catálogo remoto em formato inesperado, usando fallback local",
                url=url,
            )
            return None

        models = [m for entry in raw_models if (m := _parse_remote_model(entry)) is not None]
        return models or None

    async def models(self, *, force_refresh: bool = False) -> list[ModelInfo]:
        """Retorna o catálogo completo (remoto com cache, ou fallback local)."""

        now = time.monotonic()
        ttl = self._settings.models_cache_seconds
        if not force_refresh and self._cache is not None and (now - self._cache_time) < ttl:
            return self._cache

        remote = await self._fetch_remote()
        result = remote if remote is not None else list(FALLBACK_MODELS)
        self._cache = result
        self._cache_time = now
        return result

    async def list_models(
        self, *, provider: str | None = None, endpoint: str | None = None
    ) -> list[ModelInfo]:
        models = await self.models()
        if provider is not None:
            models = [m for m in models if m.provider == provider]
        if endpoint is not None:
            models = [m for m in models if m.payload_endpoint == endpoint]
        return models

    async def get(self, model_id: str) -> ModelInfo | None:
        for model in await self.models():
            if model.id == model_id:
                return model
        return None

    async def list_providers(self) -> list[ProviderInfo]:
        """Lista as rotas conhecidas (:data:`KNOWN_ROUTES`).

        Independente de quais modelos estão no catálogo no momento — são
        as rotas HTTP que o servidor MeliGPT reconhece.
        """

        return list(FALLBACK_PROVIDERS)


async def resolve_model(
    catalog: ModelCatalog,
    *,
    model_id: str | None = None,
    provider: str | None = None,
    require_type: ModelType | None = "chat",
) -> ModelInfo | None:
    """Resolve uma seleção de modelo/provedor pedida pelo usuário (CLI ou API).

    Retorna ``None`` quando nem ``model_id`` nem ``provider`` foram
    informados — sinal para o chamador usar o comportamento padrão
    (``Settings.model`` / ``Settings.resolved_endpoint()``).

    ``require_type=None`` aceita qualquer tipo de modelo (chat, image ou
    video) sem restrição — usado pelo endpoint de chat genérico
    (``meligpt chat`` / ``POST /v1/chat``), que é capaz de lidar com
    qualquer resposta (texto ou mídia baixada via
    :mod:`meligpt.media`). O default ``"chat"`` é o mais seguro para
    contextos que assumem uma conversa de texto (ex.:
    ``/v1/chat/completions``, usado por assistentes de código).

    Levanta :class:`ModelNotFoundError`, :class:`ProviderNotFoundError` ou
    :class:`ModelTypeNotSupportedError` conforme o caso.
    """

    if model_id is None and provider is None:
        return None

    if model_id is not None:
        model = await catalog.get(model_id)
        if model is None:
            raise ModelNotFoundError(f"modelo desconhecido: {model_id}")
        if provider is not None and model.provider != provider:
            raise ModelNotFoundError(
                f"modelo {model_id!r} não pertence ao provedor {provider!r} "
                f"(provedor real: {model.provider!r})"
            )
    else:
        candidates = await catalog.list_models(provider=provider)
        if not candidates:
            raise ProviderNotFoundError(f"provedor desconhecido: {provider}")
        if require_type is not None:
            preferred = [m for m in candidates if m.type == require_type]
            model = preferred[0] if preferred else candidates[0]
        else:
            model = candidates[0]

    if require_type is not None and model.type != require_type:
        raise ModelTypeNotSupportedError(
            f"modelo {model.id!r} é do tipo {model.type!r}, "
            f"não suportado neste endpoint (esperado: {require_type!r})"
        )
    return model
