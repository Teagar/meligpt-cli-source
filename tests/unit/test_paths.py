from __future__ import annotations

import pytest

from meligpt.exceptions import InvalidPathError, PathTraversalError
from meligpt.filesystem.paths import parse_virtual_path


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("/", ()),
        ("/files", ()),
        ("/files/x", ("x",)),
        ("/x", ("x",)),
        ("./x", ("x",)),
        ("x", ("x",)),
        ("a/b/c", ("a", "b", "c")),
        ("/files/a/b", ("a", "b")),
    ],
)
def test_parse_virtual_path_forms(raw: str, expected: tuple[str, ...]) -> None:
    assert parse_virtual_path(raw).components == expected


def test_rejects_empty_path() -> None:
    with pytest.raises(InvalidPathError):
        parse_virtual_path("")


@pytest.mark.parametrize("raw", ["..", "../x", "a/..", "a/../b", "/files/.."])
def test_rejects_dotdot_before_normalization(raw: str) -> None:
    with pytest.raises(PathTraversalError):
        parse_virtual_path(raw)


def test_dotdot_as_substring_is_not_confused_with_component() -> None:
    result = parse_virtual_path("/meu..arquivo")
    assert result.components == ("meu..arquivo",)
