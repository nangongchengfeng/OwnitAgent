---
alwaysApply: true
scene: git_message
---

- [必须] 允许 `git commit`，但执行前必须征得用户确认。user.email "1794748404@qq.com"，user.name "nangongchengfeng"
- [必须]  禁止出现 Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
- [必须] 使用约定式中文提交：`<type>(<scope>): <subject>`。
- [必须] `type` 只使用：`feat`、`fix`、`docs`、`style`、`refactor`、`test`、`chore`、`perf`。
- [必须] 主题最多 50 个字符，使用命令语气，不加句号。
- [必须] 不同问题拆成多个小而聚焦的提交。
- [优先] 每次提交前运行 linter 或项目定义的最小验证命令。
- [默认] 小改动使用单行提交信息；复杂改动在正文说明"做了什么"和"为什么做"。
