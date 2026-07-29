from __future__ import annotations

import json
from pathlib import Path

import pytest

from meligpt.auth.har_importer import import_har
from meligpt.auth.secrets import Credentials, load_credentials, save_credentials
from meligpt.exceptions import HarImportError, SecretsNotFoundError


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    secrets_path = tmp_path / "config" / "secrets.env"
    creds = Credentials(access_token="Bearer abc123", cookie_header="session=xyz; other=1")
    save_credentials(secrets_path, creds)

    loaded = load_credentials(secrets_path)
    assert loaded.access_token == "Bearer abc123"
    assert loaded.cookie_header == "session=xyz; other=1"


def test_saved_file_has_restrictive_permissions(tmp_path: Path) -> None:
    secrets_path = tmp_path / "config" / "secrets.env"
    save_credentials(secrets_path, Credentials(access_token="a", cookie_header="b"))
    mode = secrets_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(SecretsNotFoundError):
        load_credentials(tmp_path / "nope.env")


def test_load_missing_key_raises(tmp_path: Path) -> None:
    secrets_path = tmp_path / "secrets.env"
    secrets_path.write_text("ACCESS_TOKEN=abc\n")
    with pytest.raises(SecretsNotFoundError):
        load_credentials(secrets_path)


def _har_with_entry(url: str, status: int, auth: str | None, cookie: str | None) -> dict:
    headers = []
    if auth is not None:
        headers.append({"name": "authorization", "value": auth})
    if cookie is not None:
        headers.append({"name": "cookie", "value": cookie})
    return {
        "log": {
            "entries": [
                {
                    "request": {"method": "POST", "url": url, "headers": headers},
                    "response": {"status": status},
                }
            ]
        }
    }


def test_import_har_success(tmp_path: Path) -> None:
    endpoint = "https://public-meligpt.adminml.com/api/ask/openAI"
    har = _har_with_entry(endpoint + "?x=1", 200, "Bearer tok", "sess=1")
    har_path = tmp_path / "session.har"
    har_path.write_text(json.dumps(har))

    secrets_path = tmp_path / "secrets.env"
    import_har(har_path, secrets_path, expected_endpoint=endpoint)

    creds = load_credentials(secrets_path)
    assert creds.access_token == "Bearer tok"
    assert creds.cookie_header == "sess=1"


def test_import_har_ignores_non_matching_status(tmp_path: Path) -> None:
    endpoint = "https://public-meligpt.adminml.com/api/ask/openAI"
    har = _har_with_entry(endpoint, 401, "Bearer bad", "sess=bad")
    har_path = tmp_path / "session.har"
    har_path.write_text(json.dumps(har))

    with pytest.raises(HarImportError):
        import_har(har_path, tmp_path / "secrets.env", expected_endpoint=endpoint)


def test_import_har_uses_last_matching_entry(tmp_path: Path) -> None:
    endpoint = "https://public-meligpt.adminml.com/api/ask/openAI"
    har = {
        "log": {
            "entries": [
                _har_with_entry(endpoint, 200, "Bearer old", "sess=old")["log"]["entries"][0],
                _har_with_entry(endpoint, 200, "Bearer new", "sess=new")["log"]["entries"][0],
            ]
        }
    }
    har_path = tmp_path / "session.har"
    har_path.write_text(json.dumps(har))

    secrets_path = tmp_path / "secrets.env"
    import_har(har_path, secrets_path, expected_endpoint=endpoint)
    creds = load_credentials(secrets_path)
    assert creds.access_token == "Bearer new"


def test_import_har_invalid_json(tmp_path: Path) -> None:
    har_path = tmp_path / "broken.har"
    har_path.write_text("{ isso nao é json")
    with pytest.raises(HarImportError):
        import_har(har_path, tmp_path / "secrets.env", expected_endpoint="https://x/y")


def test_import_har_missing_file(tmp_path: Path) -> None:
    with pytest.raises(HarImportError):
        import_har(tmp_path / "nope.har", tmp_path / "secrets.env", expected_endpoint="https://x/y")
