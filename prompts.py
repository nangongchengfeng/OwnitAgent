from __future__ import annotations

import re
from pathlib import Path

from config import (
    BASE_SYSTEM_PROMPT,
    MEMORY_DIR_NAME,
    MEMORY_L0_FILE,
    MEMORY_L1_FILE,
    MEMORY_L2_FILE,
    MEMORY_REFRESH_INTERVAL,
    SUMMARY_MAX_LENGTH,
    WORKING_HISTORY_WINDOW,
    WORKSPACE_ROOT,
)
from memory_manager import (
    ensure_memory_scaffold,
    fold_earlier_history,
    get_memory_root,
    read_text_if_exists,
)
from models import WorkingMemoryState
from ui import _clean_content


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
    return "模型空响应"


def build_working_memory_prompt(session_memory: WorkingMemoryState) -> str:
    parts: list[str] = ["### [WORKING MEMORY]"]
    if len(session_memory.history_info) > WORKING_HISTORY_WINDOW:
        earlier = fold_earlier_history(
            session_memory.history_info[:-WORKING_HISTORY_WINDOW]
        )
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
    messages.append(
        {"role": "system", "content": build_working_memory_prompt(session_memory)}
    )
    if (
        session_memory.current_turn
        and session_memory.current_turn % MEMORY_REFRESH_INTERVAL == 0
    ):
        messages.append({"role": "system", "content": build_memory_context(workspace_root)})
    return messages


def record_working_memory(
    session_memory: WorkingMemoryState,
    content: str,
    tool_calls: list[object] | None = None,
) -> None:
    summary = extract_summary(content, tool_calls)
    session_memory.history_info.append(f"[Agent] {summary}")
