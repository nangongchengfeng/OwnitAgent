from __future__ import annotations

import re
from pathlib import Path

from config import (
    BASE_SYSTEM_PROMPT,        # 基础系统提示词
    MEMORY_DIR_NAME,           # 记忆目录名称
    MEMORY_L0_FILE,            # L0 记忆文件名（管理规范）
    MEMORY_L1_FILE,            # L1 记忆文件名（全局洞察）
    MEMORY_L2_FILE,            # L2 记忆文件名（环境事实）
    MEMORY_REFRESH_INTERVAL,   # 记忆上下文刷新间隔（轮次）
    SUMMARY_MAX_LENGTH,        # 摘要最大长度
    WORKING_HISTORY_WINDOW,    # 工作记忆历史窗口大小
    WORKSPACE_ROOT,            # 工作区根目录
)
from memory_manager import (
    ensure_memory_scaffold,    # 确保记忆目录骨架存在
    fold_earlier_history,      # 折叠较早的历史记录
    get_memory_root,           # 获取记忆根目录路径
    read_text_if_exists,       # 安全读取文件内容（不存在则返回空串）
)
from models import WorkingMemoryState  # 工作记忆状态数据类
from ui import _clean_content          # 清理内容中的特殊标记


def load_project_context(workspace_root: Path = WORKSPACE_ROOT) -> str:
    """加载项目上下文文档（CLAUDE.md、AGENTS.md、README.md），拼接为提示词片段。"""
    context_parts: list[str] = []
    # 按优先级依次尝试加载项目文档
    for name in ["CLAUDE.md", "AGENTS.md", "README.md"]:
        path = workspace_root / name
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        context_parts.append(f"--- {name} ---\n{content}")
    return "\n\n".join(context_parts)


def build_memory_context(workspace_root: Path = WORKSPACE_ROOT) -> str:
    """构建记忆上下文提示词，包含 L1 洞察索引和 L2 环境事实。"""
    memory_root = get_memory_root(workspace_root)
    if not memory_root.exists():
        return ""

    # 读取 L1 全局洞察和 L2 全局事实
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
    """组装完整的系统提示词：基础提示词 + 项目上下文 + 记忆上下文。"""
    # 确保记忆目录骨架存在
    ensure_memory_scaffold(workspace_root)
    parts = [BASE_SYSTEM_PROMPT]

    # 加载项目上下文（README 等文档）
    project_context = load_project_context(workspace_root)
    if project_context:
        parts.append(f"## Project Context\n{project_context}")

    # 加载记忆上下文（L1/L2 记忆）
    memory_context = build_memory_context(workspace_root)
    if memory_context:
        parts.append(memory_context)

    return "\n\n".join(parts)


def build_initial_history(workspace_root: Path = WORKSPACE_ROOT) -> list[dict[str, str]]:
    """构建初始对话历史，仅包含一条 system 消息。"""
    return [{"role": "system", "content": build_system_prompt(workspace_root)}]


def truncate_summary(text: str, max_len: int = SUMMARY_MAX_LENGTH) -> str:
    """将文本压缩为单行，超出最大长度则截断并追加省略号。"""
    # 将所有空白字符压缩为单个空格
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3] + "..."


def extract_summary(content: str, tool_calls: list[object] | None = None) -> str:
    """从模型响应中提取摘要：优先 <summary> 标签，其次首行非空文本，最后回退到工具名。"""
    if content:
        # 尝试匹配 <summary>...</summary> 标签
        matched = re.search(r"<summary>(.*?)</summary>", content, flags=re.DOTALL)
        if matched:
            return truncate_summary(matched.group(1))
        # 回退：取清理后内容的首行非空文本
        cleaned = _clean_content(content, shrink_code_blocks=False)
        for line in cleaned.splitlines():
            stripped = line.strip()
            if stripped:
                return truncate_summary(stripped)
    # 无文本内容时，使用第一个工具调用名作为摘要
    if tool_calls:
        first_call = tool_calls[0]
        return truncate_summary(f"调用工具 {first_call.function.name}")
    # 最终回退
    return "模型空响应"


def build_working_memory_prompt(session_memory: WorkingMemoryState) -> str:
    """构建工作记忆提示词，包含折叠的早期历史、近期历史、当前轮次和关键信息。"""
    parts: list[str] = ["### [WORKING MEMORY]"]

    # 如果历史记录超过窗口大小，折叠较早部分
    if len(session_memory.history_info) > WORKING_HISTORY_WINDOW:
        earlier = fold_earlier_history(
            session_memory.history_info[:-WORKING_HISTORY_WINDOW]
        )
        parts.append(f"<earlier_context>\n{earlier}\n</earlier_context>")

    # 追加窗口内的近期历史
    history_lines = session_memory.history_info[-WORKING_HISTORY_WINDOW:]
    if history_lines:
        parts.append(f"<history>\n" + "\n".join(history_lines) + "\n</history>")

    # 当前轮次
    parts.append(f"Current turn: {session_memory.current_turn}")

    # 关键检查点信息
    if session_memory.key_info:
        parts.append(f"<key_info>{session_memory.key_info}</key_info>")

    # 关联的 SOP 路径
    if session_memory.related_sop:
        parts.append(f"related_sop: {session_memory.related_sop}")

    return "\n".join(parts)


def build_runtime_messages(
    history: list[dict[str, str]],
    session_memory: WorkingMemoryState,
    workspace_root: Path = WORKSPACE_ROOT,
) -> list[dict[str, str]]:
    """构建每次 LLM 调用时的运行时消息列表：复制历史 + 注入工作记忆提示词 + 按间隔刷新记忆上下文。"""
    messages = list(history)

    # 注入工作记忆提示词（含历史折叠、关键信息等）
    messages.append(
        {"role": "system", "content": build_working_memory_prompt(session_memory)}
    )

    # 每隔 MEMORY_REFRESH_INTERVAL 轮刷新一次记忆上下文
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
    """记录本轮工作记忆：从模型响应中提取摘要，追加到会话历史。"""
    summary = extract_summary(content, tool_calls)
    session_memory.history_info.append(f"[Agent] {summary}")
