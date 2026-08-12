from __future__ import annotations

from pathlib import Path

from meligpt.cli import _apply_serve_scope, _normalize_argv, build_parser


def _parse(argv: list[str]):
    parser = build_parser()
    return parser.parse_args(_normalize_argv(argv))


def test_apply_serve_scope_with_here_uses_cwd(tmp_path: Path, monkeypatch, settings) -> None:
    monkeypatch.chdir(tmp_path)
    args = _parse(["serve", "--here"])

    _apply_serve_scope(args, settings)

    assert settings.files_dir == tmp_path.resolve()
    assert settings.allow_full_filesystem_access is False


def test_apply_serve_scope_with_files_dir_expands_and_resolves(tmp_path: Path, settings) -> None:
    target = tmp_path / "meu-projeto"
    target.mkdir()
    args = _parse(["serve", "--files-dir", str(target)])

    _apply_serve_scope(args, settings)

    assert settings.files_dir == target.resolve()
    assert settings.allow_full_filesystem_access is False


def test_apply_serve_scope_turns_off_full_access_even_if_it_was_on(
    tmp_path: Path, settings
) -> None:
    """Regressão: se o .env tinha ALLOW_FULL_FILESYSTEM_ACCESS=true (modo
    antigo de acesso total), `--here`/`--files-dir` tem que desligar isso
    — senão o path traversal guard (resolve_secure) não é reforçado de
    verdade dentro da pasta escolhida."""

    settings.allow_full_filesystem_access = True
    settings.files_dir = Path("/")
    args = _parse(["serve", "--here"])

    _apply_serve_scope(args, settings)

    assert settings.allow_full_filesystem_access is False
    assert settings.files_dir != Path("/")


def test_apply_serve_scope_without_flags_leaves_settings_untouched(settings) -> None:
    original_files_dir = settings.files_dir
    original_full_access = settings.allow_full_filesystem_access
    args = _parse(["serve"])

    _apply_serve_scope(args, settings)

    assert settings.files_dir == original_files_dir
    assert settings.allow_full_filesystem_access == original_full_access
