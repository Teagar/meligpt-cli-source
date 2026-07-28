"""Importação de credenciais a partir de um arquivo HAR.

Equivalente a ``legacy/importar-har.sh``: procura, no HAR, a última
requisição ``POST`` bem-sucedida (status 200) para o endpoint configurado
e extrai os headers ``Authorization``/``Cookie``.

O HAR pode conter senhas, tokens, cookies e conteúdo de conversas — nunca é
logado, e o chamador é responsável por removê-lo com segurança depois de
confirmado o funcionamento (mesma orientação do script original).
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from meligpt.auth.secrets import Credentials, save_credentials
from meligpt.exceptions import HarImportError


def _strip_query(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _extract_credentials(har_data: dict, expected_url: str) -> Credentials:
    try:
        entries = har_data["log"]["entries"]
    except (KeyError, TypeError) as exc:
        raise HarImportError("o arquivo informado não parece ser um HAR válido.") from exc
    if not isinstance(entries, list):
        raise HarImportError("o arquivo informado não parece ser um HAR válido.")

    best: Credentials | None = None

    for entry in entries:
        request = entry.get("request", {})
        response = entry.get("response", {})
        if request.get("method") != "POST":
            continue
        if _strip_query(request.get("url", "")) != expected_url:
            continue
        if response.get("status") != 200:
            continue

        headers = request.get("headers", [])
        authorization = _last_header(headers, "authorization")
        cookie = _last_header(headers, "cookie")
        if authorization and cookie:
            best = Credentials(access_token=authorization, cookie_header=cookie)

    if best is None:
        raise HarImportError("não encontrei uma requisição válida com Authorization e Cookie.")
    return best


def _last_header(headers: list[dict], name: str) -> str | None:
    value: str | None = None
    for header in headers:
        if str(header.get("name", "")).lower() == name:
            value = header.get("value")
    return value


def import_har(har_path: Path, secrets_path: Path, *, expected_endpoint: str) -> Path:
    """Importa credenciais do HAR e as grava em ``secrets_path``.

    Retorna o caminho gravado. Levanta :class:`HarImportError` para HAR
    inválido ou sem requisição correspondente.
    """

    if not har_path.is_file():
        raise HarImportError(f"arquivo HAR não encontrado: {har_path}")

    try:
        with har_path.open("r", encoding="utf-8") as handle:
            har_data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise HarImportError(f"não foi possível ler o HAR: {exc}") from exc

    credentials = _extract_credentials(har_data, _strip_query(expected_endpoint))
    save_credentials(secrets_path, credentials)
    return secrets_path
