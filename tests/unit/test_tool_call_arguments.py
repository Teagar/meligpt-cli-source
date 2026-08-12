from __future__ import annotations

from meligpt.chat.service import _coerce_arguments


def test_coerce_arguments_passthrough_dict() -> None:
    assert _coerce_arguments({"file_path": "/a.txt"}) == {"file_path": "/a.txt"}


def test_coerce_arguments_parses_json_string() -> None:
    result = _coerce_arguments('{"file_path": "/a.txt", "content": "x"}')
    assert result == {"file_path": "/a.txt", "content": "x"}


def test_coerce_arguments_invalid_json_returns_empty() -> None:
    assert _coerce_arguments("nao é json") == {}


def test_coerce_arguments_json_array_returns_empty() -> None:
    assert _coerce_arguments("[1, 2, 3]") == {}


def test_coerce_arguments_empty_string_returns_empty() -> None:
    assert _coerce_arguments("") == {}


def test_coerce_arguments_none_like_falls_back_to_empty() -> None:
    assert _coerce_arguments({}) == {}
