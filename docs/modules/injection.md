# Injection and Hook System

## Overview

MassGen uses a hook-based injection system to deliver runtime content into agent conversations mid-stream. This powers cross-agent answer sharing, background subagent result delivery, human input routing, round timeout enforcement, and more.

The challenge: agents are running inside different backend SDKs (OpenAI, Claude API, Claude Code SDK, Codex CLI) that each have different tool execution models. The hook system provides a unified abstraction that adapts to each backend's capabilities.

## Architecture

```text
                    ┌──────────────────────────────┐
                    │     GeneralHookManager        │
                    │  (global + per-agent hooks)   │
                    └──────────┬───────────────────┘
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
    ┌──────▼──────┐    ┌──────▼──────┐    ┌──────▼──────┐
    │  Standard   │    │ Claude Code │    │   Codex     │
    │  Backends   │    │   Backend   │    │   Backend   │
    │ (API-based) │    │ (SDK-based) │    │ (CLI-based) │
    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘
           │                   │                   │
    execute_hooks()    NativeHookAdapter    File-based IPC
    inline in tool     → SDK HookMatcher   → hook_post_tool_use.json
    processing loop    (PostToolUse)        → MassGenHookMiddleware
```

## Hook Types

Two interception points, each with different capabilities:

| Hook Point | Timing | Capabilities |
|---|---|---|
| **PreToolUse** | Before tool executes | Block (`deny`), modify input (`updated_input`), or prompt (`ask`) |
| **PostToolUse** | After tool executes | Inject content into tool result (`inject`) |

## Core Data Structures

### HookResult

Every hook returns a `HookResult` (`massgen/mcp_tools/hooks.py`):

- `decision`: `"allow"` / `"deny"` / `"ask"`
- `updated_input`: Modified tool arguments (PreToolUse only)
- `inject`: `{"content": "...", "strategy": "tool_result"|"user_message"}` (PostToolUse only)
- `hook_errors`: Partial failure tracking for fail-open hooks
- `executed_hooks`: Audit trail for TUI/WebUI display

### HookEvent

Input context provided to every hook handler:

- `hook_type`, `session_id`, `orchestrator_id`, `agent_id`
- `tool_name`, `tool_input`, `tool_output` (PostToolUse only)

## Hook Registration

### GeneralHookManager

The `GeneralHookManager` is the central registry (`massgen/mcp_tools/hooks.py`).

**Global hooks** apply to all agents:
```python
manager.register_global_hook(HookType.POST_TOOL_USE, my_hook)
```

**Per-agent hooks** are scoped to one agent:
```python
manager.register_agent_hook(agent_id, HookType.PRE_TOOL_USE, my_hook, override=False)
```

When `override=True`, global hooks for that event type are disabled for that agent.

### Aggregation Rules

**PreToolUse**: First `deny` short-circuits. Modified inputs chain — each hook sees the previous hook's output.

**PostToolUse**: All injection content is concatenated. No short-circuiting.

Errors are caught and logged but don't abort (fail-open), unless a hook has `fail_closed=True`.

## Built-in Hooks

### PostToolUse Hooks

| Hook | Matcher | Purpose |
|---|---|---|
| `MidStreamInjectionHook` | `*` | Injects peer agent answers during a round. Calls an injection callback to check for pending cross-agent content. |
| `SubagentCompleteHook` | `*` | Delivers background subagent results. Pops from a pending results queue and formats via `result_formatter.format_batch_results()`. |
| `BackgroundToolCompleteHook` | `*` | Delivers generic background custom tool completions (non-subagent async jobs). |
| `HighPriorityTaskReminderHook` | `*update_task_status` | Reminds agent to document learnings after completing high-priority tasks. |
| `HumanInputHook` | `*` | Delivers runtime human input from TUI/WebUI broadcast to agents mid-stream. |
| `RoundTimeoutPostHook` | `*` | Soft timeout: injects a time-limit warning once, then starts a grace period. |

Mid-stream answer injection messages include explicit answer-label transitions (for example `agent2.1 -> agent2.2`) so checklist scoring can target newest labels. In checklist-gated mode, injected guidance routes agents through `submit_checklist` re-evaluation first, then `draft_approach` only after accepted iterate results.

Peer-answer delivery can be configured independently from other runtime payloads. When `defer_peer_updates_until_restart: true`, peer answer updates are queued until the next safe restart instead of being injected mid-stream. Human input, background subagent completions, and background tool completions still use their normal delivery paths. In checklist-gated runs, `allow_midstream_peer_updates_before_checklist_submit` can keep peer updates mid-stream until the first accepted `submit_checklist` for the current answer.

### PreToolUse Hooks

| Hook | Matcher | Purpose |
|---|---|---|
| `RoundTimeoutPreHook` | `*` | Hard timeout: blocks all tools except `vote`/`new_answer` after grace period expires. Force-terminates after 10 consecutive denials. |
| `PermissionClientSession` | (MCP-level) | Intercepts `call_tool()` on MCP sessions to enforce path permission validation. |

### Round Timeout (Coordinated Pair)

`RoundTimeoutPostHook` and `RoundTimeoutPreHook` share a `RoundTimeoutState` object:

1. **Soft timeout** fires → injects warning, records `soft_timeout_fired_at`
2. **Hard timeout** activates only after soft has fired → blocks non-terminal tools
3. After `MAX_CONSECUTIVE_DENIALS` (10) → sets `force_terminate` flag

Different thresholds for round 0 (`initial_timeout_seconds`) vs subsequent rounds (`subsequent_timeout_seconds`). The shared state is reset via `reset_for_new_round()` at each round boundary.

## Delivery Paths by Backend

The same hooks produce the same `HookResult`, but delivery to the model differs by backend architecture.

### Path 1: Standard API Backends (OpenAI, Claude API, Gemini, Grok)

**Backend base**: `base_with_custom_tool_and_mcp.py`

The `GeneralHookManager` is called inline during the tool processing loop:

1. **PreToolUse**: `execute_hooks(PRE_TOOL_USE, ...)` before calling the tool. Deny → skip tool, return error. Modified input → use updated args.
2. Tool executes normally.
3. **PostToolUse**: `execute_hooks(POST_TOOL_USE, ...)` after tool returns. If `result.inject` has content, it's appended to the tool result message that the model sees.

This is the simplest path — hooks run in-process, synchronously within the streaming loop.

### Path 2: Claude Code Backend (SDK-native hooks)

**Backend**: `claude_code.py`
**Adapter**: `massgen/mcp_tools/native_hook_adapters/claude_code_adapter.py`

Claude Code SDK has native `PreToolUse` and `PostToolUse` hook support via `HookMatcher`. MassGen hooks are converted to SDK-native format:

1. `ClaudeCodeNativeHookAdapter.build_native_hooks_config()` converts all registered `PatternHook` instances into `HookMatcher` objects
2. Each MassGen hook is wrapped in an async function matching the SDK signature: `async def hook(input_data, tool_use_id, context) -> dict`
3. `HookResult` is converted to SDK format:
   - Deny → `{"hookSpecificOutput": {"permissionDecision": "deny", ...}}`
   - Modified input → `{"hookSpecificOutput": {"updatedInput": {...}}}`
   - Injection → `{"hookSpecificOutput": {"additionalContext": "..."}}`
4. Permission hooks (from filesystem manager) and MassGen hooks are merged via `merge_native_configs()`
5. The merged config is passed to `ClaudeAgentOptions(hooks=config)`

The SDK fires these hooks natively on each tool call — no file IPC or polling needed.

### Path 3: Codex Backend (Hybrid Native Hooks + File IPC)

**Backend**: `codex.py`
**Adapter**: `massgen/mcp_tools/native_hook_adapters/codex_adapter.py`
**Native hook script**: `massgen/mcp_tools/native_hook_adapters/codex_hook_script.py`
**Middleware**: `massgen/mcp_tools/hook_middleware.py`

Codex runs as an external CLI process. It doesn't support in-process hook callbacks, so MassGen uses a hybrid model:

1. **Native Bash hooks**: `.codex/hooks.json` enables Codex's experimental native hook surface for Bash-only events:
   - `PreToolUse`: a standalone hook script reads `permission_manifest.json` and can deny simple Bash commands that would write outside writable paths
   - `PostToolUse`: the same hook script can consume the shared `hook_post_tool_use.json` file after a Bash call and append its content as extra developer context
2. **Orchestrator side**: Writes `hook_post_tool_use.json` to a shared hook directory via `codex.py:write_post_tool_use_hook()`:
   ```json
   {
     "inject": {"content": "...", "strategy": "tool_result"},
     "tool_matcher": "*",
     "expires_at": 1740000000.0,
     "sequence": 42
   }
   ```
3. **MCP server side**: `MassGenHookMiddleware` (a FastMCP `Middleware` subclass) intercepts every `call_tool()`:
   - Executes the actual tool first
   - Reads `hook_post_tool_use.json`
   - Validates: glob matcher against tool name, expiry timestamp, monotonically increasing sequence number (dedup)
   - If valid and matching: consumes (deletes) the file, appends content as `TextContent` to the tool result
   - If not matching: leaves the file for a later tool call
4. **Unconsumed content**: After a round ends, `read_unconsumed_hook_content()` checks if the file still exists (neither Bash nor MCP consumed it). If so, the orchestrator carries the content forward.

Atomic writes (write to `.tmp`, then `rename`) prevent partial reads.

**Current limitation: Bash only for native hooks.** Codex's documented `PreToolUse` and `PostToolUse` events currently only fire for `Bash`. They do not currently intercept MCP, Write, WebSearch, or other non-shell tool calls. In practice the hybrid design works well because:

- Bash calls can consume pending payloads directly through the native hook script.
- Custom tools are loaded as MCP tools, so they are covered.
- MassGen framework tools (subagent, checklist, planning, memory) are all MCP-based.
- If Codex happens to call only non-hooked provider-native tools between injection writes (for example `Write` or `WebSearch` with no Bash or MCP call), the content goes unconsumed. The orchestrator detects this via `read_unconsumed_hook_content()` and carries the payload forward to the next turn via the hookless fallback path.

This means Codex injection is **best-effort mid-stream**: content is delivered on the next Bash or MCP tool call, or failing that, between turns. Unlike Claude Code (which intercepts all tools via SDK hooks), Codex still has no mechanism to inject into most provider-native non-Bash tool results.

**Responsibility split.** Codex native hooks and MCP/file IPC do different jobs:
- Native Codex hooks own Bash-only permission checks and Bash post-tool payload consumption.
- The shared `hook_post_tool_use.json` file remains the single source of truth for MassGen runtime payloads.
- MCP middleware still owns MCP tool interception and append behavior.
- End-of-turn carry-forward remains the fallback when neither Bash nor MCP consumed the payload.

Implication: non-injection hooks that need full callback semantics still must run in the actual tool execution path for that backend/runtime.
For Codex custom tools, this means running side-effect hooks in `custom_tools_server.py` (where tool name, args, output, and workspace context are available), not in the IPC middleware.
For new backends that are neither standard-hook nor fully native-hook compatible, add an equivalent execution-path integration point for any non-injection hooks.

### Path 4: Hookless Fallback

For backends that support neither native hooks nor file-based IPC (or when hooks fail), the orchestrator falls back to inter-turn delivery:

1. `_collect_hookless_runtime_payloads()` gathers pending injections (peer answers, subagent results, human input, background tool completions)
2. Content is delivered as synthesized enforcement/user messages between turns rather than mid-tool
3. The orchestrator sets `restart_pending = True` to trigger a safe-checkpoint restart with the injected content

This is less timely (content arrives between turns, not mid-stream) but works universally.

## Wiring: How the Orchestrator Sets Up Hooks

`_setup_hook_manager_for_agent()` in `orchestrator.py` runs at the start of each agent execution:

1. Creates a `GeneralHookManager`
2. Registers global PostToolUse hooks in order:
   - `MidStreamInjectionHook` (peer answer sharing)
   - `HighPriorityTaskReminderHook`
   - `HumanInputHook`
   - `SubagentCompleteHook` (if background subagents enabled)
   - `BackgroundToolCompleteHook` (if backend supports background tools)
3. Registers timeout hooks if configured:
   - `RoundTimeoutPostHook` (PostToolUse, soft)
   - `RoundTimeoutPreHook` (PreToolUse, hard)
4. Hands the manager to the backend:
   - API backends: `backend.set_general_hook_manager(manager)` → hooks run inline
   - Claude Code: `build_native_hooks_config()` → hooks converted to SDK `HookMatcher` format
   - Codex: native Bash hooks are configured from `.codex/hooks.json`, while runtime payloads still flow through the shared IPC file and MCP middleware

## Background Subagent Completion Flow

This is the primary interaction between the subagent system and hooks:

1. Parent agent calls `spawn_subagents(tasks, background=True)` → returns immediately
2. `SubagentManager` launches each subagent as an `asyncio.Task`
3. On completion, `_invoke_completion_callbacks()` notifies the orchestrator
4. Orchestrator queues result in `_pending_subagent_results[parent_agent_id]`
5. On the parent agent's **next tool call**, `SubagentCompleteHook` fires:
   - Calls `get_pending_results()` which pops the queue
   - Formats results via `result_formatter.format_batch_results()`
   - Returns `HookResult(inject={"content": formatted_results})`
6. The appropriate delivery path appends this to the tool result

## User-Defined Hooks

Hooks can be registered from YAML config via `register_hooks_from_config()`:

```yaml
hooks:
  - type: PostToolUse
    matcher: "Write|Edit"
    callable: "my_module.my_hook_function"
    fail_closed: false
```

`PythonCallableHook` loads a Python callable from a module path. Supports both sync and async callables.

Per-agent hooks in YAML use the `backend.hooks` key and can set `override: true` to replace global hooks for that event type.

## Key Files

| File | Role |
|---|---|
| `massgen/mcp_tools/hooks.py` | Hook framework: types, base classes, manager, all built-in hooks |
| `massgen/mcp_tools/hook_middleware.py` | FastMCP middleware for Codex file-based IPC |
| `massgen/mcp_tools/native_hook_adapters/base.py` | Abstract adapter interface for SDK-native hooks |
| `massgen/mcp_tools/native_hook_adapters/claude_code_adapter.py` | Claude Code SDK adapter (HookMatcher conversion) |
| `massgen/mcp_tools/native_hook_adapters/codex_adapter.py` | Codex hooks.json adapter (Bash bridge generation) |
| `massgen/mcp_tools/native_hook_adapters/codex_hook_script.py` | Standalone Codex hook command (permission checks + Bash payload consumption) |
| `massgen/backend/base_with_custom_tool_and_mcp.py` | Standard backend hook execution (inline `execute_hooks()`) |
| `massgen/backend/claude_code.py` | Claude Code hook wiring (`_get_execution_trace_hooks`, options assembly) |
| `massgen/backend/codex.py` | Codex hybrid hook wiring (`hooks.json`, permission manifest, payload IPC) |
| `massgen/mcp_tools/custom_tools_server.py` | Codex custom-tools execution path; runs non-injection side-effect hooks (for example media ledger capture) |
| `massgen/orchestrator.py` | Hook setup (`_setup_hook_manager_for_agent`), hookless fallback |

## Testing

Hook tests are split across several files:

| Test File | Coverage |
|---|---|
| `test_hook_framework.py` | Core hook types, manager, aggregation, pattern matching |
| `test_mcp_hook_middleware.py` | File-based IPC middleware (sequence, expiry, glob matching) |
| `test_codex_hook_ipc.py` | Codex-specific write/read/clear cycle |
| `test_codex_hook_script.py` | Standalone Codex native hook script behavior |
| `test_codex_native_hook_adapter.py` | Codex native hook adapter + workspace hooks.json writing |
| `test_custom_tools_server_background.py` | Codex custom-tools background execution path, including media ledger side-effect coverage |
| `test_orchestrator_hooks_broadcast_subagents.py` | End-to-end orchestrator hook wiring with subagent completion |
| `test_claude_code_background_tools.py` | Claude Code background tool + hook integration |
| `test_specialized_subagents.py` | Subagent type profiles + hook delivery |
