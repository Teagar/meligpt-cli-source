from __future__ import annotations

from pathlib import Path

import pytest

from meligpt.exceptions import ToolDisabledError, ToolExecutionError, ToolValidationError
from meligpt.tools.system.bash import BashTool


@pytest.mark.asyncio
async def test_bash_disabled_by_default(settings) -> None:
    assert settings.enable_bash_tool is False
    with pytest.raises(ToolDisabledError):
        await BashTool().execute({"command": "echo oi"}, settings)


@pytest.mark.asyncio
async def test_bash_runs_command_when_enabled(settings) -> None:
    settings.enable_bash_tool = True
    result = await BashTool().execute({"command": "echo hello"}, settings)
    assert result["success"] is True
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]


@pytest.mark.asyncio
async def test_bash_runs_in_sandbox_cwd(files_root: Path, settings) -> None:
    settings.enable_bash_tool = True
    (files_root / "marker.txt").write_text("x")
    result = await BashTool().execute({"command": "ls"}, settings)
    assert "marker.txt" in result["stdout"]


@pytest.mark.asyncio
async def test_bash_captures_nonzero_exit_code(settings) -> None:
    settings.enable_bash_tool = True
    result = await BashTool().execute({"command": "exit 7"}, settings)
    assert result["success"] is True  # o comando executou; o exit code é informativo
    assert result["exit_code"] == 7


@pytest.mark.asyncio
async def test_bash_captures_stderr(settings) -> None:
    settings.enable_bash_tool = True
    result = await BashTool().execute({"command": "echo erro 1>&2"}, settings)
    assert "erro" in result["stderr"]


@pytest.mark.asyncio
async def test_bash_missing_command_rejected(settings) -> None:
    settings.enable_bash_tool = True
    with pytest.raises(ToolValidationError):
        await BashTool().execute({}, settings)


@pytest.mark.asyncio
async def test_bash_timeout_kills_process(settings) -> None:
    settings.enable_bash_tool = True
    settings.bash_timeout_seconds = 0.2
    with pytest.raises(ToolExecutionError):
        await BashTool().execute({"command": "sleep 5"}, settings)


@pytest.mark.asyncio
async def test_bash_truncates_large_output(settings) -> None:
    settings.enable_bash_tool = True
    settings.bash_max_output_bytes = 10
    result = await BashTool().execute({"command": "python3 -c \"print('x' * 1000)\""}, settings)
    assert result["stdout_truncated"] is True
    assert len(result["stdout"]) <= 10
