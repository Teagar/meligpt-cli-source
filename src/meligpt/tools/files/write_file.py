"""Ferramenta ``write_file``.

Escrita atômica: arquivo temporário no mesmo diretório (mesmo
filesystem), ``fsync`` e ``os.replace`` relativo a descritores
(``dir_fd``), o que troca a *entrada de diretório* atomicamente — nunca
segue o alvo caso ``file_path`` já aponte para um symlink. Preserva
exatamente o conteúdo recebido, incluindo trailing newlines.
<<<<<<< HEAD
=======

Cria diretórios intermediários ausentes automaticamente (como
``mkdir -p``, sempre dentro da raiz sandbox) — o modelo remoto costuma
mandar um caminho "de host" (ex.: `/tmp/tmp.xxxx/index.js`, refletindo o
cwd que o cliente relatou a ele) que, na nossa raiz virtual, vira
subpastas que ainda não existem.
>>>>>>> origin/main
"""

from __future__ import annotations

<<<<<<< HEAD
import os
from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import FileTooLargeError, ToolExecutionError, ToolValidationError
from meligpt.filesystem.security import resolve_secure

_TEMP_PREFIX = ".meligpt."
=======
from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import FileTooLargeError, ToolValidationError
from meligpt.filesystem.atomic_io import atomic_write
from meligpt.filesystem.security import resolve_secure
from meligpt.tools.files._common import extract_content, extract_path
>>>>>>> origin/main


class WriteFileTool:
    name = "write_file"
    description = "Grava conteúdo textual em um arquivo dentro da raiz sandbox."

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
<<<<<<< HEAD
        virtual = arguments.get("file_path") or arguments.get("path")
        if not isinstance(virtual, str) or not virtual:
            raise ToolValidationError("file_path inválido")

        content = arguments.get("content")
        if not isinstance(content, str):
            raise ToolValidationError("content inválido")
=======
        virtual = extract_path(arguments)
        if not virtual:
            raise ToolValidationError(
                f"file_path inválido (chaves recebidas: {sorted(arguments.keys())})"
            )

        content = extract_content(arguments)
        if content is None:
            raise ToolValidationError(
                f"content inválido (chaves recebidas: {sorted(arguments.keys())})"
            )
>>>>>>> origin/main

        payload = content.encode("utf-8")
        if len(payload) > settings.max_file_size:
            raise FileTooLargeError(
                f"conteúdo maior que o limite de {settings.max_file_size} bytes"
            )

        root = settings.resolved_files_dir()

<<<<<<< HEAD
        with resolve_secure(root, virtual, allow_missing_final=True) as target:
=======
        with resolve_secure(
            root, virtual, allow_missing_final=True, create_missing_dirs=True
        ) as target:
>>>>>>> origin/main
            if target.name == "":
                raise ToolValidationError("não é possível gravar na raiz de arquivos")
            if target.exists and target.is_dir:
                raise ToolValidationError(f"o caminho é um diretório: {virtual}")

<<<<<<< HEAD
            _atomic_write(target.parent_fd, target.name, payload)

        return {"success": True, "content": f"gravado localmente: {virtual}"}


def _atomic_write(parent_fd: int, filename: str, payload: bytes) -> None:
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
=======
            atomic_write(target.parent_fd, target.name, payload)

        return {"success": True, "content": f"gravado localmente: {virtual}"}
>>>>>>> origin/main
