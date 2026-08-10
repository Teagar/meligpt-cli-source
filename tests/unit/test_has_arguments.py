from __future__ import annotations

import pytest

from meligpt.chat.service import _has_arguments


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"file_path": "/a.txt"}, True),
        ({}, False),
        ('{"file_path": "/a.txt"}', True),
        ("", False),
        ("   ", False),
        (None, False),
    ],
)
def test_has_arguments(raw, expected: bool) -> None:
    assert _has_arguments(raw) is expected
