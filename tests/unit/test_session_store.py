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
