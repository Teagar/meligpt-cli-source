from __future__ import annotations

from meligpt.filesystem.exclusions import DEFAULT_EXCLUDED_DIRS


def test_includes_common_project_dirs() -> None:
    for name in (".git", "node_modules", "__pycache__", ".venv"):
        assert name in DEFAULT_EXCLUDED_DIRS


def test_includes_dangerous_system_dirs() -> None:
    """Relevante quando MELIGPT_FILES_DIR=/ — evita varredura recursiva
    catastrófica de pseudo-sistemas de arquivo do host.
    """

    for name in ("proc", "sys", "dev", "boot"):
        assert name in DEFAULT_EXCLUDED_DIRS
