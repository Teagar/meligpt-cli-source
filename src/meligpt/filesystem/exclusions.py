"""Diretórios sempre excluídos de varreduras recursivas (`ls -r`, `glob`,
`grep`, descoberta).

Além dos diretórios de projeto óbvios (`.git`, `node_modules`, ...),
inclui pseudo-sistemas de arquivo perigosos de descer recursivamente
(`/proc`, `/sys`, `/dev`) — relevante principalmente quando
`MELIGPT_FILES_DIR=/` (modo passagem direta, ver
`docs/architecture.md`), onde uma varredura recursiva sem essa lista
tentaria descer no filesystem inteiro do host.
"""

from __future__ import annotations

DEFAULT_EXCLUDED_DIRS: set[str] = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "proc",
    "sys",
    "dev",
    "run",
    "boot",
    "lost+found",
}
