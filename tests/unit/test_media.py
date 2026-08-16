from __future__ import annotations

import httpx
import pytest

from meligpt.exceptions import UpstreamError
from meligpt.media import download_media, extract_media_references

BASE_URL = "https://public-meligpt.adminml.com"


def test_extract_relative_media_path() -> None:
    text = "Aqui está: /api/media/69a6d3ab29b848ccb550efbf/image_d4edd54c.png"
    refs = extract_media_references(text, base_url=BASE_URL)
    assert len(refs) == 1
    assert refs[0].path == "/api/media/69a6d3ab29b848ccb550efbf/image_d4edd54c.png"
    assert refs[0].filename == "image_d4edd54c.png"


def test_extract_absolute_media_url_normalizes_to_relative_path() -> None:
    text = f"![img]({BASE_URL}/api/media/abc123/image_x.png)"
    refs = extract_media_references(text, base_url=BASE_URL)
    assert len(refs) == 1
    assert refs[0].path == "/api/media/abc123/image_x.png"


def test_extract_dedups_same_reference() -> None:
    text = f"/api/media/abc/img.png e de novo {BASE_URL}/api/media/abc/img.png"
    refs = extract_media_references(text, base_url=BASE_URL)
    assert len(refs) == 1


def test_extract_multiple_distinct_references_preserves_order() -> None:
    text = "primeiro /api/media/a/1.png depois /api/media/b/2.png"
    refs = extract_media_references(text, base_url=BASE_URL)
    assert [r.filename for r in refs] == ["1.png", "2.png"]


def test_extract_returns_empty_for_text_without_media() -> None:
    assert extract_media_references("nada aqui", base_url=BASE_URL) == []


def test_extract_returns_empty_for_empty_text() -> None:
    assert extract_media_references("", base_url=BASE_URL) == []


@pytest.mark.asyncio
async def test_download_media_direct_200(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/media/u1/img.png"
        assert "Authorization" in request.headers
        assert "Cookie" in request.headers
        return httpx.Response(200, content=b"PNGDATA")

    from meligpt.auth.secrets import Credentials

    creds = Credentials(access_token="tok", cookie_header="c=1")
    content = await download_media(
        settings, creds, "/api/media/u1/img.png", transport=httpx.MockTransport(handler)
    )
    assert content == b"PNGDATA"


@pytest.mark.asyncio
async def test_download_media_follows_redirect_without_forwarding_auth(settings) -> None:
    from meligpt.auth.secrets import Credentials

    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "public-meligpt.adminml.com":
            return httpx.Response(
                302, headers={"location": "https://bucket.s3.amazonaws.com/img.png?sig=abc"}
            )
        return httpx.Response(200, content=b"S3DATA")

    creds = Credentials(access_token="tok", cookie_header="c=1")
    content = await download_media(
        settings, creds, "/api/media/u1/img.png", transport=httpx.MockTransport(handler)
    )
    assert content == b"S3DATA"
    assert len(calls) == 2
    # segunda requisição (S3) não deve levar nossas credenciais
    assert "Authorization" not in calls[1].headers
    assert "Cookie" not in calls[1].headers


@pytest.mark.asyncio
async def test_download_media_raises_upstream_error_on_http_failure(settings) -> None:
    from meligpt.auth.secrets import Credentials

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    creds = Credentials(access_token="tok", cookie_header="c=1")
    with pytest.raises(UpstreamError):
        await download_media(
            settings, creds, "/api/media/u1/img.png", transport=httpx.MockTransport(handler)
        )


@pytest.mark.asyncio
async def test_download_media_raises_upstream_error_on_redirect_without_location(settings) -> None:
    from meligpt.auth.secrets import Credentials

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302)

    creds = Credentials(access_token="tok", cookie_header="c=1")
    with pytest.raises(UpstreamError):
        await download_media(
            settings, creds, "/api/media/u1/img.png", transport=httpx.MockTransport(handler)
        )
