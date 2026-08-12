from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.exceptions import (
    AmbiguousMatchError,
    BinaryFileError,
    FileNotFoundToolError,
    NotAFileToolError,
    TextNotFoundError,
    ToolValidationError,
)
from meligpt.tools.files.edit_file import EditFileTool


@pytest.mark.asyncio
async def test_edit_file_single_replacement(files_root: Path, settings) -> None:
    (files_root / "a.txt").write_text("linha 1\nlinha 2\nlinha 3\n")
    result = await EditFileTool().execute(
        {"file_path": "/a.txt", "old_string": "linha 2", "new_string": "LINHA DOIS"}, settings
    )
    assert result["success"] is True
    assert result["replacements"] == 1
    assert (files_root / "a.txt").read_text() == "linha 1\nLINHA DOIS\nlinha 3\n"


@pytest.mark.asyncio
async def test_edit_file_preserves_trailing_newline(files_root: Path, settings) -> None:
    (files_root / "a.txt").write_text("x\n\n\n")
    await EditFileTool().execute(
        {"file_path": "/a.txt", "old_string": "x", "new_string": "y"}, settings
    )
    assert (files_root / "a.txt").read_bytes() == b"y\n\n\n"


@pytest.mark.asyncio
async def test_edit_file_text_not_found(files_root: Path, settings) -> None:
    (files_root / "a.txt").write_text("conteudo")
    with pytest.raises(TextNotFoundError):
        await EditFileTool().execute(
            {"file_path": "/a.txt", "old_string": "nao existe", "new_string": "x"}, settings
        )


@pytest.mark.asyncio
async def test_edit_file_ambiguous_without_replace_all(files_root: Path, settings) -> None:
    (files_root / "a.txt").write_text("foo foo foo")
    with pytest.raises(AmbiguousMatchError):
        await EditFileTool().execute(
            {"file_path": "/a.txt", "old_string": "foo", "new_string": "bar"}, settings
        )
    # arquivo não deve ter sido alterado
    assert (files_root / "a.txt").read_text() == "foo foo foo"


@pytest.mark.asyncio
async def test_edit_file_replace_all(files_root: Path, settings) -> None:
    (files_root / "a.txt").write_text("foo foo foo")
    result = await EditFileTool().execute(
        {
            "file_path": "/a.txt",
            "old_string": "foo",
            "new_string": "bar",
            "replace_all": True,
        },
        settings,
    )
    assert result["replacements"] == 3
    assert (files_root / "a.txt").read_text() == "bar bar bar"


@pytest.mark.asyncio
async def test_edit_file_nonexistent_file(settings) -> None:
    with pytest.raises(FileNotFoundToolError):
        await EditFileTool().execute(
            {"file_path": "/nope.txt", "old_string": "x", "new_string": "y"}, settings
        )


@pytest.mark.asyncio
async def test_edit_file_directory_rejected(files_root: Path, settings) -> None:
    (files_root / "adir").mkdir()
    with pytest.raises(NotAFileToolError):
        await EditFileTool().execute(
            {"file_path": "/adir", "old_string": "x", "new_string": "y"}, settings
        )


@pytest.mark.asyncio
async def test_edit_file_binary_rejected(files_root: Path, settings) -> None:
    (files_root / "bin.dat").write_bytes(b"\x00\x01\x02")
    with pytest.raises(BinaryFileError):
        await EditFileTool().execute(
            {"file_path": "/bin.dat", "old_string": "x", "new_string": "y"}, settings
        )


@pytest.mark.asyncio
async def test_edit_file_empty_old_string_rejected(files_root: Path, settings) -> None:
    (files_root / "a.txt").write_text("conteudo")
    with pytest.raises(ToolValidationError):
        await EditFileTool().execute(
            {"file_path": "/a.txt", "old_string": "", "new_string": "y"}, settings
        )


@pytest.mark.asyncio
async def test_edit_file_accepts_search_replace_aliases(files_root: Path, settings) -> None:
    (files_root / "a.txt").write_text("foo bar")
    result = await EditFileTool().execute(
        {"path": "/a.txt", "search": "foo", "replace": "baz"}, settings
    )
    assert result["success"] is True
    assert (files_root / "a.txt").read_text() == "baz bar"
