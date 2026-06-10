# OwnitAgent

> 终端 AI 编程助手 — 基于 OpenAI 兼容 API，支持流式输出、12 种工具调用、分层记忆系统与工作记忆管理。

[![Python](https://img.shields.io/badge/python-%3E%3D3.13-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

---

## 📖 简介

OwnitAgent 是一个运行在终端中的 AI 编程助手，基于 OpenAI 兼容 API（支持 DeepSeek、SiliconFlow、火山方舟等），具备**流式输出**、**Function Calling 工具调用**、**分层记忆系统**和**工作记忆管理**能力。

它可以直接操作工作区内的文件，完成代码分析、重构、调试等任务：

- 📖 **读取文件** — 带行号展示源码
- ✍️ **写入文件** — 自动创建父目录
- ✏️ **编辑文件** — 精确替换文本（首次匹配）
- 🗑️ **删除文件** — 删除文件或递归删除目录
- 📝 **重命名/移动** — 重命名或移动文件/目录
- 🖥️ **执行命令** — 30s 超时 + 危险命令拦截
- 📁 **浏览目录** — 递归列出，自动忽略 `.git`、`node_modules` 等
- 🔍 **搜索代码** — 文本搜索（大小写不敏感）与正则搜索
- 🧠 **分层记忆** — L0-L4 五层持久记忆，跨会话保留
- 📋 **工作记忆** — 会话内自动摘要 + 历史折叠 + 检查点管理
- 📊 **日志系统** — 支持 `-v`/`-d` 参数控制日志级别，输出到 stderr 和 `agent.log`

---

## ✨ 特性

- 🔌 **兼容 OpenAI API** — 支持 DeepSeek、SiliconFlow、火山方舟等任意兼容接口
- ⚡ **流式输出** — 基于 Rich 库实时渲染 Markdown 回复，支持 Live 动态刷新
- 🛠️ **12 种工具** — 文件操作（5）、搜索浏览（3）、记忆管理（3）、命令执行（1）
- 🧠 **分层记忆** — L0 管理规范 → L1 洞察索引（≤30行）→ L2 环境事实 → L3 SOP/工具脚本 → L4 原始会话
- 💾 **工作记忆** — 每轮自动提取摘要，超 30 轮自动折叠早期历史
- 🔒 **工作区隔离** — 路径解析确保文件操作不超出项目根目录
- 🛡️ **危险命令拦截** — 自动拒绝 `rm -rf /`、`format C:` 等高风险操作
- 🎨 **美观终端 UI** — Rich Panel、Markdown、Live 组件
- 📊 **Token 统计** — 会话结束时显示输入/输出 Token 用量
- 📋 **项目上下文** — 自动加载 README.md、CLAUDE.md、AGENTS.md 等项目文档
- 🔄 **非流式回退** — 流式响应异常时自动回退到非流式请求（含重试机制）
- 🧹 **历史清空** — 输入 `clear` 重置对话历史与工作记忆
- 🛑 **安全退出** — `exit`/`quit` 退出，`Ctrl+C` 安全中断
- 📝 **详细日志** — `-v` 启用 INFO 日志，`-d` 启用 DEBUG 日志（含文件日志 `agent.log`）

---

## 🚀 快速开始

### 环境要求

- Python **>= 3.13**
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip

### 安装

```bash
# 克隆项目
git clone <your-repo-url>
cd OwnitAgent

# 使用 uv 安装依赖
uv sync

# 或使用 pip
pip install openai rich prompt-toolkit
```

### 配置

在项目根目录创建 `.env` 文件：

```env
OPENAI_API_KEY=your-api-key-here
OPENAI_MODEL=deepseek-ai/DeepSeek-V4-Flash
OPENAI_BASE_URL=https://api.siliconflow.cn/v1
```

| 变量 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `OPENAI_API_KEY` | ✅ | - | API 密钥 |
| `OPENAI_MODEL` | ❌ | `deepseek-ai/DeepSeek-V4-Flash` | 模型名称 |
| `OPENAI_BASE_URL` | ❌ | `https://api.siliconflow.cn/v1` | API 地址 |

### 运行

```bash
# 普通模式（仅 WARNING 级别日志）
python main.py

# 详细日志模式（INFO 级别，输出到 stderr）
python main.py -v

# 调试模式（DEBUG 级别，同时写入 agent.log）
python main.py -d
```

启动后你将看到欢迎面板，输入消息即可与 AI 对话。

---

## 📂 项目结构

```
OwnitAgent/
├── .env                      # 环境变量配置（不纳入版本控制）
├── .gitignore                # Git 忽略规则
├── .python-version           # Python 版本声明
├── .trae/                    # Trae IDE 配置
│   └── rules/
│       └── git-commit-message.md
├── main.py                   # 入口文件，聚合导出所有公共接口
├── chat_agent.py             # 对话主循环（run_chat/chat/chat_once）、Token 统计、非流式回退
├── config.py                 # .env 加载、默认常量、Settings 构造、OpenAI 客户端构造
├── logging_config.py         # 日志系统：stderr 输出 + agent.log 文件，支持 -v/-d 参数
├── memory_manager.py         # 记忆目录 scaffold、路径安全解析、易变内容检测、历史折叠
├── models.py                 # 核心数据结构：Settings、TokenUsageStats、StepOutcome、WorkingMemoryState
├── prompts.py                # 系统提示词组装、项目上下文加载、记忆上下文构建、工作记忆管理
├── tools.py                  # 12 种工具定义（OpenAI Function Calling 格式）与执行逻辑
├── ui.py                     # Rich 终端渲染：Panel、Markdown、工具调用消息、内容清理
├── pyproject.toml            # 项目元数据与依赖声明
├── uv.lock                   # 依赖锁定文件
├── README.md                 # 项目文档
├── agent.log                 # 调试日志文件（-d 模式下生成）
├── docs/                     # 设计文档
│   └── context-management-design.md   # 上下文管理系统设计文档
├── memory/                   # 分层记忆存储
│   ├── README.md                       # 记忆目录说明
│   ├── memory_management_sop.md        # L0 - 记忆管理规范（写入前必读）
│   ├── global_mem_insight.txt          # L1 - 全局记忆洞察索引（≤30 行）
│   ├── global_mem.txt                  # L2 - 全局记忆事实（路径、配置等）
│   ├── task_sops/                      # L3 - 任务 SOP
│   ├── tools/                          # L3 - 工具脚本
│   ├── sessions/                       # 会话记录
│   └── L4_raw_sessions/                # L4 - 原始会话归档
└── tests/                    # 测试目录
    ├── __init__.py
    └── test_main.py          # 单元测试（含 20+ 测试用例）
```

---

## 🛠️ 工具说明

AI 助手可调用以下 12 种工具：

### 文件操作

| 工具 | 功能 | 参数 |
|------|------|------|
| `read_file` | 读取文件，返回带行号内容 | `path` — 文件路径 |
| `write_file` | 写入文件，自动创建父目录 | `path` — 文件路径，`content` — 文件内容 |
| `edit_file` | 替换文件中的文本（首次匹配） | `path` — 文件路径，`old_text` — 原文本，`new_text` — 新文本 |
| `delete_file` | 删除文件或递归删除目录 | `path` — 文件或目录路径 |
| `rename_file` | 重命名或移动文件/目录 | `old_path` — 当前路径，`new_path` — 新路径 |

### 搜索与浏览

| 工具 | 功能 | 参数 |
|------|------|------|
| `list_files` | 递归列出目录内容（最多 3 层） | `path` — 目录路径（默认 `.`） |
| `search_code` | 在项目中搜索文本模式（大小写不敏感） | `pattern` — 搜索模式，`path` — 搜索目录（默认 `.`） |
| `grep_search` | 在项目中搜索正则表达式模式 | `pattern` — 正则表达式，`path` — 搜索目录（默认 `.`） |

### 记忆管理

| 工具 | 功能 | 参数 |
|------|------|------|
| `read_memory` | 读取记忆文件（相对 `memory/` 路径） | `path` — 记忆文件路径 |
| `write_memory` | 写入记忆文件，支持追加模式，含易变内容检测 | `path` — 记忆文件路径，`content` — 内容，`append` — 是否追加 |
| `update_working_checkpoint` | 更新工作记忆检查点与关联 SOP | `key_info` — 检查点摘要，`related_sop` — SOP 路径 |

### 命令执行

| 工具 | 功能 | 参数 |
|------|------|------|
| `run_command` | 执行 Shell 命令（30s 超时 + 危险命令拦截） | `command` — Shell 命令 |

### 特殊命令

| 命令 | 功能 |
|------|------|
| `exit` / `quit` | 退出程序 |
| `clear` | 清空对话历史与工作记忆 |
| `Ctrl+C` | 安全中断退出 |

---

## 🏗️ 架构概览

```
┌──────────────────────────────────────────────────────────────────┐
│                        main.py (入口)                             │
│  聚合导出所有公共接口，支持 -v/-d 日志参数                          │
├──────────────────────────────────────────────────────────────────┤
│  chat_agent.py              │  tools.py          │  ui.py        │
│  ┌───────────────────────┐  │  ┌──────────────┐  │  ┌─────────┐  │
│  │ run_chat()  REPL 循环  │  │  │ 12 种工具定义 │  │  │ Rich    │  │
│  │ chat()  多轮 ReAct     │──▶│  │ 执行调度+安全 │  │  │ Panel   │  │
│  │ chat_once() 单次流式   │  │  │ 路径校验      │  │  │ Markdown│  │
│  │ 非流式回退 + 重试      │  │  │ 危险命令拦截  │  │  │ Live    │  │
│  └───────────────────────┘  │  └──────────────┘  │  └─────────┘  │
├──────────────────────────────────────────────────────────────────┤
│  prompts.py                 │  memory_manager.py                 │
│  ┌───────────────────────┐  │  ┌────────────────────────────┐    │
│  │ build_system_prompt()  │  │  │ ensure_memory_scaffold()   │    │
│  │ load_project_context() │  │  │ resolve_workspace_path()   │    │
│  │ build_memory_context() │  │  │ resolve_memory_path()      │    │
│  │ build_working_memory() │  │  │ is_volatile_memory_content()│   │
│  │ record_working_memory()│  │  │ fold_earlier_history()     │    │
│  │ extract_summary()      │  │  │ reject_memory_file_tool()  │    │
│  └───────────────────────┘  │  └────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────┤
│  config.py                  │  models.py                         │
│  ┌───────────────────────┐  │  ┌────────────────────────────┐    │
│  │ load_env_file()        │  │  │ Settings (frozen)          │    │
│  │ get_settings()         │  │  │ TokenUsageStats            │    │
│  │ build_client()         │  │  │ StepOutcome                │    │
│  │ 默认常量 (30+ 项)      │  │  │ WorkingMemoryState         │    │
│  └───────────────────────┘  │  └────────────────────────────┘    │
├──────────────────────────────────────────────────────────────────┤
│  logging_config.py                                              │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ setup_logging() — stderr 输出 + agent.log 文件日志        │   │
│  │ get_logger() — 全局 logger 获取                           │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

### 核心流程

1. **`run_chat()`** — 加载 `.env` → 初始化记忆目录 → 构建客户端 → 启动 REPL 循环
2. **`chat()`** — 多轮 ReAct 核心：发送消息 → 流式接收响应 → 解析工具调用 → 执行工具 → 循环直到无工具调用（最多 50 轮）
3. **`_request_chat_message()`** — LLM 请求封装：支持流式/非流式、自动重试（指数退避，最多 3 次）、`stream_options` 兼容处理
4. **`build_runtime_messages()`** — 每次 LLM 调用前注入工作记忆提示词，每 10 轮刷新记忆上下文
5. **`execute_tool()`** — 工具调度器：路径安全校验 → 危险命令拦截 → 记忆内容易变检测 → L1 行数限制
6. **`record_working_memory()`** — 每轮自动提取摘要（优先 `<summary>` 标签 → 首行文本 → 工具名），追加到滑动窗口

### 记忆层级

```
L0: memory_management_sop.md   → 记忆管理规范（写入前必读，元规则）
L1: global_mem_insight.txt     → 全局洞察索引（极简，≤30 行，存在性编码）
L2: global_mem.txt             → 环境事实（路径、用户偏好、配置常量）
L3: task_sops/ + tools/        → 任务 SOP 与可复用工具脚本
L4: sessions/ + L4_raw_sessions/ → 会话记录与原始日志归档
```

### 工作记忆机制

- **滑动窗口**：保留最近 30 轮摘要，超出部分折叠为 `（N turns）`
- **检查点**：通过 `update_working_checkpoint` 工具保存关键上下文
- **摘要提取**：优先匹配 `<summary>` 标签 → 首行非空文本 → 工具调用名 → "模型空响应"
- **记忆刷新**：每 10 轮重新注入 L1+L2 全局记忆上下文

---

## 📦 依赖

| 包 | 版本 | 用途 |
|----|------|------|
| `openai` | >=2.41.0 | OpenAI 兼容 API 客户端 |
| `rich` | >=15.0.0 | 终端美化渲染（Panel、Markdown、Live） |
| `prompt-toolkit` | >=3.0.52 | 终端输入增强 |

---

## 📄 License

MIT © 2025
