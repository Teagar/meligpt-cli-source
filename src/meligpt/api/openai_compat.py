"""Adaptador compatível com a API de Chat Completions da OpenAI.

Permite conectar clientes que só sabem falar "OpenAI-compatible /v1"
(ex.: OpenClaude, via ``OPENAI_BASE_URL``) ao servidor meligpt, traduzindo
para/de :func:`meligpt.chat.service.run_chat`.

MEMÓRIA DE CONVERSA (gambiarra deliberada, ver `_build_transcript_prompt`):
o MeliGPT não tem `conversationId` persistente do nosso lado, e o
protocolo OpenAI não manda nenhum identificador de sessão estável — mas o
cliente (OpenClaude) reenvia o histórico completo em `messages` a cada
requisição. Em vez de usar só a última mensagem (que fazia o modelo
"esquecer" tudo a cada turno), serializamos a conversa inteira num único
prompt de texto. Sem estado no servidor, funciona com qualquer cliente
compatível.

DESCOBERTA DE ARQUIVO DESLIGADA (`discovery_enabled=False`): a heurística
de descoberta automática (`chat/prompt_builder.py`) foi desenhada para
prompts curtos digitados por humano na CLI. Rodando sobre uma transcrição
inteira de um agente como o OpenClaude — que injeta bastante contexto
próprio na mensagem — ela gerava avisos de "arquivo não encontrado" para
nomes que nem apareciam na pergunta real do usuário. `auto_files=True`
continua ligado (só reage a referências explícitas `/files/...`, sem
falsos positivos).

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

from meligpt.catalog import ModelCatalog
from meligpt.chat.service import (
    ChatFinished,
    GeneratedImage,
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


def _build_transcript_prompt(
    messages: list[ChatMessage], *, file_context: str | None = None
) -> str:
    """Monta um prompt único com a conversa inteira, dando "memória" ao
    chat apesar do MeliGPT não ter `conversationId` persistente do nosso
    lado.

    O OpenClaude (como qualquer cliente OpenAI-compatible padrão) reenvia
    o histórico completo em `messages` a cada requisição — então, em vez
    de só repassar a última mensagem (que fazia o modelo "esquecer" tudo
    a cada turno), serializamos todo o histórico como transcrição e
    pedimos para o modelo continuar como assistente. É uma solução
    "gambiarra" deliberada: sem estado do lado do servidor, sem
    `conversationId` mapeado — só reaproveita o que o próprio cliente já
    manda.

    ``file_context``, quando informado, entra como um bloco de sistema
    adicional com o snapshot atual do sandbox local (ver
    `_build_directory_snapshot`) — assim o modelo já sabe quais arquivos
    existem sem precisar que o usuário peça `ls` manualmente.
    """

    system_parts = [m.content for m in messages if m.role == "system" and m.content.strip()]
    turns = [m for m in messages if m.role in ("user", "assistant") and m.content.strip()]

    if not turns:
        return ""

    # Turno único e sem contexto extra: não precisa de transcrição, evita
    # sobrecarregar o modelo remoto com formatação desnecessária.
    if len(turns) == 1 and turns[0].role == "user" and not system_parts and not file_context:
        return turns[0].content

    lines: list[str] = []
    if system_parts:
        lines.append("[Instruções do sistema]\n" + "\n".join(system_parts))
        lines.append("")
    if file_context:
        lines.append(file_context)
        lines.append("")

    lines.append(
        "A seguir está o histórico completo desta conversa. Continue-a "
        "respondendo à última mensagem do usuário, mantendo consistência "
        "com tudo o que já foi dito antes (nomes, decisões, contexto)."
    )
    lines.append("")

    role_label = {"user": "Usuário", "assistant": "Assistente"}
    for turn in turns:
        lines.append(f"{role_label[turn.role]}: {turn.content}")

    lines.append("")
    lines.append("Assistente:")
    return "\n".join(lines)


async def _build_directory_snapshot(settings: Settings) -> str | None:
    """Lista o sandbox local (`/`) e formata um bloco compacto para o
    modelo saber o que já existe, sem precisar que o usuário peça `ls`
    manualmente antes de pedir para ler/editar um arquivo.

    Retorna ``None`` quando o sandbox está vazio (evita ruído) ou em caso
    de erro (nunca deve derrubar a requisição por causa disso).
    """

    from meligpt.exceptions import MeliGPTError
    from meligpt.tools.files.ls import LsTool

    try:
        result = await LsTool().execute({"path": "/", "recursive": True}, settings)
    except MeliGPTError:
        return None

    files = [e["path"] for e in result.get("entries", []) if e["type"] == "file"]
    files = [f for f in files if not f.endswith("/.gitkeep")]
    if not files:
        return None

    max_listed = 100
    listed = files[:max_listed]
    lines = ["[Arquivos locais disponíveis nesta sessão]"]
    lines.extend(listed)
    if len(files) > max_listed:
        lines.append(f"... e mais {len(files) - max_listed} arquivo(s)")
    lines.append(
        "Use os caminhos acima exatamente como estão (com a barra inicial) "
        "ao ler, editar ou listar esses arquivos."
    )
    return "\n".join(lines)


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


def build_openai_router(
    settings: Settings, registry: ToolRegistry, catalog: ModelCatalog | None = None
) -> APIRouter:
    local_router = APIRouter()
    catalog = catalog or ModelCatalog(settings)

    @local_router.get("/v1/models")
    async def list_models(provider: str | None = None, endpoint: str | None = None) -> JSONResponse:
        """Lista o catálogo de modelos multi-provedor.

        ``?provider=`` filtra pelo vendor lógico (ex.: ``google``,
        ``anthropic``); ``?endpoint=`` filtra pelo valor real do campo
        ``endpoint`` do payload (ex.: ``bedrock``) — que pode diferir do
        provider (ver :mod:`meligpt.catalog`).
        """

        models = await catalog.list_models(provider=provider, endpoint=endpoint)
        return JSONResponse(
            {
                "object": "list",
                "data": [
                    {
                        "id": m.id,
                        "object": "model",
                        "created": 0,
                        "owned_by": m.provider,
                        "provider": m.provider,
                        "endpoint": m.payload_endpoint,
                        "route": m.route,
                        "type": m.type,
                    }
                    for m in models
                ],
            }
        )

    @local_router.get("/v1/models/{model_id}")
    async def get_model(model_id: str) -> JSONResponse:
        model = await catalog.get(model_id)
        if model is None:
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "error": f"modelo desconhecido: {model_id}",
                    "code": "model_not_found",
                },
            )
        return JSONResponse(
            {
                "id": model.id,
                "object": "model",
                "created": 0,
                "owned_by": model.provider,
                "provider": model.provider,
                "endpoint": model.payload_endpoint,
                "route": model.route,
                "type": model.type,
            }
        )

    @local_router.get("/v1/providers")
    async def list_providers() -> JSONResponse:
        providers = await catalog.list_providers()
        return JSONResponse(
            {"object": "list", "data": [{"id": p.id, "route": p.route} for p in providers]}
        )

    @local_router.post("/v1/chat/completions")
    async def chat_completions(body: ChatCompletionRequest):
        # `body.model` costuma ser um rótulo genérico (ex.: "meligpt", o
        # default do OpenClaude) e não necessariamente um id do catálogo —
        # só troca de modelo/rota quando ele bate com uma entrada real,
        # preservando o comportamento padrão (Settings.model) caso
        # contrário.
        model_info = await catalog.get(body.model)
        if model_info is not None and model_info.type != "chat":
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "error": (
                        f"modelo {model_info.id!r} é do tipo {model_info.type!r}, "
                        "não suportado em /v1/chat/completions"
                    ),
                    "code": "model_type_not_supported",
                },
            )

        file_context = await _build_directory_snapshot(settings)
        prompt = _build_transcript_prompt(body.messages, file_context=file_context)
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

        if not body.stream:
            parts: list[str] = []
            try:
                async for event in run_chat(
                    prompt=prompt,
                    settings=settings,
                    registry=registry,
                    discovery_enabled=False,
                    auto_files=True,
                    model_info=model_info,
                ):
                    if isinstance(event, TextChunk):
                        parts.append(event.text)
                    elif isinstance(event, MirroredToolResult):
                        parts.append(f"\n[{event.name}] {event.message}\n")
                    elif isinstance(event, GeneratedImage):
                        parts.append(f"\n![imagem gerada]({event.virtual_path})\n")
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
                async for event in run_chat(
                    prompt=prompt,
                    settings=settings,
                    registry=registry,
                    discovery_enabled=False,
                    auto_files=True,
                    model_info=model_info,
                ):
                    if isinstance(event, TextChunk):
                        text = event.text
                    elif isinstance(event, MirroredToolResult):
                        text = f"\n[{event.name}] {event.message}\n"
                    elif isinstance(event, GeneratedImage):
                        text = f"\n![imagem gerada]({event.virtual_path})\n"
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
