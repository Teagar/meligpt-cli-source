"""Modelos Pydantic compartilhados entre camadas (CLI, API, ferramentas)."""

from __future__ import annotations

from pydantic import BaseModel


class ToolCallPayload(BaseModel):
    """Forma serializável de uma tool call, usada nos limites de módulo
    (ex.: logging, respostas de API) — o tipo de execução interno é
    :class:`meligpt.chat.events.ToolCallEvent`.
    """

    id: str = ""
    name: str
    arguments: dict = {}
