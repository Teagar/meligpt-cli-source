from __future__ import annotations

from meligpt.ui import console


def test_info_survives_brackets_in_message(capsys) -> None:
    """Regressão: `meligpt providers` formatava a rota como
    "id  [rota]" e o `rich` interpretava `[rota]` como uma tag de markup
    não fechada, derrubando o comando com `MarkupError`.
    """

    console.info("gpt-5.6-sol  [openAI -> /api/ask/openAI]")
    captured = capsys.readouterr()
    assert "[openAI -> /api/ask/openAI]" in captured.err


def test_warning_survives_brackets_in_message(capsys) -> None:
    console.warning("valor inesperado: [1, 2, 3]")
    captured = capsys.readouterr()
    assert "[1, 2, 3]" in captured.err


def test_error_survives_brackets_in_message(capsys) -> None:
    console.error("caminho inválido: /tmp/[teste]/arquivo.txt")
    captured = capsys.readouterr()
    assert "/tmp/[teste]/arquivo.txt" in captured.err


def test_header_survives_brackets_in_model_name(capsys) -> None:
    console.header("modelo-[experimental]")
    captured = capsys.readouterr()
    assert "modelo-[experimental]" in captured.err
