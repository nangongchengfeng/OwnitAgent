from __future__ import annotations

import json
from types import SimpleNamespace

from openai import OpenAI
from rich.console import Console
from rich.live import Live

from config import WORKSPACE_ROOT, TOOL_CALL_LIMIT, build_client, get_settings, load_env_file
from memory_manager import ensure_memory_scaffold
from models import Settings, TokenUsageStats, WorkingMemoryState
from prompts import (
    build_initial_history,
    build_runtime_messages,
    record_working_memory,
)
from tools import TOOLS, execute_tool, normalize_tool_outcome, serialize_tool_data
from ui import (
    build_console,
    build_reply_panel,
    build_tool_result_message,
    build_tool_start_message,
    build_turn_message,
    build_welcome_panel,
)

EMPTY_RESPONSE_MESSAGE = "模型未返回内容，也未发起工具调用，请重试或检查模型/网关兼容性。"


def record_token_usage(stats: TokenUsageStats, response: object) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    stats.input_tokens += getattr(usage, "prompt_tokens", 0) or 0
    stats.output_tokens += getattr(usage, "completion_tokens", 0) or 0


def build_token_summary(stats: TokenUsageStats) -> str:
    return f"[dim]Token 统计 — 输入: {stats.input_tokens} | 输出: {stats.output_tokens}[/]"


def _has_message_content(message: object) -> bool:
    return bool((getattr(message, "content", None) or "").strip())


def _parse_tool_calls(
    message: object,
    console: Console,
    report_errors: bool = True,
) -> tuple[list[object], list[tuple[object, dict]], bool]:
    tool_calls = getattr(message, "tool_calls", None) or []
    parsed_tool_calls: list[tuple[object, dict]] = []
    for tool_call in tool_calls:
        try:
            tool_args = json.loads(tool_call.function.arguments or "{}")
        except json.JSONDecodeError as error:
            if report_errors:
                console.print(
                    "[red]工具参数解析失败[/] "
                    f"[dim]{tool_call.function.name}: {error.msg} (pos {error.pos})[/]"
                )
            return tool_calls, [], False
        parsed_tool_calls.append((tool_call, tool_args))
    return tool_calls, parsed_tool_calls, True


def _stream_response_to_message(
    response: object,
    console: Console,
    live_factory=Live,
    token_stats: TokenUsageStats | None = None,
) -> tuple[object, bool]:
    if hasattr(response, "choices"):
        if token_stats is not None:
            record_token_usage(token_stats, response)
        return response.choices[0].message, False

    reply_parts: list[str] = []
    streamed_tool_calls: dict[int, dict[str, object]] = {}
    rendered = False

    with live_factory(console=console, refresh_per_second=8) as live:
        for chunk in response:
            if token_stats is not None:
                record_token_usage(token_stats, chunk)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue

            delta = choices[0].delta
            content_delta = getattr(delta, "content", None) or ""
            if content_delta:
                reply_parts.append(content_delta)
                live.update(build_reply_panel("".join(reply_parts)))
                rendered = True

            for tool_call in getattr(delta, "tool_calls", None) or []:
                index = getattr(tool_call, "index", 0)
                function = getattr(tool_call, "function", None)
                tool_state = streamed_tool_calls.setdefault(
                    index,
                    {
                        "id": "",
                        "function": {"name": "", "arguments": ""},
                    },
                )
                tool_id = getattr(tool_call, "id", None)
                if tool_id:
                    tool_state["id"] = tool_id
                if function is None:
                    continue
                function_name = getattr(function, "name", None)
                if function_name:
                    tool_state["function"]["name"] += function_name
                function_arguments = getattr(function, "arguments", None)
                if function_arguments:
                    tool_state["function"]["arguments"] += function_arguments

    tool_calls = [
        SimpleNamespace(
            id=tool_state["id"],
            function=SimpleNamespace(
                name=tool_state["function"]["name"],
                arguments=tool_state["function"]["arguments"],
            ),
        )
        for _, tool_state in sorted(streamed_tool_calls.items())
    ]
    message = SimpleNamespace(content="".join(reply_parts), tool_calls=tool_calls)
    return message, rendered


def serialize_tool_call(tool_call: object) -> dict:
    function = getattr(tool_call, "function")
    return {
        "id": getattr(tool_call, "id"),
        "type": "function",
        "function": {
            "name": getattr(function, "name"),
            "arguments": getattr(function, "arguments"),
        },
    }


def serialize_assistant_message(message: object) -> dict:
    tool_calls = getattr(message, "tool_calls", None) or []
    payload = {
        "role": "assistant",
        "content": getattr(message, "content", None) or "",
    }
    if tool_calls:
        payload["tool_calls"] = [
            serialize_tool_call(tool_call) for tool_call in tool_calls
        ]
    return payload


def handle_control_command(
    command: str,
    console: Console,
    history: list[dict[str, str]],
) -> tuple[bool, list[dict[str, str]]]:
    if command == "clear":
        console.print("[dim]历史已清空[/]")
        return True, build_initial_history()
    return False, history


def chat_once(
    client: OpenAI,
    settings: Settings,
    history: list[dict[str, str]],
    console: Console,
    live_factory=Live,
    token_stats: TokenUsageStats | None = None,
) -> str:
    response = client.chat.completions.create(
        model=settings.model,
        messages=history,
        stream=True,
        stream_options={"include_usage": True},
    )
    message, _ = _stream_response_to_message(
        response,
        console,
        live_factory=live_factory,
        token_stats=token_stats,
    )
    return message.content or ""


def _request_chat_message(
    client: OpenAI,
    settings: Settings,
    runtime_messages: list[dict[str, str]],
    console: Console,
    live_factory=Live,
    token_stats: TokenUsageStats | None = None,
    stream: bool = True,
) -> tuple[object, bool]:
    request_kwargs: dict[str, object] = {
        "model": settings.model,
        "messages": runtime_messages,
        "tools": TOOLS,
    }
    if stream:
        request_kwargs["stream"] = True
        request_kwargs["stream_options"] = {"include_usage": True}
    response = client.chat.completions.create(**request_kwargs)
    if stream:
        return _stream_response_to_message(
            response,
            console,
            live_factory=live_factory,
            token_stats=token_stats,
        )
    if token_stats is not None:
        record_token_usage(token_stats, response)
    return response.choices[0].message, False


def chat(
    user_input: str,
    client: OpenAI,
    settings: Settings,
    history: list[dict[str, str]],
    console: Console,
    execute_tool_fn=execute_tool,
    token_stats: TokenUsageStats | None = None,
    session_memory: WorkingMemoryState | None = None,
    live_factory=Live,
) -> str:
    session_memory = session_memory or WorkingMemoryState()
    history.append({"role": "user", "content": user_input})
    tool_count = 0

    while True:
        session_memory.current_turn += 1
        runtime_messages = build_runtime_messages(
            history,
            session_memory,
            workspace_root=WORKSPACE_ROOT,
        )
        console.print(build_turn_message(session_memory.current_turn))
        message, content_rendered = _request_chat_message(
            client,
            settings,
            runtime_messages,
            console,
            live_factory=live_factory,
            token_stats=token_stats,
            stream=True,
        )
        tool_calls, parsed_tool_calls, parse_ok = _parse_tool_calls(
            message,
            console,
            report_errors=False,
        )
        used_non_stream_fallback = False

        if not parse_ok:
            message, _ = _request_chat_message(
                client,
                settings,
                runtime_messages,
                console,
                live_factory=live_factory,
                token_stats=token_stats,
                stream=False,
            )
            used_non_stream_fallback = True
            tool_calls, parsed_tool_calls, parse_ok = _parse_tool_calls(message, console)
            if not parse_ok:
                return message.content or ""
            if _has_message_content(message) and not content_rendered:
                console.print(build_reply_panel(message.content))
                content_rendered = True

        if not _has_message_content(message) and not tool_calls and not used_non_stream_fallback:
            message, _ = _request_chat_message(
                client,
                settings,
                runtime_messages,
                console,
                live_factory=live_factory,
                token_stats=token_stats,
                stream=False,
            )
            used_non_stream_fallback = True
            tool_calls, parsed_tool_calls, parse_ok = _parse_tool_calls(message, console)
            if not parse_ok:
                return message.content or ""
            if _has_message_content(message) and not content_rendered:
                console.print(build_reply_panel(message.content))
                content_rendered = True

        empty_response = not _has_message_content(message) and not tool_calls
        record_working_memory(session_memory, message.content or "", tool_calls)
        history.append(serialize_assistant_message(message))

        if empty_response:
            console.print(f"[yellow]{EMPTY_RESPONSE_MESSAGE}[/]")
            return ""

        if not tool_calls:
            if _has_message_content(message) and not content_rendered:
                console.print(build_reply_panel(message.content))
            return message.content or ""

        for tool_call, tool_args in parsed_tool_calls:
            if tool_count >= TOOL_CALL_LIMIT:
                console.print(f"[red]Tool call limit reached ({TOOL_CALL_LIMIT})[/]")
                return ""

            tool_count += 1
            tool_name = tool_call.function.name
            console.print(build_tool_start_message(tool_count, tool_name, tool_args))
            result = execute_tool_fn(
                tool_name,
                tool_args,
                workspace_root=WORKSPACE_ROOT,
                session_memory=session_memory,
            )
            outcome = normalize_tool_outcome(result)
            result_text = serialize_tool_data(outcome.data)
            console.print(build_tool_result_message(result_text))
            if outcome.should_exit:
                return result_text
            history.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": result_text,
                }
            )


def run_chat(console: Console | None = None, live_factory=Live) -> None:
    load_env_file()
    ensure_memory_scaffold(WORKSPACE_ROOT)
    settings = get_settings()
    client = build_client(settings)
    console = console or build_console()
    history = build_initial_history()
    token_stats = TokenUsageStats()
    session_memory = WorkingMemoryState()

    console.print(build_welcome_panel(settings))
    try:
        while True:
            console.print()
            user_input = console.input("[bold green]You >[/] ").strip()
            if user_input.lower() in {"exit", "quit"}:
                break
            if not user_input:
                continue

            handled, history = handle_control_command(user_input.lower(), console, history)
            if handled:
                session_memory = WorkingMemoryState()
                continue

            chat(
                user_input,
                client,
                settings,
                history,
                console,
                token_stats=token_stats,
                session_memory=session_memory,
            )
    except KeyboardInterrupt:
        console.print("\n[yellow]检测到 Ctrl+C，请求已中断，正在退出会话。[/]")
    finally:
        console.print(build_token_summary(token_stats))
