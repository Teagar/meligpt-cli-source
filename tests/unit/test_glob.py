from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.tools.files.glob import GlobTool


@pytest.mark.asyncio
async def test_glob_matches_extension_recursively(files_root: Path, settings) -> None:
    (files_root / "src").mkdir()
    (files_root / "src" / "Main.java").write_text("x")
    (files_root / "HelloWorld.java").write_text("x")
    (files_root / "readme.md").write_text("x")

    result = await GlobTool().execute({"pattern": "**/*.java"}, settings)
    assert set(result["matches"]) == {"/HelloWorld.java", "/src/Main.java"}


@pytest.mark.asyncio
async def test_glob_star_does_not_cross_directories(files_root: Path, settings) -> None:
    (files_root / "sub").mkdir()
    (files_root / "sub" / "a.txt").write_text("x")
    (files_root / "b.txt").write_text("x")

    result = await GlobTool().execute({"pattern": "*.txt"}, settings)
    assert result["matches"] == ["/b.txt"]


@pytest.mark.asyncio
async def test_glob_respects_root_only_hint_dir(files_root: Path, settings) -> None:
    (files_root / "sub").mkdir()
    (files_root / "sub" / "x.txt").write_text("x")
    (files_root / "outra").mkdir()
    (files_root / "outra" / "y.txt").write_text("x")

    result = await GlobTool().execute({"pattern": "*.txt", "path": "/sub"}, settings)
    assert result["matches"] == ["/sub/x.txt"]


@pytest.mark.asyncio
async def test_glob_skips_symlinks(files_root: Path, settings) -> None:
    real = files_root / "real.txt"
    real.write_text("x")
    (files_root / "link.txt").symlink_to(real)

    result = await GlobTool().execute({"pattern": "*.txt"}, settings)
    assert result["matches"] == ["/real.txt"]


@pytest.mark.asyncio
async def test_glob_deterministic_order(files_root: Path, settings) -> None:
    for name in ("c.txt", "a.txt", "b.txt"):
        (files_root / name).write_text("x")

    r1 = await GlobTool().execute({"pattern": "*.txt"}, settings)
    r2 = await GlobTool().execute({"pattern": "*.txt"}, settings)
    assert r1["matches"] == r2["matches"] == ["/a.txt", "/b.txt", "/c.txt"]


@pytest.mark.asyncio
async def test_glob_respects_max_results(files_root: Path, settings) -> None:
    settings.max_glob_results = 2
    for i in range(5):
        (files_root / f"f{i}.txt").write_text("x")

    result = await GlobTool().execute({"pattern": "*.txt"}, settings)
    assert len(result["matches"]) == 2
    assert result["truncated"] is True
