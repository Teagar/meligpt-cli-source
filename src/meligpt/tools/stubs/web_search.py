"""Stub de ``WebSearch``. Sem contraparte no Bash original (ver edit_file.py)."""

from __future__ import annotations

from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import ToolNotImplementedError


class WebSearchStub:
    name = "WebSearch"
    description = "[NÃO IMPLEMENTADO] Pesquisaria a web via provedor externo configurável."

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        raise ToolNotImplementedError(
            "WebSearch não possui implementação real: o projeto Bash "
            "original não integra nenhum provedor de busca. Defina "
            "MELIGPT_WEB_SEARCH_PROVIDER e implemente "
            "clients/web_search.py para habilitar esta ferramenta."
        )
