"""Renovação automática de token.

Equivalente ao que o próprio front-end do MeliGPT faz silenciosamente em
segundo plano (visível no HAR como ``POST /api/auth/refresh``): usa o
``refreshToken`` já presente no ``Cookie`` para obter um novo
``access_token`` (JWT curto, ~15 min de vida) sem precisar reimportar HAR.

Este módulo nunca loga o conteúdo de tokens/cookies — apenas sucesso,
falha, e o instante do próximo refresh agendado.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import time

import httpx

from meligpt.auth.secrets import Credentials, load_credentials, save_credentials
from meligpt.config import Settings
from meligpt.exceptions import SecretsNotFoundError, TokenRefreshError
from meligpt.logging import get_logger, log_with_fields

_logger = get_logger("auth.refresher")


def _decode_jwt_exp(access_token: str) -> int | None:
    """Extrai o claim ``exp`` de um JWT sem verificar assinatura.

    Usado apenas para decidir *quando* agendar o próximo refresh — nunca
    para autorizar nada. Retorna ``None`` se o token não puder ser
    decodificado (formato inesperado).
    """

    token = access_token[len("Bearer ") :] if access_token.startswith("Bearer ") else access_token
    try:
        payload_b64 = token.split(".")[1]
        padding = "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64 + padding))
        exp = payload.get("exp")
        return int(exp) if exp is not None else None
    except (IndexError, ValueError, binascii.Error, json.JSONDecodeError):
        return None


def _parse_cookie_header(header: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for part in header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        pairs[key.strip()] = value.strip()
    return pairs


def _merge_cookie_header(original: str, response_cookies: httpx.Cookies) -> str:
    """Atualiza apenas os cookies que o servidor efetivamente reenviou
    (ex.: ``refreshToken``), preservando os demais (``lang``,
    ``tigerToken``) exatamente como estavam.
    """

    pairs = _parse_cookie_header(original)
    for name in response_cookies.keys():
        value = response_cookies.get(name)
        if value:
            pairs[name] = value
    return "; ".join(f"{k}={v}" for k, v in pairs.items())


async def refresh_access_token(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> Credentials:
    """Executa um refresh e persiste as novas credenciais em ``secrets.env``.

    Levanta :class:`TokenRefreshError` (subclasse de ``AuthenticationError``)
    em qualquer falha — HTTP inesperado, corpo sem campo ``token``, etc.
    """

    secrets_path = settings.resolved_secrets_path()
    credentials = load_credentials(secrets_path)

    headers = {
        "Authorization": credentials.authorization_header(),
        "Cookie": credentials.cookie_header,
        "Accept": "application/json, text/plain, */*",
        "Origin": settings.base_url,
        "User-Agent": settings.user_agent,
    }

    try:
        async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(20.0)) as client:
            response = await client.post(
                settings.resolved_refresh_endpoint(), headers=headers, content=b""
            )
    except httpx.HTTPError as exc:
        raise TokenRefreshError(f"falha de transporte ao renovar token: {exc}") from exc

    if response.status_code != 200:
        raise TokenRefreshError(
            f"refresh retornou HTTP {response.status_code} (o refreshToken pode ter expirado)"
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise TokenRefreshError("resposta de refresh não é JSON válido") from exc

    new_token = data.get("token")
    if not new_token:
        raise TokenRefreshError("resposta de refresh sem campo 'token'")

    new_credentials = Credentials(
        access_token=f"Bearer {new_token}",
        cookie_header=_merge_cookie_header(credentials.cookie_header, response.cookies),
    )
    save_credentials(secrets_path, new_credentials)
    return new_credentials


async def run_auto_refresh_loop(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    """Loop infinito (rode como ``asyncio.Task``) que mantém o token vivo.

    Agenda o próximo refresh com base no claim ``exp`` do JWT atual, com
    uma margem de segurança (`token_refresh_margin_seconds`). Cancele a
    task (`task.cancel()`) para encerrar de forma limpa — o
    ``asyncio.CancelledError`` propaga normalmente e não é engolido pelo
    ``except Exception`` abaixo.
    """

    while True:
        try:
            credentials = load_credentials(settings.resolved_secrets_path())
        except SecretsNotFoundError:
            log_with_fields(_logger, 20, "secrets.env ainda não existe, aguardando import-har")
            await asyncio.sleep(settings.token_refresh_interval_seconds)
            continue

        exp = _decode_jwt_exp(credentials.access_token)
        if exp is not None:
            delay = max(exp - time.time() - settings.token_refresh_margin_seconds, 5.0)
        else:
            delay = settings.token_refresh_interval_seconds

        log_with_fields(_logger, 10, "próximo refresh agendado", seconds=round(delay, 1))
        await asyncio.sleep(delay)

        try:
            await refresh_access_token(settings, transport=transport)
            log_with_fields(_logger, 20, "token renovado automaticamente")
        except TokenRefreshError as exc:
            log_with_fields(_logger, 30, "falha ao renovar token automaticamente", code=exc.code)
            await asyncio.sleep(settings.token_refresh_retry_seconds)
        except Exception as exc:  # noqa: BLE001 - nunca deve derrubar o loop
            log_with_fields(_logger, 40, "erro inesperado no refresh automático", error=str(exc))
            await asyncio.sleep(settings.token_refresh_retry_seconds)
