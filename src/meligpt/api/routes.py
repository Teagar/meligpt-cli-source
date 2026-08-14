"""Rotas HTTP/SSE.

Este servidor é opcional (o CLI continua sendo a forma primária de uso) e
expõe a mesma orquestração de :mod:`meligpt.chat.service` via
Server-Sent Events, para integrações que preferem falar HTTP em vez de
invocar o binário ``meligpt``.

Servidor NÃO expõe ``import-har`` interativo (não há terminal em um
processo de servidor) — 401 aqui sempre resulta em erro estruturado para o
cliente decidir o que fazer, preservando "não bloquear o event loop" e
"nunca vazar token/cookie em erro".
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse
from starlette.responses import JSONResponse

from meligpt.api.schemas import ChatRequest, ForkRequest, HealthResponse
from meligpt.catalog import ModelCatalog, resolve_model
from meligpt.chat.service import (
    ChatFinished,
    GeneratedMedia,
    InfoMessage,
    MirroredToolResult,
    TextChunk,
    WarningMessage,
    fork_conversation,
    run_chat,
)
from meligpt.clients.meligpt_http import ForkOption
from meligpt.config import Settings
from meligpt.exceptions import MeliGPTError
from meligpt.logging import get_logger, log_with_fields, new_request_id
from meligpt.tools.registry import ToolRegistry

_FORK_OPTIONS_BY_VALUE = {option.value: option for option in ForkOption}

router = APIRouter()
_logger = get_logger("api.routes")


@router.get("/healthz", response_model=HealthResponse)
async def healthz() -> HealthResponse:
    """Healthcheck que não depende de credenciais externas."""

    return HealthResponse()


@router.post("/v1/auth/refresh")
async def manual_refresh():
    """Dispara manualmente um refresh de token (o mesmo que o loop
    automático faz sozinho). Útil para depuração; nunca retorna o token.
    """

    from meligpt.auth.refresher import refresh_access_token
    from meligpt.config import get_settings
    from meligpt.exceptions import MeliGPTError

    settings = get_settings()
    try:
        await refresh_access_token(settings)
    except MeliGPTError as exc:
        return JSONResponse(status_code=502, content=exc.to_dict())
    return {"success": True, "message": "token renovado"}


def build_chat_router(
    settings: Settings, registry: ToolRegistry, catalog: ModelCatalog | None = None
) -> APIRouter:
    local_router = APIRouter()
    catalog = catalog or ModelCatalog(settings)

    @local_router.post("/v1/conversations/fork")
    async def fork(body: ForkRequest) -> JSONResponse:
        """Bifurca uma conversa MeliGPT (ver `meligpt.chat.service.fork_conversation`
        e ``docs/`` para a semântica das três opções — mesmo contrato do
        botão "Fork" da UI web, confirmado por HAR real)."""

        option = _FORK_OPTIONS_BY_VALUE.get(body.option)
        if option is None:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": (
                        f"option inválida: {body.option!r} — use 'directPath', "
                        "'includeBranches' ou '' (padrão)."
                    ),
                    "code": "invalid_fork_option",
                },
            )

        try:
            result = await fork_conversation(
                conversation_id=body.conversation_id,
                message_id=body.message_id,
                settings=settings,
                option=option,
                split_at_target=body.split_at_target,
                latest_message_id=body.latest_message_id,
            )
        except MeliGPTError as exc:
            return JSONResponse(status_code=502, content=exc.to_dict())

        return JSONResponse(
            {
                "success": True,
                "conversation_id": result.conversation_id,
                "title": result.title,
                "message_count": result.message_count,
            }
        )

    @local_router.post("/v1/chat", response_model=None)
    async def chat(request: Request, body: ChatRequest) -> EventSourceResponse | JSONResponse:
        request_id = new_request_id()

        try:
            # require_type=None: `/v1/chat` aceita modelos de vídeo/imagem
            # também — diferente de `/v1/chat/completions`, que restringe a
            # "chat" (ver openai_compat.py) por ser voltado a assistentes de
            # código conversando em texto.
            model_info = await resolve_model(
                catalog, model_id=body.model, provider=body.endpoint, require_type=None
            )
        except MeliGPTError as exc:
            return JSONResponse(status_code=400, content=exc.to_dict())

        async def event_generator():
            try:
                async for event in run_chat(
                    prompt=body.message,
                    settings=settings,
                    registry=registry,
                    explicit_files=body.files,
                    explicit_directories=body.directories,
                    auto_files=body.auto_files,
                    discovery_enabled=body.discovery_enabled,
                    interactive=False,
                    prompt_for_har=None,
                    model_info=model_info,
                    media_dir=body.media_dir,
                ):
                    if await request.is_disconnected():
                        log_with_fields(
                            _logger, 20, "cliente desconectado, cancelando", request_id=request_id
                        )
                        return

                    if isinstance(event, TextChunk):
                        yield {"event": "text_delta", "data": json.dumps({"text": event.text})}
                    elif isinstance(event, InfoMessage):
                        yield {"event": "info", "data": json.dumps({"message": event.message})}
                    elif isinstance(event, WarningMessage):
                        yield {"event": "warning", "data": json.dumps({"message": event.message})}
                    elif isinstance(event, MirroredToolResult):
                        yield {
                            "event": "tool_result",
                            "data": json.dumps(
                                {
                                    "name": event.name,
                                    "success": event.success,
                                    "message": event.message,
                                }
                            ),
                        }
                    elif isinstance(event, GeneratedMedia):
                        yield {
                            "event": "generated_media",
                            "data": json.dumps(
                                {
                                    "virtual_path": event.virtual_path,
                                    "url": event.url,
                                    "media_type": event.media_type,
                                }
                            ),
                        }
                    elif isinstance(event, ChatFinished):
                        yield {
                            "event": "done",
                            "data": json.dumps(
                                {"had_text": event.had_text, "length": len(event.full_text)}
                            ),
                        }
            except MeliGPTError as exc:
                yield {"event": "error", "data": json.dumps(exc.to_dict())}

        return EventSourceResponse(event_generator())

    return local_router
