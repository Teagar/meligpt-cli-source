from __future__ import annotations

import pytest

from meligpt.clients.web_search import SearchResult
from meligpt.exceptions import ToolValidationError, WebSearchNotConfiguredError
from meligpt.tools.research.web_search import WebSearchTool


@pytest.mark.asyncio
async def test_web_search_missing_query_rejected(settings) -> None:
    with pytest.raises(ToolValidationError):
        await WebSearchTool().execute({}, settings)


@pytest.mark.asyncio
async def test_web_search_without_key_raises_not_configured(settings) -> None:
    settings.brave_api_key = None
    with pytest.raises(WebSearchNotConfiguredError):
        await WebSearchTool().execute({"query": "python"}, settings)


@pytest.mark.asyncio
async def test_web_search_success(settings, monkeypatch) -> None:
    async def fake_search(query, settings_arg, *, transport=None):
        assert query == "python asyncio"
        return [SearchResult(title="Asyncio", url="https://x", snippet="resumo")]

    import meligpt.tools.research.web_search as tool_module

    monkeypatch.setattr(tool_module, "search_web", fake_search)

    result = await WebSearchTool().execute({"query": "python asyncio"}, settings)
    assert result["success"] is True
    assert result["results"] == [{"title": "Asyncio", "url": "https://x", "snippet": "resumo"}]
