"""Stub de ``ImageGeneration``. Sem contraparte no Bash original (ver edit_file.py)."""

from __future__ import annotations

from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import ToolNotImplementedError


class ImageGenerationStub:
    name = "ImageGeneration"
    description = "[NÃO IMPLEMENTADO] Geraria/editaria imagens via provedor externo configurável."

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        raise ToolNotImplementedError(
            "ImageGeneration não possui implementação real: o projeto Bash "
            "original não integra nenhum provedor de geração de imagem."
        )
