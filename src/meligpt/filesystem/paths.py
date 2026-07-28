"""Semântica de caminhos virtuais.

Espelha ``resolve_path`` de ``legacy/local-tools.sh`` e ``normalize_hint`` de
``legacy/local-file-discovery.sh``.

Semântica documentada (ver ``docs/architecture.md``):

- ``/`` e ``/files``               -> raiz virtual (equivale à raiz sandbox).
- ``/files/x``                     -> ``x`` relativo à raiz sandbox.
- ``/x`` (qualquer outro prefixo)  -> ``x`` relativo à raiz sandbox — o
  ``/`` inicial é a raiz *virtual*, não a raiz real do sistema operacional.
- ``./x``                          -> ``x`` relativo à raiz sandbox.
- ``x`` (sem prefixo)              -> ``x`` relativo à raiz sandbox.

Nenhuma dessas formas alcança o filesystem real fora da raiz sandbox.
"""

from __future__ import annotations

from dataclasses import dataclass

from meligpt.exceptions import InvalidPathError, PathTraversalError

_FORBIDDEN_CHARS = ("\0", "\n", "\r")


@dataclass(frozen=True)
class VirtualPath:
    """Resultado da normalização: componentes relativos à raiz sandbox."""

    components: tuple[str, ...]

    @property
    def is_root(self) -> bool:
        return len(self.components) == 0

    def as_relative_posix(self) -> str:
        return "/".join(self.components)


def _strip_quotes(value: str) -> str:
    for quote in ("`", '"', "'"):
        if len(value) >= 2 and value.startswith(quote) and value.endswith(quote):
            return value[1:-1]
    return value


def parse_virtual_path(raw: str, *, strip_quotes: bool = False) -> VirtualPath:
    """Normaliza uma string de caminho virtual em componentes seguros.

    Levanta :class:`InvalidPathError` para entradas malformadas e
    :class:`PathTraversalError` assim que encontra um componente ``..``
    literal — a rejeição acontece ANTES de qualquer resolução no
    filesystem, conforme exigido.
    """

    if raw is None:
        raise InvalidPathError("caminho ausente")

    value = _strip_quotes(raw) if strip_quotes else raw

    if value == "" or any(ch in value for ch in _FORBIDDEN_CHARS):
        raise InvalidPathError(f"caminho inválido: {raw!r}")

    if value in ("/", "/files"):
        relative = ""
    elif value.startswith("/files/"):
        relative = value[len("/files/") :]
    elif value.startswith("./"):
        relative = value[2:]
    elif value.startswith("/"):
        relative = value[1:]
    else:
        relative = value

    relative = relative[:-1] if relative.endswith("/") and relative != "/" else relative

    if relative in ("", "."):
        return VirtualPath(components=())

    raw_components = relative.split("/")

    # Regra 1 do prompt: rejeitar qualquer componente EXATAMENTE ".."
    # antes de normalizar. Não confundir com nomes que apenas contêm ".."
    # como substring (ex.: "meu..arquivo" é válido).
    for component in raw_components:
        if component == "..":
            raise PathTraversalError(f"componente '..' não é permitido em caminho virtual: {raw!r}")

    components = tuple(c for c in raw_components if c not in ("", "."))
    return VirtualPath(components=components)
