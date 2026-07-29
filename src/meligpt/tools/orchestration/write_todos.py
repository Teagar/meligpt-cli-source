"""Ferramenta ``write_todos`` (lista estruturada de tarefas).

Cada chamada substitui a lista inteira (comportamento comum em agentes de
coding: o modelo manda o estado completo e atualizado). Persistida em
``<config_dir>/todos.json``, gravação atômica.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from typing import Any

from meligpt.config import Settings
from meligpt.exceptions import ToolExecutionError, ToolValidationError

_ALLOWED_STATUSES = {"pending", "in_progress", "completed"}


def _todos_path(settings: Settings) -> str:
    settings.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    return str(settings.config_dir / "todos.json")


def _validate_todo(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ToolValidationError("cada todo deve ser um objeto")

    content = raw.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ToolValidationError("todo sem 'content' válido")

    status = raw.get("status", "pending")
    if status not in _ALLOWED_STATUSES:
        raise ToolValidationError(
            f"status inválido: {status!r} (esperado um de {sorted(_ALLOWED_STATUSES)})"
        )

    todo_id = raw.get("id") or uuid.uuid4().hex[:8]
    if not isinstance(todo_id, str):
        raise ToolValidationError("id do todo deve ser string")

    return {"id": todo_id, "content": content, "status": status}


class WriteTodosTool:
    name = "write_todos"
    description = (
        "Cria/atualiza a lista de tarefas da sessão. Cada chamada substitui "
        "a lista inteira — mande sempre o estado completo e atualizado. "
        "Status permitidos: pending, in_progress, completed."
    )

    async def execute(self, arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
        raw_todos = arguments.get("todos")
        if not isinstance(raw_todos, list):
            raise ToolValidationError("'todos' deve ser uma lista")

        todos = [_validate_todo(item) for item in raw_todos]

        in_progress = [t for t in todos if t["status"] == "in_progress"]
        if len(in_progress) > 1:
            raise ToolValidationError("no máximo uma tarefa pode estar 'in_progress' por vez")

        path = _todos_path(settings)
        payload = json.dumps({"todos": todos}, ensure_ascii=False, indent=2).encode("utf-8")

        directory = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(prefix=".todos.", dir=directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        except OSError as exc:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            raise ToolExecutionError(f"falha ao gravar lista de tarefas: {exc}") from exc

        summary = ", ".join(f"[{t['status']}] {t['content']}" for t in todos) or "(vazia)"
        return {
            "success": True,
            "content": f"lista de tarefas atualizada: {summary}",
            "todos": todos,
        }
