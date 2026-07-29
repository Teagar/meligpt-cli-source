from __future__ import annotations

import os
from pathlib import Path

import pytest

from meligpt.exceptions import (
    FileNotFoundToolError,
    NotADirectoryToolError,
    PathTraversalError,
    SymlinkNotAllowedError,
)
from meligpt.filesystem.security import resolve_secure


def _write(path: Path, content: str = "conteudo") -> None:
    path.write_text(content)


class TestPathTraversal:
    @pytest.mark.parametrize(
        "virtual",
        [
            "../secret",
            "a/../../secret",
            "/files/../secret",
            "../../../../etc/passwd",
            "a/../..",
        ],
    )
    def test_rejects_dotdot_component(self, files_root: Path, virtual: str) -> None:
        with pytest.raises(PathTraversalError):
            with resolve_secure(files_root, virtual):
                pass

    def test_component_containing_dotdot_as_substring_is_allowed(self, files_root: Path) -> None:
        target = files_root / "meu..arquivo.txt"
        _write(target)
        with resolve_secure(files_root, "/meu..arquivo.txt") as resolved:
            assert resolved.exists
            assert resolved.name == "meu..arquivo.txt"

    def test_root_forms_resolve_to_root(self, files_root: Path) -> None:
        for virtual in ("/", "/files"):
            with resolve_secure(files_root, virtual) as resolved:
                assert resolved.is_dir
                assert resolved.name == ""


class TestSymlinks:
    def test_final_component_symlink_rejected(self, files_root: Path) -> None:
        target = files_root / "real.txt"
        _write(target)
        link = files_root / "link.txt"
        link.symlink_to(target)

        with pytest.raises(SymlinkNotAllowedError):
            with resolve_secure(files_root, "/link.txt", allow_missing_final=False):
                pass

    def test_intermediate_component_symlink_rejected(self, files_root: Path) -> None:
        real_dir = files_root / "real_dir"
        real_dir.mkdir()
        _write(real_dir / "inside.txt")
        link_dir = files_root / "link_dir"
        link_dir.symlink_to(real_dir)

        with pytest.raises(SymlinkNotAllowedError):
            with resolve_secure(files_root, "/link_dir/inside.txt"):
                pass

    def test_symlink_pointing_outside_root_rejected(self, files_root: Path, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        _write(secret, "top secret")
        link = files_root / "escape.txt"
        link.symlink_to(secret)

        with pytest.raises(SymlinkNotAllowedError):
            with resolve_secure(files_root, "/escape.txt", allow_missing_final=False):
                pass

    def test_symlink_pointing_inside_root_still_rejected_by_policy(self, files_root: Path) -> None:
        # Política adotada: NENHUM symlink é seguido, mesmo apontando para
        # dentro da própria raiz sandbox (evita reintrodução de ciclos e
        # simplifica o modelo de ameaça).
        target = files_root / "inside.txt"
        _write(target)
        link = files_root / "inside_link.txt"
        link.symlink_to(target)

        with pytest.raises(SymlinkNotAllowedError):
            with resolve_secure(files_root, "/inside_link.txt", allow_missing_final=False):
                pass

    def test_creation_through_symlink_directory_blocked(self, files_root: Path) -> None:
        outside = files_root.parent / "outside_dir"
        outside.mkdir()
        link_dir = files_root / "escape_dir"
        link_dir.symlink_to(outside)

        with pytest.raises(SymlinkNotAllowedError):
            with resolve_secure(files_root, "/escape_dir/new_file.txt"):
                pass

        assert not (outside / "new_file.txt").exists()

    def test_symlink_swap_during_operation_is_still_blocked(self, files_root: Path) -> None:
        """Simula troca de symlink: mesmo se o alvo for trocado entre a
        checagem lstat e o uso, o descritor aberto com O_NOFOLLOW garante
        que o processo nunca segue um link — a pior consequência possível
        é uma corrida sobre o próprio arquivo dentro da raiz, nunca um
        escape.
        """

        target_a = files_root / "a.txt"
        _write(target_a, "A")
        link = files_root / "swappable.txt"
        link.symlink_to(target_a)

        with pytest.raises(SymlinkNotAllowedError):
            with resolve_secure(files_root, "/swappable.txt", allow_missing_final=False):
                pass

        # Troca o alvo do link por um caminho fora da raiz.
        os.unlink(link)
        outside = files_root.parent / "b.txt"
        outside.write_text("B")
        link.symlink_to(outside)

        with pytest.raises(SymlinkNotAllowedError):
            with resolve_secure(files_root, "/swappable.txt", allow_missing_final=False):
                pass


class TestErrorDifferentiation:
    def test_missing_file_is_file_not_found(self, files_root: Path) -> None:
        with pytest.raises(FileNotFoundToolError):
            with resolve_secure(files_root, "/does/not/exist.txt", allow_missing_final=False):
                pass

    def test_intermediate_non_directory_raises_not_a_directory(self, files_root: Path) -> None:
        _write(files_root / "im_a_file.txt")
        with pytest.raises(NotADirectoryToolError):
            with resolve_secure(files_root, "/im_a_file.txt/child.txt"):
                pass

    def test_missing_intermediate_directory_raises_file_not_found(self, files_root: Path) -> None:
        with pytest.raises(FileNotFoundToolError):
            with resolve_secure(files_root, "/missing_dir/child.txt"):
                pass


class TestSpecialNames:
    @pytest.mark.parametrize(
        "name",
        [
            "arquivo com espaços.txt",
            "arquivo\tcom\ttab.txt",
            "arquivo-unicode-café-日本語.txt",
        ],
    )
    def test_names_with_spaces_tabs_unicode(self, files_root: Path, name: str) -> None:
        target = files_root / name
        _write(target, "conteudo")
        with resolve_secure(files_root, f"/{name}", allow_missing_final=False) as resolved:
            assert resolved.exists
            assert resolved.name == name

    def test_newline_in_virtual_path_rejected(self, files_root: Path) -> None:
        from meligpt.exceptions import InvalidPathError

        with pytest.raises(InvalidPathError):
            with resolve_secure(files_root, "/arquivo\ncom\nquebra.txt"):
                pass
