from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Generator

from config import (
    IGNORED_PATH_NAMES,
    LIST_FILES_MAX_DEPTH,
    MEMORY_L1_FILE,
    SEARCH_RESULT_LIMIT,
    WORKSPACE_ROOT,
)
from memory_manager import (
    ensure_memory_scaffold,
    is_volatile_memory_content,
    reject_memory_file_tool,
    resolve_memory_path,
    resolve_workspace_path,
)
from models import StepOutcome, WorkingMemoryState
from prompts import build_working_memory_prompt


# 构建一个符合 OpenAI Function Calling 规范的工具定义字典
# name: 工具名称（函数名）
# description: 工具的功能描述
# properties: 参数属性字典，键为参数名，值为包含 type 和 description 的字典
# required: 必填参数名列表
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


# 工具列表 — 注册所有可供 AI 调用的工具
TOOLS = [
    # 读取文件内容并附加行号
    _fn(
        "read_file",
        "Read the contents of a file. Returns the content with line numbers.",
        {"path": {"type": "string", "description": "File path to read"}},
        ["path"],
    ),
    # 写入文件，自动创建父目录
    _fn(
        "write_file",
        "Write content to a file. Creates parent directories if needed.",
        {
            "path": {"type": "string", "description": "File path"},
            "content": {"type": "string", "description": "Complete file content"},
        },
        ["path", "content"],
    ),
    # 在文件中查找并替换文本（仅首次匹配）
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
    # 删除文件或递归删除目录
    _fn(
        "delete_file",
        "Delete a file or directory inside the workspace.",
        {"path": {"type": "string", "description": "File or directory path"}},
        ["path"],
    ),
    # 重命名或移动文件/目录
    _fn(
        "rename_file",
        "Rename or move a file or directory inside the workspace.",
        {
            "old_path": {"type": "string", "description": "Current file path"},
            "new_path": {"type": "string", "description": "New file path"},
        },
        ["old_path", "new_path"],
    ),
    # 读取记忆文件并附加行号
    _fn(
        "read_memory",
        "Read a memory file inside the memory directory.",
        {"path": {"type": "string", "description": "Memory file path relative to memory/"}},
        ["path"],
    ),
    # 写入记忆文件，含易变内容检测和 L1 行数限制
    _fn(
        "write_memory",
        "Write verified information into a memory file inside the memory directory.",
        {
            "path": {"type": "string", "description": "Memory file path relative to memory/"},
            "content": {"type": "string", "description": "Verified memory content"},
            "append": {
                "type": "boolean",
                "description": "Append instead of overwrite",
                "default": False,
            },
        },
        ["path", "content"],
    ),
    # 更新会话工作记忆检查点
    _fn(
        "update_working_checkpoint",
        "Update working memory with the current key checkpoint and related SOP path.",
        {
            "key_info": {
                "type": "string",
                "description": "Short validated checkpoint summary",
            },
            "related_sop": {
                "type": "string",
                "description": "Related SOP path for later reference",
            },
        },
        [],
    ),
    # 执行 Shell 命令（含危险命令拦截和 30s 超时）
    _fn(
        "run_command",
        "Execute a shell command. Times out after 30 seconds.",
        {"command": {"type": "string", "description": "Shell command to execute"}},
        ["command"],
    ),
    # 递归列出目录内容（最多 3 层，忽略 .git 等目录）
    _fn(
        "list_files",
        "Recursively list directory contents up to 3 levels deep.",
        {"path": {"type": "string", "description": "Directory path", "default": "."}},
        [],
    ),
    # 在目录中搜索文本模式（大小写不敏感）
    _fn(
        "search_code",
        "Search for a text pattern across files in a directory.",
        {
            "pattern": {"type": "string", "description": "Search pattern"},
            "path": {"type": "string", "description": "Search directory", "default": "."},
        },
        ["pattern"],
    ),
    # 在目录中搜索正则表达式模式
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


# 检测命令是否包含危险操作（支持 Linux 和 Windows）
def _is_dangerous_command(command: str) -> bool:
    lowered = command.lower().strip()
    dangerous_patterns = [
        # Linux 危险命令
        "rm -rf /",
        "rm -r -f /",
        "rm --recursive --force /",
        "rm -rf /*",
        "mkfs",
        "dd if=",
        "> /dev/sd",
        # Windows 危险命令
        "format c:",
        "format d:",
        "del /f /s c:\\",
        "del /f /s d:\\",
        "remove-item -recurse -force c:\\",
        "remove-item -recurse -force d:\\",
        "rmdir /s /q c:\\",
        "rmdir /s /q d:\\",
        "diskpart",
    ]
    # 压缩多余空格后匹配
    compact = " ".join(lowered.split())
    return any(pattern in compact for pattern in dangerous_patterns)


# 将工具执行结果统一规范化为 StepOutcome 类型
# 如果结果已经是 StepOutcome 实例则直接返回，否则将其包装为 data 字段
def _walk_files(search_path: Path, workspace_root: Path) -> Generator[tuple[Path, int, str], None, None]:
    for current_root, dir_names, file_names in os.walk(search_path):
        dir_names[:] = [d for d in dir_names if d not in IGNORED_PATH_NAMES]
        for file_name in sorted(file_names):
            file_path = Path(current_root) / file_name
            try:
                with file_path.open("r", encoding="utf-8", errors="replace") as f:
                    for index, line in enumerate(f, start=1):
                        yield file_path, index, line
            except OSError:
                continue

def normalize_tool_outcome(result: Any) -> StepOutcome:
    if isinstance(result, StepOutcome):
        return result
    return StepOutcome(data=result)


# 将工具返回的数据序列化为字符串，用于传递给 LLM
# 字典/列表 → JSON 字符串（保留 Unicode）
# None → 空字符串
# 其他类型 → str() 转换
def serialize_tool_data(data: Any) -> str:
    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False)
    if data is None:
        return ""
    return str(data)


# 执行指定的工具调用，返回执行结果
# 根据工具名称 name 分发到对应的处理分支
# 所有文件操作都会经过工作区路径解析和安全校验，确保不越权访问
def execute_tool(
    name: str,
    params: dict,
    workspace_root: Path = WORKSPACE_ROOT,
    session_memory: WorkingMemoryState | None = None,
) -> Any:
    try:
        # read_file: 读取文件内容并附加行号
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

        # write_file: 写入文件，自动创建父目录
        if name == "write_file":
            path = resolve_workspace_path(params["path"], workspace_root)
            rejected = reject_memory_file_tool(path, workspace_root)
            if rejected:
                return rejected
            path.parent.mkdir(parents=True, exist_ok=True)
            content = params["content"]
            path.write_text(content, encoding="utf-8")
            return f"Written to {path} ({len(content)} chars)"

        # edit_file: 在文件中查找并替换文本（仅首次匹配）
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

        # delete_file: 删除文件或递归删除目录
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

        # rename_file: 重命名或移动文件/目录
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

        # read_memory: 读取记忆文件并附加行号
        if name == "read_memory":
            ensure_memory_scaffold(workspace_root)
            path = resolve_memory_path(params["path"], workspace_root)
            if not path.exists():
                return f"Error: memory file not found: {params['path']}"
            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.split("\n")
            numbered = "\n".join(
                f"{index + 1:4d} | {line}" for index, line in enumerate(lines)
            )
            return f"{path} ({len(lines)} lines)\n{numbered}"

        # write_memory: 写入记忆文件，含易变内容检测和 L1 行数限制
        if name == "write_memory":
            ensure_memory_scaffold(workspace_root)
            content = params["content"]
            # 拒绝写入易变内容（如临时 ID、时间戳等）
            if is_volatile_memory_content(content):
                return "Error: volatile content is not allowed in memory"

            path = resolve_memory_path(params["path"], workspace_root)
            path.parent.mkdir(parents=True, exist_ok=True)
            append = bool(params.get("append", False))

            # L1 洞察文件必须保持在 30 行以内
            if path.name == MEMORY_L1_FILE:
                if append and path.exists():
                    existing = path.read_text(encoding="utf-8", errors="replace")
                    total_lines = len(existing.splitlines()) + len(content.splitlines())
                    if total_lines > 30:
                        return "Error: L1 insight must stay within 30 lines"
                elif not append and len(content.splitlines()) > 30:
                    return "Error: L1 insight must stay within 30 lines"

            # 追加模式：在现有内容后拼接新内容
            if append and path.exists():
                existing = path.read_text(encoding="utf-8", errors="replace")
                if existing:
                    separator = "" if existing.endswith("\n") else "\n"
                    path.write_text(existing + separator + content, encoding="utf-8")
                else:
                    path.write_text(content, encoding="utf-8")
            else:
                path.write_text(content, encoding="utf-8")
            return f"Written memory to {path}"

        # update_working_checkpoint: 更新会话工作记忆检查点
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

        # run_command: 执行 Shell 命令（含危险命令拦截和 30s 超时）
        if name == "run_command":
            command = params["command"]
            if _is_dangerous_command(command):
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

        # list_files: 递归列出目录内容（最多 3 层，忽略 .git 等目录）
        if name == "list_files":
            path = resolve_workspace_path(params.get("path", "."), workspace_root)
            result: list[str] = []

            # 递归遍历目录，收集文件和子目录信息
            def walk_directory(current_path: Path, prefix: str = "", depth: int = 0) -> None:
                if depth >= LIST_FILES_MAX_DEPTH:
                    return

                entries = sorted(
                    entry
                    for entry in current_path.iterdir()
                    if entry.name not in IGNORED_PATH_NAMES
                )
                for entry in entries:
                    if entry.is_dir():
                        result.append(f"{prefix}[dir] {entry.name}/")
                        walk_directory(entry, prefix + "  ", depth + 1)
                    else:
                        result.append(f"{prefix}[file] {entry.name}")

            walk_directory(path)
            return "\n".join(result) or "Empty directory"


# 遍历目录中的文件，过滤忽略目录，生成 (文件路径, 行号, 行内容) 元组
        # search_code: 在目录中搜索文本模式（大小写不敏感）
        if name == "search_code":
            pattern = params["pattern"].lower()
            path = resolve_workspace_path(params.get("path", "."), workspace_root)
            matches: list[str] = []
            for file_path, index, line in _walk_files(path, workspace_root):
                if pattern in line.lower():
                    relative_path = file_path.relative_to(workspace_root)
                    matches.append(f"{relative_path}:{index}: {line.rstrip()}")
                    if len(matches) >= SEARCH_RESULT_LIMIT:
                        return "\n".join(matches)
            return "\n".join(matches) or f"No matches for '{params['pattern']}'"

        # grep_search: 在目录中搜索正则表达式模式
        if name == "grep_search":
            regex = re.compile(params["pattern"])
            path = resolve_workspace_path(params.get("path", "."), workspace_root)
            matches: list[str] = []
            for file_path, index, line in _walk_files(path, workspace_root):
                if regex.search(line):
                    relative_path = file_path.relative_to(workspace_root)
                    matches.append(f"{relative_path}:{index}: {line.rstrip()}")
                    if len(matches) >= SEARCH_RESULT_LIMIT:
                        return "\n".join(matches)
            return "\n".join(matches) or f"No matches for regex '{params['pattern']}'"

        # 未知工具
        return f"Error: unknown tool: {name}"
    except Exception as error:
        return f"Error: {type(error).__name__}: {error}"
