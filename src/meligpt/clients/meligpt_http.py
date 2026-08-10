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


def _build_payload(
    prompt: str,
    message_id: str,
    model: str,
    *,
    browsing: bool = False,
    payload_endpoint: str = "openAI",
) -> dict[str, Any]:
    return {
        "text": prompt,
        "sender": "User",
        "isCreatedByUser": True,
        "parentMessageId": "00000000-0000-0000-0000-000000000000",
        "conversationId": None,
        "messageId": message_id,
        "error": False,
        "browsing": browsing,
        "tools": [],
        "parameters": {"timestamp": "non", "document": "simple-text"},
        "generation": "",
        "responseMessageId": None,
        "overrideParentMessageId": None,
        "endpoint": payload_endpoint,
        "model": model,
        "key": "newer",
        "isContinued": False,
    }


def _build_headers(settings: Settings, credentials: Credentials) -> dict[str, str]:
    return {
        "Authorization": credentials.authorization_header(),
        "Cookie": credentials.cookie_header,
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Accept-Language": settings.accept_language,
        "Origin": settings.base_url,
        "Referer": settings.resolved_referer(),
        "User-Agent": settings.user_agent,
    }


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
                        raise UpstreamError(f"resposta inesperada: Content-Type {content_type!r}")

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
