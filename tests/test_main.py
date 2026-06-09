import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

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
        self.assertEqual(panel.title, "MagicCode")
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
        self.assertIn("MagicCode", panel.renderable)
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

    def test_tools_include_delete_and_rename(self) -> None:
        tool_names = [tool["function"]["name"] for tool in main.TOOLS]

        self.assertIn("delete_file", tool_names)
        self.assertIn("rename_file", tool_names)
        self.assertIn("grep_search", tool_names)

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
        self.assertIn("[1] read_file", console_text)
        self.assertIn("Done", console_text)

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


if __name__ == "__main__":
    unittest.main()
