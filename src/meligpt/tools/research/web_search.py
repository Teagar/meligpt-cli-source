"""Ferramenta ``WebSearch``.

Delega para :mod:`meligpt.clients.web_search`. Injetável/simulável em
testes via monkeypatch do cliente HTTP (ver ``tests/unit/test_web_search.py``).
"""

from __future__ import annotations

from typing import Any

from meligpt.clients.web_search import search_web
from meligpt.config import Settings
from meligpt.exceptions import ToolValidationError


class WebSearchTool:
    name = "WebSearch"
    description = (
        "Pesquisa a web e retorna uma lista de resultados (título, URL, "
        "resumo). Requer MELIGPT_BRAVE_API_KEY configurada no servidor."
    )

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ToolValidationError("query inválida")

        results = await search_web(query, settings)

        return {
            "success": True,
            "query": query,
            "results": [{"title": r.title, "url": r.url, "snippet": r.snippet} for r in results],
        }
