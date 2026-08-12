from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.api.openai_compat import _build_directory_snapshot


@pytest.mark.asyncio
async def test_snapshot_none_when_sandbox_empty(settings) -> None:
    assert await _build_directory_snapshot(settings) is None


@pytest.mark.asyncio
async def test_snapshot_lists_existing_files(files_root: Path, settings) -> None:
    (files_root / "index.js").write_text("console.log(1)")
    (files_root / "sub").mkdir()
    (files_root / "sub" / "a.txt").write_text("x")

    snapshot = await _build_directory_snapshot(settings)
    assert snapshot is not None
    assert "/index.js" in snapshot
    assert "/sub/a.txt" in snapshot


@pytest.mark.asyncio
async def test_snapshot_ignores_gitkeep_only(files_root: Path, settings) -> None:
    (files_root / ".gitkeep").write_text("")
    assert await _build_directory_snapshot(settings) is None


@pytest.mark.asyncio
async def test_snapshot_caps_and_flags_truncation(files_root: Path, settings) -> None:
    for i in range(150):
        (files_root / f"f{i}.txt").write_text("x")

    snapshot = await _build_directory_snapshot(settings)
    assert snapshot is not None
    assert "e mais" in snapshot
