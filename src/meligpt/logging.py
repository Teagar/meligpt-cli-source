"""Logging estruturado, colorido (mesmo estilo do uvicorn) e com
sanitização de segredos.

Nunca registra o conteúdo de ``Authorization`` ou ``Cookie`` — apenas indica
presença/tamanho, equivalente ao ``sed 's/^(authorization:).*/[OCULTO]/I'``
do script Bash original.
"""

from __future__ import annotations

import logging
import re
import sys
import uuid
from contextvars import ContextVar
from typing import Any

from uvicorn.logging import DefaultFormatter as _UvicornDefaultFormatter

_SENSITIVE_KEYS = {"authorization", "cookie", "access_token", "cookie_header"}
_BEARER_RE = re.compile(r"Bearer\s+\S+", re.IGNORECASE)

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def new_request_id() -> str:
    """Gera e associa um ID de correlação ao contexto de execução atual."""

    request_id = uuid.uuid4().hex[:12]
    _request_id_ctx.set(request_id)
    return request_id


def current_request_id() -> str:
    return _request_id_ctx.get()


def sanitize(value: Any) -> Any:
    """Remove segredos de dicts/strings antes de logar."""

    if isinstance(value, dict):
        return {
            k: ("[OCULTO]" if k.lower() in _SENSITIVE_KEYS else sanitize(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, str):
        return _BEARER_RE.sub("Bearer [OCULTO]", value)
    return value


class _ColorFormatter(_UvicornDefaultFormatter):
    """Mesmo estilo visual dos logs do próprio uvicorn (``INFO:     ...``,
    colorido por nível quando o terminal suporta) — em vez do antigo JSON
    lines, que era preciso mas ilegível de bater o olho no meio dos logs
    de acesso do servidor (que já usam exatamente esse formato).

    Os campos estruturados (``log_with_fields``) continuam saindo, como
    ``chave: valor`` no fim da linha (em vez de um blob JSON) — e ainda
    passam por :func:`sanitize` antes de aparecer. Campos cuja chave
    termina em ``_id`` (``conversation_id``, ``response_message_id``,
    etc.) saem sublinhados e sem ``=`` colado, pra ficar fácil de
    selecionar só o valor com duplo-clique/arrastar no terminal.
    """

    def __init__(self) -> None:
        super().__init__(fmt="%(levelprefix)s %(name)s - %(message)s")

    def _format_field(self, key: str, value: Any) -> str:
        if key.endswith("_id"):
            rendered = f"\033[4m{value}\033[0m" if self.use_colors else str(value)
            return f"{key}: {rendered}"
        return f"{key}={value}"

    def formatMessage(self, record: logging.LogRecord) -> str:
        line = super().formatMessage(record)

        request_id = current_request_id()
        if request_id != "-":
            line = f"{line} [req={request_id}]"

        extra = getattr(record, "extra_fields", None)
        if extra:
            sanitized = sanitize(extra)
            pairs = " ".join(self._format_field(key, value) for key, value in sanitized.items())
            line = f"{line} ({pairs})"

        return line


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("meligpt")
    root.setLevel(level.upper())
    root.handlers.clear()
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_ColorFormatter())
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"meligpt.{name}")


def log_with_fields(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    logger.log(level, message, extra={"extra_fields": fields})
