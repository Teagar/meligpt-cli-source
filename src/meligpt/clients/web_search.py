"""Cliente de busca web, usado pela ferramenta local ``WebSearch``.

Provedor padrão: Brave Search API (tem tier gratuito). Interface
deliberadamente pequena para permitir trocar de provedor sem tocar na
ferramenta (`tools/research/web_search.py`).
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from meligpt.config import Settings
from meligpt.exceptions import WebSearchError, WebSearchNotConfiguredError


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


async def search_web(
    query: str, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> list[SearchResult]:
    """Executa uma busca e retorna resultados estruturados.

    Levanta :class:`WebSearchNotConfiguredError` se nenhuma chave de API
    estiver configurada, e :class:`WebSearchError` para qualquer outra
    falha (HTTP inesperado, resposta malformada, timeout).
    """

    provider = settings.web_search_provider.lower()
    if provider == "brave":
        return await _search_brave(query, settings, transport=transport)
    raise WebSearchError(f"provedor de busca desconhecido: {settings.web_search_provider!r}")


async def _search_brave(
    query: str, settings: Settings, *, transport: httpx.AsyncBaseTransport | None
) -> list[SearchResult]:
    if not settings.brave_api_key:
        raise WebSearchNotConfiguredError(
            "MELIGPT_BRAVE_API_KEY não configurada — cadastre-se em "
            "https://brave.com/search/api/ (tem tier gratuito) e defina a "
            "variável de ambiente para habilitar WebSearch."
        )

    try:
        async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(15.0)) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": settings.web_search_max_results},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": settings.brave_api_key,
                },
            )
    except httpx.HTTPError as exc:
        raise WebSearchError(f"falha de transporte na busca web: {exc}") from exc

    if response.status_code != 200:
        raise WebSearchError(f"provedor de busca retornou HTTP {response.status_code}")

    try:
        data = response.json()
    except ValueError as exc:
        raise WebSearchError("resposta do provedor de busca não é JSON válido") from exc

    web_results = (data.get("web") or {}).get("results") or []
    results = [
        SearchResult(
            title=item.get("title", ""),
            url=item.get("url", ""),
            snippet=item.get("description", ""),
        )
        for item in web_results[: settings.web_search_max_results]
    ]
    return results
