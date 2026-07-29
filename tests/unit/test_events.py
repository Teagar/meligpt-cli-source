from __future__ import annotations

from meligpt.chat.events import RawEvent, TextDeltaEvent, ToolCallEvent, parse_sse_data


def test_parse_text_delta() -> None:
    data = {
        "event": "on_message_delta",
        "data": {"delta": {"content": [{"type": "text", "text": "olá"}]}},
    }
    event = parse_sse_data(data)
    assert isinstance(event, TextDeltaEvent)
    assert event.text == "olá"


def test_parse_tool_call_completed() -> None:
    data = {
        "event": "on_run_step_completed",
        "data": {
            "result": {
                "type": "tool_call",
                "tool_call": {
                    "id": "call_1",
                    "name": "write_file",
                    "args": {"file_path": "/a.txt"},
                },
            }
        },
    }
    event = parse_sse_data(data)
    assert isinstance(event, ToolCallEvent)
    assert event.name == "write_file"
    assert event.arguments == {"file_path": "/a.txt"}


def test_parse_unknown_event_falls_back_to_raw() -> None:
    data = {"event": "something_else", "data": {}}
    event = parse_sse_data(data)
    assert isinstance(event, RawEvent)
    assert event.payload == data


def test_parse_empty_text_delta_falls_back_to_raw() -> None:
    data = {"event": "on_message_delta", "data": {"delta": {"content": []}}}
    event = parse_sse_data(data)
    assert isinstance(event, RawEvent)
