"""Adaptador compatível com a API de Chat Completions da OpenAI.

Permite conectar clientes que só sabem falar "OpenAI-compatible /v1"
(ex.: OpenClaude, via ``OPENAI_BASE_URL``) ao servidor meligpt, traduzindo
para/de :func:`meligpt.chat.service.run_chat`.

MEMÓRIA DE CONVERSA (ver `_ConversationTurn`/`ConversationSessionStore`):
o protocolo OpenAI não manda nenhum identificador de sessão estável — o
cliente (OpenClaude) reenvia o histórico completo em `messages` a cada
requisição, e é assim que ele "acha" que está dando memória ao servidor.
Só que o MeliGPT (LibreChat por baixo) JÁ TEM memória de conversa de
verdade do lado dele: uma vez que você manda `conversationId` +
`parentMessageId`, o próprio servidor reconstrói o histórico — o cliente
só precisa mandar a mensagem NOVA a cada turno (confirmado por HAR real,
`forks.har`: o campo `text` de cada requisição nunca contém o histórico).

A versão anterior deste adaptador ignorava isso e SEMPRE criava uma
conversa nova no MeliGPT (`conversationId: null` a cada chamada — daí o
"o assistente esquece tudo e começa um chat novo a cada mensagem"), e
"compensava" colando a transcrição inteira (sistema + todos os turnos +
snapshot de diretório) dentro do campo `text` a cada requisição — o que
também quebrava geração de imagem/vídeo: como o MeliGPT usa `text` como
prompt de geração, o vídeo/imagem acabava sendo gerado a partir da
conversa inteira, não do pedido atual.

Agora: depois de cada turno bem-sucedido, guardamos (só em memória, por
processo — ver `meligpt.chat.session_store`) uma chave derivada das
mensagens `user` da conversa (só delas — ver o porquê no docstring de
`session_store`), apontando para o `conversationId`/`messageId` reais do
MeliGPT. No próximo turno, se as mensagens `user` que chegaram batem com
essa chave (é a mesma sequência de perguntas do usuário + UMA nova), a
gente manda SÓ a mensagem nova, com `conversationId`/`parentMessageId`
apontando pra sessão certa, exatamente como o cliente web real faz — sem
depender de `system`/`assistant` baterem byte a byte, o que quebraria
até em casos legítimos de continuação (ex.: `openclaude --continue`
recarrega a conversa e recompõe o resto do payload do zero, mas o texto
que o usuário digitou continua o mesmo). Sem bater (primeira mensagem da
conversa, ou o processo reiniciou e perdeu o cache), caímos de volta no
bootstrap antigo (transcrição completa) só nessa UMA vez — depois disso
a nova sessão já fica cacheada e os turnos seguintes voltam a ser
incrementais.

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
import re
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
    GeneratedMedia,
    MirroredToolResult,
    TextChunk,
    WarningMessage,
    run_chat,
)
from meligpt.chat.session_store import ConversationSessionStore, SessionRecord, history_key
from meligpt.config import Settings
from meligpt.exceptions import MeliGPTError
from meligpt.logging import get_logger, log_with_fields
from meligpt.tools.registry import ToolRegistry

_logger = get_logger("api.openai_compat")


class ChatMessage(BaseModel):
    role: str
    content: str = ""


class ChatCompletionRequest(BaseModel):
    model: str = "meligpt"
    messages: list[ChatMessage]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    media_dir: str | None = None
    """Extensão fora do padrão OpenAI: onde salvar imagens/vídeos gerados
    neste turno. Clientes que não conhecem o campo simplesmente não o
    mandam — sem isso, usa o destino padrão."""


#: Blocos que o OpenClaude/Claude Code injeta DENTRO das próprias
#: mensagens `user` (não como `system` separado) — reminders de estado,
#: listas de ferramentas disponíveis no turno, etc. Confirmado por log
#: real (`--log-level debug`): esses blocos trazem referências efêmeras
#: (ex.: ``snip_id=...``) que mudam a cada retomada da conversa mesmo
#: quando o texto que a pessoa digitou é idêntico — por isso entram na
#: lista de exclusão antes de calcular a chave de sessão. Lista extensível
#: conforme outros nomes de tag forem observados.
_EPHEMERAL_WRAPPER_TAGS = ("system-reminder", "available-deferred-tools")
_EPHEMERAL_WRAPPER_RE = re.compile(
    r"<(" + "|".join(_EPHEMERAL_WRAPPER_TAGS) + r")\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)


def _stable_user_text(content: str) -> str:
    """Texto de uma mensagem `user` sem os blocos efêmeros acima — a parte
    que realmente identifica "a mesma pergunta" entre um envio original e
    uma retomada (`openclaude --continue`). Ver `_EPHEMERAL_WRAPPER_TAGS`.
    """

    stripped = _EPHEMERAL_WRAPPER_RE.sub("", content)
    return re.sub(r"\s+", " ", stripped).strip()


def _history_turns(messages: list[ChatMessage]) -> list[tuple[str, str]]:
    """As mensagens ``user`` (só elas — ver `session_store` pra entender
    por quê), já sem blocos efêmeros (`_stable_user_text`), usadas como
    "impressão digital" do histórico em :mod:`meligpt.chat.session_store`.
    """

    turns = []
    for m in messages:
        if m.role != "user":
            continue
        stable = _stable_user_text(m.content)
        if stable:
            turns.append(("user", stable))
    return turns


def _build_transcript_prompt(
    messages: list[ChatMessage], *, file_context: str | None = None
) -> str:
    """Monta um prompt único com a conversa inteira — usado só como
    BOOTSTRAP quando não há uma sessão MeliGPT cacheada para continuar
    (primeiro turno da conversa, ou cache perdido por reinício do
    servidor). Ver módulo para o fluxo normal (incremental).

    O OpenClaude (como qualquer cliente OpenAI-compatible padrão) reenvia
    o histórico completo em `messages` a cada requisição — então, quando
    não temos por onde continuar a conversa real do MeliGPT, serializamos
    todo o histórico como transcrição e pedimos para o modelo continuar
    como assistente, SÓ NESSE turno. A resposta gerada já cria uma
    conversa MeliGPT nova que os turnos seguintes vão conseguir
    encadear de forma incremental (ver `_lookup_or_bootstrap`).

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
    completion_id: str,
    model: str,
    *,
    delta: dict[str, Any],
    finish_reason: str | None,
    extra: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload)


def build_openai_router(
    settings: Settings,
    registry: ToolRegistry,
    catalog: ModelCatalog | None = None,
    session_store: ConversationSessionStore | None = None,
) -> APIRouter:
    local_router = APIRouter()
    catalog = catalog or ModelCatalog(settings)
    # Uma instância por servidor: dá memória de conversa real entre
    # requisições sucessivas do MESMO processo (ver docstring do módulo).
    # Injetável (`session_store=`) só para os testes conseguirem inspecionar
    # ou pré-popular o cache.
    session_store = session_store or ConversationSessionStore(max_size=200)

    async def _resolve_prompt(
        messages: list[ChatMessage],
    ) -> tuple[str, str | None, str | None]:
        """Decide o que mandar pro MeliGPT neste turno.

        Retorna ``(prompt, conversation_id, parent_message_id)``:

        - Sessão conhecida (o histórico ANTES da última mensagem bate com
          uma sessão cacheada): manda só a última mensagem, resumindo a
          conversa MeliGPT real. É o caminho normal, turno a turno.
        - Sessão desconhecida: bootstrap (ver `_build_transcript_prompt`)
          — transcrição inteira nesta ÚNICA chamada, conversa nova no
          MeliGPT (`conversation_id=None`).
        """

        if not messages:
            return "", None, None

        prior_turns = _history_turns(messages[:-1])
        session: SessionRecord | None = None
        if prior_turns:
            session = session_store.lookup(history_key(prior_turns))
            log_with_fields(
                _logger,
                10,
                "chave de sessão calculada",
                user_turn_count=len(prior_turns),
                # Prévia curta de cada mensagem `user` usada na chave — só
                # pra diagnosticar por que uma sessão não bateu (ex.: o
                # cliente reformatou o texto ao recarregar a conversa), sem
                # despejar o conteúdo inteiro no log. Só aparece com
                # `--log-level debug`.
                preview=[content[:40] for _role, content in prior_turns],
                hit=session is not None,
            )

        if session is not None:
            log_with_fields(
                _logger,
                20,
                "sessão MeliGPT reconhecida — continuando conversa existente",
                conversation_id=session.conversation_id,
                parent_message_id=session.last_message_id,
            )
            return messages[-1].content, session.conversation_id, session.last_message_id

        log_with_fields(
            _logger,
            20,
            "sessão desconhecida — bootstrap com transcrição completa (conversa nova)",
            turn_count=len(messages),
        )
        file_context = await _build_directory_snapshot(settings)
        prompt = _build_transcript_prompt(messages, file_context=file_context)
        return prompt, None, None

    def _remember_session(messages: list[ChatMessage], finished: ChatFinished) -> None:
        """Depois de um turno bem-sucedido, grava onde essa conversa está
        ancorada no MeliGPT — para o PRÓXIMO turno (que vai chegar com essa
        mesma sequência de mensagens `user` + uma mensagem nova) conseguir
        continuar em vez de recomeçar.

        A chave depende só das mensagens `user` (ver `_history_turns` e o
        docstring de `session_store` para o porquê) — então não precisamos
        do texto da resposta do assistente aqui pra nada além de decidir
        se vale a pena gravar.

        Sem `conversation_id`/`response_message_id` confirmados pelo
        backend (ex.: resposta sem `responseMessage`), não há o que
        gravar — o próximo turno cai de volta no bootstrap, degradando
        sem quebrar.
        """

        if not finished.conversation_id or not finished.response_message_id:
            return
        turns = _history_turns(messages)
        if not turns:
            return
        session_store.remember(
            history_key(turns),
            SessionRecord(
                conversation_id=finished.conversation_id,
                last_message_id=finished.response_message_id,
            ),
        )
        log_with_fields(
            _logger,
            10,
            "chave de sessão gravada",
            user_turn_count=len(turns),
            preview=[content[:40] for _role, content in turns],
        )
        log_with_fields(
            _logger,
            20,
            "sessão MeliGPT gravada — conversationId/messageId reais para este turno",
            conversation_id=finished.conversation_id,
            response_message_id=finished.response_message_id,
        )

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
        # contrário. Modelos de qualquer tipo (chat/image/video) são
        # aceitos aqui: o OpenClaude (e qualquer outro cliente
        # OpenAI-compatible) só fala com este endpoint, então bloquear
        # vídeo/imagem aqui os deixaria inacessíveis na prática — a
        # resposta (texto ou mídia baixada via meligpt.media) é tratada
        # igual independente do tipo do modelo selecionado.
        model_info = await catalog.get(body.model)

        prompt, conversation_id, parent_message_id = await _resolve_prompt(body.messages)
        completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

        if not body.stream:
            parts: list[str] = []
            finished: ChatFinished | None = None
            try:
                async for event in run_chat(
                    prompt=prompt,
                    settings=settings,
                    registry=registry,
                    discovery_enabled=False,
                    auto_files=True,
                    model_info=model_info,
                    media_dir=body.media_dir,
                    conversation_id=conversation_id,
                    parent_message_id=parent_message_id,
                ):
                    if isinstance(event, TextChunk):
                        parts.append(event.text)
                    elif isinstance(event, MirroredToolResult):
                        parts.append(f"\n[{event.name}] {event.message}\n")
                    elif isinstance(event, GeneratedMedia):
                        label = "vídeo gerado" if event.media_type == "video" else "imagem gerada"
                        parts.append(f"\n![{label}]({event.virtual_path})\n")
                    elif isinstance(event, WarningMessage):
                        parts.append(f"\n[aviso] {event.message}\n")
                    elif isinstance(event, ChatFinished):
                        finished = event
            except MeliGPTError as exc:
                return JSONResponse(status_code=502, content=exc.to_dict())

            full_text = "".join(parts)
            if finished is not None:
                _remember_session(body.messages, finished)
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
                    # Extensão fora do padrão OpenAI (o OpenClaude e outros
                    # clientes ignoram campos desconhecidos): o conversationId/
                    # messageId REAIS do MeliGPT para este turno — útil pra
                    # testar/usar `meligpt fork` sem precisar abrir a UI web.
                    "meligpt_conversation_id": finished.conversation_id if finished else None,
                    "meligpt_message_id": finished.response_message_id if finished else None,
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
                    media_dir=body.media_dir,
                    conversation_id=conversation_id,
                    parent_message_id=parent_message_id,
                ):
                    if isinstance(event, TextChunk):
                        text = event.text
                    elif isinstance(event, MirroredToolResult):
                        text = f"\n[{event.name}] {event.message}\n"
                    elif isinstance(event, GeneratedMedia):
                        label = "vídeo gerado" if event.media_type == "video" else "imagem gerada"
                        text = f"\n![{label}]({event.virtual_path})\n"
                    elif isinstance(event, WarningMessage):
                        text = f"\n[aviso] {event.message}\n"
                    elif isinstance(event, ChatFinished):
                        _remember_session(body.messages, event)
                        yield {
                            "data": _sse_chunk(
                                completion_id,
                                body.model,
                                delta={},
                                finish_reason="stop",
                                extra={
                                    # Mesma extensão fora do padrão OpenAI da
                                    # resposta não-streaming — ver ali.
                                    "meligpt_conversation_id": event.conversation_id,
                                    "meligpt_message_id": event.response_message_id,
                                },
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
