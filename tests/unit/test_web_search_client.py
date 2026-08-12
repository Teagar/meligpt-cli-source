from __future__ import annotations

import httpx
import pytest

from meligpt.clients.web_search import search_web
from meligpt.exceptions import WebSearchError, WebSearchNotConfiguredError


@pytest.mark.asyncio
async def test_search_without_api_key_raises_not_configured(settings) -> None:
    settings.brave_api_key = None
    with pytest.raises(WebSearchNotConfiguredError):
        await search_web("python asyncio", settings)


@pytest.mark.asyncio
async def test_search_success(settings) -> None:
    settings.brave_api_key = "fake-key"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "fake-key"
        assert request.url.params["q"] == "python asyncio"
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Asyncio docs",
                            "url": "https://docs.python.org/3/library/asyncio.html",
                            "description": "Biblioteca assíncrona.",
                        }
                    ]
                }
            },
        )

    results = await search_web("python asyncio", settings, transport=httpx.MockTransport(handler))
    assert len(results) == 1
    assert results[0].title == "Asyncio docs"
    assert results[0].url == "https://docs.python.org/3/library/asyncio.html"


@pytest.mark.asyncio
async def test_search_respects_max_results(settings) -> None:
    settings.brave_api_key = "fake-key"
    settings.web_search_max_results = 2

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {"title": f"r{i}", "url": f"https://x/{i}", "description": ""}
                        for i in range(5)
                    ]
                }
            },
        )

    results = await search_web("x", settings, transport=httpx.MockTransport(handler))
    assert len(results) == 2


@pytest.mark.asyncio
async def test_search_http_error_raises(settings) -> None:
    settings.brave_api_key = "fake-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid key"})

    with pytest.raises(WebSearchError):
        await search_web("x", settings, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_search_missing_web_results_key_returns_empty(settings) -> None:
    settings.brave_api_key = "fake-key"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    results = await search_web("x", settings, transport=httpx.MockTransport(handler))
    assert results == []


@pytest.mark.asyncio
async def test_unknown_provider_raises(settings) -> None:
    settings.web_search_provider = "nao-existe"
    with pytest.raises(WebSearchError):
        await search_web("x", settings)
