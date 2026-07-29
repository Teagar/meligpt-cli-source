from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.auth.secrets import Credentials, save_credentials
from meligpt.auth.token_manager import TokenManager
from meligpt.exceptions import RecoveryFailedError, UpstreamHTTPError


@pytest.mark.asyncio
async def test_recover_non_interactive_fails_immediately(settings) -> None:
    manager = TokenManager(settings)
    error = UpstreamHTTPError("expirado", status_code=401)
    with pytest.raises(RecoveryFailedError):
        await manager.recover_from_401(error, interactive=False, prompt_for_har=None)


@pytest.mark.asyncio
async def test_recover_user_declines(settings) -> None:
    manager = TokenManager(settings)
    error = UpstreamHTTPError("expirado", status_code=401)

    async def decline() -> None:
        return None

    with pytest.raises(RecoveryFailedError):
        await manager.recover_from_401(error, interactive=True, prompt_for_har=decline)


@pytest.mark.asyncio
async def test_recover_succeeds_once_then_blocks_second_attempt(
    settings, tmp_path: Path, monkeypatch
) -> None:
    import meligpt.auth.token_manager as tm

    def fake_import_har(har_path, secrets_path, *, expected_endpoint):
        save_credentials(secrets_path, Credentials(access_token="novo", cookie_header="c=1"))
        return secrets_path

    monkeypatch.setattr(tm, "import_har", fake_import_har)

    manager = TokenManager(settings)
    error = UpstreamHTTPError("expirado", status_code=401)

    async def accept() -> Path:
        return tmp_path / "fake.har"

    creds = await manager.recover_from_401(error, interactive=True, prompt_for_har=accept)
    assert creds.access_token == "novo"

    # Segunda tentativa na mesma instância deve ser bloqueada (sem loop infinito).
    with pytest.raises(RecoveryFailedError):
        await manager.recover_from_401(error, interactive=True, prompt_for_har=accept)
