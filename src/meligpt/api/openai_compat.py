"""Adaptador compatível com a API de Chat Completions da OpenAI.

Permite conectar clientes que só sabem falar "OpenAI-compatible /v1"
(ex.: OpenClaude, via ``OPENAI_BASE_URL``) ao servidor meligpt, traduzindo
para/de :func:`meligpt.chat.service.run_chat`.

LIMITAÇÃO IMPORTANTE (documentada também no README): este adaptador NÃO
implementa function calling no formato OpenAI (`tools` / `tool_calls`
estruturados na resposta). Ele repassa apenas o texto da conversa como
prompt para o MeliGPT. Ferramentas que o próprio MeliGPT executar
remotamente continuam sendo espelhadas localmente (`write_file`/
`read_file`/`ls`) pelo `chat.service`, mas aparecem embutidas no texto da
resposta, não como `tool_calls` estruturados — então o loop de
tool-calling *nativo* do OpenClaude (bash, grep, glob rodando no lado do
OpenClaude) não é acionado por este adaptador.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse
from starlette.responses import JSONResponse

from meligpt.chat.service import (
    ChatFinished,
    MirroredToolResult,
    TextChunk,
    WarningMessage,
    run_chat,
)
from meligpt.config import Settings
from meligpt.exceptions import MeliGPTError
from meligpt.tools.registry import ToolRegistry


class ChatMessage(BaseModel):
    role: str
    content: str = ""


class ChatCompletionRequest(BaseModel):
    model: str = "meligpt"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


def _last_user_prompt(messages: list[ChatMessage]) -> str:
    """Usa a última mensagem `user` como prompt.

    O MeliGPT (via este adaptador) não mantém `conversationId` persistente
    entre chamadas — cada requisição é um turno novo.
    """

    user_messages = [m for m in messages if m.role == "user"]
    return user_messages[-1].content if user_messages else ""


def _sse_chunk(
    completion_id: str, model: str, *, delta: dict[str, Any], finish_reason: str | None
) -> str:
    payload = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return json.dumps(payload)


def build_openai_router(settings: Settings, registry: ToolRegistry) -> APIRouter:
    local_router = APIRouter()

    @local_router.get("/v1/models")
    async def list_models() -> JSONResponse:
        return JSONResponse(
            {
                "object": "list",
                "data": [
                    {"id": settings.model, "object": "model", "created": 0, "owned_by": "meligpt"}
                ],
            }
        )

    @local_router.post("/v1/chat/completions")
    async def chat_completions(body: ChatCompletionRequest):
        prompt = _last_user_prompt(body.messages)
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

        if not body.stream:
            parts: list[str] = []
            try:
                async for event in run_chat(prompt=prompt, settings=settings, registry=registry):
                    if isinstance(event, TextChunk):
                        parts.append(event.text)
                    elif isinstance(event, MirroredToolResult):
                        parts.append(f"\n[{event.name}] {event.message}\n")
                    elif isinstance(event, WarningMessage):
                        parts.append(f"\n[aviso] {event.message}\n")
            except MeliGPTError as exc:
                return JSONResponse(status_code=502, content=exc.to_dict())

            full_text = "".join(parts)
            return JSONResponse(
                {
                    "id": completion_id,
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": body.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": full_text},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                }
            )

        async def event_generator() -> AsyncIterator[dict[str, str]]:
            yield {
                "data": _sse_chunk(
                    completion_id, body.model, delta={"role": "assistant"}, finish_reason=None
                )
            }
            try:
                async for event in run_chat(prompt=prompt, settings=settings, registry=registry):
                    if isinstance(event, TextChunk):
                        text = event.text
                    elif isinstance(event, MirroredToolResult):
                        text = f"\n[{event.name}] {event.message}\n"
                    elif isinstance(event, WarningMessage):
                        text = f"\n[aviso] {event.message}\n"
                    elif isinstance(event, ChatFinished):
                        yield {
                            "data": _sse_chunk(
                                completion_id, body.model, delta={}, finish_reason="stop"
                            )
                        }
                        continue
                    else:
                        continue
                    yield {
                        "data": _sse_chunk(
                            completion_id, body.model, delta={"content": text}, finish_reason=None
                        )
                    }
            except MeliGPTError as exc:
                yield {
                    "data": _sse_chunk(
                        completion_id,
                        body.model,
                        delta={"content": f"\n[erro: {exc.message}]"},
                        finish_reason="stop",
                    )
                }
            yield {"data": "[DONE]"}

        return EventSourceResponse(event_generator())

    return local_router
