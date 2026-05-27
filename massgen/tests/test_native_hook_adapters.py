"""Tests for native hook adapters.

This module tests the NativeHookAdapter interface and ClaudeCodeNativeHookAdapter
implementation for converting MassGen hooks to backend-native formats.
"""

from unittest.mock import MagicMock

import pytest

from massgen.mcp_tools.hooks import (
    GeneralHookManager,
    HighPriorityTaskReminderHook,
    HookEvent,
    HookResult,
    HookType,
    MidStreamInjectionHook,
    PythonCallableHook,
)


class TestNativeHookAdapterBase:
    """Tests for the NativeHookAdapter base class."""

    def test_create_hook_event_from_native(self):
        """Test creating HookEvent from native input format."""
        from massgen.mcp_tools.native_hook_adapters.base import NativeHookAdapter

        native_input = {
            "tool_name": "test_tool",
            "tool_input": {"arg1": "value1"},
            "tool_output": "result",
        }
        context = {
            "session_id": "session-123",
            "orchestrator_id": "orch-456",
            "agent_id": "agent-789",
        }

        event = NativeHookAdapter.create_hook_event_from_native(
            native_input,
            HookType.POST_TOOL_USE,
            context,
        )

        assert event.hook_type == "PostToolUse"
        assert event.session_id == "session-123"
        assert event.orchestrator_id == "orch-456"
        assert event.agent_id == "agent-789"
        assert event.tool_name == "test_tool"
        assert event.tool_input == {"arg1": "value1"}
        assert event.tool_output == "result"

    def test_convert_hook_result_to_native_raises_not_implemented(self):
        """Test that convert_hook_result_to_native raises NotImplementedError."""
        from massgen.mcp_tools.native_hook_adapters.base import NativeHookAdapter

        result = HookResult.allow()
        with pytest.raises(NotImplementedError):
            NativeHookAdapter.convert_hook_result_to_native(result, HookType.PRE_TOOL_USE)


@pytest.mark.skipif(
    not pytest.importorskip("claude_agent_sdk", reason="claude_agent_sdk not installed"),
    reason="claude_agent_sdk not available",
)
class TestClaudeCodeNativeHookAdapter:
    """Tests for ClaudeCodeNativeHookAdapter."""

    @pytest.fixture
    def adapter(self):
        """Create adapter instance."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        return ClaudeCodeNativeHookAdapter()

    def test_supports_pre_tool_use(self, adapter):
        """Test that adapter supports PreToolUse hooks."""
        assert adapter.supports_hook_type(HookType.PRE_TOOL_USE)

    def test_supports_post_tool_use(self, adapter):
        """Test that adapter supports PostToolUse hooks."""
        assert adapter.supports_hook_type(HookType.POST_TOOL_USE)

    def test_convert_allow_result(self, adapter):
        """Test converting allow HookResult to Claude format."""
        result = HookResult.allow()
        native = adapter._convert_result_to_claude_format(result, HookType.PRE_TOOL_USE)
        assert native == {}

    def test_convert_deny_result(self, adapter):
        """Test converting deny HookResult to Claude format."""
        result = HookResult.deny(reason="Test denial")
        native = adapter._convert_result_to_claude_format(result, HookType.PRE_TOOL_USE)

        assert "hookSpecificOutput" in native
        assert native["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "Test denial" in native["hookSpecificOutput"]["permissionDecisionReason"]

    def test_convert_ask_result(self, adapter):
        """Test converting ask HookResult to Claude format."""
        result = HookResult.ask(reason="Need confirmation")
        native = adapter._convert_result_to_claude_format(result, HookType.PRE_TOOL_USE)

        assert "hookSpecificOutput" in native
        assert native["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "User confirmation required" in native["hookSpecificOutput"]["permissionDecisionReason"]

    def test_convert_updated_input_result(self, adapter):
        """Test converting HookResult with updated input to Claude format."""
        result = HookResult(
            allowed=True,
            updated_input={"modified_arg": "new_value"},
        )
        native = adapter._convert_result_to_claude_format(result, HookType.PRE_TOOL_USE)

        assert "hookSpecificOutput" in native
        assert native["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert native["hookSpecificOutput"]["updatedInput"] == {"modified_arg": "new_value"}

    def test_convert_injection_result(self, adapter):
        """Test converting HookResult with injection to Claude format."""
        result = HookResult(
            allowed=True,
            inject={"content": "Injected content", "strategy": "tool_result"},
        )
        native = adapter._convert_result_to_claude_format(result, HookType.POST_TOOL_USE)

        assert "hookSpecificOutput" in native
        assert native["hookSpecificOutput"]["additionalContext"] == "Injected content"

    def test_build_native_hooks_config_empty_manager(self, adapter):
        """Test building native config from empty manager."""
        manager = GeneralHookManager()
        config = adapter.build_native_hooks_config(manager)

        # Empty manager should return empty config
        assert config == {}

    def test_build_native_hooks_config_with_hooks(self, adapter):
        """Test building native config with registered hooks."""
        manager = GeneralHookManager()

        # Add a simple hook
        async def test_hook(event: HookEvent) -> HookResult:
            return HookResult.allow()

        hook = PythonCallableHook(
            name="test_hook",
            handler=test_hook,
            matcher="*",
        )
        manager.register_global_hook(HookType.PRE_TOOL_USE, hook)

        config = adapter.build_native_hooks_config(manager)

        assert "PreToolUse" in config
        assert len(config["PreToolUse"]) == 1

    def test_build_native_hooks_config_with_both_types(self, adapter):
        """Test building native config with both PreToolUse and PostToolUse hooks."""
        manager = GeneralHookManager()

        async def pre_hook(event: HookEvent) -> HookResult:
            return HookResult.allow()

        async def post_hook(event: HookEvent) -> HookResult:
            return HookResult.allow()

        manager.register_global_hook(
            HookType.PRE_TOOL_USE,
            PythonCallableHook(name="pre_hook", handler=pre_hook, matcher="*"),
        )
        manager.register_global_hook(
            HookType.POST_TOOL_USE,
            PythonCallableHook(name="post_hook", handler=post_hook, matcher="*"),
        )

        config = adapter.build_native_hooks_config(manager)

        assert "PreToolUse" in config
        assert "PostToolUse" in config
        assert len(config["PreToolUse"]) == 1
        assert len(config["PostToolUse"]) == 1

    def test_merge_configs_empty(self, adapter):
        """Test merging empty configs."""
        merged = adapter.merge_native_configs({}, {})
        assert merged == {}

    def test_merge_configs_with_hooks(self, adapter):
        """Test merging configs with hooks."""
        from claude_agent_sdk import HookMatcher

        async def hook1(input_data, tool_use_id, context):
            return {}

        async def hook2(input_data, tool_use_id, context):
            return {}

        config1 = {"PreToolUse": [HookMatcher(matcher="*", hooks=[hook1])]}
        config2 = {"PostToolUse": [HookMatcher(matcher="*", hooks=[hook2])]}

        merged = adapter.merge_native_configs(config1, config2)

        assert "PreToolUse" in merged
        assert "PostToolUse" in merged
        assert len(merged["PreToolUse"]) == 1
        assert len(merged["PostToolUse"]) == 1

    def test_merge_configs_combines_same_type(self, adapter):
        """Test merging configs combines hooks of same type."""
        from claude_agent_sdk import HookMatcher

        async def hook1(input_data, tool_use_id, context):
            return {}

        async def hook2(input_data, tool_use_id, context):
            return {}

        config1 = {"PreToolUse": [HookMatcher(matcher="Read", hooks=[hook1])]}
        config2 = {"PreToolUse": [HookMatcher(matcher="Write", hooks=[hook2])]}

        merged = adapter.merge_native_configs(config1, config2)

        assert "PreToolUse" in merged
        assert len(merged["PreToolUse"]) == 2


@pytest.mark.skipif(
    not pytest.importorskip("claude_agent_sdk", reason="claude_agent_sdk not installed"),
    reason="claude_agent_sdk not available",
)
class TestMidStreamInjectionWithNativeHooks:
    """Tests for MidStreamInjectionHook with native hook adapter."""

    @pytest.fixture
    def adapter(self):
        """Create adapter instance."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        return ClaudeCodeNativeHookAdapter()

    def test_mid_stream_injection_converted_to_native(self, adapter):
        """Test that MidStreamInjectionHook is properly converted to native format."""
        manager = GeneralHookManager()

        # Create mid-stream hook with callback
        hook = MidStreamInjectionHook()
        hook.set_callback(lambda: "Injected update from other agent")

        manager.register_global_hook(HookType.POST_TOOL_USE, hook)

        config = adapter.build_native_hooks_config(manager)

        assert "PostToolUse" in config
        assert len(config["PostToolUse"]) == 1

    def test_high_priority_task_reminder_converted_to_native(self, adapter):
        """Test that HighPriorityTaskReminderHook is properly converted to native format."""
        manager = GeneralHookManager()

        hook = HighPriorityTaskReminderHook()
        manager.register_global_hook(HookType.POST_TOOL_USE, hook)

        config = adapter.build_native_hooks_config(manager)

        assert "PostToolUse" in config
        assert len(config["PostToolUse"]) == 1


@pytest.mark.skipif(
    not pytest.importorskip("claude_agent_sdk", reason="claude_agent_sdk not installed"),
    reason="claude_agent_sdk not available",
)
class TestHookWrapperExecution:
    """Tests for hook wrapper function execution."""

    @pytest.fixture
    def adapter(self):
        """Create adapter instance."""
        from massgen.mcp_tools.native_hook_adapters import ClaudeCodeNativeHookAdapter

        return ClaudeCodeNativeHookAdapter()

    @pytest.mark.asyncio
    async def test_wrapper_executes_hook_and_returns_allow(self, adapter):
        """Test that wrapper executes hook and returns allow response."""
        executed = []

        async def test_hook(event: HookEvent) -> HookResult:
            executed.append(event.tool_name)
            return HookResult.allow()

        hook = PythonCallableHook(
            name="test_hook",
            handler=test_hook,
            matcher="*",
        )

        # Convert to native
        native_matcher = adapter.convert_hook_to_native(hook, HookType.PRE_TOOL_USE)

        # Execute the wrapper function
        wrapper_func = native_matcher.hooks[0]
        result = await wrapper_func(
            {"tool_name": "Read", "tool_input": {"file_path": "/test.txt"}},
            "tool-use-123",
            MagicMock(),
        )

        assert executed == ["Read"]
        assert result == {}

    @pytest.mark.asyncio
    async def test_wrapper_returns_deny_on_hook_deny(self, adapter):
        """Test that wrapper returns deny response when hook denies."""

        async def test_hook(event: HookEvent) -> HookResult:
            return HookResult.deny(reason="Access denied")

        hook = PythonCallableHook(
            name="test_hook",
            handler=test_hook,
            matcher="*",
        )

        native_matcher = adapter.convert_hook_to_native(hook, HookType.PRE_TOOL_USE)
        wrapper_func = native_matcher.hooks[0]

        result = await wrapper_func(
            {"tool_name": "Write", "tool_input": {}},
            "tool-use-123",
            MagicMock(),
        )

        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.asyncio
    async def test_wrapper_skips_non_matching_tool(self, adapter):
        """Test that wrapper skips execution for non-matching tool names."""
        executed = []

        async def test_hook(event: HookEvent) -> HookResult:
            executed.append(event.tool_name)
            return HookResult.allow()

        hook = PythonCallableHook(
            name="test_hook",
            handler=test_hook,
            matcher="Write|Edit",  # Only matches Write or Edit
        )

        native_matcher = adapter.convert_hook_to_native(hook, HookType.PRE_TOOL_USE)
        wrapper_func = native_matcher.hooks[0]

        # Call with non-matching tool
        result = await wrapper_func(
            {"tool_name": "Read", "tool_input": {}},
            "tool-use-123",
            MagicMock(),
        )

        # Should not execute hook, return allow
        assert executed == []
        assert result == {}

    @pytest.mark.asyncio
    async def test_wrapper_handles_injection_callback(self, adapter):
        """Test that wrapper handles injection callback for PostToolUse."""
        # Create injection hook with callback
        hook = MidStreamInjectionHook()
        hook.set_callback(lambda: "New answer available!")

        native_matcher = adapter.convert_hook_to_native(hook, HookType.POST_TOOL_USE)
        wrapper_func = native_matcher.hooks[0]

        result = await wrapper_func(
            {"tool_name": "Read", "tool_input": {}, "tool_output": "file contents"},
            "tool-use-123",
            MagicMock(),
        )

        assert "hookSpecificOutput" in result
        assert result["hookSpecificOutput"]["additionalContext"] == "New answer available!"


class TestIsClaudeSdkAvailable:
    """Tests for the is_claude_sdk_available helper function."""

    def test_is_claude_sdk_available(self):
        """Test the SDK availability check."""
        from massgen.mcp_tools.native_hook_adapters import is_claude_sdk_available

        # This should return True or False based on whether SDK is installed
        result = is_claude_sdk_available()
        assert isinstance(result, bool)
