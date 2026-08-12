"""Ferramenta ``edit_file`` (substituição exata de texto em arquivo).

Reaproveita a resolução/segurança de `filesystem/security.py` e a escrita
atômica de `filesystem/atomic_io.py` — não duplica nenhuma das duas.
"""

from __future__ import annotations

import os
from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import (
    AmbiguousMatchError,
    BinaryFileError,
    FileNotFoundToolError,
    NotAFileToolError,
    TextNotFoundError,
    ToolValidationError,
)
from meligpt.filesystem.atomic_io import atomic_write
from meligpt.filesystem.security import resolve_secure
from meligpt.tools.files._common import extract_path

_SNIFF_BYTES = 8192
_OLD_STRING_KEYS = ("old_string", "old", "old_text", "search", "find")
_NEW_STRING_KEYS = ("new_string", "new", "new_text", "replace", "replacement")


def _pick_str(arguments: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    return None


class EditFileTool:
    name = "edit_file"
    description = (
        "Substitui um trecho de texto exato por outro em um arquivo dentro "
        "da raiz sandbox. Por padrão exige que o texto original apareça "
        "exatamente uma vez (evita edições ambíguas); use "
        "`replace_all: true` para substituir todas as ocorrências."
    )

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        virtual = extract_path(arguments)
        if not virtual:
            raise ToolValidationError(
                f"file_path inválido (chaves recebidas: {sorted(arguments.keys())})"
            )

        old_string = _pick_str(arguments, _OLD_STRING_KEYS)
        if not old_string:
            raise ToolValidationError(
                f"old_string inválido/vazio (chaves recebidas: {sorted(arguments.keys())})"
            )

        new_string = _pick_str(arguments, _NEW_STRING_KEYS)
        if not isinstance(new_string, str):
            raise ToolValidationError(
                f"new_string inválido (chaves recebidas: {sorted(arguments.keys())})"
            )

        replace_all = bool(arguments.get("replace_all", False))

        root = settings.resolved_files_dir()

        with resolve_secure(root, virtual, allow_missing_final=False) as target:
            if not target.exists:
                raise FileNotFoundToolError(f"arquivo local não encontrado: {virtual}")
            if target.is_dir:
                raise NotAFileToolError(f"não é possível editar um diretório: {virtual}")

            try:
                fd = os.open(target.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=target.parent_fd)
            except OSError as exc:
                raise FileNotFoundToolError(f"não foi possível abrir o arquivo: {virtual}") from exc

            try:
                size = os.fstat(fd).st_size
                if size > settings.max_file_size:
                    raise ToolValidationError(
                        f"arquivo maior que o limite de {settings.max_file_size} "
                        "bytes; edit_file não suporta arquivos grandes"
                    )
                raw = os.pread(fd, size, 0)
            finally:
                os.close(fd)

            if b"\0" in raw[:_SNIFF_BYTES]:
                raise BinaryFileError(f"arquivo binário não suportado: {virtual}")

            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise BinaryFileError(
                    f"arquivo não é UTF-8 válido, tratado como binário: {virtual}"
                ) from exc

            occurrences = text.count(old_string)
            if occurrences == 0:
                raise TextNotFoundError(f"texto não encontrado em {virtual}: {old_string!r}")
            if occurrences > 1 and not replace_all:
                raise AmbiguousMatchError(
                    f"o texto aparece {occurrences} vezes em {virtual}; "
                    "informe um trecho mais específico ou use replace_all=true"
                )

            if replace_all:
                new_text = text.replace(old_string, new_string)
                replaced = occurrences
            else:
                new_text = text.replace(old_string, new_string, 1)
                replaced = 1

            atomic_write(target.parent_fd, target.name, new_text.encode("utf-8"))

        return {
            "success": True,
            "content": f"editado localmente: {virtual} ({replaced} substituição(ões))",
            "path": virtual,
            "replacements": replaced,
        }
