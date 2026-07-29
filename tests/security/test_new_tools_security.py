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
