"""Ferramenta ``glob`` (busca de arquivos por padrão, ex.: ``**/*.java``).

Suporta ``**`` (qualquer profundidade de diretórios), ``*``, ``?`` e
``[...]`` — semântica compatível com glob de shell, mas sempre restrita à
raiz sandbox (sem seguir symlinks, sem escapar via ``..``).
"""

from __future__ import annotations

import os
import re
from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import NotADirectoryToolError, ToolValidationError
from meligpt.filesystem.security import resolve_secure

_EXCLUDED_DIRS = {".git", "node_modules", "__pycache__", ".venv"}


def _translate_glob(pattern: str) -> str:
    """Converte um padrão glob (com suporte a ``**``) numa regex ancorada."""

    i, n = 0, len(pattern)
    parts: list[str] = []
    while i < n:
        char = pattern[i]
        if char == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                if i + 2 < n and pattern[i + 2] == "/":
                    parts.append("(?:.*/)?")
                    i += 3
                    continue
                parts.append(".*")
                i += 2
                continue
            parts.append("[^/]*")
            i += 1
        elif char == "?":
            parts.append("[^/]")
            i += 1
        elif char == "[":
            end = i + 1
            if end < n and pattern[end] == "!":
                end += 1
            if end < n and pattern[end] == "]":
                end += 1
            while end < n and pattern[end] != "]":
                end += 1
            if end >= n:
                parts.append(re.escape(char))
                i += 1
            else:
                body = pattern[i + 1 : end]
                if body.startswith("!"):
                    body = "^" + body[1:]
                parts.append("[" + body + "]")
                i = end + 1
        else:
            parts.append(re.escape(char))
            i += 1
    return "^" + "".join(parts) + "$"


def _walk_files(base: str, *, excluded_dirs: set[str]) -> list[str]:
    """Retorna caminhos relativos (posix, sem barra inicial) de todos os
    arquivos sob ``base``, sem seguir symlinks, ordenados deterministicamente.
    """

    results: list[str] = []
    stack = [(base, "")]
    while stack:
        current_physical, current_relative = stack.pop()
        try:
            entries = sorted(os.scandir(current_physical), key=lambda e: e.name)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            rel = f"{current_relative}/{entry.name}" if current_relative else entry.name
            if entry.is_dir(follow_symlinks=False):
                if entry.name in excluded_dirs:
                    continue
                stack.append((entry.path, rel))
            elif entry.is_file(follow_symlinks=False):
                results.append(rel)
    return results


class GlobTool:
    name = "glob"
    description = "Busca arquivos por padrão glob (ex.: '**/*.java') dentro da raiz sandbox."

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        pattern = arguments.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ToolValidationError("pattern inválido")

        base_virtual = arguments.get("path") or "/"

        root = settings.resolved_files_dir()
        with resolve_secure(root, base_virtual, allow_missing_final=False) as target:
            if not target.is_dir:
                raise NotADirectoryToolError(f"caminho base não é diretório: {base_virtual}")
            base_physical = target.physical_path

        regex = re.compile(_translate_glob(pattern))
        all_files = _walk_files(str(base_physical), excluded_dirs=_EXCLUDED_DIRS)
        matches = sorted(rel for rel in all_files if regex.match(rel))

        truncated = len(matches) > settings.max_glob_results
        matches = matches[: settings.max_glob_results]

        base_prefix = "" if base_virtual in ("/", "/files") else base_virtual.rstrip("/")
        virtual_matches = [f"{base_prefix}/{rel}" for rel in matches]

        return {
            "success": True,
            "pattern": pattern,
            "truncated": truncated,
            "matches": virtual_matches,
        }
