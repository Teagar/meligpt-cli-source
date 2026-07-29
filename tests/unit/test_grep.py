from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.exceptions import ToolValidationError
from meligpt.tools.files.grep import GrepTool


@pytest.mark.asyncio
async def test_grep_literal_match(files_root: Path, settings) -> None:
    (files_root / "a.txt").write_text("olá mundo\nlinha sem nada\nfoo bar\n")
    result = await GrepTool().execute({"pattern": "mundo"}, settings)
    assert len(result["matches"]) == 1
    assert result["matches"][0]["line"] == 1
    assert result["matches"][0]["path"] == "/a.txt"


@pytest.mark.asyncio
async def test_grep_regex_mode(files_root: Path, settings) -> None:
    (files_root / "a.txt").write_text("abc123\nxyz\nabc456\n")
    result = await GrepTool().execute({"pattern": r"abc\d+", "regex": True}, settings)
    assert len(result["matches"]) == 2


@pytest.mark.asyncio
async def test_grep_invalid_regex_rejected(settings) -> None:
    with pytest.raises(ToolValidationError):
        await GrepTool().execute({"pattern": "(", "regex": True}, settings)


@pytest.mark.asyncio
async def test_grep_case_insensitive(files_root: Path, settings) -> None:
    (files_root / "a.txt").write_text("Hello World\n")
    result = await GrepTool().execute({"pattern": "hello", "case_sensitive": False}, settings)
    assert len(result["matches"]) == 1


@pytest.mark.asyncio
async def test_grep_skips_binary_files(files_root: Path, settings) -> None:
    (files_root / "bin.dat").write_bytes(b"\x00\x01mundo\x02")
    (files_root / "text.txt").write_text("mundo real\n")

    result = await GrepTool().execute({"pattern": "mundo"}, settings)
    paths = {m["path"] for m in result["matches"]}
    assert paths == {"/text.txt"}


@pytest.mark.asyncio
async def test_grep_respects_max_results(files_root: Path, settings) -> None:
    settings.max_grep_results = 2
    (files_root / "a.txt").write_text("x\nx\nx\nx\n")

    result = await GrepTool().execute({"pattern": "x"}, settings)
    assert len(result["matches"]) == 2
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_grep_scoped_to_subdirectory(files_root: Path, settings) -> None:
    (files_root / "sub").mkdir()
    (files_root / "sub" / "a.txt").write_text("alvo\n")
    (files_root / "b.txt").write_text("alvo\n")

    result = await GrepTool().execute({"pattern": "alvo", "path": "/sub"}, settings)
    assert [m["path"] for m in result["matches"]] == ["/sub/a.txt"]
