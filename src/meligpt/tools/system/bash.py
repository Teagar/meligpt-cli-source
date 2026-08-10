"""Ferramenta ``bash`` — execução real de comando de shell.

**DESLIGADA POR PADRÃO** (`MELIGPT_ENABLE_BASH_TOOL=false`). Isso não é
uma ferramenta de arquivo com sandbox de caminho como as outras — é
execução de comando de verdade, com o mesmo poder que qualquer processo
rodando dentro deste container tem. A única fronteira de segurança real
aqui é o isolamento do próprio container Docker (usuário não-root,
filesystem read-only fora de `/data`, sem privilégios extras — ver
`Dockerfile`). Ativar isso fora de um container assim equivale a dar
acesso de shell ao host onde o `meligpt serve` está rodando.

Restrições aplicadas mesmo com a ferramenta ligada:
- diretório de trabalho fixo na raiz sandbox (`resolved_files_dir()`);
- timeout configurável, mata o processo se estourar;
- saída truncada a um limite de bytes configurável;
- nunca levanta exceção genérica não tratada — timeout e falha de spawn
  viram erros estruturados.
"""

from __future__ import annotations

import asyncio
from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import ToolDisabledError, ToolExecutionError, ToolValidationError


class BashTool:
    name = "bash"
    description = (
        "Executa um comando de shell dentro da raiz sandbox de arquivos "
        "locais. Pode estar desligada por configuração do servidor "
        "(MELIGPT_ENABLE_BASH_TOOL)."
    )

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        if not settings.enable_bash_tool:
            raise ToolDisabledError(
                "a ferramenta bash está desligada neste servidor "
                "(MELIGPT_ENABLE_BASH_TOOL=false). Isso é proposital: dá "
                "execução de comando real dentro do container. Ative com "
                "cuidado — ver docs/tools.md."
            )

        command = arguments.get("command")
        if not isinstance(command, str) or not command.strip():
            raise ToolValidationError("command inválido")

        root = settings.resolved_files_dir()
        root.mkdir(parents=True, exist_ok=True)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise ToolExecutionError(f"falha ao iniciar o comando: {exc}") from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=settings.bash_timeout_seconds
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            raise ToolExecutionError(
                f"comando excedeu o timeout de {settings.bash_timeout_seconds}s e foi encerrado"
            ) from None

        limit = settings.bash_max_output_bytes
        stdout = stdout_bytes[:limit].decode("utf-8", errors="replace")
        stderr = stderr_bytes[:limit].decode("utf-8", errors="replace")
        stdout_truncated = len(stdout_bytes) > limit
        stderr_truncated = len(stderr_bytes) > limit

        exit_code = process.returncode
        parts = [f"$ {command}", f"(exit code: {exit_code})"]
        if stdout:
            parts.append(stdout + ("\n[...saída truncada...]" if stdout_truncated else ""))
        if stderr:
            parts.append(
                "[stderr]\n" + stderr + ("\n[...stderr truncado...]" if stderr_truncated else "")
            )

        return {
            "success": True,
            "content": "\n".join(parts),
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }
