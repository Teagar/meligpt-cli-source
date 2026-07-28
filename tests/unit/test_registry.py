from __future__ import annotations

import pytest

from meligpt.exceptions import ToolNotFoundError
from meligpt.tools.registry import ToolRegistry, build_default_registry


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_structured_error(settings) -> None:
    registry = ToolRegistry()
    result = await registry.dispatch("nao_existe", {}, settings)
    assert result["success"] is False
    assert result["code"] == "tool_not_found"


def test_get_unknown_tool_raises() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolNotFoundError):
        registry.get("nao_existe")


def test_default_registry_has_all_eleven_public_names() -> None:
    registry = build_default_registry()
    expected = {
        "WebSearch",
        "ImageGeneration",
        "task",
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        "write_todos",
        "parallel",
    }
    assert expected <= set(registry.names())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "edit_file",
        "glob",
        "grep",
        "write_todos",
        "parallel",
        "task",
        "WebSearch",
        "ImageGeneration",
    ],
)
async def test_stub_tools_report_not_implemented(name: str, settings) -> None:
    registry = build_default_registry()
    result = await registry.dispatch(name, {}, settings)
    assert result["success"] is False
    assert result["code"] == "tool_not_implemented"


@pytest.mark.asyncio
async def test_dispatch_never_leaks_raw_exception(settings, monkeypatch) -> None:
    registry = ToolRegistry()

    class BoomTool:
        name = "boom"
        description = "sempre falha"

        async def execute(self, arguments, settings):
            raise RuntimeError("algo quebrou")

    registry.register(BoomTool())
    result = await registry.dispatch("boom", {}, settings)
    assert result["success"] is False
    assert result["code"] == "tool_execution_error"
