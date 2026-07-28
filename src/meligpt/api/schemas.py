from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    files: list[str] = Field(default_factory=list)
    directories: list[str] = Field(default_factory=list)
    auto_files: bool = False
    discovery_enabled: bool = True


class HealthResponse(BaseModel):
    status: str = "ok"
