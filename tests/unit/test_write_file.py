from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.exceptions import (
    FileTooLargeError,
    NotADirectoryToolError,
    SymlinkNotAllowedError,
    ToolValidationError,
)
from meligpt.tools.files.write_file import WriteFileTool


@pytest.mark.asyncio
async def test_write_creates_file_with_exact_content(files_root: Path, settings) -> None:
    await WriteFileTool().execute(
        {"file_path": "/novo.txt", "content": "linha 1\nlinha 2\n"}, settings
    )
    assert (files_root / "novo.txt").read_bytes() == b"linha 1\nlinha 2\n"


@pytest.mark.asyncio
async def test_write_preserves_trailing_newlines(files_root: Path, settings) -> None:
    await WriteFileTool().execute({"file_path": "/nl.txt", "content": "x\n\n\n"}, settings)
    assert (files_root / "nl.txt").read_bytes() == b"x\n\n\n"


@pytest.mark.asyncio
async def test_write_no_trailing_newline(files_root: Path, settings) -> None:
    await WriteFileTool().execute({"file_path": "/sem_nl.txt", "content": "sem quebra"}, settings)
    assert (files_root / "sem_nl.txt").read_bytes() == b"sem quebra"


@pytest.mark.asyncio
async def test_write_is_atomic_no_temp_leftovers(files_root: Path, settings) -> None:
    await WriteFileTool().execute({"file_path": "/atomic.txt", "content": "ok"}, settings)
    leftovers = [p for p in files_root.iterdir() if p.name.startswith(".meligpt.")]
    assert leftovers == []


@pytest.mark.asyncio
async def test_write_overwrites_existing_file(files_root: Path, settings) -> None:
    (files_root / "existing.txt").write_text("velho")
    await WriteFileTool().execute({"file_path": "/existing.txt", "content": "novo"}, settings)
    assert (files_root / "existing.txt").read_text() == "novo"


@pytest.mark.asyncio
async def test_write_content_too_large(files_root: Path, settings) -> None:
    with pytest.raises(FileTooLargeError):
        await WriteFileTool().execute(
            {"file_path": "/big.txt", "content": "a" * (settings.max_file_size + 1)}, settings
        )
    assert not (files_root / "big.txt").exists()


@pytest.mark.asyncio
async def test_write_rejects_missing_content(settings) -> None:
    with pytest.raises(ToolValidationError):
        await WriteFileTool().execute({"file_path": "/x.txt"}, settings)


@pytest.mark.asyncio
async def test_write_to_root_rejected(settings) -> None:
    with pytest.raises(ToolValidationError):
        await WriteFileTool().execute({"file_path": "/", "content": "x"}, settings)


@pytest.mark.asyncio
async def test_write_through_final_symlink_rejected(files_root: Path, settings) -> None:
    real = files_root / "real_target.txt"
    real.write_text("original")
    link = files_root / "link.txt"
    link.symlink_to(real)

    with pytest.raises(SymlinkNotAllowedError):
        await WriteFileTool().execute({"file_path": "/link.txt", "content": "hackeado"}, settings)

    assert real.read_text() == "original"


@pytest.mark.asyncio
async def test_write_through_symlink_directory_rejected(files_root: Path, settings) -> None:
    outside = files_root.parent / "outside"
    outside.mkdir()
    link_dir = files_root / "escape"
    link_dir.symlink_to(outside)

    with pytest.raises(SymlinkNotAllowedError):
        await WriteFileTool().execute(
            {"file_path": "/escape/new.txt", "content": "vazou"}, settings
        )

    assert not (outside / "new.txt").exists()


@pytest.mark.asyncio
async def test_write_failure_does_not_corrupt_original(
    files_root: Path, settings, monkeypatch
) -> None:
    real = files_root / "preserved.txt"
    real.write_text("valor original")

    from meligpt.filesystem import atomic_io as atomic_io_module

    def _boom(*args, **kwargs):
        raise OSError("falha simulada de disco")

    monkeypatch.setattr(atomic_io_module.os, "fsync", _boom)

    from meligpt.exceptions import ToolExecutionError

    with pytest.raises(ToolExecutionError):
        await WriteFileTool().execute(
            {"file_path": "/preserved.txt", "content": "novo valor"}, settings
        )

    assert real.read_text() == "valor original"
    leftovers = [p for p in files_root.iterdir() if p.name.startswith(".meligpt.")]
    assert leftovers == []


@pytest.mark.asyncio
async def test_write_file_accepts_filename_alias(files_root: Path, settings) -> None:
    await WriteFileTool().execute({"filename": "/via_alias.txt", "text": "conteudo"}, settings)
    assert (files_root / "via_alias.txt").read_text() == "conteudo"


@pytest.mark.asyncio
async def test_write_file_error_message_lists_received_keys(settings) -> None:
    result = None
    try:
        await WriteFileTool().execute({"unexpected_key": "x"}, settings)
    except Exception as exc:  # noqa: BLE001
        result = str(exc)
    assert result is not None
    assert "unexpected_key" in result


@pytest.mark.asyncio
async def test_write_creates_missing_intermediate_directories(files_root: Path, settings) -> None:
    """Reproduz o cenário real relatado: o modelo remoto manda um
    caminho 'de host' (refletindo o cwd que o cliente informou a ele),
    que dentro da nossa raiz vira subpastas ainda não criadas.
    """

    await WriteFileTool().execute(
        {
            "file_path": "/tmp/tmp.vqfikPR6fM/index.js",
            "content": "console.log('Hello, World!');\n",
        },
        settings,
    )
    created = files_root / "tmp" / "tmp.vqfikPR6fM" / "index.js"
    assert created.read_text() == "console.log('Hello, World!');\n"


@pytest.mark.asyncio
async def test_write_creates_multiple_nested_directories(files_root: Path, settings) -> None:
    await WriteFileTool().execute({"file_path": "/a/b/c/d/arquivo.txt", "content": "x"}, settings)
    assert (files_root / "a" / "b" / "c" / "d" / "arquivo.txt").read_text() == "x"


@pytest.mark.asyncio
async def test_write_reuses_existing_intermediate_directory(files_root: Path, settings) -> None:
    (files_root / "existente").mkdir()
    await WriteFileTool().execute({"file_path": "/existente/novo.txt", "content": "x"}, settings)
    assert (files_root / "existente" / "novo.txt").read_text() == "x"


@pytest.mark.asyncio
async def test_write_intermediate_creation_blocked_by_existing_file(
    files_root: Path, settings
) -> None:
    """Se um componente intermediário já existe como ARQUIVO (não
    diretório), a criação automática não deve sobrescrevê-lo.
    """

    (files_root / "nao_e_pasta").write_text("sou um arquivo")
    with pytest.raises(NotADirectoryToolError):
        await WriteFileTool().execute(
            {"file_path": "/nao_e_pasta/novo.txt", "content": "x"}, settings
        )
