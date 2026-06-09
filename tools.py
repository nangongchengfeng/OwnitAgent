from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

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
            "append": {
                "type": "boolean",
                "description": "Append instead of overwrite",
                "default": False,
            },
        },
        ["path", "content"],
    ),
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

        if name == "search_code":
            pattern = params["pattern"].lower()
            path = resolve_workspace_path(params.get("path", "."), workspace_root)
            matches: list[str] = []

            for current_root, dir_names, file_names in os.walk(path):
                dir_names[:] = [
                    dir_name
                    for dir_name in dir_names
                    if dir_name not in IGNORED_PATH_NAMES
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
                    dir_name
                    for dir_name in dir_names
                    if dir_name not in IGNORED_PATH_NAMES
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
