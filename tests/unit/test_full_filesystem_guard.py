from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.config import Settings
from meligpt.exceptions import UnsafeConfigurationError


def test_normal_files_dir_does_not_require_confirmation(tmp_path: Path) -> None:
    settings = Settings(files_dir=tmp_path / "files")
    assert settings.resolved_files_dir() == tmp_path / "files"


def test_root_files_dir_without_confirmation_raises() -> None:
    settings = Settings(files_dir=Path("/"))
    with pytest.raises(UnsafeConfigurationError):
        settings.resolved_files_dir()


def test_root_files_dir_with_confirmation_succeeds() -> None:
    settings = Settings(files_dir=Path("/"), allow_full_filesystem_access=True)
    assert settings.resolved_files_dir() == Path("/")


def test_default_files_dir_never_resolves_to_root() -> None:
    settings = Settings()
    resolved = settings.resolved_files_dir()
    assert str(resolved) != "/"


def test_create_app_fails_fast_on_unsafe_files_dir() -> None:
    from meligpt.api.app import create_app

    settings = Settings(files_dir=Path("/"))
    with pytest.raises(UnsafeConfigurationError):
        create_app(settings)


def test_create_app_succeeds_with_confirmation(tmp_path: Path) -> None:
    from meligpt.api.app import create_app

    settings = Settings(
        config_dir=tmp_path / "config",
        files_dir=tmp_path / "files",
        secrets_path=tmp_path / "config" / "secrets.env",
        auto_refresh_enabled=False,
    )
    app = create_app(settings)
    assert app is not None


def test_media_dir_independent_of_root_files_dir(tmp_path: Path) -> None:
    """Regressão: com `files_dir=/` (modo acesso total), a pasta de
    imagens geradas NÃO pode ser resolvida sob a raiz real do
    filesystem (exigiria permissão de root para criar
    `/generated-images`) — confirmado via teste end-to-end real em
    2026-08-10 (`falha ao salvar imagem gerada: não foi possível criar
    diretório intermediário: generated-images/...`). `resolved_media_dir()`
    deve ficar sob `config_dir`, nunca sob `files_dir`.
    """

    settings = Settings(
        config_dir=tmp_path / "config",
        files_dir=Path("/"),
        allow_full_filesystem_access=True,
    )
    media_dir = settings.resolved_media_dir()
    assert media_dir == tmp_path / "config" / "generated-images"
    assert str(media_dir) != "/generated-images"


def test_media_dir_explicit_override(tmp_path: Path) -> None:
    custom = tmp_path / "custom-media"
    settings = Settings(config_dir=tmp_path / "config", media_dir=custom)
    assert settings.resolved_media_dir() == custom
