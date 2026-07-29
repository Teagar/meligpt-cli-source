"""Stub de ``write_todos``. Sem contraparte no Bash original (ver edit_file.py)."""

from __future__ import annotations

from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import ToolNotImplementedError


class WriteTodosStub:
    name = "write_todos"
    description = "[NÃO IMPLEMENTADO] Manteria uma lista estruturada de tarefas (pending/in_progress/completed)."

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        raise ToolNotImplementedError(
            "write_todos não possui implementação real: não existia no projeto Bash original."
        )
