"""Extração de referências a arquivos e pastas dentro do prompt do usuário.

Migra, camada por camada, a lógica hoje espalhada em
``legacy/chat-api.sh`` (``extract_file_name_hint``, ``extract_directory_hint``,
``extract_requested_directory_name``, ``prompt_requests_directory_content``,
e a extração ``--auto-files`` de caminhos ``/files/...``), separada em
etapas testáveis independentemente da API:

1. tokenização/extração (regex simples, sem estado)
2. normalização (aspas, prefixos)
3. interpretação de intenção (o usuário quer o conteúdo de uma pasta?)
4. descoberta (delegada a :mod:`meligpt.filesystem.discovery`)
5. desambiguação (0/1/N resultados)

Não há, na implementação Bash original, lógica de "exclusão em linguagem
natural" (ex.: "sem ser o que está na pasta X") — múltiplos resultados
sempre exigem que o usuário informe um caminho mais específico. Preservamos
esse comportamento em vez de inventar um recurso inexistente.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_FILE_NAME_RE = re.compile(r"([\w@%+=~-]+\.)+[\w@%+=~-]+")
_AUTO_FILE_RE = re.compile(r"/files/[A-Za-z0-9._/+@%=-]+")

_DIRECTORY_HINT_RE = re.compile(
    r"(?:dentro da pasta|na pasta|pasta|diret[óo]rio)\s+[`\"']?([\w.@+%=-]+)",
    re.IGNORECASE,
)
_DIRECTORY_BACKTICK_RE = re.compile(r"(?:pasta|diret[óo]rio)\s+`([^`]+)`", re.IGNORECASE)
_DIRECTORY_DQUOTE_RE = re.compile(r'(?:pasta|diret[óo]rio)\s+"([^"]+)"', re.IGNORECASE)
_DIRECTORY_PLAIN_RE = re.compile(r"(?:pasta|diret[óo]rio)\s+([\w.@+%=-]+)", re.IGNORECASE)

_DIRECTORY_CONTENT_PHRASES = (
    "conteudo da pasta",
    "conteúdo da pasta",
    "conteudo do diretorio",
    "conteúdo do diretório",
    "conteúdo do diretorio",
    "conteudo do diretório",
    "leia a pasta",
    "ler a pasta",
    "listar a pasta",
    "liste a pasta",
    "leia o diretorio",
    "leia o diretório",
    "ler o diretorio",
    "ler o diretório",
    "listar o diretorio",
    "listar o diretório",
    "arquivos da pasta",
    "arquivos do diretorio",
    "arquivos do diretório",
    "o que tem na pasta",
    "o que existe na pasta",
)


def extract_file_name_hint(prompt: str) -> str | None:
    """Primeiro token com aparência de nome de arquivo (contém um ponto)."""

    match = _FILE_NAME_RE.search(prompt)
    return match.group(0) if match else None


def extract_directory_hint(prompt: str) -> str | None:
    match = _DIRECTORY_HINT_RE.search(prompt)
    return match.group(1) if match else None


def extract_requested_directory_name(prompt: str) -> str | None:
    """Nome de pasta pedido explicitamente, tentando crases, aspas duplas e
    por fim um token simples — na mesma ordem de prioridade do Bash.
    """

    for pattern in (_DIRECTORY_BACKTICK_RE, _DIRECTORY_DQUOTE_RE, _DIRECTORY_PLAIN_RE):
        match = pattern.search(prompt)
        if match:
            return match.group(1)
    return None


def prompt_requests_directory_content(prompt: str) -> bool:
    lowered = prompt.lower()
    return any(phrase in lowered for phrase in _DIRECTORY_CONTENT_PHRASES)


def extract_auto_file_references(prompt: str) -> list[str]:
    """Referências explícitas ``/files/...`` na mensagem, sem duplicatas,
    na ordem em que aparecem (equivalente ao ``--auto-files`` do Bash).
    """

    seen: dict[str, None] = {}
    for match in _AUTO_FILE_RE.finditer(prompt):
        candidate = re.sub(r"[.,;:!?]+$", "", match.group(0))
        seen.setdefault(candidate, None)
    return list(seen)


@dataclass
class FileReferenceRequest:
    """Resultado da interpretação de intenção, pronto para a etapa de
    descoberta.
    """

    explicit_files: list[str] = field(default_factory=list)
    """Caminhos passados via --file ou detectados por --auto-files."""

    directory_name_hint: str | None = None
    """Nome de pasta cujo conteúdo o usuário pediu explicitamente."""

    file_name_hint: str | None = None
    directory_hint_for_file: str | None = None
    """Pasta mencionada junto com o nome de arquivo, para desambiguar."""


def interpret_prompt(
    prompt: str, *, auto_files: bool, discovery_enabled: bool
) -> FileReferenceRequest:
    """Interpreta a intenção do usuário a partir do texto livre, sem tocar
    no filesystem (etapa 3 — a etapa 4, descoberta, fica em
    :mod:`meligpt.filesystem.discovery`).
    """

    request = FileReferenceRequest()

    if auto_files:
        request.explicit_files = extract_auto_file_references(prompt)

    if not discovery_enabled:
        return request

    if prompt_requests_directory_content(prompt):
        request.directory_name_hint = extract_requested_directory_name(prompt)

    request.file_name_hint = extract_file_name_hint(prompt)
    request.directory_hint_for_file = extract_directory_hint(prompt)

    return request
