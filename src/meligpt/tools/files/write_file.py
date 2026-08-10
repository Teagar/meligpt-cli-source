"""Ferramenta ``write_file``.

Escrita atômica: arquivo temporário no mesmo diretório (mesmo
filesystem), ``fsync`` e ``os.replace`` relativo a descritores
(``dir_fd``), o que troca a *entrada de diretório* atomicamente — nunca
segue o alvo caso ``file_path`` já aponte para um symlink. Preserva
exatamente o conteúdo recebido, incluindo trailing newlines.

Cria diretórios intermediários ausentes automaticamente (como
``mkdir -p``, sempre dentro da raiz sandbox) — o modelo remoto costuma
mandar um caminho "de host" (ex.: `/tmp/tmp.xxxx/index.js`, refletindo o
cwd que o cliente relatou a ele) que, na nossa raiz virtual, vira
subpastas que ainda não existem.
"""

from __future__ import annotations

from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import FileTooLargeError, ToolValidationError
from meligpt.filesystem.atomic_io import atomic_write
from meligpt.filesystem.security import resolve_secure
from meligpt.tools.files._common import extract_content, extract_path


class WriteFileTool:
    name = "write_file"
    description = "Grava conteúdo textual em um arquivo dentro da raiz sandbox."

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
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

        payload = content.encode("utf-8")
        if len(payload) > settings.max_file_size:
            raise FileTooLargeError(
                f"conteúdo maior que o limite de {settings.max_file_size} bytes"
            )

        root = settings.resolved_files_dir()

        with resolve_secure(
            root, virtual, allow_missing_final=True, create_missing_dirs=True
        ) as target:
            if target.name == "":
                raise ToolValidationError("não é possível gravar na raiz de arquivos")
            if target.exists and target.is_dir:
                raise ToolValidationError(f"o caminho é um diretório: {virtual}")

            atomic_write(target.parent_fd, target.name, payload)

        return {"success": True, "content": f"gravado localmente: {virtual}"}
