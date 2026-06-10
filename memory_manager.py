from __future__ import annotations

import re
from pathlib import Path

from config import (
    DEFAULT_MEMORY_FACTS,
    DEFAULT_MEMORY_INSIGHT,
    DEFAULT_MEMORY_MANAGEMENT_SOP,
    MEMORY_DIR_NAME,
    MEMORY_L0_FILE,
    MEMORY_L1_FILE,
    MEMORY_L2_FILE,
    WORKSPACE_ROOT,
)


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


def is_memory_path(path: Path, workspace_root: Path = WORKSPACE_ROOT) -> bool:
    memory_root = get_memory_root(workspace_root).resolve()
    try:
        path.resolve().relative_to(memory_root)
        return True
    except ValueError:
        return False


def reject_memory_file_tool(
    path: Path, workspace_root: Path = WORKSPACE_ROOT
) -> str | None:
    if is_memory_path(path, workspace_root):
        return "Error: memory paths are managed separately. Use memory tools instead."
    return None


def read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace").strip()


def is_volatile_memory_content(content: str) -> bool:
    volatile_patterns = [
        r"\b\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}\b",
        r"\bpid[:= ]\d+\b",
        r"\bsession[_ -]?id\b",
        r"\b当前时间\b",
        r"\b时间戳\b",
    ]
    lowered = content.lower()
    return any(
        re.search(pattern, lowered, flags=re.IGNORECASE)
        for pattern in volatile_patterns
    )


def fold_earlier_history(lines: list[str]) -> str:
    if not lines:
        return ""
    if len(lines) <= 5:
        return "\n".join(lines)
    return "\n".join([lines[0], f"... 共 {len(lines)} 条较早记录 ...", lines[-1]])
