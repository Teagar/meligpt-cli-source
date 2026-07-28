from __future__ import annotations

from meligpt.chat.prompt_builder import (
    extract_auto_file_references,
    extract_directory_hint,
    extract_file_name_hint,
    extract_requested_directory_name,
    interpret_prompt,
    prompt_requests_directory_content,
)


def test_extract_file_name_hint_finds_extension() -> None:
    assert extract_file_name_hint("leia o HelloWorld.java por favor") == "HelloWorld.java"


def test_extract_file_name_hint_none_when_absent() -> None:
    assert extract_file_name_hint("me ajude com o projeto") is None


def test_extract_directory_hint() -> None:
    assert extract_directory_hint("leia o arquivo dentro da pasta thiago") == "thiago"


def test_extract_requested_directory_name_backtick_priority() -> None:
    prompt = 'mostre a pasta `calculadora` e não a pasta "outra"'
    assert extract_requested_directory_name(prompt) == "calculadora"


def test_extract_requested_directory_name_double_quotes() -> None:
    prompt = 'mostre a pasta "calculadora-docker"'
    assert extract_requested_directory_name(prompt) == "calculadora-docker"


def test_extract_requested_directory_name_plain() -> None:
    prompt = "mostre a pasta calculadora"
    assert extract_requested_directory_name(prompt) == "calculadora"


def test_prompt_requests_directory_content_true() -> None:
    assert prompt_requests_directory_content("qual o conteúdo da pasta thiago?")


def test_prompt_requests_directory_content_false() -> None:
    assert not prompt_requests_directory_content("leia o HelloWorld.java")


def test_extract_auto_file_references_multiple_dedup() -> None:
    prompt = "compare /files/a.txt com /files/b.txt e de novo /files/a.txt."
    assert extract_auto_file_references(prompt) == ["/files/a.txt", "/files/b.txt"]


def test_interpret_prompt_auto_files_disabled() -> None:
    result = interpret_prompt("veja /files/a.txt", auto_files=False, discovery_enabled=True)
    assert result.explicit_files == []


def test_interpret_prompt_discovery_disabled_skips_hints() -> None:
    result = interpret_prompt(
        "leia HelloWorld.java na pasta thiago", auto_files=False, discovery_enabled=False
    )
    assert result.file_name_hint is None
    assert result.directory_name_hint is None
