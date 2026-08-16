"""CLI do MeliGPT — equivalente funcional a ``legacy/chat-api.sh``.

Uso:
    meligpt [opções] [mensagem]
    meligpt chat [opções] [mensagem]
    meligpt import-har [ARQUIVO.har]
    meligpt serve  # inicia o servidor HTTP/SSE opcional
    meligpt models [--provider P] [--endpoint E]
    meligpt providers

Preserva os contratos de linha de comando do script Bash original:
``-f/--file``, ``--auto-files``, ``--no-discovery``, leitura da mensagem
via argumento ou stdin interativo quando omitida. ``chat`` é o
subcomando padrão: ``meligpt "explique X"`` é equivalente a
``meligpt chat "explique X"`` (ver :func:`_normalize_argv`).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from meligpt.auth.har_importer import import_har
from meligpt.catalog import ModelCatalog, ModelInfo, resolve_model
from meligpt.chat.service import (
    AmbiguousDiscoveryError,
    ChatFinished,
    GeneratedMedia,
    ImageInput,
    InfoMessage,
    MirroredToolResult,
    TextChunk,
    WarningMessage,
    fork_conversation,
    run_chat,
    upload_images,
)
from meligpt.clients.meligpt_http import ForkOption
from meligpt.config import Settings, get_settings
from meligpt.exceptions import MeliGPTError
from meligpt.logging import configure_logging, new_request_id
from meligpt.media_upload import sniff_content_type
from meligpt.tools.registry import build_default_registry
from meligpt.ui import console

KNOWN_COMMANDS = {"chat", "import-har", "serve", "models", "providers", "fork"}

_FORK_OPTIONS_BY_VALUE = {option.value: option for option in ForkOption}
#: Aliases mais fáceis de digitar que os valores reais do payload (que
#: incluem uma string vazia para a opção padrão — ver `ForkOption`).
_FORK_OPTION_CHOICES = {
    "visible-only": ForkOption.VISIBLE_ONLY,
    "direct-path": ForkOption.VISIBLE_ONLY,
    "related-branches": ForkOption.INCLUDE_RELATED_BRANCHES,
    "include-branches": ForkOption.INCLUDE_RELATED_BRANCHES,
    "all": ForkOption.INCLUDE_ALL,
    "default": ForkOption.INCLUDE_ALL,
}


def _normalize_argv(argv: list[str]) -> list[str]:
    """Insere o subcomando ``chat`` implícito quando omitido.

    ``argparse`` não tem um jeito nativo de misturar "subcomando padrão"
    com ``add_subparsers`` sem essa normalização manual — sem ela, o
    positional de ``subparsers`` (que vem primeiro) engole o primeiro
    token e tenta interpretá-lo como nome de subcomando, quebrando tanto
    ``meligpt "mensagem"`` quanto ``meligpt --model x "mensagem"``.
    """

    if not argv:
        return ["chat"]
    first = argv[0]
    if first in ("-h", "--help"):
        return argv
    if first in KNOWN_COMMANDS:
        return argv
    return ["chat", *argv]


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
    serve_parser.add_argument(
        "--files-dir",
        default=None,
        help=(
            "Restringe ls/read_file/write_file/edit_file/glob/grep a esta pasta "
            "(sandbox com proteção contra path traversal — nunca sai daqui, mesmo "
            "com '..' ou symlinks). Sobrepõe MELIGPT_FILES_DIR e desliga o modo de "
            "acesso total, se estava ligado. ⚠️ bash NÃO é sandboxed da mesma forma "
            "(só começa nesta pasta — ver aviso na documentação)."
        ),
    )
    serve_parser.add_argument(
        "--here",
        action="store_true",
        help="Atalho para '--files-dir <diretório atual>' — restringe a sessão à pasta onde você rodou este comando.",
    )

    models_parser = subparsers.add_parser(
        "models", help="Lista o catálogo de modelos multi-provedor."
    )
    models_parser.add_argument("--provider", default=None)
    models_parser.add_argument("--endpoint", default=None)

    subparsers.add_parser("providers", help="Lista os provedores/rotas conhecidos.")

    fork_parser = subparsers.add_parser(
        "fork", help="Bifurca uma conversa MeliGPT existente a partir de uma mensagem."
    )
    fork_parser.add_argument("conversation_id", help="conversationId da conversa original.")
    fork_parser.add_argument("message_id", help="messageId da mensagem alvo da bifurcação.")
    fork_parser.add_argument(
        "--option",
        choices=sorted(_FORK_OPTION_CHOICES),
        default="all",
        help=(
            "visible-only = apenas mensagens visíveis (sem ramificações); "
            "related-branches = caminho direto + ramificações relacionadas; "
            "all (padrão) = todas as mensagens de/para o alvo, visíveis ou não."
        ),
    )
    fork_parser.add_argument(
        "--split-at-target",
        action="store_true",
        help="Corta a conversa bifurcada exatamente na mensagem alvo (não inclui respostas depois dela).",
    )
    fork_parser.add_argument(
        "--latest-message-id",
        default=None,
        help="Sobrepõe qual mensagem é tratada como 'mais recente' na bifurcação (default: message_id).",
    )

    return parser


def _add_chat_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-f", "--file", action="append", dest="files", default=[])
    parser.add_argument("--auto-files", action="store_true")
    parser.add_argument("--no-discovery", action="store_true")
    parser.add_argument(
        "--model", default=None, help="Id de modelo do catálogo (ver `meligpt models`)."
    )
    parser.add_argument(
        "--endpoint", default=None, help="Provedor lógico do catálogo (ver `meligpt providers`)."
    )
    parser.add_argument(
        "--media-dir",
        default=None,
        help=(
            "Onde salvar imagens/vídeos gerados neste turno (caminho relativo à "
            "raiz de arquivos configurada, ou absoluto em modo de acesso total). "
            "Sem isso, usa o destino padrão (MELIGPT_MEDIA_DIR / config_dir/generated-images)."
        ),
    )
    parser.add_argument(
        "--image",
        action="append",
        dest="images",
        default=[],
        help=(
            "Caminho de uma imagem local para anexar à mensagem (input multimodal — "
            "ex.: 'descreva essa imagem'). Pode ser usado várias vezes para anexar "
            "mais de uma. Diferente de -f/--file: aquele injeta o CONTEÚDO TEXTUAL "
            "de um arquivo no prompt; --image faz upload de verdade "
            "(POST /api/files/images, confirmado por HAR real) e anexa como imagem."
        ),
    )
    parser.add_argument("message", nargs="*")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    argv = _normalize_argv(argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level)

    command = getattr(args, "command", None) or "chat"

    if command == "import-har":
        return _run_import_har(args, settings)

    if command == "models":
        return asyncio.run(_run_models_command(args, settings))

    if command == "providers":
        return asyncio.run(_run_providers_command(settings))

    if command == "fork":
        return asyncio.run(_run_fork_command(args, settings))

    if command == "serve":
        _apply_serve_scope(args, settings)

    try:
        settings.resolved_files_dir()  # falha rápido em configuração insegura (ex.: FILES_DIR=/)
    except MeliGPTError as exc:
        console.error(exc.message)
        return 1

    if command == "serve":
        return _run_serve(args, settings)
    return asyncio.run(_run_chat_command(args, settings))


def _apply_serve_scope(args: argparse.Namespace, settings: Settings) -> None:
    """Aplica `--files-dir`/`--here` de `meligpt serve` ANTES do
    fail-fast check de `main()` — senão a validação rodaria em cima da
    config antiga (ex.: `FILES_DIR=/` sem acesso total no .env) mesmo
    quando o usuário está justamente sobrescrevendo isso na hora.
    """

    if args.here:
        scoped_dir = Path.cwd()
    elif args.files_dir:
        scoped_dir = Path(args.files_dir).expanduser().resolve()
    else:
        return

    settings.files_dir = scoped_dir
    settings.allow_full_filesystem_access = False
    console.info(f"Sandbox de arquivos restrito a: {scoped_dir}")
    console.warning(
        "bash começa nesta pasta, mas NÃO é limitado a ela (sem sandbox de "
        "processo) — um comando pode navegar/referenciar caminhos fora dela. "
        "Só ls/read_file/write_file/edit_file/glob/grep têm essa garantia."
    )


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


_TYPE_LABELS: dict[str, str] = {"chat": "GERAL (chat)", "image": "IMAGEM", "video": "VÍDEO"}
_TYPE_ORDER = ("chat", "image", "video")


async def _run_models_command(args: argparse.Namespace, settings: Settings) -> int:
    catalog = ModelCatalog(settings)
    models = await catalog.list_models(provider=args.provider, endpoint=args.endpoint)
    if not models:
        console.info("nenhum modelo encontrado.")
        return 0

    by_type: dict[str, list[ModelInfo]] = {t: [] for t in _TYPE_ORDER}
    for model in models:
        by_type.setdefault(model.type, []).append(model)

    for model_type in (*_TYPE_ORDER, *[t for t in by_type if t not in _TYPE_ORDER]):
        entries = by_type.get(model_type) or []
        if not entries:
            continue
        console.info(f"── {_TYPE_LABELS.get(model_type, model_type.upper())} ──")
        for model in entries:
            flag = "" if model.confirmed else "  [NÃO CONFIRMADO]"
            console.info(
                f"  {model.id}  [{model.provider} -> {model.payload_endpoint}, "
                f"rota={model.route}]{flag}"
            )
    return 0


async def _run_providers_command(settings: Settings) -> int:
    catalog = ModelCatalog(settings)
    for provider in await catalog.list_providers():
        console.info(f"{provider.id}  [{provider.route}]")
    return 0


async def _run_fork_command(args: argparse.Namespace, settings: Settings) -> int:
    new_request_id()
    option = _FORK_OPTION_CHOICES[args.option]

    async def prompt_for_har() -> Path | None:
        if not sys.stdin.isatty():
            return None
        answer = (
            input("\nDeseja importar um HAR recente e tentar novamente? [s/N] ").strip().lower()
        )
        if answer not in ("s", "sim"):
            return None
        return Path(input("Caminho do arquivo HAR: ").strip())

    try:
        result = await fork_conversation(
            conversation_id=args.conversation_id,
            message_id=args.message_id,
            settings=settings,
            option=option,
            split_at_target=args.split_at_target,
            latest_message_id=args.latest_message_id,
            interactive=sys.stdin.isatty(),
            prompt_for_har=prompt_for_har,
        )
    except MeliGPTError as exc:
        console.error(exc.message)
        return 1

    console.info(f"Conversa bifurcada: {result.conversation_id!r} ({result.title!r})")
    console.info(f"{result.message_count} mensagem(ns) copiada(s).")
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
    catalog = ModelCatalog(settings)
    try:
        # require_type=None: `meligpt chat` aceita modelos de vídeo/imagem
        # também, não só chat — a resposta (texto ou mídia baixada via
        # meligpt.media) é tratada igual independente do tipo do modelo.
        model_info = await resolve_model(
            catalog, model_id=args.model, provider=args.endpoint, require_type=None
        )
    except MeliGPTError as exc:
        console.error(exc.message)
        return 1

    async def prompt_for_har() -> Path | None:
        if not sys.stdin.isatty():
            return None
        answer = (
            input("\nDeseja importar um HAR recente e tentar novamente? [s/N] ").strip().lower()
        )
        if answer not in ("s", "sim"):
            return None
        return Path(input("Caminho do arquivo HAR: ").strip())

    attachments = None
    if args.images:
        images: list[ImageInput] = []
        for image_path in args.images:
            path = Path(image_path).expanduser()
            try:
                data = path.read_bytes()
            except OSError as exc:
                console.error(f"não foi possível ler '{image_path}': {exc}")
                return 1
            images.append(
                ImageInput(
                    data=data,
                    filename=path.name,
                    content_type=sniff_content_type(data),
                )
            )
        try:
            attachments = await upload_images(
                images,
                settings=settings,
                payload_endpoint=model_info.payload_endpoint if model_info else "openAI",
                interactive=sys.stdin.isatty(),
                prompt_for_har=prompt_for_har,
            )
        except MeliGPTError as exc:
            console.error(exc.message)
            return 1

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
            model_info=model_info,
            media_dir=args.media_dir,
            attachments=attachments,
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
            elif isinstance(event, GeneratedMedia):
                label = "Vídeo gerado" if event.media_type == "video" else "Imagem gerada"
                console.info(f"{label} salvo em: {event.virtual_path}")
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
