<<<<<<< HEAD
"""Stub de ``ImageGeneration``. Sem contraparte no Bash original (ver edit_file.py)."""
=======
"""Stub de ``ImageGeneration`` como *tool call de terceiros* (ver ``meligpt.media``).

Isto continua sem implementação real como ferramenta CLIENT-SIDE — o
projeto Bash original não integra nenhum provedor de geração de imagem
próprio, e não temos evidência de HAR do schema exato do tool_call
``ImageGeneration`` (args/result) para replicá-lo aqui.

Mas a geração de imagem em si acontece do lado do MeliGPT (servidor
remoto), não como uma ação que o cliente precisa executar: quando o
modelo gera uma imagem, o link ``/api/media/{userId}/{filename}`` (rota
confirmada por HAR) aparece no texto da resposta, e
``chat/service.py:_download_generated_media`` já baixa e salva isso
automaticamente ao final de cada turno — sem depender desta ferramenta.

Este stub só existe para o caso (não confirmado) de o modelo remoto
também emitir um tool_call ``ImageGeneration`` separado que espere uma
resposta client-side; se isso acontecer, o turno mostra
"ferramenta não espelhada: ImageGeneration" como aviso informativo, sem
impedir que a imagem (se houver) já tenha sido baixada via `media.py`.
"""
>>>>>>> origin/main

from __future__ import annotations

from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import ToolNotImplementedError


class ImageGenerationStub:
    name = "ImageGeneration"
<<<<<<< HEAD
    description = "[NÃO IMPLEMENTADO] Geraria/editaria imagens via provedor externo configurável."

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        raise ToolNotImplementedError(
            "ImageGeneration não possui implementação real: o projeto Bash "
            "original não integra nenhum provedor de geração de imagem."
=======
    description = (
        "[NÃO IMPLEMENTADO COMO TOOL CLIENT-SIDE] A geração de imagem em si é "
        "feita pelo MeliGPT remoto; o link resultante é baixado automaticamente "
        "(ver meligpt.media). Este stub cobre só um eventual tool_call separado "
        "sem schema confirmado."
    )

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        raise ToolNotImplementedError(
            "ImageGeneration não possui implementação client-side: a imagem "
            "gerada pelo MeliGPT remoto é baixada automaticamente a partir do "
            "link /api/media/... presente na resposta (ver meligpt.media), sem "
            "precisar desta ferramenta."
>>>>>>> origin/main
        )
