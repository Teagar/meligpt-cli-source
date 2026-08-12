from __future__ import annotations

from meligpt.api.openai_compat import ChatMessage, _build_transcript_prompt


def test_single_user_message_passthrough() -> None:
    messages = [ChatMessage(role="user", content="Olá")]
    assert _build_transcript_prompt(messages) == "Olá"


def test_multi_turn_includes_full_history() -> None:
    messages = [
        ChatMessage(role="user", content="Ola"),
        ChatMessage(role="assistant", content="Olá! Como posso ajudar?"),
        ChatMessage(role="user", content="Seu nome será Joao"),
        ChatMessage(role="assistant", content="Combinado! Pode me chamar de João."),
        ChatMessage(role="user", content="Qual é o seu nome?"),
    ]
    prompt = _build_transcript_prompt(messages)

    assert "Usuário: Ola" in prompt
    assert "Assistente: Olá! Como posso ajudar?" in prompt
    assert "Usuário: Seu nome será Joao" in prompt
    assert "Combinado! Pode me chamar de João." in prompt
    assert "Usuário: Qual é o seu nome?" in prompt
    assert prompt.rstrip().endswith("Assistente:")


def test_system_message_included_as_instructions() -> None:
    messages = [
        ChatMessage(role="system", content="Você é um assistente de código."),
        ChatMessage(role="user", content="oi"),
        ChatMessage(role="assistant", content="olá"),
        ChatMessage(role="user", content="tudo bem?"),
    ]
    prompt = _build_transcript_prompt(messages)
    assert "Você é um assistente de código." in prompt
    assert "[Instruções do sistema]" in prompt


def test_empty_messages_returns_empty_string() -> None:
    assert _build_transcript_prompt([]) == ""


def test_blank_content_messages_are_skipped() -> None:
    messages = [
        ChatMessage(role="user", content="   "),
        ChatMessage(role="user", content="mensagem real"),
    ]
    prompt = _build_transcript_prompt(messages)
    assert "mensagem real" in prompt
