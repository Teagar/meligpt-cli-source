"""Stub de ``parallel``. Sem contraparte no Bash original (ver edit_file.py).

O executor local (``legacy/local-tools.sh``) processa uma única chamada de
ferramenta por invocação; não existe orquestração paralela no projeto
original.
"""

from __future__ import annotations

from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import ToolNotImplementedError


class ParallelStub:
    name = "parallel"
    description = (
        "[NÃO IMPLEMENTADO] Executaria ferramentas independentes concorrentemente via asyncio."
    )

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        raise ToolNotImplementedError(
            "parallel não possui implementação real: não existia no projeto Bash original."
        )
