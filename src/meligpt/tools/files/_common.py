"""Extração defensiva de argumentos comuns entre ferramentas de arquivo.

Sem acesso ao backend real do MeliGPT para inspecionar o formato exato
das tool calls, aceitamos várias variações plausíveis de nome de chave em
vez de assumir uma única — isso é uma rede de segurança, não um
substituto para o diagnóstico feito em `chat/service.py` (que mostra os
argumentos brutos quando tudo isso falha).
"""

from __future__ import annotations

from typing import Any

_PATH_KEYS = ("file_path", "path", "filepath", "file", "filename", "target_path", "target")
_CONTENT_KEYS = ("content", "text", "file_content", "data", "body")


def extract_path(arguments: dict[str, Any]) -> str | None:
    for key in _PATH_KEYS:
        value = arguments.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def extract_content(arguments: dict[str, Any]) -> str | None:
    for key in _CONTENT_KEYS:
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    return None
