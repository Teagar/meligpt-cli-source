"""Ferramenta ``ls`` / ``list_files``.

Lista arquivos e diretórios de forma determinística, sem seguir symlinks,
com JSON válido, diferenciando "não existe", "não é diretório" e "sem
permissão". Equivalente ao case ``ls|list_files`` de
``legacy/local-tools.sh``.
"""

from __future__ import annotations

import os
from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import NotADirectoryToolError, ToolValidationError
from meligpt.filesystem.security import resolve_secure


class LsTool:
    name = "ls"
    description = (
        "Lista o conteúdo (arquivos e diretórios) de um caminho virtual "
        "dentro da raiz sandbox de arquivos locais."
    )

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        virtual = (
            arguments.get("path")
            or arguments.get("directory")
            or arguments.get("dir_path")
            or arguments.get("file_path")
            or "/"
        )
        if not isinstance(virtual, str) or not virtual:
            raise ToolValidationError("caminho de diretório inválido")

        recursive = arguments.get("recursive", arguments.get("recurse", False))
        recursive = recursive is True

        root = settings.resolved_files_dir()

        with resolve_secure(root, virtual, allow_missing_final=False) as target:
            if not target.is_dir:
                raise NotADirectoryToolError(f"diretório local não encontrado: {virtual}")
            base_physical = target.physical_path

        entries: list[dict[str, Any]] = []
        truncated = False
        limit = settings.max_ls_results

        for physical, virtual_path, is_dir, size in _walk(base_physical, root, recursive):
            entries.append(
                {
                    "name": physical.name,
                    "path": virtual_path,
                    "type": "directory" if is_dir else "file",
                    "size": size,
                }
            )
            if len(entries) >= limit:
                truncated = True
                break

        return {
            "success": True,
            "path": virtual,
            "recursive": recursive,
            "truncated": truncated,
            "entries": entries,
        }


def _to_virtual(root, physical) -> str:
    relative = physical.relative_to(root)
    return "/" + relative.as_posix()


def _walk(base_physical, root, recursive: bool):
    """Gera (physical, caminho_virtual, is_dir, size), determinístico,
    sem seguir symlinks — equivalente a ``find -P ... | sort``.
    """

    try:
        entries = sorted(os.scandir(base_physical), key=lambda e: e.name)
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return

    for entry in entries:
        if entry.is_symlink():
            continue
        physical = base_physical / entry.name
        try:
            resolved = physical.resolve()
        except OSError:
            continue
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue

        if entry.is_dir(follow_symlinks=False):
            yield physical, _to_virtual(root, physical), True, 0
            if recursive:
                yield from _walk(physical, root, recursive)
        elif entry.is_file(follow_symlinks=False):
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            yield physical, _to_virtual(root, physical), False, size
