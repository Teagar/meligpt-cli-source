"""Cliente HTTP/SSE assíncrono para ``POST /api/ask/openAI``.

Equivalente à seção de ``curl``/leitura de stream de ``legacy/chat-api.sh``,
preservando: headers, timeouts, formato do payload, detecção de
Content-Type, e o particionamento de linhas ``data: ...`` até ``[DONE]``.
Não bloqueia o event loop (I/O via ``httpx`` assíncrono) e nunca loga
``Authorization``/``Cookie`` (ver :mod:`meligpt.logging`).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Any

import httpx

from meligpt.auth.secrets import Credentials
from meligpt.catalog import ModelInfo
from meligpt.config import Settings
from meligpt.exceptions import (
    UpstreamError,
    UpstreamForbiddenError,
    UpstreamHTTPError,
    UpstreamTimeoutError,
)
from meligpt.logging import get_logger, log_with_fields

_logger = get_logger("clients.meligpt_http")

_ROOT_PARENT_MESSAGE_ID = "00000000-0000-0000-0000-000000000000"


def _build_payload(
    prompt: str,
    message_id: str,
    model: str,
    *,
    browsing: bool = False,
    payload_endpoint: str = "openAI",
    conversation_id: str | None = None,
    parent_message_id: str | None = None,
) -> dict[str, Any]:
    """Monta o payload de ``POST /api/ask/{endpoint}``.

    ``conversation_id``/``parent_message_id``, quando informados,
    continuam uma conversa MeliGPT já existente em vez de criar uma
    nova a cada chamada — ver HAR real (``forks.har``, turno 2):
    ``parentMessageId`` E ``responseMessageId`` do payload são ambos
    preenchidos com o ``messageId`` da resposta do turno anterior. Sem
    eles (default), mantém o comportamento antigo: sempre uma conversa
    nova (``conversationId: null``, ``parentMessageId`` raiz).
    """

    return {
        "text": prompt,
        "sender": "User",
        "isCreatedByUser": True,
        "parentMessageId": parent_message_id or _ROOT_PARENT_MESSAGE_ID,
        "conversationId": conversation_id,
        "messageId": message_id,
        "error": False,
        "browsing": browsing,
        "tools": [],
        "parameters": {"timestamp": "non", "document": "simple-text"},
        "generation": "",
        "responseMessageId": parent_message_id,
        "overrideParentMessageId": None,
        "endpoint": payload_endpoint,
        "model": model,
        # Confirmado por HAR real (requisição de vídeo, 2026-08-10):
        # sempre presente no payload, mesmo com conteúdo vazio. Nossa
        # implementação nunca mandava isso antes — pode ser exigido pelo
        # backend para alguns modelos (ex.: geração de vídeo) mesmo que
        # pareça inofensivo para os demais.
        "examples": [{"input": {"content": ""}, "output": {"content": ""}}],
        "key": "newer",
        "isContinued": False,
    }


def _build_headers(
    settings: Settings, credentials: Credentials, *, accept: str = "text/event-stream"
) -> dict[str, str]:
    return {
        "Authorization": credentials.authorization_header(),
        "Cookie": credentials.cookie_header,
        "Accept": accept,
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Accept-Language": settings.accept_language,
        "Origin": settings.base_url,
        "Referer": settings.resolved_referer(),
        "User-Agent": settings.user_agent,
    }


class ForkOption(StrEnum):
    """As três opções de ``POST /api/convos/fork`` (confirmadas por HAR
    real, ``forks.har``, 2026-08-13) — mapeadas 1:1 nos rótulos exibidos
    na UI do MeliGPT/LibreChat:

    - ``VISIBLE_ONLY`` ("Apenas mensagens visíveis"): bifurca só o
      caminho direto até a mensagem alvo — sem nenhuma ramificação.
    - ``INCLUDE_RELATED_BRANCHES`` ("Incluir ramificações relacionadas"):
      o caminho direto MAIS as ramificações que tocam esse caminho.
    - ``INCLUDE_ALL`` ("Incluir todos para/de aqui" — padrão do
      MeliGPT/LibreChat): TODAS as mensagens até a mensagem alvo,
      incluindo vizinhos — estejam ou não visíveis, no mesmo caminho ou
      não. Mandada como string vazia no payload (visto no HAR).
    """

    VISIBLE_ONLY = "directPath"
    INCLUDE_RELATED_BRANCHES = "includeBranches"
    INCLUDE_ALL = ""


class MeliGPTClient:
    """Cliente de streaming. Uma instância por requisição de chat."""

    def __init__(
        self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._timeout = httpx.Timeout(
            connect=settings.connect_timeout_seconds,
            read=settings.read_timeout_seconds,
            write=settings.write_timeout_seconds,
            pool=settings.pool_timeout_seconds,
        )

    async def stream_chat(
        self,
        *,
        prompt: str,
        message_id: str,
        credentials: Credentials,
        model_info: ModelInfo | None = None,
        conversation_id: str | None = None,
        parent_message_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Envia a mensagem e produz eventos SSE já decodificados (JSON).

        ``model_info``, quando informado (resolvido via
        :func:`meligpt.catalog.resolve_model`), sobrescreve a rota HTTP
        (``model_info.route``), o modelo (``model_info.id``) e o campo
        ``endpoint`` do payload (``model_info.payload_endpoint``) — que
        pode ser diferente da rota, ex.: Claude usa a rota
        ``/api/ask/generic`` mas manda ``"endpoint": "bedrock"``. Sem
        ``model_info``, preserva o comportamento padrão baseado em
        ``Settings`` (``resolved_endpoint()`` / ``model`` / ``"openAI"``).

        ``conversation_id``/``parent_message_id``, quando informados,
        continuam uma conversa MeliGPT existente (ver
        :func:`_build_payload`) — dando memória real de conversa sem
        precisar reenviar a transcrição inteira a cada turno.

        Levanta:
        - :class:`UpstreamHTTPError` (com ``status_code=401``) em token
          expirado — a recuperação/retry fica a cargo da camada de
          serviço (:mod:`meligpt.chat.service`), que conhece a política
          de "no máximo uma tentativa".
        - :class:`UpstreamForbiddenError` em 403.
        - :class:`UpstreamTimeoutError` em timeout de conexão/leitura.
        - :class:`UpstreamError` para Content-Type inesperado ou falha de
          transporte.
        """

        endpoint = (
            f"{self._settings.base_url}{model_info.route}"
            if model_info
            else self._settings.resolved_endpoint()
        )
        model = model_info.id if model_info else self._settings.model
        payload_endpoint = model_info.payload_endpoint if model_info else "openAI"
        headers = _build_headers(self._settings, credentials)
        payload = _build_payload(
            prompt,
            message_id,
            model,
            browsing=self._settings.enable_browsing,
            payload_endpoint=payload_endpoint,
            conversation_id=conversation_id,
            parent_message_id=parent_message_id,
        )

        try:
            async with httpx.AsyncClient(
                http2=self._transport is None,
                timeout=self._timeout,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                async with client.stream(
                    "POST", endpoint, json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        body = (await response.aread())[:4000]
                        log_with_fields(
                            _logger,
                            30,
                            "API upstream retornou status inesperado",
                            status_code=response.status_code,
                            content_type=response.headers.get("content-type"),
                        )
                        if response.status_code == 401:
                            raise UpstreamHTTPError(
                                "o access token ou a sessão expirou (401)",
                                status_code=401,
                            )
                        if response.status_code == 403:
                            raise UpstreamForbiddenError(
                                "requisição recusada (403) — verifique sessão, "
                                "conta, VPN e política do serviço",
                                status_code=403,
                            )
                        raise UpstreamHTTPError(
                            f"a API retornou HTTP {response.status_code}: {body[:500]!r}",
                            status_code=response.status_code,
                        )

                    content_type = response.headers.get("content-type", "")
                    if "text/event-stream" not in content_type:
                        body_preview = (await response.aread())[:2000]
                        log_with_fields(
                            _logger,
                            30,
                            "resposta 200 sem Content-Type de SSE — corpo abaixo",
                            content_type=content_type,
                            body_preview=body_preview.decode("utf-8", errors="replace"),
                        )
                        raise UpstreamError(
                            f"resposta inesperada: Content-Type {content_type!r} "
                            f"(corpo: {body_preview[:300]!r})"
                        )

                    async for line in response.aiter_lines():
                        line = line.rstrip("\r")
                        if not line.startswith("data:"):
                            continue
                        data = line[len("data:") :].strip()
                        if not data:
                            continue
                        if data == "[DONE]":
                            return
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        yield parsed
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError(f"timeout ao comunicar com a API: {exc}") from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(f"falha de transporte: {exc}") from exc

    async def fork_conversation(
        self,
        *,
        conversation_id: str,
        message_id: str,
        credentials: Credentials,
        option: ForkOption | str = ForkOption.INCLUDE_ALL,
        split_at_target: bool = False,
        latest_message_id: str | None = None,
    ) -> dict[str, Any]:
        """``POST /api/convos/fork`` — cria uma conversa nova a partir de
        uma mensagem existente, replicando (total ou parcialmente,
        conforme ``option``, ver :class:`ForkOption`) a árvore de
        mensagens original.

        Payload e semântica confirmados ponta a ponta por HAR real
        (``forks.har``, 2026-08-13): resposta traz a nova
        ``conversation`` (com seu próprio ``conversationId``) e a lista
        de ``messages`` copiadas para ela.

        ``latest_message_id``, quando omitido, usa ``message_id`` (visto
        assim em todo o HAR — os dois sempre coincidiam na prática).
        """

        endpoint = f"{self._settings.base_url}/api/convos/fork"
        headers = _build_headers(self._settings, credentials, accept="application/json")
        payload = {
            "messageId": message_id,
            "conversationId": conversation_id,
            "option": option.value if isinstance(option, ForkOption) else option,
            "splitAtTarget": split_at_target,
            "latestMessageId": latest_message_id or message_id,
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError(f"timeout ao comunicar com a API: {exc}") from exc
        except httpx.HTTPError as exc:
            raise UpstreamError(f"falha de transporte: {exc}") from exc

        if response.status_code != 200:
            log_with_fields(
                _logger,
                30,
                "API upstream retornou status inesperado ao bifurcar conversa",
                status_code=response.status_code,
                content_type=response.headers.get("content-type"),
            )
            if response.status_code == 401:
                raise UpstreamHTTPError("o access token ou a sessão expirou (401)", status_code=401)
            if response.status_code == 403:
                raise UpstreamForbiddenError(
                    "requisição recusada (403) — verifique sessão, conta, VPN e "
                    "política do serviço",
                    status_code=403,
                )
            body = response.text[:500]
            raise UpstreamHTTPError(
                f"a API retornou HTTP {response.status_code}: {body!r}",
                status_code=response.status_code,
            )

        try:
            return response.json()
        except ValueError as exc:
            raise UpstreamError(f"resposta inválida ao bifurcar conversa: {exc}") from exc
