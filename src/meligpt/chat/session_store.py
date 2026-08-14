"""Cache de sessão que mapeia uma conversa OpenAI-compatible (como o
OpenClaude enxerga: uma lista ``messages`` que cresce a cada turno) para a
conversa MeliGPT real correspondente (``conversationId`` + o
``messageId`` da última resposta do assistente).

Por que isso existe
--------------------
O MeliGPT (LibreChat por baixo) tem memória de conversa de verdade do
lado do servidor: uma vez que você manda ``conversationId`` +
``parentMessageId``, ele reconstrói o histórico sozinho — o cliente só
precisa mandar a mensagem NOVA (ver HAR real, ``forks.har``: o campo
``text`` de cada turno nunca contém o histórico, só a mensagem daquele
turno).

O protocolo OpenAI (falado pelo OpenClaude) não tem esse conceito — cada
requisição HTTP é isolada e o cliente reenvia `messages` inteiro,
supostamente para dar "memória" ao servidor stateless do outro lado. Sem
mapear isso para o `conversationId` real do MeliGPT, cada requisição
criava uma conversa NOVA (comportamento visível como "o assistente cria
um novo chat a cada mensagem") e, pior, a única forma de dar alguma
continuidade era colar a transcrição inteira dentro do campo `text` —
o que faz qualquer geração de imagem/vídeo usar a conversa inteira como
prompt, em vez de só o pedido atual.

Este módulo resolve isso: guardamos, após cada turno bem-sucedido, uma
chave derivada do histórico completo (`messages` + a resposta que acabou
de ser gerada) apontando para ``(conversation_id, last_message_id)`` do
MeliGPT. No próximo turno, o histórico que chega é exatamente esse
histórico + UMA mensagem nova — batendo com a chave gravada. Quando bate,
mandamos só a mensagem nova pro MeliGPT, com ``conversationId``/
``parentMessageId`` apontando pra sessão certa. Quando não bate (primeiro
turno da conversa, ou o processo reiniciou e perdeu o cache em memória),
caímos de volta no bootstrap (ver :mod:`meligpt.api.openai_compat`).

É um cache best-effort e só em memória: perder uma entrada nunca causa
erro, só degrada de volta para o bootstrap de uma transcrição.
"""

from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from dataclasses import dataclass

#: Papel + conteúdo de uma mensagem, na forma mínima usada para a chave de
#: histórico — evita acoplar este módulo ao schema Pydantic da API.
HistoryTurn = tuple[str, str]


@dataclass(frozen=True)
class SessionRecord:
    """Onde uma conversa OpenAI-compatible está "ancorada" no MeliGPT."""

    conversation_id: str
    last_message_id: str


def history_key(turns: list[HistoryTurn]) -> str:
    """Deriva uma chave estável a partir da sequência (role, content).

    Determinístico entre processos/execuções (não usa ``hash()`` do
    Python, que é aleatorizado por padrão) — importante porque a chave
    gravada num turno precisa bater com a calculada no próximo.
    """

    payload = json.dumps(turns, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ConversationSessionStore:
    """Cache LRU simples, thread-safe, em memória.

    Uma instância por servidor (ver ``build_openai_router``) — cada
    processo/app tem seu próprio cache; reiniciar o servidor limpa tudo
    (degrada para bootstrap, nunca quebra).
    """

    def __init__(self, max_size: int = 200) -> None:
        self._max_size = max_size
        self._data: OrderedDict[str, SessionRecord] = OrderedDict()
        self._lock = threading.Lock()

    def lookup(self, key: str) -> SessionRecord | None:
        with self._lock:
            record = self._data.get(key)
            if record is not None:
                self._data.move_to_end(key)
            return record

    def remember(self, key: str, record: SessionRecord) -> None:
        with self._lock:
            self._data[key] = record
            self._data.move_to_end(key)
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)
