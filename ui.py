from __future__ import annotations

import json
import os
import re

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from models import Settings


def build_console() -> Console:
    """构建 Rich Console 实例，用于终端渲染输出"""
    return Console()


def preview_text(text: str, limit: int = 100) -> str:
    """生成文本预览，超过长度限制则截断并加省略号"""
    preview = text[:limit].replace("\n", " ")
    if len(text) > limit:
        preview += "..."
    return preview


def _clean_content(text: str, shrink_code_blocks: bool = True) -> str:
    """
    清理内容文本：
    - 可选：折叠过长的代码块（超过 6 行只展示前 5 行）
    - 移除 <file_content>、<tool_use>、<tool_call> 等 XML 标签内容
    - 压缩连续空行为最多两个换行
    """
    if not text:
        return ""

    def shrink_code(match: re.Match[str]) -> str:
        """折叠代码块：超过 6 行时只保留前 5 行 + 行数提示"""
        lines = match.group(0).split("\n")
        language = lines[0].replace("```", "").strip()
        body = [line for line in lines[1:-1] if line.strip()]
        if len(body) <= 6:
            return match.group(0)
        preview = "\n".join(body[:5])
        return f"```{language}\n{preview}\n  ... ({len(body)} lines)\n```"

    cleaned = text
    # 折叠过长的代码块
    if shrink_code_blocks:
        cleaned = re.sub(r"```[\s\S]*?```", shrink_code, cleaned)
    # 移除文件内容标签
    cleaned = re.sub(r"<file_content>[\s\S]*?</file_content>", "", cleaned)
    # 移除工具调用/使用标签
    cleaned = re.sub(r"<tool_(?:use|call)>[\s\S]*?</tool_(?:use|call)>", "", cleaned)
    # 压缩连续空行
    cleaned = re.sub(r"(\r?\n){3,}", "\n\n", cleaned)
    return cleaned.strip()


def _compact_tool_args(name: str, args: dict) -> str:
    """
    压缩工具参数显示：
    - 移除内部索引字段 _index
    - 路径类参数只显示文件名（去掉目录前缀）
    - 超过 120 字符则截断
    """
    compact_args = {key: value for key, value in args.items() if key != "_index"}
    for key in ("path", "old_path", "new_path"):
        if key in compact_args:
            compact_args[key] = os.path.basename(str(compact_args[key]))

    compact = json.dumps(compact_args, ensure_ascii=False)
    if len(compact) > 120:
        compact = compact[:120] + "..."
    return compact


def build_welcome_panel(settings: Settings) -> Panel:
    """构建启动欢迎面板，显示 Agent 名称、当前模型和退出提示"""
    return Panel(
        "[bold cyan]OwnitAgent v3[/] - 终端 AI 编程助手\n"
        f"当前模型: {settings.model}\n"
        "输入 'exit' 退出",
        border_style="cyan",
    )


def build_reply_panel(reply: str) -> Panel:
    """构建 AI 回复面板，使用 Markdown 渲染回复内容"""
    return Panel(
        Markdown(_clean_content(reply, shrink_code_blocks=False)),
        title="OwnitAgent",
        border_style="blue",
    )


def build_tool_start_message(tool_index: int, name: str, args: dict) -> str:
    """构建工具调用开始消息，显示工具序号、名称和压缩后的参数"""
    return f"  [yellow][{tool_index}] {name}[/] [dim]{_compact_tool_args(name, args)}[/]"


def build_tool_result_message(result: str) -> str:
    """构建工具调用结果消息，显示完成状态和结果预览"""
    return f"  [green]Done[/] [dim]{preview_text(_clean_content(result))}[/]"


def build_turn_message(turn: int) -> str:
    """构建轮次提示消息，显示当前 LLM 调用轮次"""
    return f"[dim]LLM Running (Turn {turn})...[/]"
