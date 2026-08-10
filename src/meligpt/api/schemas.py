from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list)
    directories: list[str] = Field(default_factory=list)
    auto_files: bool = False
    discovery_enabled: bool = True
    model: str | None = None
    """Id de modelo do catálogo (ver ``GET /v1/models``). Quando omitido,
    usa ``Settings.model`` / ``Settings.resolved_endpoint()``."""

    endpoint: str | None = None
    """Provedor lógico (ex.: ``google``, ``anthropic``) do catálogo.
    Ignorado se ``model`` também for informado e apontar para outro
    provedor (nesse caso a requisição é rejeitada)."""


class HealthResponse(BaseModel):
    status: str = "ok"
