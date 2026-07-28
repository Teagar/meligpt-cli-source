"""Stub de ``glob``. Sem contraparte no Bash original (ver edit_file.py)."""

from __future__ import annotations

from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import ToolNotImplementedError


class GlobStub:
    name = "glob"
    description = "[NÃO IMPLEMENTADO] Buscaria arquivos por padrão glob (ex.: **/*.java)."

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        raise ToolNotImplementedError(
            "glob não possui implementação real: não existia no projeto Bash original."
        )
