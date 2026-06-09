from __future__ import annotations

import json
import os
import re

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from models import Settings


def build_console() -> Console:
    return Console()


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


def build_turn_message(turn: int) -> str:
    return f"[dim]LLM Running (Turn {turn})...[/]"
