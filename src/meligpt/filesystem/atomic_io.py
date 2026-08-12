"""Escrita atômica de arquivo por descritor (``dir_fd``).

Compartilhado por ``tools/files/write_file.py`` e ``tools/files/edit_file.py``
— nenhuma ferramenta deve reimplementar sua própria versão.
"""

from __future__ import annotations

import os

from meligpt.exceptions import ToolExecutionError

_TEMP_PREFIX = ".meligpt."


def atomic_write(parent_fd: int, filename: str, payload: bytes) -> None:
    """Grava ``payload`` em ``filename`` (dentro do diretório referenciado
    por ``parent_fd``) de forma atômica: escreve num temporário, ``fsync``,
    depois ``os.replace`` — nunca deixa o arquivo original num estado
    parcialmente escrito, mesmo em caso de falha no meio do processo.
    """

    tmp_name: str | None = None
    fd: int | None = None
    try:
        for _ in range(10):
            candidate = f"{_TEMP_PREFIX}{os.urandom(6).hex()}"
            try:
                fd = os.open(
                    candidate,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent_fd,
                )
                tmp_name = candidate
                break
            except FileExistsError:
                continue
        if fd is None or tmp_name is None:
            raise ToolExecutionError("não foi possível criar arquivo temporário seguro")

        with os.fdopen(fd, "wb") as handle:
            fd = None  # fdopen tomou posse do descritor; seu __exit__ sempre o fecha
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(tmp_name, filename, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        tmp_name = None
    except OSError as exc:
        raise ToolExecutionError(f"falha ao gravar arquivo: {exc}") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if tmp_name is not None:
            try:
                os.unlink(tmp_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
