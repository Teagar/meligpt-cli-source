"""Segurança de filesystem centralizada.

Único módulo que qualquer ferramenta de arquivo pode usar para tocar o
disco. Nenhuma ferramenta deve reimplementar resolução de caminho.

Estratégia contra traversal e symlink (ver ``docs/architecture.md``):

1. :func:`~meligpt.filesystem.paths.parse_virtual_path` rejeita ``..``
   *antes* de qualquer normalização lexical ou acesso ao filesystem.
2. A resolução real caminha componente a componente a partir de um file
   descriptor da raiz sandbox, abrindo cada diretório intermediário com
   ``O_DIRECTORY | O_NOFOLLOW`` relativo ao descritor anterior
   (``dir_fd``). Isso elimina a janela TOCTOU clássica de
   "resolve o caminho, depois abre por string": o encadeamento de
   descritores garante que cada passo enxergue exatamente o inode que foi
   verificado, mesmo que alguém troque um componente por um symlink entre
   a checagem e o uso.
3. A abertura do componente final também usa ``O_NOFOLLOW`` relativo ao
   descritor do diretório pai, então nunca seguimos um symlink final —
   nem para leitura, nem para escrita (que usa ``os.replace`` com
   ``dst_dir_fd``, substituindo a *entrada de diretório*, não o alvo do
   link).
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from meligpt.exceptions import (
    FileNotFoundToolError,
    NotADirectoryToolError,
    PathTraversalError,
    PermissionDeniedToolError,
    SymlinkNotAllowedError,
)
from meligpt.filesystem.paths import VirtualPath, parse_virtual_path

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


@dataclass
class ResolvedTarget:
    """Referência segura a um componente final dentro da raiz sandbox.

    ``parent_fd`` é um descritor aberto do diretório pai imediato; o
    chamador é responsável por fechá-lo (use como context manager via
    :func:`resolve_secure`). ``name`` é o nome do componente final
    (string vazia quando o alvo é a própria raiz). ``physical_path`` é
    apenas informativo (logging, mensagens de erro) — nenhuma operação de
    segurança deve depender dele.
    """

    parent_fd: int
    name: str
    physical_path: Path
    virtual_path: str
    exists: bool
    is_dir: bool
    is_symlink: bool


def _open_root_fd(root: Path) -> int:
    try:
        return os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    except NotADirectoryError as exc:
        raise NotADirectoryToolError(f"raiz sandbox não é um diretório: {root}") from exc
    except PermissionError as exc:
        raise PermissionDeniedToolError(f"sem permissão na raiz sandbox: {root}") from exc
    except FileNotFoundError as exc:
        raise FileNotFoundToolError(f"raiz sandbox não encontrada: {root}") from exc


@contextmanager
def resolve_secure(
    root: Path, virtual: str, *, allow_missing_final: bool = True
) -> Iterator[ResolvedTarget]:
    """Resolve um caminho virtual com segurança e produz um ``ResolvedTarget``.

    Levanta ``PathTraversalError``/``SymlinkNotAllowedError`` para
    tentativas de escape, e diferencia ``FileNotFoundToolError`` de
    ``NotADirectoryToolError``/``PermissionDeniedToolError`` conforme a
    causa real.
    """

    vpath: VirtualPath = parse_virtual_path(virtual)
    root_fd = _open_root_fd(root)
    opened: list[int] = []
    try:
        if vpath.is_root:
            st = os.fstat(root_fd)
            yield ResolvedTarget(
                parent_fd=root_fd,
                name="",
                physical_path=root,
                virtual_path="/",
                exists=True,
                is_dir=stat.S_ISDIR(st.st_mode),
                is_symlink=False,
            )
            return

        current_fd = root_fd
        physical = root
        components = vpath.components

        for index, component in enumerate(components):
            is_last = index == len(components) - 1
            physical = physical / component

            try:
                st = os.lstat(component, dir_fd=current_fd)
            except FileNotFoundError:
                if is_last and allow_missing_final:
                    yield ResolvedTarget(
                        parent_fd=current_fd,
                        name=component,
                        physical_path=physical,
                        virtual_path="/" + "/".join(components),
                        exists=False,
                        is_dir=False,
                        is_symlink=False,
                    )
                    return
                raise FileNotFoundToolError(f"caminho local não encontrado: {virtual}") from None
            except NotADirectoryError as exc:
                raise NotADirectoryToolError(
                    f"componente do caminho não é um diretório: {virtual}"
                ) from exc
            except PermissionError as exc:
                raise PermissionDeniedToolError(f"sem permissão para acessar: {virtual}") from exc

            is_symlink = stat.S_ISLNK(st.st_mode)

            if is_last:
                if is_symlink:
                    raise SymlinkNotAllowedError(
                        f"symlink não permitido no componente final: {virtual}"
                    )
                yield ResolvedTarget(
                    parent_fd=current_fd,
                    name=component,
                    physical_path=physical,
                    virtual_path="/" + "/".join(components),
                    exists=True,
                    is_dir=stat.S_ISDIR(st.st_mode),
                    is_symlink=False,
                )
                return

            # Componente intermediário: nunca pode ser symlink, e deve ser
            # diretório real para continuarmos a descida.
            if is_symlink:
                raise SymlinkNotAllowedError(
                    f"symlink não permitido em componente intermediário: {virtual}"
                )
            if not stat.S_ISDIR(st.st_mode):
                raise NotADirectoryToolError(f"componente intermediário não é diretório: {virtual}")

            try:
                new_fd = os.open(component, _DIR_FLAGS, dir_fd=current_fd)
            except (FileNotFoundError, NotADirectoryError, OSError) as exc:
                # Coberto por checagens acima na maioria dos casos, mas uma
                # troca concorrente (TOCTOU) cairia aqui como último
                # recurso e é tratada como violação de segurança, não como
                # "não encontrado".
                raise SymlinkNotAllowedError(
                    f"não foi possível abrir componente com segurança: {virtual}"
                ) from exc

            opened.append(new_fd)
            current_fd = new_fd
    finally:
        for fd in reversed(opened):
            os.close(fd)
        if root_fd not in opened:
            # root_fd só é fechado aqui se não foi (nunca é) reaproveitado
            # como um dos "opened"; ele é sempre o descritor mais externo.
            os.close(root_fd)


def ensure_under_root(physical: Path, root: Path) -> None:
    """Checagem defensiva adicional (defesa em profundidade, não a única)."""

    try:
        physical.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PathTraversalError(f"caminho fora da raiz autorizada: {physical}") from exc
