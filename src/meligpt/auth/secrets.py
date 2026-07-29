"""Leitura/escrita de ``secrets.env``.

Equivalente a ``source "$SECRETS"`` em ``legacy/chat-api.sh``, mas sem
``source`` de shell: parseamos apenas as duas chaves esperadas
(``ACCESS_TOKEN``, ``COOKIE_HEADER``), no formato ``KEY=valor`` (com ou
sem aspas), gerado por :func:`meligpt.auth.har_importer.import_har`.
"""

from __future__ import annotations

import os
import re
import shlex
import tempfile
from dataclasses import dataclass
from pathlib import Path

from meligpt.exceptions import SecretsNotFoundError

_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)$")


@dataclass(frozen=True)
class Credentials:
    access_token: str
    cookie_header: str

    def authorization_header(self) -> str:
        if self.access_token.startswith("Bearer "):
            return self.access_token
        return f"Bearer {self.access_token}"


def load_credentials(secrets_path: Path) -> Credentials:
    if not secrets_path.is_file():
        raise SecretsNotFoundError(f"arquivo de credenciais não encontrado: {secrets_path}")

    values: dict[str, str] = {}
    with secrets_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            match = _LINE_RE.match(line.rstrip("\n"))
            if not match:
                continue
            key, raw_value = match.group(1), match.group(2)
            values[key] = _unquote(raw_value)

    access_token = values.get("ACCESS_TOKEN")
    cookie_header = values.get("COOKIE_HEADER")
    if not access_token:
        raise SecretsNotFoundError(f"ACCESS_TOKEN não definido em {secrets_path}")
    if not cookie_header:
        raise SecretsNotFoundError(f"COOKIE_HEADER não definido em {secrets_path}")

    return Credentials(access_token=access_token, cookie_header=cookie_header)


def save_credentials(secrets_path: Path, credentials: Credentials) -> None:
    """Grava credenciais com permissão 600, de forma atômica."""

    secrets_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    fd, tmp_path = tempfile.mkstemp(prefix=".secrets.env.", dir=str(secrets_path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"ACCESS_TOKEN={shlex.quote(credentials.access_token)}\n")
            handle.write(f"COOKIE_HEADER={shlex.quote(credentials.cookie_header)}\n")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, secrets_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    try:
        parts = shlex.split(value)
        return parts[0] if parts else value
    except ValueError:
        return value
