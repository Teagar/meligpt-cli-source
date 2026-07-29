"""CLI do MeliGPT — equivalente funcional a ``legacy/chat-api.sh``.

Uso:
    meligpt [opções] [mensagem]
    meligpt import-har [ARQUIVO.har]
    meligpt serve  # inicia o servidor HTTP/SSE opcional

Preserva os contratos de linha de comando do script Bash original:
``-f/--file``, ``--auto-files``, ``--no-discovery``, leitura da mensagem
via argumento ou stdin interativo quando omitida.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from meligpt.auth.har_importer import import_har
from meligpt.chat.service import (
    AmbiguousDiscoveryError,
    ChatFinished,
    InfoMessage,
    MirroredToolResult,
    TextChunk,
    WarningMessage,
    run_chat,
)
from meligpt.config import Settings, get_settings
from meligpt.exceptions import MeliGPTError
from meligpt.logging import configure_logging, new_request_id
from meligpt.tools.registry import build_default_registry
from meligpt.ui import console


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meligpt", description="Cliente de linha de comando para o MeliGPT."
    )
    subparsers = parser.add_subparsers(dest="command")

    chat_parser = subparsers.add_parser("chat", help="Envia uma mensagem (padrão).")
    _add_chat_arguments(chat_parser)

    import_parser = subparsers.add_parser(
        "import-har", help="Importa credenciais de um arquivo HAR."
    )
    import_parser.add_argument("har_file", nargs="?", default=None)

    serve_parser = subparsers.add_parser(
        "serve", help="Inicia o servidor HTTP/SSE opcional (uvicorn)."
    )
    serve_parser.add_argument("--host", default=None)
    serve_parser.add_argument("--port", type=int, default=None)

    # Compatibilidade: `meligpt "mensagem"` sem subcomando == `meligpt chat "mensagem"`.
    _add_chat_arguments(parser)

    return parser


def _add_chat_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-f", "--file", action="append", dest="files", default=[])
    parser.add_argument("--auto-files", action="store_true")
    parser.add_argument("--no-discovery", action="store_true")
    parser.add_argument("message", nargs="*")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)

    command = getattr(args, "command", None) or "chat"

    if command == "import-har":
        return _run_import_har(args, settings)
    if command == "serve":
        return _run_serve(args, settings)
    return asyncio.run(_run_chat_command(args, settings))


def _run_import_har(args: argparse.Namespace, settings: Settings) -> int:
    har_file = args.har_file
    if not har_file:
        if not sys.stdin.isatty():
            console.error("informe o caminho do HAR como argumento.")
            return 1
        har_file = input("Caminho do arquivo HAR: ").strip().strip("'\"")

    try:
        path = import_har(
            Path(har_file),
            settings.resolved_secrets_path(),
            expected_endpoint=settings.resolved_endpoint(),
        )
    except MeliGPTError as exc:
        console.error(exc.message)
        return 1

    console.info(f"Credenciais importadas com segurança em: {path}")
    console.warning("O HAR contém segredos; apague-o quando não for mais necessário.")
    return 0


def _run_serve(args: argparse.Namespace, settings: Settings) -> int:
    import uvicorn

    from meligpt.api.app import create_app

    uvicorn.run(
        create_app(settings),
        host=args.host or settings.server_host,
        port=args.port or settings.server_port,
        log_level=settings.log_level.lower(),
    )
    return 0


async def _run_chat_command(args: argparse.Namespace, settings: Settings) -> int:
    new_request_id()

    message = " ".join(args.message).strip()
    if not message:
        if sys.stdin.isatty():
            message = input("Mensagem: ").strip()
        else:
            message = sys.stdin.read().strip()

    if not message:
        console.error("a mensagem não pode ficar vazia")
        return 1

    registry = build_default_registry()

    async def prompt_for_har() -> Path | None:
        if not sys.stdin.isatty():
            return None
        answer = (
            input("\nDeseja importar um HAR recente e tentar novamente? [s/N] ").strip().lower()
        )
        if answer not in ("s", "sim"):
            return None
        return Path(input("Caminho do arquivo HAR: ").strip())

    console.stream_start()
    had_output = False
    try:
        async for event in run_chat(
            prompt=message,
            settings=settings,
            registry=registry,
            explicit_files=args.files,
            auto_files=args.auto_files,
            discovery_enabled=not args.no_discovery,
            interactive=sys.stdin.isatty(),
            prompt_for_har=prompt_for_har,
        ):
            if isinstance(event, TextChunk):
                console.stream_chunk(event.text)
                had_output = True
            elif isinstance(event, InfoMessage):
                console.info(event.message)
            elif isinstance(event, WarningMessage):
                console.warning(event.message)
            elif isinstance(event, MirroredToolResult):
                console.tool_result(event.name, event.success, event.message)
            elif isinstance(event, ChatFinished):
                console.stream_end()
                if not event.had_text:
                    console.warning("HTTP 200 recebido, mas nenhum texto foi encontrado no stream.")
    except AmbiguousDiscoveryError as exc:
        console.stream_end()
        console.error(exc.message)
        for candidate in exc.candidates:
            console.info(f"  {candidate}")
        console.info("Informe um caminho mais específico com --file.")
        return 2
    except MeliGPTError as exc:
        if not had_output:
            console.stream_end()
        console.error(exc.message)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
