from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.config import Settings


@pytest.fixture
def files_root(tmp_path: Path) -> Path:
    root = tmp_path / "files"
    root.mkdir()
    return root


@pytest.fixture
def settings(tmp_path: Path, files_root: Path) -> Settings:
    return Settings(
        config_dir=tmp_path / "config",
        files_dir=files_root,
        secrets_path=tmp_path / "config" / "secrets.env",
        max_file_size=1024,
    )
