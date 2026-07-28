from __future__ import annotations

from pathlib import Path

from meligpt.filesystem.discovery import find_by_name, find_directory_by_name


def test_exact_case_match(files_root: Path, settings) -> None:
    (files_root / "HelloWorld.java").write_text("x")
    matches = find_by_name(settings, name="HelloWorld.java")
    assert [m.virtual_path for m in matches] == ["/HelloWorld.java"]


def test_case_insensitive_fallback(files_root: Path, settings) -> None:
    (files_root / "HelloWorld.java").write_text("x")
    matches = find_by_name(settings, name="helloworld.java")
    assert [m.virtual_path for m in matches] == ["/HelloWorld.java"]


def test_multiple_results(files_root: Path, settings) -> None:
    (files_root / "dupe.txt").write_text("x")
    sub = files_root / "sub"
    sub.mkdir()
    (sub / "dupe.txt").write_text("y")

    matches = find_by_name(settings, name="dupe.txt")
    assert {m.virtual_path for m in matches} == {"/dupe.txt", "/sub/dupe.txt"}


def test_root_only(files_root: Path, settings) -> None:
    (files_root / "top.txt").write_text("x")
    sub = files_root / "sub"
    sub.mkdir()
    (sub / "top.txt").write_text("y")

    matches = find_by_name(settings, name="top.txt", root_only=True)
    assert [m.virtual_path for m in matches] == ["/top.txt"]


def test_excluded_dirs_are_skipped(files_root: Path, settings) -> None:
    git = files_root / ".git"
    git.mkdir()
    (git / "config.txt").write_text("x")

    matches = find_by_name(settings, name="config.txt")
    assert matches == []


def test_directory_hint_at_various_depths(files_root: Path, settings) -> None:
    deep = files_root / "a" / "b" / "thiago"
    deep.mkdir(parents=True)
    (deep / "notas.txt").write_text("x")
    (files_root / "notas.txt").write_text("y")

    matches = find_by_name(settings, name="notas.txt", directory_hint="thiago")
    assert [m.virtual_path for m in matches] == ["/a/b/thiago/notas.txt"]


def test_max_discovery_results_limit(files_root: Path, settings) -> None:
    for i in range(settings.max_discovery_results + 5):
        d = files_root / f"d{i}"
        d.mkdir()
        (d / "same.txt").write_text("x")

    matches = find_by_name(settings, name="same.txt")
    assert len(matches) == settings.max_discovery_results


def test_virtual_output_format(files_root: Path, settings) -> None:
    (files_root / "x.txt").write_text("x")
    matches = find_by_name(settings, name="x.txt")
    assert matches[0].virtual_path.startswith("/")


def test_deterministic_ordering(files_root: Path, settings) -> None:
    for name in ("z", "a", "m"):
        d = files_root / name
        d.mkdir()
        (d / "same.txt").write_text("x")

    m1 = find_by_name(settings, name="same.txt")
    m2 = find_by_name(settings, name="same.txt")
    assert [m.virtual_path for m in m1] == [m.virtual_path for m in m2]


def test_find_directory_by_name(files_root: Path, settings) -> None:
    (files_root / "thiago").mkdir()
    matches = find_directory_by_name(settings, name="thiago")
    assert [m.virtual_path for m in matches] == ["/thiago"]


def test_find_directory_case_insensitive(files_root: Path, settings) -> None:
    (files_root / "Thiago").mkdir()
    matches = find_directory_by_name(settings, name="thiago")
    assert [m.virtual_path for m in matches] == ["/Thiago"]
