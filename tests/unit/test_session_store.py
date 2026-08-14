from __future__ import annotations

from meligpt.chat.session_store import ConversationSessionStore, SessionRecord, history_key


def test_history_key_is_stable_and_order_sensitive() -> None:
    a = history_key([("user", "oi"), ("assistant", "ola")])
    b = history_key([("user", "oi"), ("assistant", "ola")])
    c = history_key([("assistant", "ola"), ("user", "oi")])
    assert a == b
    assert a != c


def test_history_key_is_content_sensitive() -> None:
    a = history_key([("user", "oi")])
    b = history_key([("user", "oi!")])
    assert a != b


def test_lookup_returns_none_for_unknown_key() -> None:
    store = ConversationSessionStore()
    assert store.lookup("nope") is None


def test_remember_and_lookup_roundtrip() -> None:
    store = ConversationSessionStore()
    record = SessionRecord(conversation_id="c1", last_message_id="m1")
    store.remember("k1", record)
    assert store.lookup("k1") == record


def test_lru_eviction_drops_oldest_entry() -> None:
    store = ConversationSessionStore(max_size=2)
    store.remember("k1", SessionRecord("c1", "m1"))
    store.remember("k2", SessionRecord("c2", "m2"))
    store.remember("k3", SessionRecord("c3", "m3"))
    assert store.lookup("k1") is None
    assert store.lookup("k2") is not None
    assert store.lookup("k3") is not None
    assert len(store) == 2


def test_lookup_refreshes_lru_order() -> None:
    store = ConversationSessionStore(max_size=2)
    store.remember("k1", SessionRecord("c1", "m1"))
    store.remember("k2", SessionRecord("c2", "m2"))
    store.lookup("k1")  # toca k1 -> k2 vira o menos usado recentemente
    store.remember("k3", SessionRecord("c3", "m3"))
    assert store.lookup("k2") is None
    assert store.lookup("k1") is not None
    assert store.lookup("k3") is not None


def test_clear_empties_store() -> None:
    store = ConversationSessionStore()
    store.remember("k1", SessionRecord("c1", "m1"))
    store.clear()
    assert len(store) == 0


# --- _stable_user_text / _history_turns (api/openai_compat.py) --------
#
# Testados aqui (não em test_openai_compat.py) porque são funções puras
# de normalização — mais fácil de testar isolado do endpoint HTTP.


def test_stable_user_text_strips_system_reminder_block() -> None:
    from meligpt.api.openai_compat import _stable_user_text

    content = "Ola\n<system-reminder>snip_id=701tx1; sessão original</system-reminder>"
    assert _stable_user_text(content) == "Ola"


def test_stable_user_text_strips_available_deferred_tools_block() -> None:
    from meligpt.api.openai_compat import _stable_user_text

    content = (
        "<available-deferred-tools>\nAskUserQuestion, WebSearch\n</available-deferred-tools>\n\n"
        "Como você se chama?"
    )
    assert _stable_user_text(content) == "Como você se chama?"


def test_stable_user_text_strips_multiple_blocks_regardless_of_position() -> None:
    from meligpt.api.openai_compat import _stable_user_text

    content = (
        "<available-deferred-tools>A</available-deferred-tools>"
        "meio\n<system-reminder>B</system-reminder>fim"
    )
    assert _stable_user_text(content) == "meio fim"


def test_stable_user_text_ignores_content_beyond_snip_id_when_equal_after_stripping() -> None:
    from meligpt.api.openai_compat import _stable_user_text

    a = "Ola\n<system-reminder>snip_id=701tx1; sessão original</system-reminder>"
    b = "Ola\n<system-reminder>snip_id=99zzq2; outro contexto totalmente diferente</system-reminder>"
    assert _stable_user_text(a) == _stable_user_text(b) == "Ola"


def test_stable_user_text_returns_empty_for_pure_wrapper_content() -> None:
    from meligpt.api.openai_compat import _stable_user_text

    content = "<available-deferred-tools>\nAskUserQuestion\n</available-deferred-tools>"
    assert _stable_user_text(content) == ""


def test_history_turns_skips_non_user_roles_and_empty_after_stripping() -> None:
    from meligpt.api.openai_compat import ChatMessage, _history_turns

    messages = [
        ChatMessage(role="system", content="Você é um agente."),
        ChatMessage(role="user", content="<system-reminder>x</system-reminder>"),
        ChatMessage(role="assistant", content="oi"),
        ChatMessage(role="user", content="pergunta real"),
    ]
    assert _history_turns(messages) == [("user", "pergunta real")]
