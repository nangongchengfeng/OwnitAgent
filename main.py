"""MagicCode v1 - 从 .env 读取配置的终端 AI 助手。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel

DEFAULT_ENV_PATH = Path(__file__).with_name(".env")
DEFAULT_MODEL = "deepseek-ai/DeepSeek-V4-Flash"
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1"
WORKSPACE_ROOT = Path(__file__).resolve().parent
IGNORED_PATH_NAMES = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
    "dist",
    "build",
}
LIST_FILES_MAX_DEPTH = 3
SEARCH_RESULT_LIMIT = 50
TOOL_CALL_LIMIT = 20
BASE_SYSTEM_PROMPT = (
    "You are MagicCode, a terminal AI coding assistant. "
    "Be concise and helpful. Format responses in Markdown."
)


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    base_url: str


@dataclass
class TokenUsageStats:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class StepOutcome:
    data: Any
    next_prompt: str | None = None
    should_exit: bool = False


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


TOOLS = [
    _fn(
        "read_file",
        "Read the contents of a file. Returns the content with line numbers.",
        {"path": {"type": "string", "description": "File path to read"}},
        ["path"],
    ),
    _fn(
        "write_file",
        "Write content to a file. Creates parent directories if needed.",
        {
            "path": {"type": "string", "description": "File path"},
            "content": {"type": "string", "description": "Complete file content"},
        },
        ["path", "content"],
    ),
    _fn(
        "edit_file",
        "Replace old_text with new_text in a file (first match).",
        {
            "path": {"type": "string", "description": "File path"},
            "old_text": {"type": "string", "description": "Text to find"},
            "new_text": {"type": "string", "description": "Replacement text"},
        },
        ["path", "old_text", "new_text"],
    ),
    _fn(
        "delete_file",
        "Delete a file or directory inside the workspace.",
        {"path": {"type": "string", "description": "File or directory path"}},
        ["path"],
    ),
    _fn(
        "rename_file",
        "Rename or move a file or directory inside the workspace.",
        {
            "old_path": {"type": "string", "description": "Current file path"},
            "new_path": {"type": "string", "description": "New file path"},
        },
        ["old_path", "new_path"],
    ),
    _fn(
        "run_command",
        "Execute a shell command. Times out after 30 seconds.",
        {"command": {"type": "string", "description": "Shell command to execute"}},
        ["command"],
    ),
    _fn(
        "list_files",
        "Recursively list directory contents up to 3 levels deep.",
        {"path": {"type": "string", "description": "Directory path", "default": "."}},
        [],
    ),
    _fn(
        "search_code",
        "Search for a text pattern across files in a directory.",
        {
            "pattern": {"type": "string", "description": "Search pattern"},
            "path": {"type": "string", "description": "Search directory", "default": "."},
        },
        ["pattern"],
    ),
    _fn(
        "grep_search",
        "Search for a regular expression pattern across files in a directory.",
        {
            "pattern": {"type": "string", "description": "Regular expression pattern"},
            "path": {"type": "string", "description": "Search directory", "default": "."},
        },
        ["pattern"],
    ),
]

def load_env_file(env_path: Path = DEFAULT_ENV_PATH) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        key, separator, value = line.partition("=")
        if not separator:
            continue

        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def get_settings() -> Settings:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("缺少 OPENAI_API_KEY，请检查 .env 配置。")

    return Settings(
        api_key=api_key,
        model=os.environ.get("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        base_url=os.environ.get("OPENAI_BASE_URL", DEFAULT_BASE_URL).strip()
        or DEFAULT_BASE_URL,
    )


def build_client(settings: Settings) -> OpenAI:
    return OpenAI(api_key=settings.api_key, base_url=settings.base_url)


def load_project_context(workspace_root: Path = WORKSPACE_ROOT) -> str:
    context_parts: list[str] = []
    for name in ["CLAUDE.md", "AGENTS.md", "README.md"]:
        path = workspace_root / name
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        context_parts.append(f"--- {name} ---\n{content}")
    return "\n\n".join(context_parts)


def build_system_prompt(workspace_root: Path = WORKSPACE_ROOT) -> str:
    project_context = load_project_context(workspace_root)
    if not project_context:
        return BASE_SYSTEM_PROMPT
    return f"{BASE_SYSTEM_PROMPT}\n\n## Project Context\n{project_context}"


def build_initial_history(workspace_root: Path = WORKSPACE_ROOT) -> list[dict[str, str]]:
    return [{"role": "system", "content": build_system_prompt(workspace_root)}]


def record_token_usage(stats: TokenUsageStats, response: object) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    stats.input_tokens += getattr(usage, "prompt_tokens", 0) or 0
    stats.output_tokens += getattr(usage, "completion_tokens", 0) or 0


def build_token_summary(stats: TokenUsageStats) -> str:
    return (
        f"[dim]Token 统计 — 输入: {stats.input_tokens} | 输出: {stats.output_tokens}[/]"
    )


def resolve_workspace_path(path: str, workspace_root: Path = WORKSPACE_ROOT) -> Path:
    root = workspace_root.resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (root / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"路径超出工作区: {path}") from error
    return candidate


def preview_text(text: str, limit: int = 100) -> str:
    preview = text[:limit].replace("\n", " ")
    if len(text) > limit:
        preview += "..."
    return preview


def _clean_content(text: str, shrink_code_blocks: bool = True) -> str:
    if not text:
        return ""

    def shrink_code(match: re.Match[str]) -> str:
        lines = match.group(0).split("\n")
        language = lines[0].replace("```", "").strip()
        body = [line for line in lines[1:-1] if line.strip()]
        if len(body) <= 6:
            return match.group(0)
        preview = "\n".join(body[:5])
        return f"```{language}\n{preview}\n  ... ({len(body)} lines)\n```"

    cleaned = text
    if shrink_code_blocks:
        cleaned = re.sub(r"```[\s\S]*?```", shrink_code, cleaned)
    cleaned = re.sub(r"<file_content>[\s\S]*?</file_content>", "", cleaned)
    cleaned = re.sub(r"<tool_(?:use|call)>[\s\S]*?</tool_(?:use|call)>", "", cleaned)
    cleaned = re.sub(r"(\r?\n){3,}", "\n\n", cleaned)
    return cleaned.strip()


def _compact_tool_args(name: str, args: dict) -> str:
    compact_args = {key: value for key, value in args.items() if key != "_index"}
    for key in ("path", "old_path", "new_path"):
        if key in compact_args:
            compact_args[key] = os.path.basename(str(compact_args[key]))

    compact = json.dumps(compact_args, ensure_ascii=False)
    if len(compact) > 120:
        compact = compact[:120] + "..."
    return compact


def normalize_tool_outcome(result: Any) -> StepOutcome:
    if isinstance(result, StepOutcome):
        return result
    return StepOutcome(data=result)


def serialize_tool_data(data: Any) -> str:
    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False)
    if data is None:
        return ""
    return str(data)


def execute_tool(
    name: str,
    params: dict,
    workspace_root: Path = WORKSPACE_ROOT,
) -> str:
    try:
        if name == "read_file":
            path = resolve_workspace_path(params["path"], workspace_root)
            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            numbered = "\n".join(
                f"{index + 1:4d} | {line}" for index, line in enumerate(lines)
            )
            return f"{path} ({len(lines)} lines)\n{numbered}"

        if name == "write_file":
            path = resolve_workspace_path(params["path"], workspace_root)
            path.parent.mkdir(parents=True, exist_ok=True)
            content = params["content"]
            path.write_text(content, encoding="utf-8")
            return f"Written to {path} ({len(content)} chars)"

        if name == "edit_file":
            path = resolve_workspace_path(params["path"], workspace_root)
            content = path.read_text(encoding="utf-8", errors="replace")
            old_text = params["old_text"]
            if old_text not in content:
                return "Error: Target text not found in file"
            new_content = content.replace(old_text, params["new_text"], 1)
            path.write_text(new_content, encoding="utf-8")
            return f"Edited {path}"

        if name == "delete_file":
            path = resolve_workspace_path(params["path"], workspace_root)
            if not path.exists():
                return f"Error: Path not found: {path}"
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            return f"Deleted {path}"

        if name == "rename_file":
            old_path = resolve_workspace_path(params["old_path"], workspace_root)
            new_path = resolve_workspace_path(params["new_path"], workspace_root)
            if not old_path.exists():
                return f"Error: Path not found: {old_path}"
            if new_path.exists():
                return f"Error: Target already exists: {new_path}"
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            return f"Renamed {old_path} -> {new_path}"

        if name == "run_command":
            command = params["command"]
            dangerous = ["rm -rf /", "mkfs", "dd if=", "> /dev/sd"]
            if any(item in command for item in dangerous):
                return "Refused to execute dangerous command"

            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=str(workspace_root),
            )
            output = result.stdout
            if result.stderr:
                output += "\n--- stderr ---\n" + result.stderr
            return output.strip() or "(Command completed with no output)"

        if name == "list_files":
            path = resolve_workspace_path(params.get("path", "."), workspace_root)
            result: list[str] = []

            def walk_directory(current_path: Path, prefix: str = "", depth: int = 0) -> None:
                if depth >= LIST_FILES_MAX_DEPTH:
                    return

                entries = sorted(
                    entry for entry in current_path.iterdir() if entry.name not in IGNORED_PATH_NAMES
                )
                for entry in entries:
                    if entry.is_dir():
                        result.append(f"{prefix}[dir] {entry.name}/")
                        walk_directory(entry, prefix + "  ", depth + 1)
                    else:
                        result.append(f"{prefix}[file] {entry.name}")

            walk_directory(path)
            return "\n".join(result) or "Empty directory"

        if name == "search_code":
            pattern = params["pattern"].lower()
            path = resolve_workspace_path(params.get("path", "."), workspace_root)
            matches: list[str] = []

            for current_root, dir_names, file_names in os.walk(path):
                dir_names[:] = [
                    dir_name for dir_name in dir_names if dir_name not in IGNORED_PATH_NAMES
                ]
                for file_name in sorted(file_names):
                    file_path = Path(current_root) / file_name
                    try:
                        with file_path.open("r", encoding="utf-8", errors="replace") as file:
                            for index, line in enumerate(file, start=1):
                                if pattern in line.lower():
                                    relative_path = file_path.relative_to(workspace_root)
                                    matches.append(f"{relative_path}:{index}: {line.rstrip()}")
                                    if len(matches) >= SEARCH_RESULT_LIMIT:
                                        return "\n".join(matches)
                    except OSError:
                        continue

            return "\n".join(matches) or f"No matches for '{params['pattern']}'"

        if name == "grep_search":
            regex = re.compile(params["pattern"])
            path = resolve_workspace_path(params.get("path", "."), workspace_root)
            matches: list[str] = []

            for current_root, dir_names, file_names in os.walk(path):
                dir_names[:] = [
                    dir_name for dir_name in dir_names if dir_name not in IGNORED_PATH_NAMES
                ]
                for file_name in sorted(file_names):
                    file_path = Path(current_root) / file_name
                    try:
                        with file_path.open("r", encoding="utf-8", errors="replace") as file:
                            for index, line in enumerate(file, start=1):
                                if regex.search(line):
                                    relative_path = file_path.relative_to(workspace_root)
                                    matches.append(f"{relative_path}:{index}: {line.rstrip()}")
                                    if len(matches) >= SEARCH_RESULT_LIMIT:
                                        return "\n".join(matches)
                    except OSError:
                        continue

            return "\n".join(matches) or f"No matches for regex '{params['pattern']}'"

        return f"Error: unknown tool: {name}"
    except Exception as error:
        return f"Error: {type(error).__name__}: {error}"


def build_console() -> Console:
    return Console()


def build_welcome_panel(settings: Settings) -> Panel:
    return Panel(
        "[bold cyan]MagicCode v3[/] - 终端 AI 编程助手\n"
        f"当前模型: {settings.model}\n"
        "输入 'exit' 退出",
        border_style="cyan",
    )


def build_reply_panel(reply: str) -> Panel:
    return Panel(
        Markdown(_clean_content(reply, shrink_code_blocks=False)),
        title="MagicCode",
        border_style="blue",
    )


def build_tool_start_message(tool_index: int, name: str, args: dict) -> str:
    return f"  [yellow][{tool_index}] {name}[/] [dim]{_compact_tool_args(name, args)}[/]"


def build_tool_result_message(result: str) -> str:
    return f"  [green]Done[/] [dim]{preview_text(_clean_content(result))}[/]"


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
        stream=True,  # 关键改动
    )
    if token_stats is not None:
        record_token_usage(token_stats, response)
    reply_parts: list[str] = []

    with live_factory(console=console, refresh_per_second=8) as live:
        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue
            reply_parts.append(delta)
            live.update(build_reply_panel("".join(reply_parts)))

    return "".join(reply_parts)


def chat(
    user_input: str,
    client: OpenAI,
    settings: Settings,
    history: list[dict[str, str]],
    console: Console,
    execute_tool_fn=execute_tool,
    token_stats: TokenUsageStats | None = None,
) -> str:
    history.append({"role": "user", "content": user_input})
    tool_count = 0

    while True:
        response = client.chat.completions.create(
            model=settings.model,
            messages=history,
            tools=TOOLS,
        )
        if token_stats is not None:
            record_token_usage(token_stats, response)
        message = response.choices[0].message
        history.append(serialize_assistant_message(message))

        if message.content:
            console.print(build_reply_panel(message.content))

        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return message.content or ""

        for tool_call in tool_calls:
            if tool_count >= TOOL_CALL_LIMIT:
                console.print(f"[red]Tool call limit reached ({TOOL_CALL_LIMIT})[/]")
                return ""

            tool_count += 1
            tool_name = tool_call.function.name
            tool_args = json.loads(tool_call.function.arguments or "{}")
            console.print(build_tool_start_message(tool_count, tool_name, tool_args))
            result = execute_tool_fn(
                tool_name,
                tool_args,
                workspace_root=WORKSPACE_ROOT,
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
    settings = get_settings()
    client = build_client(settings)
    console = console or build_console()
    history = build_initial_history()
    token_stats = TokenUsageStats()

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
                continue

            chat(
                user_input,
                client,
                settings,
                history,
                console,
                token_stats=token_stats,
            )
    except KeyboardInterrupt:
        console.print("\n[cyan]再见！[/]")
    finally:
        console.print(build_token_summary(token_stats))


if __name__ == "__main__":
    run_chat()
