from __future__ import annotations

import pytest

from meligpt.tools.files._common import extract_content, extract_path


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"file_path": "/a.txt"}, "/a.txt"),
        ({"path": "/a.txt"}, "/a.txt"),
        ({"filepath": "/a.txt"}, "/a.txt"),
        ({"file": "/a.txt"}, "/a.txt"),
        ({"filename": "/a.txt"}, "/a.txt"),
        ({"target_path": "/a.txt"}, "/a.txt"),
        ({"target": "/a.txt"}, "/a.txt"),
    ],
)
def test_extract_path_accepts_known_aliases(arguments: dict, expected: str) -> None:
    assert extract_path(arguments) == expected


def test_extract_path_prefers_file_path_over_other_aliases() -> None:
    assert extract_path({"file_path": "/a.txt", "path": "/b.txt"}) == "/a.txt"


def test_extract_path_returns_none_for_unknown_keys() -> None:
    assert extract_path({"destination": "/a.txt"}) is None


def test_extract_path_ignores_empty_string() -> None:
    assert extract_path({"file_path": ""}) is None


def test_extract_path_ignores_non_string_value() -> None:
    assert extract_path({"file_path": 123}) is None


@pytest.mark.parametrize(
    "arguments,expected",
    [
        ({"content": "x"}, "x"),
        ({"text": "x"}, "x"),
        ({"file_content": "x"}, "x"),
        ({"data": "x"}, "x"),
        ({"body": "x"}, "x"),
    ],
)
def test_extract_content_accepts_known_aliases(arguments: dict, expected: str) -> None:
    assert extract_content(arguments) == expected


def test_extract_content_allows_empty_string() -> None:
    # conteúdo vazio é válido (arquivo vazio) — só ausência é inválida.
    assert extract_content({"content": ""}) == ""


def test_extract_content_returns_none_when_absent() -> None:
    assert extract_content({}) is None
