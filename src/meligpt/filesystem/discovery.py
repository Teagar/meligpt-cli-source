"""Descoberta de arquivos e diretórios por nome dentro da raiz sandbox.

Equivalente a ``legacy/local-file-discovery.sh``: recebe uma dica de nome
(e opcionalmente uma dica de diretório) e retorna caminhos virtuais
candidatos, com fallback case-insensitive apenas quando a busca
case-sensitive não encontra nada.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from meligpt.config import Settings
<<<<<<< HEAD

_DEFAULT_EXCLUDED_DIRS = {".git", "node_modules", "__pycache__", ".venv"}
=======
from meligpt.filesystem.exclusions import DEFAULT_EXCLUDED_DIRS as _DEFAULT_EXCLUDED_DIRS
>>>>>>> origin/main


@dataclass(frozen=True)
class DiscoveryMatch:
    virtual_path: str
    is_dir: bool


def _is_safe_component(value: str) -> bool:
    if not value or value in (".", ".."):
        return False
    if "/" in value or "\n" in value or "\r" in value:
        return False
    return True


def _normalize_hint(value: str) -> str:
    value = value.strip("`\"'")
    if value.startswith("/files/"):
        value = value[len("/files/") :]
    elif value == "/files":
        value = ""
    elif value.startswith("./"):
        value = value[2:]
    elif value.startswith("/"):
        value = value[1:]
    return value.rstrip("/")


def _walk_candidates(root: Path, *, excluded_dirs: set[str]) -> list[tuple[Path, bool]]:
    """Retorna pares (caminho_físico, is_dir) sob a raiz, sem seguir symlinks."""

    results: list[tuple[Path, bool]] = []
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda e: e.name)
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.name in excluded_dirs and entry.is_dir(follow_symlinks=False):
                continue
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                results.append((path, True))
                stack.append(path)
            elif entry.is_file(follow_symlinks=False):
                results.append((path, False))
    return results


def _to_virtual(root: Path, physical: Path) -> str:
    relative = physical.relative_to(root)
    return "/" + relative.as_posix() if str(relative) != "." else "/"


def find_by_name(
    settings: Settings,
    *,
    name: str,
    directory_hint: str | None = None,
    root_only: bool = False,
) -> list[DiscoveryMatch]:
    """Busca por arquivo com nome exato (case-sensitive), com fallback
    case-insensitive apenas se nada for encontrado.
    """

    root = settings.resolved_files_dir()
    name = _normalize_hint(name)
    if not _is_safe_component(name.rsplit("/", 1)[-1] if "/" in name else name):
        return []

    directory_hint = _normalize_hint(directory_hint) if directory_hint else None

    candidates = _walk_candidates(root, excluded_dirs=_DEFAULT_EXCLUDED_DIRS)
    files = [(p, is_dir) for p, is_dir in candidates if not is_dir]

    if root_only:
        files = [(p, d) for p, d in files if p.parent == root]

    def matches_dir_hint(p: Path) -> bool:
        if not directory_hint:
            return True
        return directory_hint in p.relative_to(root).as_posix().split("/")

    matches = [p for p, _ in files if p.name == name and matches_dir_hint(p)]
    if not matches:
        lowered = name.lower()
        matches = [p for p, _ in files if p.name.lower() == lowered and matches_dir_hint(p)]

    result = [DiscoveryMatch(virtual_path=_to_virtual(root, p), is_dir=False) for p in matches]
    return result[: settings.max_discovery_results]


def find_directory_by_name(settings: Settings, *, name: str) -> list[DiscoveryMatch]:
    root = settings.resolved_files_dir()
    name = _normalize_hint(name)
    if not _is_safe_component(name):
        return []

    candidates = _walk_candidates(root, excluded_dirs=_DEFAULT_EXCLUDED_DIRS)
    dirs = [p for p, is_dir in candidates if is_dir]

    matches = [p for p in dirs if p.name == name]
    if not matches:
        lowered = name.lower()
        matches = [p for p in dirs if p.name.lower() == lowered]

    result = [DiscoveryMatch(virtual_path=_to_virtual(root, p), is_dir=True) for p in matches]
    return result[: settings.max_discovery_results]
