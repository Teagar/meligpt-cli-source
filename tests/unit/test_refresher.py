from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx
import pytest

from meligpt.auth.refresher import _decode_jwt_exp, refresh_access_token, run_auto_refresh_loop
from meligpt.auth.secrets import Credentials, load_credentials, save_credentials
from meligpt.exceptions import TokenRefreshError


def _fake_jwt(exp: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def test_decode_jwt_exp_extracts_claim() -> None:
    token = "Bearer " + _fake_jwt(1234567890)
    assert _decode_jwt_exp(token) == 1234567890


def test_decode_jwt_exp_returns_none_for_garbage() -> None:
    assert _decode_jwt_exp("Bearer not-a-jwt") is None


@pytest.mark.asyncio
async def test_refresh_access_token_success(settings) -> None:
    original = Credentials(
        access_token="Bearer " + _fake_jwt(int(time.time())),
        cookie_header="lang=en-US; refreshToken=old; tigerToken=Bearer%20abc",
    )
    save_credentials(settings.resolved_secrets_path(), original)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/auth/refresh"
        return httpx.Response(
            200,
            headers={
                "content-type": "application/json",
                "set-cookie": "refreshToken=new; Path=/; HttpOnly; Secure",
            },
            json={"token": "novo.jwt.token", "user": {"_id": "x"}},
        )

    new_creds = await refresh_access_token(settings, transport=httpx.MockTransport(handler))

    assert new_creds.access_token == "Bearer novo.jwt.token"
    assert "refreshToken=new" in new_creds.cookie_header
    assert "tigerToken=Bearer%20abc" in new_creds.cookie_header
    assert "lang=en-US" in new_creds.cookie_header

    persisted = load_credentials(settings.resolved_secrets_path())
    assert persisted.access_token == "Bearer novo.jwt.token"


@pytest.mark.asyncio
async def test_refresh_access_token_expired_refresh_token(settings) -> None:
    save_credentials(
        settings.resolved_secrets_path(),
        Credentials(access_token="Bearer " + _fake_jwt(0), cookie_header="refreshToken=expired"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, headers={"content-type": "text/plain"}, content=b"Unauthorized")

    with pytest.raises(TokenRefreshError):
        await refresh_access_token(settings, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_refresh_access_token_missing_token_field(settings) -> None:
    save_credentials(
        settings.resolved_secrets_path(),
        Credentials(access_token="Bearer " + _fake_jwt(0), cookie_header="refreshToken=x"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/json"}, json={})

    with pytest.raises(TokenRefreshError):
        await refresh_access_token(settings, transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_auto_refresh_loop_reschedules_based_on_exp(settings, monkeypatch) -> None:
    """O loop deve calcular o delay a partir do exp do JWT (com margem) e
    chamar refresh_access_token nesse instante — sem dormir o intervalo
    fallback inteiro.
    """

    save_credentials(
        settings.resolved_secrets_path(),
        Credentials(
            access_token="Bearer " + _fake_jwt(int(time.time()) + 130),
            cookie_header="refreshToken=x",
        ),
    )
    settings.token_refresh_margin_seconds = 120.0

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError()

    import meligpt.auth.refresher as refresher_module

    monkeypatch.setattr(refresher_module.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await run_auto_refresh_loop(settings)

    assert len(sleep_calls) == 1
    assert 5.0 <= sleep_calls[0] <= 15.0
