from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.tools.files.ls import LsTool


@pytest.mark.asyncio
async def test_ls_root_lists_entries_sorted(files_root: Path, settings) -> None:
    (files_root / "b.txt").write_text("b")
    (files_root / "a.txt").write_text("a")
    (files_root / "zdir").mkdir()

    result = await LsTool().execute({"path": "/"}, settings)
    names = [e["name"] for e in result["entries"]]
    assert names == sorted(names)
    assert {"a.txt", "b.txt", "zdir"} <= set(names)


@pytest.mark.asyncio
async def test_ls_skips_symlinks(files_root: Path, settings) -> None:
    real = files_root / "real.txt"
    real.write_text("x")
    (files_root / "link.txt").symlink_to(real)

    result = await LsTool().execute({"path": "/"}, settings)
    names = [e["name"] for e in result["entries"]]
    assert "real.txt" in names
    assert "link.txt" not in names


@pytest.mark.asyncio
async def test_ls_recursive(files_root: Path, settings) -> None:
    sub = files_root / "sub"
    sub.mkdir()
    (sub / "nested.txt").write_text("x")

    result = await LsTool().execute({"path": "/", "recursive": True}, settings)
    paths = [e["path"] for e in result["entries"]]
    assert "/sub/nested.txt" in paths


@pytest.mark.asyncio
async def test_ls_names_with_spaces_and_unicode(files_root: Path, settings) -> None:
    (files_root / "nome com espaço.txt").write_text("x")
    (files_root / "café-日本語.txt").write_text("x")

    result = await LsTool().execute({"path": "/"}, settings)
    names = {e["name"] for e in result["entries"]}
    assert "nome com espaço.txt" in names
    assert "café-日本語.txt" in names


@pytest.mark.asyncio
async def test_ls_deterministic_order_repeated_calls(files_root: Path, settings) -> None:
    for name in ("c.txt", "a.txt", "b.txt"):
        (files_root / name).write_text("x")

    r1 = await LsTool().execute({"path": "/"}, settings)
    r2 = await LsTool().execute({"path": "/"}, settings)
    assert [e["name"] for e in r1["entries"]] == [e["name"] for e in r2["entries"]]


@pytest.mark.asyncio
async def test_ls_json_serializable(files_root: Path, settings) -> None:
    import json

    (files_root / "a.txt").write_text("x")
    result = await LsTool().execute({"path": "/"}, settings)
    json.dumps(result)  # não deve levantar
