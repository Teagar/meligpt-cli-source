"""Ferramenta ``read_file``.

Lê arquivos sem passar conteúdo por variáveis de shell (não aplicável em
Python, mas preservamos a garantia equivalente: leitura binária direta,
decodificação UTF-8 explícita, sem interpolação). Preserva exatamente o
conteúdo textual, incluindo trailing newlines. Detecta binário via byte
NUL nos primeiros bytes lidos, sem carregar o arquivo inteiro quando ele
excede o limite.
"""

from __future__ import annotations

import os
from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import (
    BinaryFileError,
    FileNotFoundToolError,
    FileTooLargeError,
    NotAFileToolError,
    ToolValidationError,
)
from meligpt.filesystem.security import resolve_secure
<<<<<<< HEAD
=======
from meligpt.tools.files._common import extract_path
>>>>>>> origin/main

_SNIFF_BYTES = 8192


class ReadFileTool:
    name = "read_file"
    description = "Lê o conteúdo textual de um arquivo dentro da raiz sandbox."

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
<<<<<<< HEAD
        virtual = arguments.get("file_path") or arguments.get("path")
        if not isinstance(virtual, str) or not virtual:
            raise ToolValidationError("file_path inválido")
=======
        virtual = extract_path(arguments)
        if not virtual:
            raise ToolValidationError(
                f"file_path inválido (chaves recebidas: {sorted(arguments.keys())})"
            )
>>>>>>> origin/main

        offset = arguments.get("offset")
        limit = arguments.get("limit")
        if offset is not None and (not isinstance(offset, int) or offset < 0):
            raise ToolValidationError("offset deve ser um inteiro >= 0")
        if limit is not None and (not isinstance(limit, int) or limit <= 0):
            raise ToolValidationError("limit deve ser um inteiro positivo")

        root = settings.resolved_files_dir()

        with resolve_secure(root, virtual, allow_missing_final=False) as target:
            if not target.exists:
                raise FileNotFoundToolError(f"arquivo local não encontrado: {virtual}")
            if target.is_dir:
                raise NotAFileToolError(
                    f"não é possível ler a raiz/diretório como arquivo: {virtual}"
                )

            try:
                fd = os.open(
                    target.name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=target.parent_fd,
                )
            except OSError as exc:
                raise FileNotFoundToolError(f"não foi possível abrir o arquivo: {virtual}") from exc

            try:
                real_size = os.fstat(fd).st_size
                start = offset or 0

                if offset is None and limit is None:
                    if real_size > settings.max_file_size:
                        raise FileTooLargeError(
                            f"arquivo maior que o limite de {settings.max_file_size} bytes"
                        )
                    to_read = real_size
                else:
                    to_read = min(limit or settings.max_file_size, settings.max_file_size)

                sniff = os.pread(fd, min(_SNIFF_BYTES, real_size), start)
                if b"\0" in sniff:
                    raise BinaryFileError(f"arquivo binário não suportado: {virtual}")

                if to_read <= len(sniff):
                    raw = sniff[:to_read]
                else:
                    remaining = os.pread(fd, to_read - len(sniff), start + len(sniff))
                    raw = sniff + remaining
            finally:
                os.close(fd)

        try:
            content = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise BinaryFileError(
                f"arquivo não é UTF-8 válido, tratado como binário: {virtual}"
            ) from exc
        return {
            "success": True,
            "content": content,
            "size": real_size,
            "path": virtual,
            "truncated": (offset or 0) + len(raw) < real_size,
        }
