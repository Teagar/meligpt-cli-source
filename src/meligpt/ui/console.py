"""Saída visual da CLI (aprimoramento sobre o ``printf`` puro do Bash).

Usa ``rich`` quando disponível; cai para ``print`` simples em stdout/stderr
caso a saída não seja um terminal (ex.: redirecionada para arquivo/pipe),
preservando a legibilidade em scripts que consumem a saída da CLI.
"""

from __future__ import annotations

import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.status import Status
from rich.text import Text

_stdout = Console()
_stderr = Console(stderr=True)


def info(message: str) -> None:
    _stderr.print(f"[dim]›[/dim] {escape(message)}")


def warning(message: str) -> None:
    _stderr.print(f"[yellow]⚠ {escape(message)}[/yellow]")


def error(message: str) -> None:
    _stderr.print(f"[bold red]Erro:[/bold red] {escape(message)}")


def tool_result(name: str, success: bool, message: str) -> None:
    icon = "[green]✓[/green]" if success else "[red]✗[/red]"
    _stderr.print(f"{icon} [bold]{escape(name)}[/bold]")
    _stderr.print(Text(message, style="dim"), soft_wrap=True)


def header(model: str) -> None:
    _stderr.print(Panel.fit(f"MeliGPT CLI · [bold]{escape(model)}[/bold]", border_style="cyan"))


def sending_status() -> Status:
    return _stderr.status("[cyan]Enviando mensagem...[/cyan]", spinner="dots")


def stream_chunk(text: str) -> None:
    _stdout.file.write(text)
    _stdout.file.flush()


def stream_start() -> None:
    _stderr.print("[bold cyan]IA:[/bold cyan]")


def stream_end() -> None:
    _stdout.file.write("\n")
    _stdout.file.flush()


def render_markdown_summary(text: str) -> None:
    if not sys.stdout.isatty():
        return
    _stderr.print(Panel(Markdown(text), title="resumo", border_style="dim"))
