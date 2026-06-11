from __future__ import annotations

import os
from pathlib import Path

from openai import OpenAI

from models import Settings

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
TOOL_CALL_LIMIT = 50
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
