# MagicCode

> 终端 AI 编程助手 — 从 `.env` 读取配置，支持多模型、流式输出与工具调用。

[![Python](https://img.shields.io/badge/python-%3E%3D3.13-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](./LICENSE)

---

## 📖 简介

MagicCode 是一个运行在终端中的 AI 编程助手，基于 OpenAI 兼容 API，支持**流式输出**和**工具调用**（Function Calling）。它可以：

- 📖 **读取文件** — 带行号展示源码
- ✍️ **写入文件** — 自动创建父目录
- ✏️ **编辑文件** — 精确替换文件中的文本
- 🖥️ **执行命令** — 带超时与危险命令拦截
- 📁 **浏览目录** — 自动忽略 `.git`、`node_modules` 等
- 🔍 **搜索代码** — 在项目中搜索文本模式

通过对话式交互，你可以让 AI 直接操作工作区内的文件，完成代码分析、重构、调试等任务。

---

## ✨ 特性

- 🔌 **兼容 OpenAI API** — 支持 DeepSeek、SiliconFlow、火山方舟等任意兼容接口
- ⚡ **流式输出** — 基于 Rich 库实时渲染 Markdown 回复
- 🛠️ **工具调用** — AI 可自主选择调用文件读写、命令执行等 6 种工具
- 🔒 **工作区隔离** — 路径解析确保操作不超出项目根目录
- 🛡️ **危险命令拦截** — 自动拒绝 `rm -rf /` 等高风险操作
- 🎨 **美观终端 UI** — 使用 Rich 的 Panel、Markdown、Live 组件
- 📊 **Token 统计** — 会话结束时显示输入/输出 Token 用量
- 📋 **项目上下文** — 自动加载 README.md 等项目文档作为上下文
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
cd demo_agents

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

启动后你将看到欢迎面板，输入消息即可与 AI 对话，输入 `exit` 或 `quit` 退出。

---

## 📂 项目结构

```
demo_agents/
├── .env                 # 环境变量配置（不纳入版本控制）
├── .gitignore           # Git 忽略规则
├── .python-version      # Python 版本声明
├── main.py              # 主程序入口
├── pyproject.toml       # 项目元数据与依赖
├── uv.lock              # 依赖锁定文件
├── README.md            # 项目文档
└── tests/               # 测试目录
```

---

## 🛠️ 工具说明

AI 助手可调用以下六种工具：

| 工具 | 功能 | 参数 |
|------|------|------|
| `read_file` | 读取文件，返回带行号内容 | `path` — 文件路径 |
| `write_file` | 写入文件，自动创建父目录 | `path` — 文件路径，`content` — 文件内容 |
| `edit_file` | 替换文件中的文本（首次匹配） | `path` — 文件路径，`old_text` — 原文本，`new_text` — 新文本 |
| `run_command` | 执行 Shell 命令（30s 超时） | `command` — Shell 命令 |
| `list_files` | 递归列出目录内容（最多 3 层） | `path` — 目录路径（默认 `.`） |
| `search_code` | 在项目中搜索文本模式 | `pattern` — 搜索模式，`path` — 搜索目录（默认 `.`） |

### 特殊命令

| 命令 | 功能 |
|------|------|
| `exit` / `quit` | 退出程序 |
| `clear` | 清空对话历史 |

---

## 🏗️ 架构概览

```
┌──────────────┐     ┌────────────────┐     ┌─────────────────┐
│   main.py    │────▶│  OpenAI API    │────▶│  Tool Executor  │
│  (终端交互)   │◀────│  (流式 + 工具)  │◀────│  (安全沙箱)      │
└──────────────┘     └────────────────┘     └─────────────────┘
```

- **`Settings`** — 数据类，封装 API 配置
- **`TokenUsageStats`** — Token 用量统计
- **`execute_tool()`** — 工具调度器，含路径校验与危险命令拦截（6 种工具）
- **`chat()`** — 核心对话循环，处理工具调用的多轮交互
- **`chat_once()`** — 单轮流式对话，使用 Rich Live 实时渲染
- **`handle_control_command()`** — 特殊命令处理（如 `clear` 清空历史）
- **`build_system_prompt()`** — 构建系统提示词，自动加载项目上下文
- **`run_chat()`** — 主入口，加载配置并启动 REPL 循环

---

## 📦 依赖

| 包 | 版本 | 用途 |
|----|------|------|
| `openai` | >=2.41.0 | OpenAI 兼容 API 客户端 |
| `rich` | >=15.0.0 | 终端美化渲染 |
| `prompt-toolkit` | >=3.0.52 | 终端输入增强 |

---

## 📄 License

MIT © 2025
