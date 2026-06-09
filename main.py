"""OwnitAgent v1 - 从 .env 读取配置的终端 AI 助手。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any
from dataclasses import dataclass, field
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
MEMORY_DIR_NAME = "memory"
MEMORY_ROOT = WORKSPACE_ROOT / MEMORY_DIR_NAME
MEMORY_L0_FILE = "memory_management_sop.md"
MEMORY_L1_FILE = "global_mem_insight.txt"
MEMORY_L2_FILE = "global_mem.txt"
WORKING_HISTORY_WINDOW = 30
SUMMARY_MAX_LENGTH = 80
MEMORY_REFRESH_INTERVAL = 10
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
    "You are OwnitAgent, a terminal AI coding assistant. "
    "Be concise and helpful. Format responses in Markdown."
)
DEFAULT_MEMORY_MANAGEMENT_SOP = """# Memory Management SOP

1. 只有工具调用成功验证的信息才能写入记忆。
2. 禁止把推理猜测、计划草稿、易变状态写入记忆。
3. L1 只保留极简索引，L2 保留环境事实，L3 保留 SOP 和复用脚本。
4. 写入记忆前，先确认信息对跨会话仍有价值。
"""
DEFAULT_MEMORY_INSIGHT = """# Global Memory Insight

[RULES]
1. 写入记忆前先核对 memory_management_sop.md
2. 仅记录执行验证过的关键事实与 SOP
"""
DEFAULT_MEMORY_FACTS = """# Global Memory - L2

## [PATHS]
PROJECT_ROOT = .
"""


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


@dataclass
class WorkingMemoryState:
    history_info: list[str] = field(default_factory=list)
    key_info: str = ""
    related_sop: str = ""
    current_turn: int = 0


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
        "read_memory",
        "Read a memory file inside the memory directory.",
        {"path": {"type": "string", "description": "Memory file path relative to memory/"}},
        ["path"],
    ),
    _fn(
        "write_memory",
        "Write verified information into a memory file inside the memory directory.",
        {
            "path": {"type": "string", "description": "Memory file path relative to memory/"},
            "content": {"type": "string", "description": "Verified memory content"},
            "append": {"type": "boolean", "description": "Append instead of overwrite", "default": False},
        },
        ["path", "content"],
    ),
    _fn(
        "update_working_checkpoint",
        "Update working memory with the current key checkpoint and related SOP path.",
        {
            "key_info": {"type": "string", "description": "Short validated checkpoint summary"},
            "related_sop": {"type": "string", "description": "Related SOP path for later reference"},
        },
        [],
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


def get_memory_root(workspace_root: Path = WORKSPACE_ROOT) -> Path:
    return workspace_root / MEMORY_DIR_NAME


def ensure_memory_scaffold(workspace_root: Path = WORKSPACE_ROOT) -> None:
    memory_root = get_memory_root(workspace_root)
    memory_root.mkdir(parents=True, exist_ok=True)
    for directory in ("task_sops", "tools", "sessions", "L4_raw_sessions"):
        (memory_root / directory).mkdir(parents=True, exist_ok=True)

    defaults = {
        MEMORY_L0_FILE: DEFAULT_MEMORY_MANAGEMENT_SOP,
        MEMORY_L1_FILE: DEFAULT_MEMORY_INSIGHT,
        MEMORY_L2_FILE: DEFAULT_MEMORY_FACTS,
    }
    for file_name, content in defaults.items():
        path = memory_root / file_name
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def resolve_memory_path(path: str, workspace_root: Path = WORKSPACE_ROOT) -> Path:
    memory_root = get_memory_root(workspace_root).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = (memory_root / candidate).resolve()
    else:
        candidate = candidate.resolve()

    try:
        candidate.relative_to(memory_root)
    except ValueError as error:
        raise ValueError(f"记忆路径超出 memory 目录: {path}") from error
    return candidate


def is_memory_path(path: Path, workspace_root: Path = WORKSPACE_ROOT) -> bool:
    memory_root = get_memory_root(workspace_root).resolve()
    try:
        path.resolve().relative_to(memory_root)
        return True
    except ValueError:
        return False


def reject_memory_file_tool(path: Path, workspace_root: Path = WORKSPACE_ROOT) -> str | None:
    if is_memory_path(path, workspace_root):
        return "Error: memory paths are managed separately. Use memory tools instead."
    return None


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip()


def load_project_context(workspace_root: Path = WORKSPACE_ROOT) -> str:
    context_parts: list[str] = []
    for name in ["CLAUDE.md", "AGENTS.md", "README.md"]:
        path = workspace_root / name
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        context_parts.append(f"--- {name} ---\n{content}")
    return "\n\n".join(context_parts)


def build_memory_context(workspace_root: Path = WORKSPACE_ROOT) -> str:
    memory_root = get_memory_root(workspace_root)
    if not memory_root.exists():
        return ""

    insight = read_text_if_exists(memory_root / MEMORY_L1_FILE)
    facts = read_text_if_exists(memory_root / MEMORY_L2_FILE)
    return (
        "## Memory Context\n"
        f"[Memory Root] {MEMORY_DIR_NAME}/\n"
        f"L0: {MEMORY_DIR_NAME}/{MEMORY_L0_FILE}\n"
        f"L1: {MEMORY_DIR_NAME}/{MEMORY_L1_FILE}\n"
        f"L2: {MEMORY_DIR_NAME}/{MEMORY_L2_FILE}\n"
        f"L3: {MEMORY_DIR_NAME}/task_sops/ and {MEMORY_DIR_NAME}/tools/\n\n"
        f"[L1 Insight]\n{insight or '(empty)'}\n\n"
        f"[L2 Facts]\n{facts or '(empty)'}"
    )


def build_system_prompt(workspace_root: Path = WORKSPACE_ROOT) -> str:
    ensure_memory_scaffold(workspace_root)
    parts = [BASE_SYSTEM_PROMPT]
    project_context = load_project_context(workspace_root)
    if project_context:
        parts.append(f"## Project Context\n{project_context}")
    memory_context = build_memory_context(workspace_root)
    if memory_context:
        parts.append(memory_context)
    return "\n\n".join(parts)


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


def is_volatile_memory_content(content: str) -> bool:
    volatile_patterns = [
        r"\b\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?\b",
        r"\bpid[:= ]\d+\b",
        r"\bsession[_ -]?id\b",
        r"\b当前时间\b",
        r"\b时间戳\b",
    ]
    lowered = content.lower()
    return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in volatile_patterns)


def truncate_summary(text: str, max_len: int = SUMMARY_MAX_LENGTH) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def extract_summary(content: str, tool_calls: list[object] | None = None) -> str:
    if content:
        matched = re.search(r"<summary>(.*?)</summary>", content, flags=re.DOTALL)
        if matched:
            return truncate_summary(matched.group(1))
        cleaned = _clean_content(content, shrink_code_blocks=False)
        for line in cleaned.splitlines():
            stripped = line.strip()
            if stripped:
                return truncate_summary(stripped)
    if tool_calls:
        first_call = tool_calls[0]
        return truncate_summary(f"调用工具 {first_call.function.name}")
    return "完成一轮响应"


def fold_earlier_history(lines: list[str]) -> str:
    if not lines:
        return ""
    if len(lines) <= 5:
        return "\n".join(lines)
    return "\n".join([lines[0], f"... 共 {len(lines)} 条较早记录 ...", lines[-1]])


def build_working_memory_prompt(session_memory: WorkingMemoryState) -> str:
    parts: list[str] = ["### [WORKING MEMORY]"]
    if len(session_memory.history_info) > WORKING_HISTORY_WINDOW:
        earlier = fold_earlier_history(session_memory.history_info[:-WORKING_HISTORY_WINDOW])
        parts.append(f"<earlier_context>\n{earlier}\n</earlier_context>")
    history_lines = session_memory.history_info[-WORKING_HISTORY_WINDOW:]
    if history_lines:
        parts.append(f"<history>\n" + "\n".join(history_lines) + "\n</history>")
    parts.append(f"Current turn: {session_memory.current_turn}")
    if session_memory.key_info:
        parts.append(f"<key_info>{session_memory.key_info}</key_info>")
    if session_memory.related_sop:
        parts.append(f"related_sop: {session_memory.related_sop}")
    return "\n".join(parts)


def build_runtime_messages(
    history: list[dict[str, str]],
    session_memory: WorkingMemoryState,
    workspace_root: Path = WORKSPACE_ROOT,
) -> list[dict[str, str]]:
    messages = list(history)
    messages.append({"role": "system", "content": build_working_memory_prompt(session_memory)})
    if session_memory.current_turn and session_memory.current_turn % MEMORY_REFRESH_INTERVAL == 0:
        messages.append({"role": "system", "content": build_memory_context(workspace_root)})
    return messages


def build_turn_message(turn: int) -> str:
    return f"[dim]LLM Running (Turn {turn})...[/]"


def record_working_memory(
    session_memory: WorkingMemoryState,
    content: str,
    tool_calls: list[object] | None = None,
) -> None:
    summary = extract_summary(content, tool_calls)
    session_memory.history_info.append(f"[Agent] {summary}")


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
    session_memory: WorkingMemoryState | None = None,
) -> Any:
    try:
        if name == "read_file":
            path = resolve_workspace_path(params["path"], workspace_root)
            rejected = reject_memory_file_tool(path, workspace_root)
            if rejected:
                return rejected
            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            numbered = "\n".join(
                f"{index + 1:4d} | {line}" for index, line in enumerate(lines)
            )
            return f"{path} ({len(lines)} lines)\n{numbered}"

        if name == "write_file":
            path = resolve_workspace_path(params["path"], workspace_root)
            rejected = reject_memory_file_tool(path, workspace_root)
            if rejected:
                return rejected
            path.parent.mkdir(parents=True, exist_ok=True)
            content = params["content"]
            path.write_text(content, encoding="utf-8")
            return f"Written to {path} ({len(content)} chars)"

        if name == "edit_file":
            path = resolve_workspace_path(params["path"], workspace_root)
            rejected = reject_memory_file_tool(path, workspace_root)
            if rejected:
                return rejected
            content = path.read_text(encoding="utf-8", errors="replace")
            old_text = params["old_text"]
            if old_text not in content:
                return "Error: Target text not found in file"
            new_content = content.replace(old_text, params["new_text"], 1)
            path.write_text(new_content, encoding="utf-8")
            return f"Edited {path}"

        if name == "delete_file":
            path = resolve_workspace_path(params["path"], workspace_root)
            rejected = reject_memory_file_tool(path, workspace_root)
            if rejected:
                return rejected
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
            rejected = reject_memory_file_tool(old_path, workspace_root)
            if rejected:
                return rejected
            rejected = reject_memory_file_tool(new_path, workspace_root)
            if rejected:
                return rejected
            if not old_path.exists():
                return f"Error: Path not found: {old_path}"
            if new_path.exists():
                return f"Error: Target already exists: {new_path}"
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            return f"Renamed {old_path} -> {new_path}"

        if name == "read_memory":
            ensure_memory_scaffold(workspace_root)
            path = resolve_memory_path(params["path"], workspace_root)
            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            numbered = "\n".join(
                f"{index + 1:4d} | {line}" for index, line in enumerate(lines)
            )
            return f"{path} ({len(lines)} lines)\n{numbered}"

        if name == "write_memory":
            ensure_memory_scaffold(workspace_root)
            content = params["content"]
            if is_volatile_memory_content(content):
                return "Error: volatile content is not allowed in memory"

            path = resolve_memory_path(params["path"], workspace_root)
            path.parent.mkdir(parents=True, exist_ok=True)
            append = bool(params.get("append", False))

            if path.name == MEMORY_L1_FILE and not append and len(content.splitlines()) > 30:
                return "Error: L1 insight must stay within 30 lines"

            if append and path.exists() and path.read_text(encoding="utf-8", errors="replace"):
                existing = path.read_text(encoding="utf-8", errors="replace")
                separator = "" if existing.endswith("\n") else "\n"
                path.write_text(existing + separator + content, encoding="utf-8")
            else:
                path.write_text(content, encoding="utf-8")
            return f"Written memory to {path}"

        if name == "update_working_checkpoint":
            if session_memory is None:
                return "Error: missing session memory"
            if "key_info" in params:
                session_memory.key_info = str(params.get("key_info", "")).strip()
            if "related_sop" in params:
                session_memory.related_sop = str(params.get("related_sop", "")).strip()
            return StepOutcome(
                data={"result": "working checkpoint updated"},
                next_prompt=build_working_memory_prompt(session_memory),
            )

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
        "[bold cyan]OwnitAgent v3[/] - 终端 AI 编程助手\n"
        f"当前模型: {settings.model}\n"
        "输入 'exit' 退出",
        border_style="cyan",
    )


def build_reply_panel(reply: str) -> Panel:
    return Panel(
        Markdown(_clean_content(reply, shrink_code_blocks=False)),
        title="OwnitAgent",
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
    session_memory: WorkingMemoryState | None = None,
) -> str:
    session_memory = session_memory or WorkingMemoryState()
    history.append({"role": "user", "content": user_input})
    tool_count = 0

    while True:
        session_memory.current_turn += 1
        runtime_messages = build_runtime_messages(history, session_memory, workspace_root=WORKSPACE_ROOT)
        console.print(build_turn_message(session_memory.current_turn))
        response = client.chat.completions.create(
            model=settings.model,
            messages=runtime_messages,
            tools=TOOLS,
        )
        if token_stats is not None:
            record_token_usage(token_stats, response)
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        record_working_memory(session_memory, message.content or "", tool_calls)
        history.append(serialize_assistant_message(message))

        if message.content:
            console.print(build_reply_panel(message.content))

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
        console.print("\n[cyan]再见！[/]")
    finally:
        console.print(build_token_summary(token_stats))


if __name__ == "__main__":
    run_chat()
