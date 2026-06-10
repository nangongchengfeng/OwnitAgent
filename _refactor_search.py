"""Refactor search_code and grep_search to share _walk_files helper."""
import os
from pathlib import Path

path = r"D:\Code\Agents\demo_agents\tools.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# Add Generator import
for i, line in enumerate(lines):
    if "from typing import Any" in line:
        lines[i] = "from typing import Any, Generator\n"
        break

# Find search_code start
search_start = None
grep_start = None
unknown_start = None
for i, line in enumerate(lines):
    if "# search_code:" in line and "搜索文本" in line:
        search_start = i
    if "# grep_search:" in line and "正则" in line:
        grep_start = i
    if "# 未知工具" in line:
        unknown_start = i

print(f"search_start={search_start}, grep_start={grep_start}, unknown_start={unknown_start}")

# Build _walk_files helper
helper = [
    "\n",
    "# 遍历目录中的文件，过滤忽略目录，生成 (文件路径, 行号, 行内容) 元组\n",
    "def _walk_files(search_path: Path, workspace_root: Path) -> Generator[tuple[Path, int, str], None, None]:\n",
    "    for current_root, dir_names, file_names in os.walk(search_path):\n",
    '        dir_names[:] = [d for d in dir_names if d not in IGNORED_PATH_NAMES]\n',
    "        for file_name in sorted(file_names):\n",
    "            file_path = Path(current_root) / file_name\n",
    "            try:\n",
    '                with file_path.open("r", encoding="utf-8", errors="replace") as f:\n',
    "                    for index, line in enumerate(f, start=1):\n",
    "                        yield file_path, index, line\n",
    "            except OSError:\n",
    "                continue\n",
    "\n",
]

# Insert helper before search_code
for h in reversed(helper):
    lines.insert(search_start, h)

# Adjust indices after insertion
offset = len(helper)
search_start += offset
grep_start += offset
unknown_start += offset

# Build new search_code block
new_search = [
    "        # search_code: 在目录中搜索文本模式（大小写不敏感）\n",
    '        if name == "search_code":\n',
    '            pattern = params["pattern"].lower()\n',
    '            path = resolve_workspace_path(params.get("path", "."), workspace_root)\n',
    "            matches: list[str] = []\n",
    "            for file_path, index, line in _walk_files(path, workspace_root):\n",
    "                if pattern in line.lower():\n",
    "                    relative_path = file_path.relative_to(workspace_root)\n",
    '                    matches.append(f"{relative_path}:{index}: {line.rstrip()}")\n',
    "                    if len(matches) >= SEARCH_RESULT_LIMIT:\n",
    '                        return "\\n".join(matches)\n',
    "            return \"\\n\".join(matches) or f\"No matches for '{params['pattern']}'\"\n",
    "\n",
]

# Replace search_code -> grep_start
lines[search_start:grep_start] = new_search

# Adjust indices
offset2 = len(new_search) - (grep_start - search_start)
grep_start = search_start + len(new_search)
unknown_start += offset2

# Build new grep_search block
new_grep = [
    "        # grep_search: 在目录中搜索正则表达式模式\n",
    '        if name == "grep_search":\n',
    '            regex = re.compile(params["pattern"])\n',
    '            path = resolve_workspace_path(params.get("path", "."), workspace_root)\n',
    "            matches: list[str] = []\n",
    "            for file_path, index, line in _walk_files(path, workspace_root):\n",
    "                if regex.search(line):\n",
    "                    relative_path = file_path.relative_to(workspace_root)\n",
    '                    matches.append(f"{relative_path}:{index}: {line.rstrip()}")\n',
    "                    if len(matches) >= SEARCH_RESULT_LIMIT:\n",
    '                        return "\\n".join(matches)\n',
    "            return \"\\n\".join(matches) or f\"No matches for regex '{params['pattern']}'\"\n",
    "\n",
]

# Replace grep_search -> unknown_start
lines[grep_start:unknown_start] = new_grep

with open(path, "w", encoding="utf-8") as f:
    f.writelines(lines)
print("Done - refactored search_code and grep_search")
