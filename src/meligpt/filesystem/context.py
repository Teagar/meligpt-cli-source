"""Geração do contexto local injetado no prompt.

Equivalente a ``legacy/local-file-context.sh``: para cada caminho (arquivo
ou diretório) solicitado, produz um bloco ``<local_file>`` ou
``<local_directory>`` com o conteúdo real, respeitando limites de
tamanho/quantidade e escapando conteúdo/atributos para não permitir que um
nome de arquivo ou conteúdo malicioso "feche" a tag e injete instruções
falsas no prompt (mitigação de prompt injection via metadados).
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape, quoteattr

from meligpt.config import Settings
from meligpt.exceptions import MeliGPTError
from meligpt.tools.files.ls import LsTool
from meligpt.tools.files.read_file import ReadFileTool


@dataclass
class ContextResult:
    xml: str
    included_files: int
    skipped_files: int
    total_bytes: int


async def build_local_context(paths: list[str], settings: Settings) -> ContextResult:
    ls_tool = LsTool()
    read_tool = ReadFileTool()

    blocks: list[str] = []
    included = 0
    skipped = 0
    total_bytes = 0

    for virtual in paths:
        is_dir, listing = await _try_list_as_directory(virtual, ls_tool, settings)

        if is_dir:
            assert listing is not None
            blocks.append(f"\n<local_directory path={quoteattr(virtual)}>")
            for entry in listing["entries"]:
                if entry["type"] != "file":
                    continue
                block, inc, size = await _read_one(
                    entry["path"], read_tool, settings, total_bytes, included
                )
                blocks.append(block)
                if inc:
                    included += 1
                    total_bytes += size
                else:
                    skipped += 1
                if included >= settings.max_context_files:
                    break
            blocks.append("</local_directory>\n")
        else:
            block, inc, size = await _read_one(virtual, read_tool, settings, total_bytes, included)
            blocks.append(block)
            if inc:
                included += 1
                total_bytes += size
            else:
                skipped += 1

        if included >= settings.max_context_files:
            break

    blocks.append(
        f'\n<local_context_summary included_files="{included}" '
        f'skipped_files="{skipped}" bytes="{total_bytes}"/>'
    )

    return ContextResult(
        xml="".join(blocks), included_files=included, skipped_files=skipped, total_bytes=total_bytes
    )


async def _try_list_as_directory(
    virtual: str, ls_tool: LsTool, settings: Settings
) -> tuple[bool, dict | None]:
    """Tenta listar ``virtual`` como diretório; retorna (False, None) se
    ele não for um diretório (ex.: é um arquivo, ou não existe).
    """

    try:
        listing = await ls_tool.execute({"path": virtual, "recursive": True}, settings)
    except MeliGPTError:
        return False, None
    return True, listing


async def _read_one(
    virtual: str,
    read_tool: ReadFileTool,
    settings: Settings,
    bytes_so_far: int,
    included_so_far: int,
) -> tuple[str, bool, int]:
    if included_so_far >= settings.max_context_files:
        return (
            f'\n<local_file_skipped path={quoteattr(virtual)} reason="max-files-limit"/>\n',
            False,
            0,
        )
    try:
        result = await read_tool.execute({"file_path": virtual}, settings)
    except MeliGPTError:
        return (
            f'\n<local_file_skipped path={quoteattr(virtual)} reason="unreadable-or-binary"/>\n',
            False,
            0,
        )

    content = result["content"]
    size = len(content.encode("utf-8"))

    if bytes_so_far + size > settings.max_context_size:
        return (
            f'\n<local_file_skipped path={quoteattr(virtual)} reason="context-size-limit"/>\n',
            False,
            0,
        )

    escaped = escape(content)
    block = f'\n<local_file path={quoteattr(virtual)} size="{size}">\n{escaped}\n</local_file>\n'
    return block, True, size
