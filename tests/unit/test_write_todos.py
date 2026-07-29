from __future__ import annotations

import json

import pytest

from meligpt.exceptions import ToolValidationError
from meligpt.tools.orchestration.write_todos import WriteTodosTool


@pytest.mark.asyncio
async def test_write_todos_persists_list(settings) -> None:
    todos = [
        {"content": "escrever testes", "status": "in_progress"},
        {"content": "revisar docs", "status": "pending"},
    ]
    result = await WriteTodosTool().execute({"todos": todos}, settings)
    assert result["success"] is True
    assert len(result["todos"]) == 2
    assert result["todos"][0]["status"] == "in_progress"

    path = settings.config_dir / "todos.json"
    assert path.exists()
    persisted = json.loads(path.read_text())
    assert len(persisted["todos"]) == 2


@pytest.mark.asyncio
async def test_write_todos_replaces_entire_list(settings) -> None:
    await WriteTodosTool().execute(
        {"todos": [{"content": "primeira", "status": "pending"}]}, settings
    )
    result = await WriteTodosTool().execute(
        {"todos": [{"content": "segunda", "status": "completed"}]}, settings
    )
    assert len(result["todos"]) == 1
    assert result["todos"][0]["content"] == "segunda"


@pytest.mark.asyncio
async def test_write_todos_rejects_invalid_status(settings) -> None:
    with pytest.raises(ToolValidationError):
        await WriteTodosTool().execute(
            {"todos": [{"content": "x", "status": "invalido"}]}, settings
        )


@pytest.mark.asyncio
async def test_write_todos_rejects_multiple_in_progress(settings) -> None:
    with pytest.raises(ToolValidationError):
        await WriteTodosTool().execute(
            {
                "todos": [
                    {"content": "a", "status": "in_progress"},
                    {"content": "b", "status": "in_progress"},
                ]
            },
            settings,
        )


@pytest.mark.asyncio
async def test_write_todos_rejects_missing_content(settings) -> None:
    with pytest.raises(ToolValidationError):
        await WriteTodosTool().execute({"todos": [{"status": "pending"}]}, settings)


@pytest.mark.asyncio
async def test_write_todos_empty_list_allowed(settings) -> None:
    result = await WriteTodosTool().execute({"todos": []}, settings)
    assert result["success"] is True
    assert result["todos"] == []


@pytest.mark.asyncio
async def test_write_todos_rejects_non_list(settings) -> None:
    with pytest.raises(ToolValidationError):
        await WriteTodosTool().execute({"todos": "não é lista"}, settings)
