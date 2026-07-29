"""Ferramenta ``grep`` (busca de texto ou regex dentro dos arquivos).

Nunca constrói comandos de shell — lê cada arquivo diretamente via Python.
Trata texto/binário explicitamente e nunca segue symlinks.
"""

from __future__ import annotations

import os
import re
from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import NotADirectoryToolError, ToolValidationError
from meligpt.filesystem.security import resolve_secure
from meligpt.tools.files.glob import _walk_files

_EXCLUDED_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
_SNIFF_BYTES = 8192


class GrepTool:
    name = "grep"
    description = (
        "Pesquisa um padrão (literal ou regex) dentro dos arquivos de texto "
        "autorizados, retornando arquivo, número da linha e o conteúdo da linha."
    )

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        pattern = arguments.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise ToolValidationError("pattern inválido")

        is_regex = bool(arguments.get("regex", False))
        case_sensitive = bool(arguments.get("case_sensitive", True))
        base_virtual = arguments.get("path") or "/"

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            compiled = re.compile(pattern if is_regex else re.escape(pattern), flags)
        except re.error as exc:
            raise ToolValidationError(f"regex inválida: {exc}") from exc

        root = settings.resolved_files_dir()
        with resolve_secure(root, base_virtual, allow_missing_final=False) as target:
            if not target.is_dir:
                raise NotADirectoryToolError(f"caminho base não é diretório: {base_virtual}")
            base_physical = target.physical_path

        base_prefix = "" if base_virtual in ("/", "/files") else base_virtual.rstrip("/")

        results: list[dict[str, Any]] = []
        files_scanned = 0
        truncated = False

        for rel in _walk_files(str(base_physical), excluded_dirs=_EXCLUDED_DIRS):
            if truncated:
                break
            physical = os.path.join(str(base_physical), *rel.split("/"))
            try:
                with open(physical, "rb") as handle:
                    raw = handle.read(settings.max_grep_bytes_per_file)
            except OSError:
                continue

            files_scanned += 1
            if b"\0" in raw[:_SNIFF_BYTES]:
                continue  # binário, pula silenciosamente

            try:
                text = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                continue

            virtual_path = f"{base_prefix}/{rel}"
            for line_number, line in enumerate(text.splitlines(), start=1):
                if compiled.search(line):
                    results.append({"path": virtual_path, "line": line_number, "text": line})
                    if len(results) >= settings.max_grep_results:
                        truncated = True
                        break

        return {
            "success": True,
            "pattern": pattern,
            "files_scanned": files_scanned,
            "truncated": truncated,
            "matches": results,
        }
