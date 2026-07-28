"""Stub de ``edit_file``.

O projeto Bash original (``legacy/local-tools.sh``) NÃO implementa
substituição de texto em arquivo — apenas ``ls``, ``read_file`` e
``write_file``. Esta classe existe para que o catálogo de ferramentas
tenha a interface completa pedida na Fase B, mas responde
``tool_not_implemented`` de forma explícita em vez de fingir suporte.

Uma implementação real (ver docstring de módulo em ``docs/tools.md``)
deveria: reutilizar ``filesystem.security`` para resolução/segurança,
suportar substituição única e "todas as ocorrências", detectar
ambiguidade e reaproveitar a escrita atômica de ``write_file.py``.
"""

from __future__ import annotations

from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import ToolNotImplementedError


class EditFileStub:
    name = "edit_file"
    description = (
        "[NÃO IMPLEMENTADO] Substituiria texto exato em um arquivo local. "
        "Sem contraparte no projeto Bash original."
    )

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        raise ToolNotImplementedError(
            "edit_file não possui implementação real: não existia no projeto "
            "Bash original e nenhum provedor foi definido para esta migração."
        )
