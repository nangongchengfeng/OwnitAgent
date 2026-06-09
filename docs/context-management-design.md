# GenericAgent 上下文管理系统 — 设计文档

> **目标读者**：需要在新 Agent 项目中复用此上下文管理设计的开发者 / AI Agent。
> **来源**：GenericAgent v0.1.0，约 3K 行种子代码。
> **核心哲学**：不预装技能，让 Agent 在执行中自动将经验结晶为可复用记忆。

---

## 目录

1. [设计哲学](#1-设计哲学)
2. [整体架构](#2-整体架构)
3. [持久记忆：L0-L4 分层体系](#3-持久记忆-l0-l4-分层体系)
4. [系统提示词组装](#4-系统提示词组装)
5. [Agent Loop 中的上下文流转](#5-agent-loop-中的上下文流转)
6. [工作记忆：摘要结晶机制](#6-工作记忆摘要结晶机制)
7. [Token 节省策略](#7-token-节省策略)
8. [外部干预通道](#8-外部干预通道)
9. [L4 历史会话归档](#9-l4-历史会话归档)
10. [关键设计原则（复用清单）](#10-关键设计原则复用清单)
11. [附录：完整代码参考](#11-附录完整代码参考)

---

## 1. 设计哲学

### 1.1 核心信条

| 原则 | 含义 |
|------|------|
| **执行即记忆** | 只有工具调用成功验证过的信息才能写入持久记忆，禁止写入模型的"推理猜测" |
| **最小充分指针** | 上层只保留能定位下层的最短标识，多一词即冗余 |
| **自动结晶** | 每轮执行结果自动压缩为一句话摘要，无需人工整理 |
| **分层衰减** | 越久远的信息越压缩，但关键事实永不丢失 |

### 1.2 为什么不用 RAG / 向量数据库

GenericAgent 选择文件系统 + 纯文本作为记忆载体，原因：

- **LLM 本身就是最好的压缩器和解码器**。L1 只需让模型意识到"某类知识存在"，它就能通过 tool call 自行取用深层内容。
- **零依赖**：不需要额外数据库、embedding 服务。
- **可审计**：所有记忆都是人类可读的 Markdown / Python 文件。
- **可迁移**：复制 `memory/` 目录即可迁移全部记忆。

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     System Prompt                           │
│  sys_prompt.txt + 日期 + get_global_memory()               │
│  (L1 insight + L2 facts + 结构说明)                         │
└────────────────────────┬────────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────────┐
│                    Agent Loop (agent_loop.py)               │
│                                                             │
│  ┌──────────────┐   每轮注入    ┌──────────────────────┐    │
│  │ LLM Session  │◄────────────│ Working Memory        │    │
│  │ (维护历史)    │             │ - history_info (滑动)  │    │
│  │              │             │ - working.key_info     │    │
│  │              │   提取摘要   │ - working.related_sop  │    │
│  │              │────────────►│                        │    │
│  └──────────────┘             └──────────────────────┘    │
│                                                             │
│  每轮结束: turn_end_callback()                              │
│  - 从回复中提取 <summary> → 追加到 history_info             │
│  - 折叠旧历史 (超过30轮)                                    │
│  - 定期重新注入全局记忆 (每10轮)                             │
│  - 注入干预文件 (_keyinfo, _intervene)                      │
└─────────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│              持久记忆 (memory/ 目录)                        │
│                                                             │
│  L0: memory_management_sop.md    ← 元规则                   │
│  L1: global_mem_insight.txt      ← 极简索引 (≤30行)         │
│  L2: global_mem.txt              ← 环境事实库               │
│  L3: memory/*.md, memory/*.py    ← 任务级 SOP + 工具        │
│  L4: memory/L4_raw_sessions/     ← 历史会话归档             │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 持久记忆：L0-L4 分层体系

### 3.1 L0：元规则层

**文件**：`memory/memory_management_sop.md`

这是管理所有记忆的"宪法"，定义了如何读、写、修改记忆。任何记忆操作前必须先读此文件。

核心规则：

```
1. 行动验证原则：任何写入 L1/L2/L3 的信息，必须源自成功的工具调用结果。
   严禁将模型的"固有知识"、"推理猜测"、"未执行的计划"作为事实写入。
   口号：No Execution, No Memory.

2. 神圣不可删改性：凡是经过行动验证的有效配置、避坑指南、关键路径，
   在重构时严禁丢弃。可以压缩文字、可以迁移层级，但不能丢失准确性。

3. 禁止存储易变状态：严禁存储随时间/会话高频变化的数据。
   如：当前时间戳、临时 Session ID、正在运行的 PID、连接的设备信息。

4. 最小充分指针：上层只留能定位下层的最短标识，多一词即冗余。
```

### 3.2 L1：极简索引层

**文件**：`memory/global_mem_insight.txt`

**硬约束**：≤ 30 行，< 1k tokens。

**内容结构**：

```
# [Global Memory Insight]

# 第一层：高频场景 key→value（直接给出 sop/py/L2 section 名）
浏览器特殊操作: tmwebdriver_sop(文件上传/图搜/PDF blob/物理坐标/HttpOnly Cookie/...)
键鼠: ljqCtrl_sop(禁pyautogui/先activate)
截图/视觉: ocr/vision_sop | 禁全屏截图，优先窗口

# 第二层：低频场景仅列关键词
L3: memory_cleanup_sop(记忆整理) | skill_search | ui_detect.py | ocr_utils.py | ...

# RULES：压缩版避坑准则
[RULES]
1. 搜索先行: 搜文件名严禁不用es(禁PS递归/禁dir遍历), ...
2. 交叉验证: 禁信摘要, 数值进详情页核实
3. 编码安全: 禁PS cat/type用file_read; 改前必读; ...
...
```

**设计要点**：
- L1 本质是"存在性编码"——让 LLM 意识到某类知识存在，它就能自行 tool call 取用
- 场景触发词只在**反直觉**时才加括号注释（如 `tmwebdriver_sop(httponly cookie)`），名字自解释的不加
- RULES 只放"不提醒就会犯"的规则，按 ROI 评估：`(犯错概率 × 代价) / 每轮词数成本`

### 3.3 L2：环境事实库

**文件**：`memory/global_mem.txt`

存储全局环境性事实：IP、非标路径、凭证引用、配置常量等——这些是 LLM zero-shot 无法生成的信息。

```
# [Global Memory - L2]

## [PATHS]
GA_ROOT = D:\Code\Agents\GenericAgent
TEMP_DIR = ./temp

## [CONFIG]
DEFAULT_BROWSER = chrome
...
```

**禁止**：易变状态、猜测、LLM 可推理的通用常识。

### 3.4 L3：任务级记录库

**目录**：`memory/`

包含两类文件：

| 类型 | 命名 | 示例 | 内容 |
|------|------|------|------|
| SOP | `*_sop.md` | `vision_sop.md`、`plan_sop.md` | 关键前置条件 + 典型坑点，避免长篇教程 |
| 工具脚本 | `*.py` | `ocr_utils.py`、`ui_detect.py` | 高复用、逻辑复杂、不希望每次重新推理的处理流程 |

**写入原则**：只记录跨会话仍重要、且难以通过少量探测快速重建的要点。不记录普通操作步骤。

### 3.5 L4：历史会话归档

**目录**：`memory/L4_raw_sessions/`

- 原始 `model_responses_*.txt` 经 `compress_session.py` 压缩后按月打包为 zip
- 同时提取 `<history>` 块合并到 `all_histories.txt`
- 支持 `salient_mining_sop.md` 进行情绪事件和持续活动挖掘

详见 [第 9 节](#9-l4-历史会话归档)。

### 3.6 层级同步规则

```
L1 ↔ L2/L3 同步规则：

| 操作           | L1 同步                                      |
|----------------|----------------------------------------------|
| L2/L3 新增场景 | 新建默认低频→L3列表加文件名                    |
| L2/L3 删除场景 | 删除对应层的关键词/映射行                      |
| L2/L3 修改值   | 若不影响场景定位则不动 L1                      |
| 发现通用避坑规律 | 压缩为一句加入 RULES                          |

同步红线：L1 只写关键词/名称，禁搬细节。
```

### 3.7 信息分类决策树

```
"这条信息该放哪层？"

是『环境特异性事实』? (IP、非标路径、凭证、ID 等)
  ├─ YES → L2 (global_mem.txt)
  │        然后 → 按频率归入 L1 第一层或第二层
  └─ NO
       ↓
       是『通用操作规律』? (全局性避坑指南)
       ├─ YES → L1 [RULES] (仅限 1 句压缩准则)
       └─ NO
            ↓
            是『特定任务技术』? (艰难尝试才成功，未来还能用)
            ├─ YES → L3 (专项 SOP 或脚本)
            └─ NO → 判定为『通用常识』或『冗余信息』: 严禁存储，直接丢弃
```

---

## 4. 系统提示词组装

每次会话启动时，`agentmain.py` 的 `get_system_prompt()` 组装初始上下文：

```python
# agentmain.py
def get_system_prompt():
    # 1. 加载角色定义 + 行动原则
    with open(f'assets/sys_prompt{lang_suffix}.txt', 'r', encoding='utf-8') as f:
        prompt = f.read()

    # 2. 注入当前日期
    prompt += f"\nToday: {time.strftime('%Y-%m-%d %a')}\n"

    # 3. 注入全局记忆 (L1 insight + L2 facts + 结构说明)
    prompt += get_global_memory()

    return prompt
```

`sys_prompt.txt` 内容（极简，约 5 行）：

```
# Role: 物理级全能执行者
你拥有文件读写、脚本执行、用户浏览器JS注入、系统级干预的物理操作权限。
禁止推诿"无法操作"——不空想，用工具探测。
## 行动原则
调用工具前先推演：当前阶段、上步结果是否符合预期、下步策略，
必须在回复文本中用<summary>输出极简总结。
- 探测优先：失败时先充分获取信息，关键信息存入工作记忆，再决定重试或换方案。
- 失败升级：1次→读错误理解原因，2次→探测环境状态，3次→深度分析后换方案或问用户。
```

`get_global_memory()` 组装 L1+L2：

```python
# ga.py
def get_global_memory():
    prompt = "\n"
    try:
        # L1: 极简索引
        with open('memory/global_mem_insight.txt', 'r', encoding='utf-8') as f:
            insight = f.read()
        # 结构说明模板
        with open('assets/insight_fixed_structure.txt', 'r', encoding='utf-8') as f:
            structure = f.read()
        prompt += f'cwd = {script_dir}/temp (./)\n'
        prompt += f"\n[Memory] (../memory)\n"
        prompt += structure + '\n../memory/global_mem_insight.txt:\n'
        prompt += insight + "\n"
    except FileNotFoundError:
        pass
    return prompt
```

`insight_fixed_structure.txt`（结构说明模板）：

```
Facts(L2): ../memory/global_mem.txt | GA CodeRoot: ../
SOPs(L3): ../memory/*.md or *.py | META-SOP(L0): ../memory/memory_management_sop.md
L1 Insight是极简索引，L2/L3变更时同步L1，索引必须极简。写记忆前先读META-SOP(L0)。

[CONSTITUTION]
1. 改自身源码先请示；./内可自主实验，允许装包和portable工具
2. 决策前查记忆，有SOP/utils必用；多次失败回看SOP；未查证不断言
3. 分步执行，控制粒度，限制失败半径；3次失败请求干预
4. 密钥文件仅引用，不读取/移动
5. 写任何记忆前读META-SOP核验，memory下文件只能patch修改（除非新建）
```

此外，`llmcore.py` 的 `NativeToolClient` 还会追加 `THINKING_PROMPT`：

```python
# llmcore.py
THINKING_PROMPT_ZH = """
### 行动规范（持续有效）
每次回复（含工具调用轮）都先在回复文字中包含一个<summary></summary>
中输出极简单行（<30字）物理快照：上次结果新信息+本次意图。
此内容进入长期工作记忆。
\n**若用户需求未完成，必须进行工具调用！**
""".strip()
```

---

## 5. Agent Loop 中的上下文流转

### 5.1 核心循环

`agent_loop.py` 的 `agent_runner_loop()` 是上下文流转的核心：

```python
# agent_loop.py
def agent_runner_loop(client, system_prompt, user_input, handler,
                      tools_schema, max_turns=40, verbose=True,
                      initial_user_content=None, yield_info=False):
    # 初始化：只有 system + 首条 user 消息
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": initial_user_content or user_input}
    ]
    turn = 0
    handler.max_turns = max_turns

    while turn < handler.max_turns:
        turn += 1

        # 每10轮重置工具描述，防止累积
        if turn % 10 == 0:
            client.last_tools = ''

        # 调用 LLM
        response_gen = client.chat(messages=messages, tools=tools_schema)
        response = yield from response_gen

        # 解析工具调用
        if not response.tool_calls:
            tool_calls = [{'tool_name': 'no_tool', 'args': {}}]
        else:
            tool_calls = [{'tool_name': tc.function.name,
                          'args': json.loads(tc.function.arguments),
                          'id': tc.id}
                         for tc in response.tool_calls]

        # 执行工具
        tool_results = []
        next_prompts = set()
        for tc in tool_calls:
            outcome = handler.dispatch(tc['tool_name'], tc['args'], response)
            if outcome.should_exit:
                break
            if not outcome.next_prompt:
                break
            if outcome.data is not None and tc['tool_name'] != 'no_tool':
                tool_results.append({
                    'tool_use_id': tc['id'],
                    'content': json.dumps(outcome.data, ensure_ascii=False)
                })
            next_prompts.add(outcome.next_prompt)

        # 组装下一轮消息：只发一条 user 消息，历史由 Session 维护
        next_prompt = handler.turn_end_callback(
            response, tool_calls, tool_results, turn,
            '\n'.join(next_prompts), exit_reason
        )
        messages = [{
            "role": "user",
            "content": next_prompt,
            "tool_results": tool_results
        }]
```

### 5.2 关键设计：历史不放在 messages 里

注意 `messages` 每轮都被**替换**为仅一条 user 消息。完整的对话历史由 LLM Session 对象（`ClaudeSession` / `LLMSession` / `NativeClaudeSession` 等）在内部维护。

这样做的好处：
- Agent Loop 不需要关心历史管理
- 不同 LLM 后端（Claude Native / OpenAI / Mixin）可以有不同的历史格式
- `compress_history_tags()` 在 Session 层面对历史做 token 优化

### 5.3 NativeToolClient 的消息合并

```python
# llmcore.py - NativeToolClient.chat()
def chat(self, messages, tools=None):
    if tools:
        self.backend.tools = tools
    if not self.backend.history:
        self._pending_tool_ids = []

    combined_content = []
    tool_results = []

    for msg in messages:
        c = msg.get('content', '')
        if msg['role'] == 'system':
            self.set_system(c)  # 系统提示词单独设置
            continue
        if isinstance(c, str):
            combined_content.append({"type": "text", "text": c})
        elif isinstance(c, list):
            combined_content.extend(c)
        if msg['role'] == 'user' and msg.get('tool_results'):
            tool_results.extend(msg['tool_results'])

    # 将 tool_results 转为 tool_result content blocks
    tool_result_blocks = []
    for tr in tool_results:
        tool_result_blocks.append({
            "type": "tool_result",
            "tool_use_id": tr["tool_use_id"],
            "content": tr.get("content", "")
        })

    # 合并为一条 user 消息发送
    merged = {"role": "user", "content": tool_result_blocks + combined_content}
    gen = self.backend.ask(merged)
    # ...
```

---

## 6. 工作记忆：摘要结晶机制

这是 GenericAgent 上下文管理最精妙的部分——让模型自己维护工作记忆。

### 6.1 数据结构

```python
# ga.py - GenericAgentHandler.__init__()
class GenericAgentHandler(BaseHandler):
    def __init__(self, parent, last_history=None, cwd='./temp'):
        self.parent = parent
        self.working = {}              # 工作记忆字典
        self.cwd = cwd
        self.current_turn = 0
        self.history_info = last_history if last_history else []  # 摘要列表
        self.code_stop_signal = []
        self._done_hooks = []
```

| 字段 | 类型 | 作用 |
|------|------|------|
| `history_info` | `list[str]` | 每轮追加 `[Agent] <summary>`，形成滑动窗口 |
| `working['key_info']` | `str` | 通过 `update_working_checkpoint` 工具保存的关键上下文 |
| `working['related_sop']` | `str` | 关联的 SOP 文件路径 |
| `working['in_plan_mode']` | `str` | 计划模式下的计划文件路径 |

### 6.2 摘要提取

每轮 LLM 回复后，`turn_end_callback()` 自动提取 `<summary>` 标签：

```python
# ga.py - GenericAgentHandler.turn_end_callback()
def turn_end_callback(self, response, tool_calls, tool_results,
                      turn, next_prompt, exit_reason):
    # 1. 从回复中提取 <summary> 标签
    _c = re.sub(r'```.*?```|<thinking>.*?</thinking>', '',
                response.content, flags=re.DOTALL)
    rsumm = re.search(r"<summary>(.*?)</summary>", _c, re.DOTALL)

    if rsumm:
        summary = rsumm.group(1).strip()
    else:
        # 如果没有 <summary>，用工具调用信息作为 fallback
        tc = tool_calls[0]
        tool_name, args = tc['tool_name'], tc['args']
        summary = f"调用工具{tool_name}, args: {clean_args}"
        if tool_name == 'no_tool':
            summary = "直接回答了用户问题"
        # 提醒模型下次必须包含 <summary>
        next_prompt += "\n\n\n[SYSTEM] 必须在回复文本中包含<summary>！\n\n"

    # 2. 截断到 80 字，追加到工作记忆
    summary = smart_format(summary.replace('\n', ''), max_str_len=80)
    self.history_info.append(f'[Agent] {summary}')

    # ... 后续处理
```

### 6.3 工作记忆注入

每轮通过 `_get_anchor_prompt()` 将工作记忆注入到下一轮 prompt：

```python
# ga.py - GenericAgentHandler._get_anchor_prompt()
def _get_anchor_prompt(self, skip=False):
    if skip:
        return "\n"

    h = self.history_info
    W = 30  # 滑动窗口大小

    # 超过30轮的历史折叠压缩
    earlier = ''
    if len(h) > W:
        earlier = (f'<earlier_context>\n'
                   f'{self._fold_earlier(h[:-W])}\n'
                   f'</earlier_context>\n')

    # 最近30轮完整展示
    h_str = "\n".join(h[-W:])

    prompt = (f"\n### [WORKING MEMORY]\n"
              f"{earlier}"
              f"<history>\n{h_str}\n</history>")

    prompt += f"\nCurrent turn: {self.current_turn}\n"

    # 注入 key_info（检查点）
    if self.working.get('key_info'):
        prompt += f"\n<key_info>{self.working.get('key_info')}</key_info>"

    # 注入关联 SOP 提示
    if self.working.get('related_sop'):
        prompt += (f"\n有不清晰的地方请再次读取"
                   f"{self.working.get('related_sop')}")

    return prompt
```

### 6.4 历史折叠压缩

超过 30 轮的历史被折叠为紧凑格式：

```python
# ga.py - GenericAgentHandler._fold_earlier()
def _fold_earlier(self, lines):
    FALLBACK = '直接回答了用户问题'
    parts, cnt, last = [], 0, ''

    def flush():
        if cnt:
            if FALLBACK in last:
                parts.append(f'[Agent]（{cnt} turns）')
            else:
                parts.append(f'{last}（{cnt} turns）')

    for line in lines:
        if line.startswith('[USER]'):
            flush()
            parts.append(line)
            cnt = 0
            last = ''
        else:
            cnt += 1
            last = line
    flush()

    # 只保留最近 70 条折叠后的条目
    return "\n".join(parts[-70:])
```

折叠效果示例：

```
[USER] 帮我写一个爬虫
[Agent] 调用工具shell, args: {'command': 'pip install requests'}（3 turns）
[USER] 爬取结果不对
[Agent] 调用工具file_read, args: {'path': 'spider.py'}（5 turns）
```

### 6.5 检查点工具

模型可以通过 `update_working_checkpoint` 工具主动保存关键上下文：

```python
# ga.py - GenericAgentHandler.do_update_working_checkpoint()
def do_update_working_checkpoint(self, args, response):
    '''为整个任务设定后续需要临时记忆的重点。'''
    key_info = args.get("key_info", "")
    related_sop = args.get("related_sop", "")

    if "key_info" in args:
        self.working['key_info'] = key_info
    if "related_sop" in args:
        self.working['related_sop'] = related_sop

    self.working['passed_sessions'] = 0

    yield f"[Info] Updated key_info and related_sop.\n"

    next_prompt = self._get_anchor_prompt(
        skip=args.get('_index', 0) > 0
    )
    return StepOutcome(
        {"result": "working key_info updated"},
        next_prompt=next_prompt
    )
```

### 6.6 轮次感知的上下文注入

`turn_end_callback()` 还根据轮次动态注入提示：

```python
# ga.py - turn_end_callback() 中的轮次逻辑
if turn % 75 == 0 and (not _plan):
    next_prompt += (f"\n\n[DANGER] 已连续执行第 {turn} 轮。"
                    f"必须总结情况进行ask_user，不允许继续重试。")
elif turn % 7 == 0:
    next_prompt += (f"\n\n[DANGER] 已连续执行第 {turn} 轮。"
                    f"禁止无效重试。若无有效进展，必须切换策略："
                    f"1. 探测物理边界 2. 请求用户协助。"
                    f"如有需要，可调用 update_working_checkpoint 保存关键上下文。")
elif turn % 10 == 0:
    # 每10轮重新注入全局记忆
    next_prompt += get_global_memory()
```

---

## 7. Token 节省策略

### 7.1 历史标签截断

`llmcore.py` 的 `compress_history_tags()` 对旧消息中的标签内容做首尾截断：

```python
# llmcore.py
def compress_history_tags(messages, keep_recent=10, max_len=800,
                          force=False, interval=5):
    """Compress <thinking>/<tool_use>/<tool_result> tags in older messages."""
    # 每 interval 轮执行一次
    compress_history_tags._cd = getattr(compress_history_tags, '_cd', 0) + 1
    if force:
        compress_history_tags._cd = 0
    if compress_history_tags._cd % interval != 0:
        return messages

    _pats = {
        tag: re.compile(rf'(<{tag}>)([\s\S]*?)(</{tag}>)')
        for tag in ('thinking', 'think', 'tool_use', 'tool_result')
    }
    _hist_pat = re.compile(
        r'<(history|key_info|earlier_context)>[\s\S]*?</\1>'
    )

    def _trunc_str(s):
        """保留首尾各 max_len//2 字符"""
        if isinstance(s, str) and len(s) > max_len:
            return s[:max_len//2] + '\n...[Truncated]...\n' + s[-max_len//2:]
        return s

    def _trunc(text):
        # 先压缩历史块
        text = _hist_pat.sub(
            lambda m: f'<{m.group(1)}>[...]</{m.group(1)}>', text
        )
        # 再压缩 thinking/tool 标签
        for pat in _pats.values():
            text = pat.sub(
                lambda m: m.group(1) + _trunc_str(m.group(2)) + m.group(3),
                text
            )
        return text

    # 只处理旧消息，保留最近 keep_recent 条
    for i, msg in enumerate(messages):
        if i >= len(messages) - keep_recent:
            break
        c = msg['content']
        if isinstance(c, str):
            msg['content'] = _trunc(c)
        elif isinstance(c, list):
            for b in c:
                if not isinstance(b, dict):
                    continue
                t = b.get('type')
                if t == 'text':
                    b['text'] = _trunc(b.get('text', ''))
                elif t == 'tool_result':
                    b['content'] = _trunc_str(b.get('content', ''))
                elif t == 'tool_use':
                    for k, v in b.get('input', {}).items():
                        b['input'][k] = _trunc_str(v)

    return messages
```

### 7.2 代码块收缩

```python
# agent_loop.py - _clean_content()
def _clean_content(text):
    if not text:
        return ''

    def _shrink_code(m):
        lines = m.group(0).split('\n')
        lang = lines[0].replace('```', '').strip()
        body = [l for l in lines[1:-1] if l.strip()]
        if len(body) <= 6:
            return m.group(0)
        preview = '\n'.join(body[:5])
        return f'```{lang}\n{preview}\n  ... ({len(body)} lines)\n```'

    text = re.sub(r'```[\s\S]*?```', _shrink_code, text)

    # 移除 XML 标签块和多余空行
    for p in [r'<file_content>[\s\S]*?</file_content>',
              r'<tool_(?:use|call)>[\s\S]*?</tool_(?:use|call)>',
              r'(\r?\n){3,}']:
        text = re.sub(p, '\n\n' if '\\n' in p else '', text)

    return text.strip()
```

### 7.3 工具描述重置

```python
# agent_loop.py - agent_runner_loop()
if turn % 10 == 0:
    client.last_tools = ''  # 每10轮重置，防止工具描述累积
```

### 7.4 策略总结

| 策略 | 触发条件 | 效果 |
|------|----------|------|
| 历史标签截断 | 每 5 轮 | 旧消息中的 `<thinking>`/`<tool_use>`/`<tool_result>` 只保留首尾 |
| 代码块收缩 | 每次展示 | 超过 6 行的代码块只显示前 5 行 |
| 历史折叠 | 超过 30 轮 | 早期轮次压缩为 `（N turns）` |
| 工具描述重置 | 每 10 轮 | 防止工具描述累积膨胀 |
| 全局记忆刷新 | 每 10 轮 | 重新注入 L1+L2，确保不遗忘 |

---

## 8. 外部干预通道

支持运行时注入上下文，无需重启 Agent：

```python
# ga.py - turn_end_callback() 中的干预逻辑

# 1. 注入 key_info（追加到工作记忆）
injkeyinfo = consume_file(self.parent.task_dir, '_keyinfo')
if injkeyinfo:
    self.working['key_info'] = (
        self.working.get('key_info', '') + f"\n[MASTER] {injkeyinfo}"
    )

# 2. 注入 prompt（直接追加到下轮消息）
injprompt = consume_file(self.parent.task_dir, '_intervene')
if injprompt:
    next_prompt += f"\n\n[MASTER] {injprompt}\n"

# 3. 插件钩子
for hook in list(getattr(self.parent, '_turn_end_hooks', {}).values()):
    hook(locals())
```

`consume_file()` 是"读取后删除"的原子操作：

```python
# ga.py
def consume_file(dr, file):
    """读取文件内容后立即删除，实现一次性消息传递"""
    if dr and os.path.exists(os.path.join(dr, file)):
        with open(os.path.join(dr, file), encoding='utf-8') as f:
            content = f.read()
        os.remove(os.path.join(dr, file))
        return content
```

**使用方式**：

```bash
# 在 task_dir 下创建文件即可注入
echo "用户刚才说用 Chrome 而不是 Firefox" > temp/my_task/_keyinfo
echo "请先确认网络连接再继续" > temp/my_task/_intervene

# 停止当前任务
touch temp/my_task/_stop
```

---

## 9. L4 历史会话归档

### 9.1 压缩流程

`memory/L4_raw_sessions/compress_session.py` 负责将原始会话日志归档：

```python
# compress_session.py - 核心流程

def batch_process(src, l4_dir=None, dry_run=True):
    """
    Phase 1: 压缩原始日志 + 提取 history
    Phase 2: 追加到 all_histories.txt
    Phase 3: 按月打包 zip
    Phase 4: 删除原始文件
    """

    # Phase 1: 压缩
    for fp in raw_files:
        # 跳过最近 2 小时的文件（可能还在写入）
        if os.path.getmtime(fp) > time.time() - 7200:
            continue

        dst, info = compress_session(fp, tmp_dir)
        # compress_session 内部：
        #   - 检测格式 (JSON vs Raw)
        #   - Raw 格式：剥离系统提示词和 assistant 回显
        #   - 太小的文件（<4.5KB）丢弃
        #   - 文件名格式：MMDD_HHMM-MMDD_HHMM.txt

        # 提取 <history> 块
        hist = extract_history(dst)

    # Phase 2: 追加历史
    with open('all_histories.txt', 'a') as f:
        for sn, _, hist, _, _ in results:
            if hist:
                f.write(format_history_block(sn, hist))

    # Phase 3: 按月打包
    for month, items in by_month.items():
        with zipfile.ZipFile(f'{month}.zip', 'a') as zf:
            for sn, cp in items:
                zf.write(cp, f'{sn}.txt')

    # Phase 4: 删除原始文件
    for rp in to_del:
        os.remove(rp)
```

### 9.2 历史提取

从压缩后的会话中提取 `<history>` 块：

```python
# compress_session.py
_RE_HISTORY = re.compile(r'<history>(.*?)</history>', re.S)

def extract_history(src):
    """从会话文件中提取所有 <history> 块并合并去重"""
    with open(src, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()

    all_blocks = []
    for m in _RE_HISTORY.finditer(text):
        parsed = _parse_history_block(m.group(1))
        if parsed:
            all_blocks.append(parsed)

    return _merge_history_blocks(all_blocks)
```

### 9.3 重点挖掘

`salient_mining_sop.md` 定义了从 `all_histories.txt` 中挖掘有价值信息的流程：

- **情绪事件**：标记用户语气上的明显波动（愤怒、惊喜、沮丧等）
- **持续活动**：用户生活中仍然存在的事项
- **已消失事项**：曾经存在但已离开的事项

产物存入 `./history_insight/`，作为下游任务的输入数据库。

---

## 10. 关键设计原则（复用清单）

如果你想在新 Agent 中复用这套设计，以下是核心要点：

### 10.1 必须实现的

1. **分层记忆 (L0-L4)**
   - L0: 元规则（如何管理记忆）
   - L1: 极简索引（≤30 行，只做"存在性编码"）
   - L2: 环境事实（路径、配置、凭证引用）
   - L3: 任务级 SOP + 工具脚本
   - L4: 历史会话归档

2. **摘要结晶机制**
   - 要求模型每轮输出 `<summary>` 标签
   - 自动提取并追加到滑动窗口
   - 超过窗口的历史折叠压缩

3. **工作记忆注入**
   - 每轮将 `history_info` + `key_info` 注入 prompt
   - 支持 `update_working_checkpoint` 工具

4. **行动验证原则**
   - 只有工具调用成功的结果才能写入持久记忆
   - 禁止写入模型的推理猜测

5. **外部干预通道**
   - 文件系统作为消息传递机制
   - 支持运行时注入上下文和中断

### 10.2 建议实现的

6. **Token 节省**
   - 旧消息标签内容截断
   - 代码块收缩
   - 定期重置工具描述

7. **轮次感知提示**
   - 不同轮次注入不同级别的警告
   - 定期刷新全局记忆

8. **历史归档**
   - 原始会话压缩存储
   - 按月打包
   - 提取可检索的历史摘要

### 10.3 设计决策

9. **文件系统 > 向量数据库**
   - LLM 本身就是压缩器+解码器
   - 零依赖、可审计、可迁移

10. **历史由 Session 维护，不由 Agent Loop 维护**
    - Agent Loop 只发当前轮消息
    - 不同 LLM 后端各自管理历史格式

11. **最小充分指针**
    - 上层只留能定位下层的最短标识
    - 信息分类决策树决定存放层级

---

## 11. 附录：完整代码参考

### 11.1 文件索引

| 文件 | 职责 |
|------|------|
| `agentmain.py` | 入口，系统提示词组装，GenericAgent 类 |
| `agent_loop.py` | Agent 循环，`agent_runner_loop()`，`BaseHandler` |
| `ga.py` | `GenericAgentHandler`，工具实现，工作记忆，`get_global_memory()` |
| `llmcore.py` | LLM 后端，Session 管理，`compress_history_tags()`，`NativeToolClient` |
| `memory/memory_management_sop.md` | L0 元规则 |
| `memory/global_mem_insight.txt` | L1 极简索引 |
| `memory/global_mem.txt` | L2 环境事实库 |
| `memory/memory_cleanup_sop.md` | L1 整理 SOP |
| `memory/L4_raw_sessions/compress_session.py` | L4 归档脚本 |
| `memory/L4_raw_sessions/salient_mining_sop.md` | L4 重点挖掘 SOP |
| `assets/sys_prompt.txt` | 系统角色定义 |
| `assets/insight_fixed_structure.txt` | L1/L2 结构说明模板 |

### 11.2 关键数据流

```
启动时:
  get_system_prompt()
    → sys_prompt.txt (角色+原则)
    → 日期
    → get_global_memory()
        → insight_fixed_structure.txt (结构说明)
        → global_mem_insight.txt (L1 索引)
        → global_mem.txt (L2 事实)
    → THINKING_PROMPT (摘要要求)

每轮:
  _get_anchor_prompt()
    → history_info (滑动窗口摘要)
    → _fold_earlier() (折叠旧历史)
    → working.key_info (检查点)
    → working.related_sop (关联 SOP)

每轮结束:
  turn_end_callback()
    → 提取 <summary> → 追加 history_info
    → 轮次感知提示注入
    → 外部干预文件检查
    → 全局记忆刷新 (每10轮)

Token 优化:
  compress_history_tags() (每5轮)
  _clean_content() (代码块收缩)
  client.last_tools = '' (每10轮)
```

---

> **文档版本**: 1.0
> **基于**: GenericAgent v0.1.0
> **生成日期**: 2026-06-09
