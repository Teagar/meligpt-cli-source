"""Stub de ``grep``. Sem contraparte no Bash original (ver edit_file.py)."""

from __future__ import annotations

from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import ToolNotImplementedError


class GrepStub:
    name = "grep"
    description = "[NÃO IMPLEMENTADO] Pesquisaria texto/regex dentro dos arquivos autorizados."

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        raise ToolNotImplementedError(
            "grep não possui implementação real: não existia no projeto Bash original."
        )
