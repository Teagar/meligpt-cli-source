from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.exceptions import (
    BinaryFileError,
    FileNotFoundToolError,
    FileTooLargeError,
    NotAFileToolError,
)
from meligpt.tools.files.read_file import ReadFileTool


@pytest.mark.asyncio
async def test_read_empty_file(files_root: Path, settings) -> None:
    (files_root / "empty.txt").write_bytes(b"")
    result = await ReadFileTool().execute({"file_path": "/empty.txt"}, settings)
    assert result["content"] == ""
    assert result["size"] == 0


@pytest.mark.asyncio
async def test_read_single_trailing_newline_preserved(files_root: Path, settings) -> None:
    (files_root / "one_nl.txt").write_bytes(b"linha 1\n")
    result = await ReadFileTool().execute({"file_path": "/one_nl.txt"}, settings)
    assert result["content"] == "linha 1\n"


@pytest.mark.asyncio
async def test_read_multiple_trailing_newlines_preserved(files_root: Path, settings) -> None:
    (files_root / "multi_nl.txt").write_bytes(b"linha 1\n\n\n")
    result = await ReadFileTool().execute({"file_path": "/multi_nl.txt"}, settings)
    assert result["content"] == "linha 1\n\n\n"


@pytest.mark.asyncio
async def test_read_no_trailing_newline_preserved(files_root: Path, settings) -> None:
    (files_root / "no_nl.txt").write_bytes(b"sem quebra final")
    result = await ReadFileTool().execute({"file_path": "/no_nl.txt"}, settings)
    assert result["content"] == "sem quebra final"


@pytest.mark.asyncio
async def test_read_unicode_content(files_root: Path, settings) -> None:
    text = "café, 日本語, emoji 🎉"
    (files_root / "unicode.txt").write_text(text, encoding="utf-8")
    result = await ReadFileTool().execute({"file_path": "/unicode.txt"}, settings)
    assert result["content"] == text


@pytest.mark.asyncio
async def test_read_nul_byte_is_binary(files_root: Path, settings) -> None:
    (files_root / "withnul.bin").write_bytes(b"abc\x00def")
    with pytest.raises(BinaryFileError):
        await ReadFileTool().execute({"file_path": "/withnul.bin"}, settings)


@pytest.mark.asyncio
async def test_read_non_utf8_binary_without_nul(files_root: Path, settings) -> None:
    (files_root / "nonutf8.bin").write_bytes(b"\xff\xfe\xfd\xfc")
    with pytest.raises(BinaryFileError):
        await ReadFileTool().execute({"file_path": "/nonutf8.bin"}, settings)


@pytest.mark.asyncio
async def test_read_large_file_over_limit(files_root: Path, settings) -> None:
    (files_root / "big.txt").write_bytes(b"a" * (settings.max_file_size + 1))
    with pytest.raises(FileTooLargeError):
        await ReadFileTool().execute({"file_path": "/big.txt"}, settings)


@pytest.mark.asyncio
async def test_read_offset_and_limit(files_root: Path, settings) -> None:
    (files_root / "offset.txt").write_text("0123456789")
    result = await ReadFileTool().execute(
        {"file_path": "/offset.txt", "offset": 2, "limit": 3}, settings
    )
    assert result["content"] == "234"
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_read_names_with_spaces_and_tabs(files_root: Path, settings) -> None:
    (files_root / "com espaço.txt").write_text("ok")
    (files_root / "com\ttab.txt").write_text("ok")
    r1 = await ReadFileTool().execute({"file_path": "/com espaço.txt"}, settings)
    r2 = await ReadFileTool().execute({"file_path": "/com\ttab.txt"}, settings)
    assert r1["content"] == "ok"
    assert r2["content"] == "ok"


@pytest.mark.asyncio
async def test_read_nonexistent_directory(settings) -> None:
    with pytest.raises(FileNotFoundToolError):
        await ReadFileTool().execute({"file_path": "/missing/file.txt"}, settings)


@pytest.mark.asyncio
async def test_read_nonexistent_file(settings) -> None:
    with pytest.raises(FileNotFoundToolError):
        await ReadFileTool().execute({"file_path": "/nope.txt"}, settings)


@pytest.mark.asyncio
async def test_read_directory_as_file_fails(files_root: Path, settings) -> None:
    (files_root / "adir").mkdir()
    with pytest.raises(NotAFileToolError):
        await ReadFileTool().execute({"file_path": "/adir"}, settings)


@pytest.mark.asyncio
async def test_read_root_as_file_fails(settings) -> None:
    with pytest.raises(NotAFileToolError):
        await ReadFileTool().execute({"file_path": "/"}, settings)
