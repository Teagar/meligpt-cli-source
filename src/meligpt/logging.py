"""Logging estruturado (JSON lines) com sanitização de segredos.

Nunca registra o conteúdo de ``Authorization`` ou ``Cookie`` — apenas indica
presença/tamanho, equivalente ao ``sed 's/^(authorization:).*/[OCULTO]/I'``
do script Bash original.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from typing import Any

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


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": current_request_id(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload["fields"] = sanitize(extra)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger("meligpt")
    root.setLevel(level.upper())
    root.handlers.clear()
    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root.addHandler(handler)
    root.propagate = False


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"meligpt.{name}")


def log_with_fields(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    logger.log(level, message, extra={"extra_fields": fields})
