"""Modelos dos eventos SSE emitidos pela API upstream do MeliGPT.

Formato observado (preservado do parsing feito em
``legacy/chat-api.sh``):

- Delta de texto: ``{"event": "on_message_delta", "data": {"delta": {"content": [{"type": "text", "text": "..."}]}}}``
- Tool call completada: ``{"event": "on_run_step_completed", "data": {"result": {"type": "tool_call", "tool_call": {...}}}}``
<<<<<<< HEAD
=======
- Mensagem final/completa (sem deltas): um evento cujo payload traz
  ``responseMessage.text`` ou ``responseMessage.content[].text`` — visto
  em alguns backends estilo LibreChat como alternativa (ou complemento) ao
  streaming por delta. Reconhecido independente do nome de ``event``,
  em ``data.responseMessage`` ou ``responseMessage`` no nível raiz.
>>>>>>> origin/main
- Fim do stream: linha literal ``data: [DONE]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolCallEvent:
    index: int
    id: str
    name: str
    arguments: dict[str, Any] | str


@dataclass(frozen=True)
class TextDeltaEvent:
    text: str


@dataclass(frozen=True)
<<<<<<< HEAD
=======
class FinalTextEvent:
    """Texto final/completo (não incremental), visto em
    ``responseMessage.text`` / ``responseMessage.content[].text``. A
    camada de serviço (:mod:`meligpt.chat.service`) só usa isso quando
    nenhum ``TextDeltaEvent`` chegou antes, para não duplicar a resposta
    quando o backend manda os dois.
    """

    text: str


@dataclass(frozen=True)
>>>>>>> origin/main
class DoneEvent:
    pass


@dataclass(frozen=True)
class RawEvent:
    """Evento reconhecido como JSON válido mas sem handler específico."""

    payload: dict[str, Any]


<<<<<<< HEAD
ChatEvent = TextDeltaEvent | ToolCallEvent | DoneEvent | RawEvent


def parse_sse_data(data: dict[str, Any]) -> ChatEvent:
=======
ChatEvent = TextDeltaEvent | ToolCallEvent | FinalTextEvent | DoneEvent | RawEvent


def _extract_response_message_text(response_message: dict[str, Any]) -> str:
    text = response_message.get("text")
    if isinstance(text, str) and text:
        return text
    parts = response_message.get("content") or []
    if isinstance(parts, list):
        return "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def parse_sse_data(data: dict[str, Any]) -> ChatEvent:
    response_message = data.get("responseMessage")
    if not isinstance(response_message, dict):
        nested_data = data.get("data")
        if isinstance(nested_data, dict):
            response_message = nested_data.get("responseMessage")
    if isinstance(response_message, dict):
        text = _extract_response_message_text(response_message)
        if text:
            return FinalTextEvent(text=text)

>>>>>>> origin/main
    event_type = data.get("event")

    if event_type == "on_message_delta":
        parts = data.get("data", {}).get("delta", {}).get("content") or []
        text = "".join(part.get("text", "") for part in parts if part.get("type") == "text")
        if text:
            return TextDeltaEvent(text=text)
        return RawEvent(payload=data)

    if event_type == "on_run_step_completed":
        result = data.get("data", {}).get("result", {})
        if result.get("type") == "tool_call":
            tool_call = result.get("tool_call")
            if isinstance(tool_call, dict) and tool_call.get("name"):
                index = (
                    result.get("index")
                    or data.get("data", {}).get("index")
                    or tool_call.get("index")
                    or 0
                )
                return ToolCallEvent(
                    index=index,
                    id=tool_call.get("id", ""),
                    name=tool_call.get("name", ""),
                    arguments=tool_call.get("args") or tool_call.get("arguments") or {},
                )

    return RawEvent(payload=data)
