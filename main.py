"""OwnitAgent v0.1.0 - 从 .env 读取配置的终端 AI 助手。"""

from chat_agent import (
    build_token_summary,
    chat,
    chat_once,
    handle_control_command,
    record_token_usage,
    run_chat,
    serialize_assistant_message,
    serialize_tool_call,
)
from config import (
    BASE_SYSTEM_PROMPT,
    DEFAULT_BASE_URL,
    DEFAULT_ENV_PATH,
    DEFAULT_MODEL,
    DEFAULT_MEMORY_FACTS,
    DEFAULT_MEMORY_INSIGHT,
    DEFAULT_MEMORY_MANAGEMENT_SOP,
    IGNORED_PATH_NAMES,
    LIST_FILES_MAX_DEPTH,
    MEMORY_DIR_NAME,
    MEMORY_L0_FILE,
    MEMORY_L1_FILE,
    MEMORY_L2_FILE,
    MEMORY_REFRESH_INTERVAL,
    MEMORY_ROOT,
    SEARCH_RESULT_LIMIT,
    SUMMARY_MAX_LENGTH,
    TOOL_CALL_LIMIT,
    WORKING_HISTORY_WINDOW,
    WORKSPACE_ROOT,
    build_client,
    get_settings,
    load_env_file,
)
from memory_manager import (
    ensure_memory_scaffold,
    fold_earlier_history,
    get_memory_root,
    is_memory_path,
    is_volatile_memory_content,
    read_text_if_exists,
    reject_memory_file_tool,
    resolve_memory_path,
    resolve_workspace_path,
)
from models import Settings, StepOutcome, TokenUsageStats, WorkingMemoryState
from prompts import (
    build_initial_history,
    build_memory_context,
    build_runtime_messages,
    build_system_prompt,
    build_working_memory_prompt,
    extract_summary,
    load_project_context,
    record_working_memory,
    truncate_summary,
)
from tools import TOOLS, execute_tool, normalize_tool_outcome, serialize_tool_data
from ui import (
    _clean_content,
    _compact_tool_args,
    build_console,
    build_reply_panel,
    build_tool_result_message,
    build_tool_start_message,
    build_turn_message,
    build_welcome_panel,
    preview_text,
)


if __name__ == "__main__":
    run_chat()
