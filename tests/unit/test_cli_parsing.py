from __future__ import annotations

from meligpt.cli import _normalize_argv, build_parser


def _parse(argv: list[str]):
    parser = build_parser()
    return parser.parse_args(_normalize_argv(argv))


def test_bare_message_defaults_to_chat_subcommand() -> None:
    """Regressão: `meligpt "mensagem"` sem subcomando explícito precisa
    continuar funcionando (era o comportamento documentado desde o
    Bash original) — sem `_normalize_argv`, o positional de
    `add_subparsers` engolia o primeiro token como nome de comando
    inválido."""

    args = _parse(["explique este código"])
    assert args.command == "chat"
    assert args.message == ["explique este código"]


def test_explicit_chat_subcommand_still_works() -> None:
    args = _parse(["chat", "oi"])
    assert args.command == "chat"
    assert args.message == ["oi"]


def test_flags_before_bare_message_default_to_chat() -> None:
    """Regressão: `meligpt --model x "mensagem"` (sem `chat` explícito)
    devia funcionar como atalho — antes da correção, `message` ficava
    vazio mesmo com o token presente no argv."""

    args = _parse(["--model", "x", "oi"])
    assert args.command == "chat"
    assert args.model == "x"
    assert args.message == ["oi"]


def test_chat_with_model_and_endpoint_flags() -> None:
    args = _parse(["chat", "--model", "gemini-3.6-flash", "--endpoint", "google", "oi"])
    assert args.model == "gemini-3.6-flash"
    assert args.endpoint == "google"
    assert args.message == ["oi"]


def test_no_args_defaults_to_chat_with_empty_message() -> None:
    args = _parse([])
    assert args.command == "chat"
    assert args.message == []


def test_models_subcommand_not_swallowed_by_default_chat() -> None:
    args = _parse(["models", "--provider", "google"])
    assert args.command == "models"
    assert args.provider == "google"


def test_providers_subcommand() -> None:
    args = _parse(["providers"])
    assert args.command == "providers"


def test_import_har_subcommand_unaffected() -> None:
    args = _parse(["import-har", "arquivo.har"])
    assert args.command == "import-har"
    assert args.har_file == "arquivo.har"


def test_serve_subcommand_unaffected() -> None:
    args = _parse(["serve", "--port", "9000"])
    assert args.command == "serve"
    assert args.port == 9000


def test_help_flag_is_not_rewritten() -> None:
    assert _normalize_argv(["--help"]) == ["--help"]
    assert _normalize_argv(["-h"]) == ["-h"]
