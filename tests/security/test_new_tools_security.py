from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.exceptions import PathTraversalError, SymlinkNotAllowedError
from meligpt.tools.files.edit_file import EditFileTool
from meligpt.tools.files.glob import GlobTool
from meligpt.tools.files.grep import GrepTool


@pytest.mark.asyncio
async def test_edit_file_blocks_traversal(settings) -> None:
    with pytest.raises(PathTraversalError):
        await EditFileTool().execute(
            {"file_path": "../secret", "old_string": "x", "new_string": "y"}, settings
        )


@pytest.mark.asyncio
async def test_edit_file_blocks_symlink_target(files_root: Path, settings) -> None:
    real = files_root / "real.txt"
    real.write_text("segredo")
    link = files_root / "link.txt"
    link.symlink_to(real)

    with pytest.raises(SymlinkNotAllowedError):
        await EditFileTool().execute(
            {"file_path": "/link.txt", "old_string": "segredo", "new_string": "hackeado"},
            settings,
        )
    assert real.read_text() == "segredo"


@pytest.mark.asyncio
async def test_glob_blocks_traversal_via_path_param(settings) -> None:
    with pytest.raises(PathTraversalError):
        await GlobTool().execute({"pattern": "*.txt", "path": "../"}, settings)


@pytest.mark.asyncio
async def test_grep_blocks_traversal_via_path_param(settings) -> None:
    with pytest.raises(PathTraversalError):
        await GrepTool().execute({"pattern": "x", "path": "../etc"}, settings)


@pytest.mark.asyncio
async def test_glob_does_not_escape_via_symlinked_directory(files_root: Path, settings) -> None:
    outside = files_root.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("segredo")
    (files_root / "escape").symlink_to(outside)

    result = await GlobTool().execute({"pattern": "**/*.txt"}, settings)
    assert result["matches"] == []


@pytest.mark.asyncio
async def test_write_file_create_missing_dirs_still_blocks_traversal(settings) -> None:
    from meligpt.tools.files.write_file import WriteFileTool

    with pytest.raises(PathTraversalError):
        await WriteFileTool().execute({"file_path": "../escape/novo.txt", "content": "x"}, settings)


@pytest.mark.asyncio
async def test_write_file_create_missing_dirs_does_not_follow_symlinked_parent(
    files_root: Path, settings
) -> None:
    from meligpt.tools.files.write_file import WriteFileTool

    outside = files_root.parent / "outside_for_mkdir"
    outside.mkdir()
    (files_root / "escape").symlink_to(outside)

    with pytest.raises(SymlinkNotAllowedError):
        await WriteFileTool().execute(
            {"file_path": "/escape/sub/novo.txt", "content": "x"}, settings
        )
    assert not (outside / "sub").exists()


@pytest.mark.asyncio
async def test_resolve_secure_create_missing_dirs_stays_within_root(
    files_root: Path, settings
) -> None:
    from meligpt.filesystem.security import resolve_secure

    with resolve_secure(
        files_root, "/nivel1/nivel2/arquivo.txt", allow_missing_final=True, create_missing_dirs=True
    ) as target:
        assert target.parent_fd is not None

    created = files_root / "nivel1" / "nivel2"
    assert created.is_dir()
    # garante que nada foi criado fora da raiz
    assert not (files_root.parent / "nivel1").exists()
