"""Contrato comum, tipado e pequeno para todas as ferramentas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import BaseModel

from meligpt.config import Settings


class ToolError(BaseModel):
    success: bool = False
    error: str
    code: str


class Tool(Protocol):
    """Toda ferramenta do catálogo implementa este protocolo."""

    name: str
    description: str

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        """Executa a ferramenta e retorna um dict serializável em JSON.

        Implementações devem levantar subclasses de
        :class:`meligpt.exceptions.MeliGPTError` em caso de erro — a
        camada de despacho (:mod:`meligpt.tools.registry`) as converte em
        respostas estruturadas; nunca deve escapar uma exceção genérica
        não tratada.
        """
        ...


@dataclass(frozen=True)
class ToolResult:
    """Envelope padrão de sucesso, usado pelas ferramentas concretas."""

    data: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"success": True, **self.data}
