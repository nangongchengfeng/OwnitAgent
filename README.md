# OwnitAgent

> 终端 AI 编程助手 — 从 `.env` 读取配置，支持多模型、流式输出、工具调用与记忆系统。

[![Python](https://img.shields.io/badge/python-%3E%3D3.13-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

---

## 📖 简介

OwnitAgent 是一个运行在终端中的 AI 编程助手，基于 OpenAI 兼容 API，支持**流式输出**、**工具调用**（Function Calling）和**分层记忆系统**。它可以：

- 📖 **读取文件** — 带行号展示源码
- ✍️ **写入文件** — 自动创建父目录
- ✏️ **编辑文件** — 精确替换文件中的文本
- 🗑️ **删除文件** — 删除文件或目录
- 📝 **重命名文件** — 移动或重命名文件/目录
- 🖥️ **执行命令** — 带超时与危险命令拦截
- 📁 **浏览目录** — 自动忽略 `.git`、`node_modules` 等
- 🔍 **搜索代码** — 文本搜索与正则搜索
- 🧠 **记忆系统** — L0-L4 分层记忆，跨会话持久化
- 📋 **工作记忆** — 会话内轮次管理与上下文折叠

通过对话式交互，你可以让 AI 直接操作工作区内的文件，完成代码分析、重构、调试等任务。

---

## ✨ 特性

- 🔌 **兼容 OpenAI API** — 支持 DeepSeek、SiliconFlow、火山方舟等任意兼容接口
- ⚡ **流式输出** — 基于 Rich 库实时渲染 Markdown 回复
- 🛠️ **12 种工具** — AI 可自主调用文件操作、命令执行、记忆管理等工具
- 🧠 **分层记忆** — L0 管理规范 → L1 洞察索引 → L2 环境事实 → L3 SOP/工具脚本 → L4 原始会话
- 💾 **工作记忆** — 会话内自动记录轮次摘要，支持长对话上下文折叠
- 🔒 **工作区隔离** — 路径解析确保操作不超出项目根目录
- 🛡️ **危险命令拦截** — 自动拒绝 `rm -rf /` 等高风险操作
- 🎨 **美观终端 UI** — 使用 Rich 的 Panel、Markdown、Live 组件
- 📊 **Token 统计** — 会话结束时显示输入/输出 Token 用量
- 📋 **项目上下文** — 自动加载 README.md、CLAUDE.md、AGENTS.md 等项目文档
- 🧹 **历史清空** — 输入 `clear` 重置对话历史

---

## 🚀 快速开始

### 环境要求

- Python **>= 3.13**
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip

### 安装

```bash
# 克隆项目
git clone <your-repo-url>
cd <repo-dir>

# 使用 uv 安装依赖
uv sync

# 或使用 pip
pip install -r requirements.txt
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
python main.py
```

启动后你将看到欢迎面板，输入消息即可与 AI 对话，输入 `exit` 或 `quit` 退出，按 `Ctrl+C` 也可安全退出。

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
├── main.py                   # 兼容入口，聚合导出所有公共接口
├── chat_agent.py             # 对话主循环、控制命令、会话编排与 Token 统计
├── config.py                 # 环境变量加载、默认配置、客户端构造
├── memory_manager.py         # 记忆目录管理、路径安全校验、易变内容检测
├── models.py                 # 核心数据结构（Settings、TokenUsageStats、StepOutcome、WorkingMemoryState）
├── prompts.py                # 系统提示词、项目上下文、记忆上下文、工作记忆组装
├── tools.py                  # 12 种工具定义与执行逻辑
├── ui.py                     # Rich 终端渲染与输出格式化
├── pyproject.toml            # 项目元数据与依赖
├── uv.lock                   # 依赖锁定文件
├── README.md                 # 项目文档
├── docs/                     # 设计文档
│   └── context-management-design.md
├── memory/                   # 分层记忆存储
│   ├── memory_management_sop.md   # L0 - 记忆管理规范
│   ├── global_mem_insight.txt     # L1 - 全局记忆洞察
│   ├── global_mem.txt             # L2 - 全局记忆事实
│   ├── task_sops/                 # L3 - 任务 SOP
│   ├── tools/                     # L3 - 工具脚本
│   ├── sessions/                  # 会话记录
│   └── L4_raw_sessions/           # L4 - 原始会话
└── tests/                    # 测试目录
    └── test_main.py
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
| `delete_file` | 删除文件或目录 | `path` — 文件或目录路径 |
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
| `write_memory` | 写入记忆文件，支持追加模式 | `path` — 记忆文件路径，`content` — 内容，`append` — 是否追加 |
| `update_working_checkpoint` | 更新工作记忆检查点与关联 SOP | `key_info` — 检查点摘要，`related_sop` — SOP 路径 |

### 命令执行

| 工具 | 功能 | 参数 |
|------|------|------|
| `run_command` | 执行 Shell 命令（30s 超时） | `command` — Shell 命令 |

### 特殊命令

| 命令 | 功能 |
|------|------|
| `exit` / `quit` | 退出程序 |
| `clear` | 清空对话历史与工作记忆 |
| `Ctrl+C` | 安全中断退出 |

---

## 🏗️ 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                        main.py (入口)                         │
├──────────────────────────────────────────────────────────────┤
│  chat_agent.py          │  tools.py        │  ui.py          │
│  ┌───────────────────┐  │  ┌────────────┐  │  ┌───────────┐  │
│  │ run_chat()  REPL  │  │  │ 12 种工具   │  │  │ Rich 渲染  │  │
│  │ chat()  多轮对话   │──▶│  │ 执行+安全   │  │  │ Panel/     │  │
│  │ chat_once() 流式  │  │  │ 路径校验    │  │  │ Markdown   │  │
│  └───────────────────┘  │  └────────────┘  │  └───────────┘  │
├──────────────────────────────────────────────────────────────┤
│  prompts.py             │  memory_manager.py                 │
│  ┌───────────────────┐  │  ┌────────────────────────────┐    │
│  │ 系统提示词组装     │  │  │ 记忆目录 scaffold          │    │
│  │ 工作记忆提示词     │  │  │ 路径安全解析               │    │
│  │ 上下文加载        │  │  │ 易变内容检测               │    │
│  └───────────────────┘  │  │ 历史折叠                   │    │
│                         │  └────────────────────────────┘    │
├──────────────────────────────────────────────────────────────┤
│  config.py              │  models.py                         │
│  ┌───────────────────┐  │  ┌────────────────────────────┐    │
│  │ .env 加载         │  │  │ Settings / TokenUsageStats  │    │
│  │ 默认常量          │  │  │ StepOutcome                 │    │
│  │ OpenAI 客户端构造  │  │  │ WorkingMemoryState          │    │
│  └───────────────────┘  │  └────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘
```

### 核心流程

1. **`run_chat()`** — 加载 `.env`，初始化记忆目录，构建客户端，启动 REPL 循环
2. **`chat()`** — 多轮对话核心：发送消息 → 接收响应 → 执行工具调用 → 循环直到无工具调用
3. **`build_runtime_messages()`** — 每次 LLM 调用前注入工作记忆提示词，每 10 轮刷新记忆上下文
4. **`execute_tool()`** — 工具调度器，含路径安全校验、危险命令拦截、记忆内容验证
5. **`record_working_memory()`** — 每轮自动提取摘要存入工作记忆，支持长对话折叠

### 记忆层级

```
L0: memory_management_sop.md   → 记忆管理规范（写入前必读）
L1: global_mem_insight.txt     → 全局洞察索引（极简，≤30 行）
L2: global_mem.txt             → 环境事实（路径、用户偏好等）
L3: task_sops/ + tools/        → 任务 SOP 与可复用脚本
L4: sessions/ + L4_raw_sessions/ → 会话记录与原始日志
```

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
