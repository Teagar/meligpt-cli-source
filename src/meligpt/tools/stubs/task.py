"""Stub de ``task``. Sem contraparte no Bash original (ver edit_file.py)."""

from __future__ import annotations

from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import ToolNotImplementedError


class TaskStub:
    name = "task"
    description = "[NÃO IMPLEMENTADO] Delegaria uma tarefa isolada a um subagente."

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        raise ToolNotImplementedError(
            "task não possui implementação real: não existia no projeto "
            "Bash original (não há conceito de subagente)."
        )
