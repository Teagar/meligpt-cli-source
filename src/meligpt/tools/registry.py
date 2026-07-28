"""Catálogo central de ferramentas.

Substitui o ``case "$name" in ... esac`` de ``legacy/local-tools.sh`` por um
registro explícito. Nenhum outro módulo deve despachar ferramentas por
comparação de string.
"""

from __future__ import annotations

from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import MeliGPTError, ToolExecutionError, ToolNotFoundError
from meligpt.logging import get_logger, log_with_fields
from meligpt.tools.base import Tool

_logger = get_logger("tools.registry")


class ToolRegistry:
    """Registro simples nome -> instância de ferramenta."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"ferramenta já registrada: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"ferramenta local não permitida: {name}") from exc

    def names(self) -> list[str]:
        return sorted(self._tools)

    async def dispatch(
        self, name: str, arguments: dict[str, Any], settings: Settings
    ) -> dict[str, Any]:
        """Executa uma ferramenta pelo nome, sempre retornando um dict
        serializável — nunca deixa uma exceção não estruturada escapar.
        """

        try:
            tool = self.get(name)
        except MeliGPTError as exc:
            return exc.to_dict()

        try:
            return await tool.execute(arguments, settings)
        except MeliGPTError as exc:
            log_with_fields(_logger, 30, "falha ao executar ferramenta", tool=name, code=exc.code)
            return exc.to_dict()
        except Exception as exc:  # noqa: BLE001 - convertido para erro estruturado
            log_with_fields(_logger, 40, "erro inesperado na ferramenta", tool=name, error=str(exc))
            return ToolExecutionError(f"falha inesperada em '{name}': {exc}").to_dict()


def build_default_registry() -> ToolRegistry:
    """Constrói o registro com todas as ferramentas conhecidas.

    Ferramentas reais (Fase A, com contraparte no Bash original) e
    ferramentas stub (Fase B, sem provedor real — ver
    ``docs/tools.md``) convivem no mesmo registro, mas as stubs sempre
    respondem ``tool_not_implemented`` em vez de fingir sucesso.
    """

    from meligpt.tools.files.ls import LsTool
    from meligpt.tools.files.read_file import ReadFileTool
    from meligpt.tools.files.write_file import WriteFileTool
    from meligpt.tools.stubs.edit_file import EditFileStub
    from meligpt.tools.stubs.glob_tool import GlobStub
    from meligpt.tools.stubs.grep import GrepStub
    from meligpt.tools.stubs.image_generation import ImageGenerationStub
    from meligpt.tools.stubs.parallel import ParallelStub
    from meligpt.tools.stubs.task import TaskStub
    from meligpt.tools.stubs.web_search import WebSearchStub
    from meligpt.tools.stubs.write_todos import WriteTodosStub

    registry = ToolRegistry()
    for tool in (
        LsTool(),
        ReadFileTool(),
        WriteFileTool(),
        EditFileStub(),
        GlobStub(),
        GrepStub(),
        WriteTodosStub(),
        ParallelStub(),
        TaskStub(),
        WebSearchStub(),
        ImageGenerationStub(),
    ):
        registry.register(tool)
    return registry
