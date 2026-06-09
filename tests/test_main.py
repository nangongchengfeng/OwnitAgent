import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import chat_agent
import main
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_env = {
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY"),
            "OPENAI_MODEL": os.environ.get("OPENAI_MODEL"),
            "OPENAI_BASE_URL": os.environ.get("OPENAI_BASE_URL"),
        }
        for key in self.original_env:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_load_env_file_and_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "OPENAI_API_KEY=sk-xx\n"
                "OPENAI_MODEL=deepseek-ai/DeepSeek-V4-Flash\n"
                "OPENAI_BASE_URL=https://api.siliconflow.cn/v1\n",
                encoding="utf-8",
            )

            main.load_env_file(env_path)
            settings = main.get_settings()

            self.assertEqual(settings.api_key, "sk-xx")
            self.assertEqual(settings.model, "deepseek-ai/DeepSeek-V4-Flash")
            self.assertEqual(settings.base_url, "https://api.siliconflow.cn/v1")

    def test_build_client_uses_custom_base_url(self) -> None:
        settings = main.Settings(
            api_key="sk-xx",
            model="deepseek-ai/DeepSeek-V4-Flash",
            base_url="https://api.siliconflow.cn/v1",
        )

        client = main.build_client(settings)

        self.assertEqual(client.api_key, "sk-xx")
        self.assertEqual(str(client.base_url), "https://api.siliconflow.cn/v1/")

    def test_chat_once_renders_markdown_panel_and_returns_full_text(self) -> None:
        settings = main.Settings(
            api_key="sk-xx",
            model="deepseek-ai/DeepSeek-V4-Flash",
            base_url="https://api.siliconflow.cn/v1",
        )
        history = [{"role": "user", "content": "你好"}]
        chunks = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="你"))]
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="好"))]
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None))]
            ),
        ]

        class FakeCompletions:
            def __init__(self, stream_chunks: list[object]) -> None:
                self.stream_chunks = stream_chunks
                self.calls: list[dict[str, object]] = []

            def create(self, **kwargs: object) -> list[object]:
                self.calls.append(kwargs)
                return self.stream_chunks

        class FakeLive:
            def __init__(self, **kwargs: object) -> None:
                self.kwargs = kwargs
                self.updates: list[object] = []

            def __enter__(self) -> "FakeLive":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def update(self, renderable: object) -> None:
                self.updates.append(renderable)

        fake_completions = FakeCompletions(chunks)
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake_completions)
        )
        fake_console = SimpleNamespace()
        live = FakeLive(console=fake_console, refresh_per_second=8)

        reply = main.chat_once(
            fake_client,
            settings,
            history,
            console=fake_console,
            live_factory=lambda **kwargs: live,
        )

        self.assertEqual(reply, "你好")
        self.assertEqual(len(fake_completions.calls), 1)
        self.assertIs(fake_completions.calls[0]["messages"], history)
        self.assertEqual(fake_completions.calls[0]["model"], settings.model)
        self.assertIs(fake_completions.calls[0]["stream"], True)
        self.assertEqual(len(live.updates), 2)
        panel = live.updates[-1]
        self.assertIsInstance(panel, Panel)
        self.assertEqual(panel.title, "OwnitAgent")
        self.assertEqual(str(panel.border_style), "blue")
        self.assertIsInstance(panel.renderable, Markdown)
        self.assertEqual(panel.renderable.markup, "你好")

    def test_build_welcome_panel_uses_rich_styling(self) -> None:
        settings = main.Settings(
            api_key="sk-xx",
            model="deepseek-ai/DeepSeek-V4-Flash",
            base_url="https://api.siliconflow.cn/v1",
        )

        panel = main.build_welcome_panel(settings)

        self.assertIsInstance(panel, Panel)
        self.assertEqual(str(panel.border_style), "cyan")
        self.assertIn("OwnitAgent", panel.renderable)
        self.assertIn(settings.model, panel.renderable)

    def test_build_system_prompt_includes_project_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            (workspace_root / "README.md").write_text("readme body", encoding="utf-8")
            (workspace_root / "AGENTS.md").write_text("agents body", encoding="utf-8")

            prompt = main.build_system_prompt(workspace_root)

        self.assertIn("## Project Context", prompt)
        self.assertIn("--- README.md ---", prompt)
        self.assertIn("readme body", prompt)
        self.assertIn("--- AGENTS.md ---", prompt)
        self.assertIn("agents body", prompt)

    def test_ensure_memory_scaffold_creates_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)

            main.ensure_memory_scaffold(workspace_root)

            self.assertTrue((workspace_root / "memory" / "memory_management_sop.md").exists())
            self.assertTrue((workspace_root / "memory" / "global_mem_insight.txt").exists())
            self.assertTrue((workspace_root / "memory" / "global_mem.txt").exists())
            self.assertTrue((workspace_root / "memory" / "task_sops").is_dir())
            self.assertTrue((workspace_root / "memory" / "tools").is_dir())
            self.assertTrue((workspace_root / "memory" / "L4_raw_sessions").is_dir())

    def test_build_system_prompt_includes_memory_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            main.ensure_memory_scaffold(workspace_root)
            (workspace_root / "memory" / "global_mem_insight.txt").write_text(
                "浏览器特殊操作: browser_sop",
                encoding="utf-8",
            )
            (workspace_root / "memory" / "global_mem.txt").write_text(
                "## [PATHS]\nROOT=demo",
                encoding="utf-8",
            )

            prompt = main.build_system_prompt(workspace_root)

        self.assertIn("## Memory Context", prompt)
        self.assertIn("global_mem_insight.txt", prompt)
        self.assertIn("browser_sop", prompt)
        self.assertIn("## [PATHS]", prompt)

    def test_record_token_usage_updates_totals(self) -> None:
        stats = main.TokenUsageStats()
        response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5)
        )

        main.record_token_usage(stats, response)

        self.assertEqual(stats.input_tokens, 12)
        self.assertEqual(stats.output_tokens, 5)
        self.assertEqual(
            main.build_token_summary(stats),
            "[dim]Token 统计 — 输入: 12 | 输出: 5[/]",
        )

    def test_compact_tool_args_shortens_path_and_long_payload(self) -> None:
        compact = main._compact_tool_args(
            "read_file",
            {
                "path": "nested/demo/example.py",
                "content": "x" * 200,
            },
        )

        self.assertIn("example.py", compact)
        self.assertNotIn("nested/demo", compact)
        self.assertTrue(compact.endswith("..."))

    def test_clean_content_shrinks_large_blocks_and_tags(self) -> None:
        text = (
            "前文\n\n"
            "<tool_call>hidden</tool_call>\n\n"
            "```python\n"
            "line1\nline2\nline3\nline4\nline5\nline6\nline7\n"
            "```\n\n\n结尾"
        )

        cleaned = main._clean_content(text)

        self.assertNotIn("<tool_call>", cleaned)
        self.assertIn("... (7 lines)", cleaned)
        self.assertNotIn("\n\n\n", cleaned)

    def test_normalize_tool_outcome_wraps_string_result(self) -> None:
        outcome = main.normalize_tool_outcome("done")

        self.assertIsInstance(outcome, main.StepOutcome)
        self.assertEqual(outcome.data, "done")
        self.assertIsNone(outcome.next_prompt)
        self.assertFalse(outcome.should_exit)

    def test_execute_tool_can_write_read_and_list_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)

            write_result = main.execute_tool(
                "write_file",
                {"path": "notes/hello.txt", "content": "hello\nworld"},
                workspace_root=workspace_root,
            )
            read_result = main.execute_tool(
                "read_file",
                {"path": "notes/hello.txt"},
                workspace_root=workspace_root,
            )
            list_result = main.execute_tool(
                "list_files",
                {"path": "notes"},
                workspace_root=workspace_root,
            )
            edit_result = main.execute_tool(
                "edit_file",
                {
                    "path": "notes/hello.txt",
                    "old_text": "world",
                    "new_text": "agent",
                },
                workspace_root=workspace_root,
            )
            search_result = main.execute_tool(
                "search_code",
                {"pattern": "agent", "path": "notes"},
                workspace_root=workspace_root,
            )
            grep_result = main.execute_tool(
                "grep_search",
                {"pattern": r"he..o", "path": "notes"},
                workspace_root=workspace_root,
            )
            rename_result = main.execute_tool(
                "rename_file",
                {"old_path": "notes/hello.txt", "new_path": "notes/renamed.txt"},
                workspace_root=workspace_root,
            )
            deleted_write = main.execute_tool(
                "write_file",
                {"path": "trash/tmp.txt", "content": "remove me"},
                workspace_root=workspace_root,
            )
            delete_result = main.execute_tool(
                "delete_file",
                {"path": "trash/tmp.txt"},
                workspace_root=workspace_root,
            )
            renamed_exists = (workspace_root / "notes" / "renamed.txt").exists()
            deleted_exists = (workspace_root / "trash" / "tmp.txt").exists()

        self.assertIn("Written to", write_result)
        self.assertIn("hello.txt", read_result)
        self.assertIn("   1 | hello", read_result)
        self.assertIn("   2 | world", read_result)
        self.assertIn("[file] hello.txt", list_result)
        self.assertIn("Edited", edit_result)
        self.assertIn("hello.txt:2: agent", search_result)
        self.assertIn("hello.txt:1: hello", grep_result)
        self.assertIn("Renamed", rename_result)
        self.assertIn("Written to", deleted_write)
        self.assertIn("Deleted", delete_result)
        self.assertFalse(deleted_exists)
        self.assertTrue(renamed_exists)

    def test_execute_tool_can_manage_memory_files_and_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            main.ensure_memory_scaffold(workspace_root)
            session_memory = main.WorkingMemoryState()

            write_result = main.execute_tool(
                "write_memory",
                {"path": "global_mem.txt", "content": "## [CONFIG]\nAPI=demo"},
                workspace_root=workspace_root,
                session_memory=session_memory,
            )
            read_result = main.execute_tool(
                "read_memory",
                {"path": "global_mem.txt"},
                workspace_root=workspace_root,
                session_memory=session_memory,
            )
            checkpoint_result = main.execute_tool(
                "update_working_checkpoint",
                {"key_info": "先确认 API 配置", "related_sop": "memory/task_sops/config_sop.md"},
                workspace_root=workspace_root,
                session_memory=session_memory,
            )

        self.assertIn("Written memory", write_result)
        self.assertIn("## [CONFIG]", read_result)
        self.assertIsInstance(checkpoint_result, main.StepOutcome)
        self.assertEqual(session_memory.key_info, "先确认 API 配置")
        self.assertEqual(session_memory.related_sop, "memory/task_sops/config_sop.md")

    def test_write_memory_rejects_volatile_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            main.ensure_memory_scaffold(workspace_root)

            result = main.execute_tool(
                "write_memory",
                {"path": "global_mem.txt", "content": "时间戳: 2026-06-09 12:00:00"},
                workspace_root=workspace_root,
            )

        self.assertIn("Error: volatile content", result)

    def test_general_file_tools_reject_memory_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace_root = Path(temp_dir)
            main.ensure_memory_scaffold(workspace_root)

            read_result = main.execute_tool(
                "read_file",
                {"path": "memory/global_mem.txt"},
                workspace_root=workspace_root,
            )
            write_result = main.execute_tool(
                "write_file",
                {"path": "memory/demo.txt", "content": "x"},
                workspace_root=workspace_root,
            )
            edit_result = main.execute_tool(
                "edit_file",
                {
                    "path": "memory/global_mem.txt",
                    "old_text": "PROJECT_ROOT = .",
                    "new_text": "PROJECT_ROOT = demo",
                },
                workspace_root=workspace_root,
            )
            delete_result = main.execute_tool(
                "delete_file",
                {"path": "memory/global_mem.txt"},
                workspace_root=workspace_root,
            )
            rename_result = main.execute_tool(
                "rename_file",
                {
                    "old_path": "memory/global_mem.txt",
                    "new_path": "memory/global_mem_2.txt",
                },
                workspace_root=workspace_root,
            )

        self.assertIn("Use memory tools instead", read_result)
        self.assertIn("Use memory tools instead", write_result)
        self.assertIn("Use memory tools instead", edit_result)
        self.assertIn("Use memory tools instead", delete_result)
        self.assertIn("Use memory tools instead", rename_result)

    def test_tools_include_delete_and_rename(self) -> None:
        tool_names = [tool["function"]["name"] for tool in main.TOOLS]

        self.assertIn("delete_file", tool_names)
        self.assertIn("rename_file", tool_names)
        self.assertIn("grep_search", tool_names)
        self.assertIn("read_memory", tool_names)
        self.assertIn("write_memory", tool_names)
        self.assertIn("update_working_checkpoint", tool_names)

    def test_execute_tool_refuses_dangerous_command(self) -> None:
        result = main.execute_tool(
            "run_command",
            {"command": "rm -rf /"},
            workspace_root=Path.cwd(),
        )

        self.assertEqual(result, "Refused to execute dangerous command")

    def test_chat_runs_react_tool_loop_and_returns_final_reply(self) -> None:
        settings = main.Settings(
            api_key="sk-xx",
            model="deepseek-ai/DeepSeek-V4-Flash",
            base_url="https://api.siliconflow.cn/v1",
        )
        history = [{"role": "system", "content": "system"}]
        responses = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="我先读文件",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name="read_file",
                                        arguments='{"path":"demo.txt"}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="读取完成",
                            tool_calls=[],
                        )
                    )
                ]
            ),
        ]

        class FakeCompletions:
            def __init__(self, queued_responses: list[object]) -> None:
                self.queued_responses = queued_responses
                self.calls: list[dict[str, object]] = []

            def create(self, **kwargs: object) -> object:
                self.calls.append(kwargs)
                return self.queued_responses.pop(0)

        fake_completions = FakeCompletions(responses)
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake_completions)
        )
        tool_calls: list[tuple[str, dict[str, str]]] = []

        def fake_execute_tool(name: str, params: dict[str, str], **_: object) -> str:
            tool_calls.append((name, params))
            return "demo.txt (1 lines)\n   1 | hello"

        console = Console(record=True, width=80)

        reply = main.chat(
            "读一下 demo.txt",
            fake_client,
            settings,
            history,
            console,
            execute_tool_fn=fake_execute_tool,
        )

        self.assertEqual(reply, "读取完成")
        self.assertEqual(tool_calls, [("read_file", {"path": "demo.txt"})])
        self.assertEqual(len(fake_completions.calls), 2)
        self.assertEqual(fake_completions.calls[0]["tools"], main.TOOLS)
        self.assertTrue(
            any(message.get("role") == "tool" for message in fake_completions.calls[1]["messages"])
        )
        console_text = console.export_text()
        self.assertIn("LLM Running (Turn 1)", console_text)
        self.assertIn("LLM Running (Turn 2)", console_text)
        self.assertIn("[1] read_file", console_text)
        self.assertIn("Done", console_text)

    def test_chat_streams_reply_when_no_tools_are_needed(self) -> None:
        settings = main.Settings(
            api_key="sk-xx",
            model="deepseek-ai/DeepSeek-V4-Flash",
            base_url="https://api.siliconflow.cn/v1",
        )
        history = [{"role": "system", "content": "system"}]
        chunks = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="直", tool_calls=[]))]
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="接", tool_calls=[]))]
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="回", tool_calls=[]))]
            ),
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="复", tool_calls=[]))],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=4),
            ),
        ]

        class FakeCompletions:
            def __init__(self, queued_chunks: list[object]) -> None:
                self.queued_chunks = queued_chunks
                self.calls: list[dict[str, object]] = []

            def create(self, **kwargs: object) -> list[object]:
                self.calls.append(kwargs)
                return self.queued_chunks

        class FakeLive:
            def __init__(self, **kwargs: object) -> None:
                self.updates: list[object] = []

            def __enter__(self) -> "FakeLive":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def update(self, renderable: object) -> None:
                self.updates.append(renderable)

        fake_completions = FakeCompletions(chunks)
        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=fake_completions))
        console = Console(record=True, width=80)
        token_stats = main.TokenUsageStats()
        live = FakeLive(console=console, refresh_per_second=8)

        reply = main.chat(
            "你好",
            fake_client,
            settings,
            history,
            console,
            token_stats=token_stats,
            live_factory=lambda **kwargs: live,
        )

        self.assertEqual(reply, "直接回复")
        self.assertEqual(len(fake_completions.calls), 1)
        self.assertIs(fake_completions.calls[0]["stream"], True)
        self.assertEqual(fake_completions.calls[0]["tools"], main.TOOLS)
        self.assertEqual(token_stats.input_tokens, 10)
        self.assertEqual(token_stats.output_tokens, 4)
        self.assertEqual(len(live.updates), 4)
        self.assertIn("LLM Running (Turn 1)", console.export_text())

    def test_chat_falls_back_to_non_stream_when_stream_response_is_empty(self) -> None:
        settings = main.Settings(
            api_key="sk-xx",
            model="deepseek-ai/DeepSeek-V4-Flash",
            base_url="https://api.siliconflow.cn/v1",
        )
        history = [{"role": "system", "content": "system"}]
        streamed_chunks = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[]))]
            ),
            SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(prompt_tokens=6, completion_tokens=0),
            ),
        ]
        fallback_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="补回回复",
                        tool_calls=[],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=6, completion_tokens=3),
        )

        class FakeCompletions:
            def __init__(self, stream_chunks: list[object], fallback: object) -> None:
                self.stream_chunks = stream_chunks
                self.fallback = fallback
                self.calls: list[dict[str, object]] = []

            def create(self, **kwargs: object) -> object:
                self.calls.append(kwargs)
                if kwargs.get("stream"):
                    return self.stream_chunks
                return self.fallback

        fake_completions = FakeCompletions(streamed_chunks, fallback_response)
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=fake_completions)
        )
        console = Console(record=True, width=80)

        reply = main.chat(
            "你好",
            fake_client,
            settings,
            history,
            console,
        )

        self.assertEqual(reply, "补回回复")
        self.assertEqual(len(fake_completions.calls), 2)
        self.assertIs(fake_completions.calls[0]["stream"], True)
        self.assertNotIn("stream", fake_completions.calls[1])
        self.assertIn("补回回复", console.export_text())

    def test_chat_reports_empty_response_in_console_and_working_memory(self) -> None:
        settings = main.Settings(
            api_key="sk-xx",
            model="deepseek-ai/DeepSeek-V4-Flash",
            base_url="https://api.siliconflow.cn/v1",
        )
        history = [{"role": "system", "content": "system"}]
        session_memory = main.WorkingMemoryState()
        streamed_chunks = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=None, tool_calls=[]))]
            ),
            SimpleNamespace(
                choices=[],
                usage=SimpleNamespace(prompt_tokens=5, completion_tokens=0),
            ),
        ]
        fallback_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        tool_calls=[],
                    )
                )
            ],
            usage=SimpleNamespace(prompt_tokens=5, completion_tokens=0),
        )

        class FakeCompletions:
            def __init__(self, stream_chunks: list[object], fallback: object) -> None:
                self.stream_chunks = stream_chunks
                self.fallback = fallback

            def create(self, **kwargs: object) -> object:
                if kwargs.get("stream"):
                    return self.stream_chunks
                return self.fallback

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions(streamed_chunks, fallback_response))
        )
        console = Console(record=True, width=80)

        reply = main.chat(
            "你好",
            fake_client,
            settings,
            history,
            console,
            session_memory=session_memory,
        )

        self.assertEqual(reply, "")
        self.assertIn("模型未返回内容，也未发起工具调用", console.export_text())
        self.assertEqual(session_memory.history_info[-1], "[Agent] 模型空响应")

    def test_chat_accepts_step_outcome_and_keeps_full_reply_code(self) -> None:
        settings = main.Settings(
            api_key="sk-xx",
            model="deepseek-ai/DeepSeek-V4-Flash",
            base_url="https://api.siliconflow.cn/v1",
        )
        history = [{"role": "system", "content": "system"}]
        responses = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="先执行工具",
                            tool_calls=[
                                SimpleNamespace(
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name="read_file",
                                        arguments='{"path":"demo.txt"}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                "结果如下\n\n"
                                "<tool_call>ignore</tool_call>\n\n"
                                "```python\n"
                                "a\nb\nc\nd\ne\nf\ng\n"
                                "```"
                            ),
                            tool_calls=[],
                        )
                    )
                ]
            ),
        ]

        class FakeCompletions:
            def __init__(self, queued_responses: list[object]) -> None:
                self.queued_responses = queued_responses
                self.calls: list[dict[str, object]] = []

            def create(self, **kwargs: object) -> object:
                self.calls.append(kwargs)
                return self.queued_responses.pop(0)

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions(responses))
        )
        console = Console(record=True, width=80)

        reply = main.chat(
            "读一下 demo.txt",
            fake_client,
            settings,
            history,
            console,
            execute_tool_fn=lambda *_args, **_kwargs: main.StepOutcome(
                data={"status": "ok"}
            ),
        )

        self.assertIn("结果如下", reply)
        console_text = console.export_text()
        self.assertNotIn("<tool_call>", console_text)
        self.assertIn("a", console_text)
        self.assertIn("f", console_text)
        self.assertIn("g", console_text)
        self.assertNotIn("... (7 lines)", console_text)

    def test_chat_stops_when_tool_limit_reached(self) -> None:
        settings = main.Settings(
            api_key="sk-xx",
            model="deepseek-ai/DeepSeek-V4-Flash",
            base_url="https://api.siliconflow.cn/v1",
        )
        history = [{"role": "system", "content": "system"}]
        tool_calls = [
            SimpleNamespace(
                id=f"call_{index}",
                function=SimpleNamespace(
                    name="list_files",
                    arguments='{"path":"."}',
                ),
            )
            for index in range(main.TOOL_CALL_LIMIT + 1)
        ]
        responses = [
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content="开始执行工具",
                            tool_calls=tool_calls,
                        )
                    )
                ]
            )
        ]

        class FakeCompletions:
            def __init__(self, queued_responses: list[object]) -> None:
                self.queued_responses = queued_responses
                self.calls: list[dict[str, object]] = []

            def create(self, **kwargs: object) -> object:
                self.calls.append(kwargs)
                return self.queued_responses.pop(0)

        executed: list[str] = []

        def fake_execute_tool(name: str, params: dict[str, str], **_: object) -> str:
            executed.append(name)
            return "done"

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(completions=FakeCompletions(responses))
        )
        console = Console(record=True, width=80)

        reply = main.chat(
            "列目录",
            fake_client,
            settings,
            history,
            console,
            execute_tool_fn=fake_execute_tool,
        )

        self.assertEqual(reply, "")
        self.assertEqual(len(executed), main.TOOL_CALL_LIMIT)
        self.assertIn("Tool call limit reached", console.export_text())

    def test_chat_falls_back_to_non_stream_when_tool_json_is_incomplete(self) -> None:
        settings = main.Settings(
            api_key="sk-xx",
            model="deepseek-ai/DeepSeek-V4-Flash",
            base_url="https://api.siliconflow.cn/v1",
        )
        history = [{"role": "system", "content": "system"}]
        streamed_chunks = [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="准", tool_calls=[]))]
            ),
            SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(
                            content="备写文件",
                            tool_calls=[
                                SimpleNamespace(
                                    index=0,
                                    id="call_1",
                                    function=SimpleNamespace(
                                        name="write_file",
                                        arguments='{"path":"a.md","content":"unterminated}',
                                    ),
                                )
                            ],
                        )
                    )
                ]
            ),
        ]
        fallback_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="准备写文件",
                        tool_calls=[
                            SimpleNamespace(
                                id="call_1",
                                function=SimpleNamespace(
                                    name="write_file",
                                    arguments='{"path":"a.md","content":"ok"}',
                                ),
                            )
                        ],
                    )
                )
            ]
        )
        final_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="已完成写入",
                        tool_calls=[],
                    )
                )
            ]
        )

        class FakeCompletions:
            def __init__(self, stream_chunks: list[object], fallback: object, final: object) -> None:
                self.stream_chunks = stream_chunks
                self.fallback = fallback
                self.final = final
                self.calls: list[dict[str, object]] = []

            def create(self, **kwargs: object) -> object:
                self.calls.append(kwargs)
                if kwargs.get("stream"):
                    if len(self.calls) == 1:
                        return self.stream_chunks
                    return self.final
                return self.fallback

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=FakeCompletions(streamed_chunks, fallback_response, final_response)
            )
        )
        console = Console(record=True, width=80)
        executed: list[tuple[str, dict[str, str]]] = []

        reply = main.chat(
            "写入文件",
            fake_client,
            settings,
            history,
            console,
            execute_tool_fn=lambda name, params, **_: executed.append((name, params)) or "done",
        )

        self.assertEqual(reply, "已完成写入")
        self.assertEqual(executed, [("write_file", {"path": "a.md", "content": "ok"})])
        console_text = console.export_text()
        self.assertNotIn("工具参数解析失败", console_text)

    def test_run_chat_keyboard_interrupt_shows_explicit_message(self) -> None:
        original_load_env_file = chat_agent.load_env_file
        original_ensure_memory_scaffold = chat_agent.ensure_memory_scaffold
        original_get_settings = chat_agent.get_settings
        original_build_client = chat_agent.build_client
        try:
            chat_agent.load_env_file = lambda *args, **kwargs: None
            chat_agent.ensure_memory_scaffold = lambda *args, **kwargs: None
            chat_agent.get_settings = lambda: main.Settings(
                api_key="sk-xx",
                model="deepseek-ai/DeepSeek-V4-Flash",
                base_url="https://api.siliconflow.cn/v1",
            )
            chat_agent.build_client = lambda _settings: object()

            class InterruptConsole:
                def __init__(self) -> None:
                    self.messages: list[str] = []

                def print(self, *args: object, **kwargs: object) -> None:
                    self.messages.append(" ".join(str(arg) for arg in args))

                def input(self, _prompt: str) -> str:
                    raise KeyboardInterrupt

            console = InterruptConsole()
            main.run_chat(console=console)

            joined = "\n".join(console.messages)
            self.assertIn("请求已中断", joined)
            self.assertIn("Token 统计", joined)
        finally:
            chat_agent.load_env_file = original_load_env_file
            chat_agent.ensure_memory_scaffold = original_ensure_memory_scaffold
            chat_agent.get_settings = original_get_settings
            chat_agent.build_client = original_build_client

    def test_handle_control_command_clears_history(self) -> None:
        console = Console(record=True, width=80)
        history = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ]

        handled, new_history = main.handle_control_command("clear", console, history)

        self.assertTrue(handled)
        self.assertEqual(new_history, main.build_initial_history())
        self.assertIn("历史已清空", console.export_text())

    def test_build_working_memory_prompt_folds_earlier_history(self) -> None:
        session_memory = main.WorkingMemoryState(
            history_info=[f"[Agent] step {index}" for index in range(35)],
            key_info="关键进展",
            related_sop="memory/task_sops/demo.md",
            current_turn=35,
        )

        prompt = main.build_working_memory_prompt(session_memory)

        self.assertIn("<earlier_context>", prompt)
        self.assertIn("<history>", prompt)
        self.assertIn("关键进展", prompt)
        self.assertIn("memory/task_sops/demo.md", prompt)


if __name__ == "__main__":
    unittest.main()
