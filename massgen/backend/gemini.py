"""
Gemini backend implementation using structured output for voting and answer submission.

APPROACH: Uses structured output instead of function declarations to handle the limitation
where Gemini API cannot combine builtin tools with user-defined function declarations.

KEY FEATURES:
- ✅ Structured output for vote and new_answer mechanisms
- ✅ Builtin tools support (code_execution + grounding)
- ✅ Streaming with proper token usage tracking
- ✅ Error handling and response parsing
- ✅ Compatible with MassGen StreamChunk architecture

TECHNICAL SOLUTION:
- Uses Pydantic models to define structured output schemas
- Prompts model to use specific JSON format for voting/answering
- Converts structured responses to standard tool call format
- Maintains compatibility with existing MassGen workflow
"""

import asyncio
import contextlib
import json
import logging
import os
import random
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from typing import Any

from ..api_params_handler._gemini_api_params_handler import GeminiAPIParamsHandler
from ..configs.rate_limits import get_rate_limit_config
from ..formatter._gemini_formatter import GeminiFormatter
from ..logger_config import (
    log_backend_activity,
    log_backend_agent_message,
    log_stream_chunk,
    log_tool_call,
    logger,
)
from ._streaming_buffer_mixin import StreamingBufferMixin
from .base import FilesystemSupport, StreamChunk
from .base_with_custom_tool_and_mcp import (
    CustomToolAndMCPBackend,
    CustomToolChunk,
    ToolExecutionConfig,
)
from .gemini_utils import (
    CoordinationResponse,
    DecompositionCoordinationResponse,
    PostEvaluationResponse,
    VoteOnlyCoordinationResponse,
)
from .llm_circuit_breaker import (
    CircuitBreakerOpenError,
    LLMCircuitBreaker,
)
from .rate_limiter import GlobalRateLimiter


# Suppress Gemini SDK logger warning about non-text parts in response
# Using custom filter per https://github.com/googleapis/python-genai/issues/850
class NoFunctionCallWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "there are non-text parts in the response:" in message:
            return False
        return True


logging.getLogger("google_genai.types").addFilter(NoFunctionCallWarning())


# Gemini API prefixes that should be stripped from tool names
# Gemini sometimes returns tool names with prefixes like "default_api:" or other namespace qualifiers
GEMINI_TOOL_NAME_PREFIXES = ("default_api:", "default_api__")


def _normalize_gemini_tool_name(tool_name: str) -> str:
    """Strip Gemini-specific prefixes from tool names.

    Gemini's API sometimes adds prefixes like 'default_api:' to tool names
    when returning function calls. This normalizes the tool name by stripping
    those prefixes so the tool can be matched against our registered tools.

    Args:
        tool_name: The raw tool name from Gemini API

    Returns:
        Normalized tool name without Gemini-specific prefixes
    """
    for prefix in GEMINI_TOOL_NAME_PREFIXES:
        if tool_name.startswith(prefix):
            return tool_name[len(prefix) :]
    return tool_name


@dataclass
class BackoffConfig:
    """Configuration for exponential backoff on rate limit errors (always enabled)."""

    max_attempts: int = 5
    initial_delay: float = 2.0
    multiplier: float = 3.0
    max_delay: float = 60.0
    jitter: float = 0.2
    retry_statuses: set[int] = field(default_factory=lambda: {429, 503})


def _is_retryable_gemini_error(exc: Exception, retry_statuses: set[int]) -> tuple:
    """
    Check if exception is a retryable Gemini API error.

    Returns:
        (is_retryable, status_code, error_message)
    """
    status_code = None
    error_msg = str(exc).lower()

    # Check for status_code attribute
    if hasattr(exc, "status_code"):
        status_code = exc.status_code
    elif hasattr(exc, "code"):
        code = exc.code
        if callable(code):
            code = code()
        if code == 8:
            status_code = 429
        elif code == 14:
            status_code = 503

    # Check exception type name
    exc_type = type(exc).__name__
    if exc_type in ("ResourceExhausted", "TooManyRequests"):
        status_code = 429
    elif exc_type == "ServiceUnavailable":
        status_code = 503

    # Check error message patterns
    retryable_patterns = [
        "resource exhausted",
        "resource has been exhausted",
        "quota exceeded",
        "rate limit",
        "too many requests",
        "429",
        "503",
    ]
    pattern_suggests_rate_limit = any(pattern in error_msg for pattern in retryable_patterns)

    if status_code is not None:
        is_retryable = status_code in retry_statuses
    elif pattern_suggests_rate_limit and 429 in retry_statuses:
        is_retryable = True
    else:
        is_retryable = False
    return (is_retryable, status_code, str(exc))


def _extract_retry_after(exc: Exception) -> float | None:
    """Extract Retry-After value from exception if available."""
    # Check for response headers
    if hasattr(exc, "response") and hasattr(exc.response, "headers"):
        headers = exc.response.headers
        if "retry-after-ms" in headers:
            try:
                return float(headers["retry-after-ms"]) / 1000.0
            except (ValueError, TypeError):
                pass
        if "retry-after" in headers:
            try:
                return float(headers["retry-after"])
            except (ValueError, TypeError):
                pass

    if hasattr(exc, "metadata") and exc.metadata is not None:
        metadata = exc.metadata
        try:
            # Handle dict-like metadata
            if hasattr(metadata, "items"):
                items = metadata.items()
            # Handle tuple/list of pairs
            elif hasattr(metadata, "__iter__"):
                items = metadata
            else:
                items = []

            for key, value in items:
                if str(key).lower() == "retry-after":
                    try:
                        return float(value)
                    except (ValueError, TypeError):
                        pass
        except (ValueError, TypeError):
            pass

    return None


# MCP integration imports
try:
    from ..mcp_tools import (
        MCPConnectionError,
        MCPError,
        MCPServerError,
        MCPTimeoutError,
    )
except ImportError:  # MCP not installed or import failed within mcp_tools
    MCPError = ImportError  # type: ignore[assignment]
    MCPConnectionError = ImportError  # type: ignore[assignment]
    MCPTimeoutError = ImportError  # type: ignore[assignment]
    MCPServerError = ImportError  # type: ignore[assignment]

# Import MCP backend utilities
try:
    from ..mcp_tools.backend_utils import (
        MCPErrorHandler,
        MCPMessageManager,
        MCPResourceManager,
    )
except ImportError:
    MCPErrorHandler = None  # type: ignore[assignment]
    MCPMessageManager = None  # type: ignore[assignment]
    MCPResourceManager = None  # type: ignore[assignment]


def format_tool_response_as_json(response_text: str) -> str:
    """
    Format tool response text as pretty-printed JSON if possible.

    Args:
        response_text: The raw response text from a tool

    Returns:
        Pretty-printed JSON string if response is valid JSON, otherwise original text
    """
    try:
        # Try to parse as JSON
        parsed = json.loads(response_text)
        # Return pretty-printed JSON with 2-space indentation
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        # If not valid JSON, return original text
        return response_text


class GeminiBackend(StreamingBufferMixin, CustomToolAndMCPBackend):
    """Google Gemini backend using structured output for coordination and MCP tool integration."""

    def __init__(self, api_key: str | None = None, **kwargs):
        # Store Gemini-specific API key before calling parent init
        gemini_api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")

        # Extract circuit breaker config before other kwargs processing
        cb_config = self._build_circuit_breaker_config(kwargs)

        # Extract and remove enable_rate_limit and backoff config
        enable_rate_limit = kwargs.pop("enable_rate_limit", False)
        model_name = kwargs.get("model", "")
        backoff_max_attempts = kwargs.pop("gemini_backoff_max_attempts", 5)
        backoff_initial_delay = kwargs.pop("gemini_backoff_initial_delay", 2.0)  # Updated to match BackoffConfig default
        backoff_multiplier = kwargs.pop("gemini_backoff_multiplier", 3.0)  # Updated to match BackoffConfig default
        backoff_max_delay = kwargs.pop("gemini_backoff_max_delay", 60.0)  # Updated to match BackoffConfig default
        backoff_jitter = kwargs.pop("gemini_backoff_jitter", 0.2)

        # Call parent class __init__ - this initializes custom_tool_manager and MCP-related attributes
        super().__init__(gemini_api_key, **kwargs)

        # Override API key with Gemini-specific value
        self.api_key = gemini_api_key

        # Gemini-specific counters for builtin tools
        self.search_count = 0
        self.code_execution_count = 0

        # New components for separation of concerns
        self.formatter = GeminiFormatter()
        self.api_params_handler = GeminiAPIParamsHandler(self)

        # Gemini-specific MCP monitoring (additional to parent class)
        self._mcp_tool_successes = 0
        self._mcp_connection_retries = 0

        # Active tool result capture during manual tool execution
        self._active_tool_result_store: dict[str, str] | None = None

        # Monotonic counter for globally unique tool call IDs
        self._tool_call_counter = 0

        # Exponential backoff configuration
        self.backoff_config = BackoffConfig(
            max_attempts=int(backoff_max_attempts),
            initial_delay=float(backoff_initial_delay),
            multiplier=float(backoff_multiplier),
            max_delay=float(backoff_max_delay),
            jitter=float(backoff_jitter),
        )

        # Backoff telemetry counters
        self.backoff_retry_count = 0
        self.backoff_total_delay = 0.0

        # LLM circuit breaker (opt-in, default disabled)
        self.circuit_breaker = LLMCircuitBreaker(
            config=cb_config,
            backend_name="gemini",
        )

        # Initialize multi-dimensional rate limiter for Gemini API
        # Supports RPM (Requests Per Minute), TPM (Tokens Per Minute), RPD (Requests Per Day)
        # Configuration loaded from massgen/config/rate_limits.yaml
        # This is shared across ALL instances of the SAME MODEL

        if enable_rate_limit:
            # Load rate limits from configuration
            rate_config = get_rate_limit_config()
            limits = rate_config.get_limits("gemini", model_name)

            # Create a unique provider key for the rate limiter
            # Use the full model name to distinguish between different models
            provider_key = f"gemini-{model_name}" if model_name else "gemini-default"

            # Initialize multi-dimensional rate limiter
            self.rate_limiter = GlobalRateLimiter.get_multi_limiter_sync(
                provider=provider_key,
                rpm=limits.get("rpm"),
                tpm=limits.get("tpm"),
                rpd=limits.get("rpd"),
            )

            # Log the active rate limits
            active_limits = []
            if limits.get("rpm"):
                active_limits.append(f"RPM: {limits['rpm']}")
            if limits.get("tpm"):
                active_limits.append(f"TPM: {limits['tpm']:,}")
            if limits.get("rpd"):
                active_limits.append(f"RPD: {limits['rpd']}")

            if active_limits:
                logger.info(
                    f"[Gemini] Multi-dimensional rate limiter enabled for '{model_name}': " f"{', '.join(active_limits)}",
                )
            else:
                logger.info(f"[Gemini] No rate limits configured for '{model_name}'")
        else:
            # No rate limiting - use a pass-through limiter
            self.rate_limiter = None
            logger.info(f"[Gemini] Rate limiting disabled for '{model_name}'")

    def _normalize_and_resolve_tool_name(self, tool_name: str) -> str:
        """Normalize Gemini tool names and resolve MCP aliases.

        Gemini can emit tool calls in different forms:
        - API-prefixed names (for example, ``default_api:tool``)
        - Canonical MCP names (``mcp__server__tool``)
        - Bare server/tool MCP names (``server__tool``)

        We normalize provider-specific prefixes first, then map bare MCP names to
        their canonical ``mcp__...`` form when the canonical name is registered.
        """
        normalized_name = _normalize_gemini_tool_name(tool_name or "")
        if not normalized_name:
            return normalized_name

        # Keep already-known names unchanged.
        if normalized_name in self._mcp_functions:
            return normalized_name
        if normalized_name in self._custom_tool_names:
            return normalized_name

        # Preserve explicit namespace prefixes when present.
        if normalized_name.startswith("mcp__"):
            return normalized_name
        if normalized_name.startswith("custom_tool__"):
            return normalized_name

        # Gemini may emit MCP names without the mcp__ prefix.
        mcp_alias = f"mcp__{normalized_name}"
        if mcp_alias in self._mcp_functions:
            return mcp_alias

        return normalized_name

    def _get_rate_limiter_context(self):
        """Get rate limiter context manager (or nullcontext if rate limiting is disabled)."""
        if self.rate_limiter is not None:
            return self.rate_limiter
        else:
            return contextlib.nullcontext()

    async def _generate_with_backoff(
        self,
        make_stream_coro: Callable,
        op_name: str,
        model_name: str,
        agent_id: str | None = None,
    ):
        """
        Execute generate_content_stream with exponential backoff on rate limit errors.
        """
        last_exc = None
        cfg = self.backoff_config

        for attempt in range(1, cfg.max_attempts + 1):
            try:
                async with self._get_rate_limiter_context():
                    return await make_stream_coro()

            except Exception as exc:
                is_retryable, status_code, error_msg = _is_retryable_gemini_error(exc, cfg.retry_statuses)
                last_exc = exc

                if not is_retryable:
                    logger.error(f"[Gemini] Non-retryable error in {op_name}: {error_msg}")
                    raise

                if attempt >= cfg.max_attempts:
                    logger.error(
                        f"[Gemini] Max retries ({cfg.max_attempts}) exhausted for {op_name}. " f"Last error: {error_msg}",
                    )
                    raise

                retry_after = _extract_retry_after(exc)
                if retry_after is not None:
                    delay = min(retry_after, cfg.max_delay)
                else:
                    delay = min(cfg.initial_delay * (cfg.multiplier ** (attempt - 1)), cfg.max_delay)

                # Apply jitter
                if cfg.jitter > 0:
                    delay *= random.uniform(1 - cfg.jitter, 1 + cfg.jitter)

                # Update telemetry
                self.backoff_retry_count += 1
                self.backoff_total_delay += delay

                log_backend_activity(
                    "gemini",
                    "Rate limited, backing off",
                    {
                        "op_name": op_name,
                        "model": model_name,
                        "attempt": attempt,
                        "max_attempts": cfg.max_attempts,
                        "delay_seconds": round(delay, 2),
                        "status_code": status_code,
                        "error": error_msg[:200],
                    },
                    agent_id=agent_id,
                )

                logger.warning(
                    f"[Gemini] Rate limited (HTTP {status_code}) in {op_name}. " f"Retry {attempt}/{cfg.max_attempts} in {delay:.1f}s",
                )

                await asyncio.sleep(delay)

        if last_exc:
            raise last_exc

    async def _process_stream(self, stream, all_params, agent_id: str | None = None) -> AsyncGenerator[StreamChunk, None]:
        """
        Required by CustomToolAndMCPBackend abstract method.
        Not used by Gemini - Gemini SDK handles streaming directly in stream_with_tools().
        """
        if False:
            yield  # Make this an async generator
        raise NotImplementedError("Gemini uses custom streaming logic in stream_with_tools()")

    async def _setup_mcp_tools(self) -> None:
        """
        Override parent class - Use base class MCP setup for manual execution pattern.
        This method is called by the parent class's __aenter__() context manager.
        """
        await super()._setup_mcp_tools()

    def supports_upload_files(self) -> bool:
        """
        Override parent class - Gemini does not support upload_files preprocessing.
        Returns False to skip upload_files processing in parent class methods.
        """
        return False

    def _create_client(self, **kwargs):
        pass

    async def _stream_with_custom_and_mcp_tools(
        self,
        current_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        client,
        **kwargs,
    ) -> AsyncGenerator[StreamChunk, None]:
        yield StreamChunk(type="error", error="Not implemented")

    async def stream_with_tools(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], **kwargs) -> AsyncGenerator[StreamChunk, None]:
        """Stream response using Gemini API with manual MCP execution pattern.

        Tool Execution Behavior:
        - Custom tools: Always executed (not blocked by planning mode or circuit breaker)
        - MCP tools: Blocked by planning mode during coordination, blocked by circuit breaker when servers fail
        - Provider tools (vote/new_answer): Emitted as StreamChunks but not executed (handled by orchestrator)
        """
        self._clear_streaming_buffer(**kwargs)
        # Use instance agent_id (from __init__) or get from kwargs if not set
        agent_id = self.agent_id or kwargs.get("agent_id", None)
        client = None
        stream = None

        # Build execution context for tools (generic, not tool-specific)
        # This is required for custom tool execution
        from .base_with_custom_tool_and_mcp import ExecutionContext

        self._execution_context = ExecutionContext(
            messages=messages,
            agent_system_message=kwargs.get("system_message", None),
            agent_id=self.agent_id,
            backend_name="gemini",
            backend_type="gemini",  # For multimodal capability lookup
            model=kwargs.get("model", ""),  # For model-specific multimodal capability lookup
            current_stage=self.coordination_stage,
        )

        if self._nlip_enabled:
            logger.info(
                f"[Gemini] NLIP routing enabled for agent {agent_id or self.agent_id}",
            )

        # Track whether MCP tools were actually used in this turn
        mcp_used = False

        log_backend_activity(
            "gemini",
            "Starting stream_with_tools",
            {"num_messages": len(messages), "num_tools": len(tools) if tools else 0},
            agent_id=agent_id,
        )

        # Trim message history for MCP if needed
        if self.mcp_servers and MCPMessageManager is not None and hasattr(self, "_max_mcp_message_history") and self._max_mcp_message_history > 0:
            original_count = len(messages)
            messages = MCPMessageManager.trim_message_history(messages, self._max_mcp_message_history)
            if len(messages) < original_count:
                log_backend_activity(
                    "gemini",
                    "Trimmed MCP message history",
                    {
                        "original": original_count,
                        "trimmed": len(messages),
                        "limit": self._max_mcp_message_history,
                    },
                    agent_id=agent_id,
                )

        try:
            from google import genai
            from google.genai import types

            # Setup MCP using base class if not already initialized
            if not self._mcp_initialized and self.mcp_servers:
                await self._setup_mcp_tools()
                if self._mcp_initialized:
                    yield StreamChunk(
                        type="mcp_status",
                        status="mcp_initialized",
                        content="✅ [MCP] Tools initialized",
                        source="mcp_tools",
                    )

            # Remove enable_rate_limit from kwargs if present (it's already been consumed in __init__)
            # This prevents it from being passed to Gemini SDK API calls
            kwargs.pop("enable_rate_limit", None)

            # Extract and remove _compression_retry from kwargs (internal flag for preventing recursive compression)
            # Must be extracted before popping, and popped before merging with config to prevent Pydantic errors
            # Store as instance variable so it's accessible in the except block
            self._compression_retry_flag = kwargs.pop("_compression_retry", False)

            # Extract vote_only flag before merging (not a Gemini API param)
            vote_only = kwargs.pop("vote_only", False)

            # Merge constructor config with stream kwargs
            all_params = {**self.config, **kwargs}

            # Detect custom tools
            using_custom_tools = bool(self.custom_tool_manager and len(self._custom_tool_names) > 0)

            # Detect coordination mode
            is_coordination = self.formatter.has_coordination_tools(tools)
            is_post_evaluation = self.formatter.has_post_evaluation_tools(tools)

            valid_agent_ids = None

            # Check if broadcast tools are available and detect decomposition mode
            broadcast_enabled = False
            is_decomposition = False
            if is_coordination:
                # Extract valid agent IDs from vote tool enum if available
                for tool in tools:
                    if tool.get("type") == "function":
                        func_def = tool.get("function", {})
                        tool_name = func_def.get("name")
                        if tool_name == "vote":
                            agent_id_param = func_def.get("parameters", {}).get("properties", {}).get("agent_id", {})
                            if "enum" in agent_id_param:
                                valid_agent_ids = agent_id_param["enum"]
                        elif tool_name == "stop":
                            is_decomposition = True
                        elif tool_name == "ask_others":
                            broadcast_enabled = True

            # Build content string from messages using formatter
            full_content = self.formatter.format_messages(messages)
            # For coordination requests, modify the prompt to use structured output
            if is_coordination:
                # vote_only was extracted earlier from kwargs (before merging into all_params)
                full_content = self.formatter.build_structured_output_prompt(
                    full_content,
                    valid_agent_ids,
                    broadcast_enabled=broadcast_enabled,
                    vote_only=vote_only,
                    decomposition_mode=is_decomposition,
                )
                if vote_only:
                    logger.info(f"[Gemini] Using vote-only prompt for agent {agent_id} (answer limit reached)")
                if is_decomposition:
                    logger.info(f"[Gemini] Using decomposition prompt for agent {agent_id} (stop instead of vote)")
            elif is_post_evaluation:
                # For post-evaluation, modify prompt to use structured output
                full_content = self.formatter.build_post_evaluation_prompt(full_content)

            # Create Gemini client
            client = genai.Client(api_key=self.api_key)

            # Setup builtin tools via API params handler
            builtin_tools = self.api_params_handler.get_provider_tools(all_params)

            # Build config via API params handler
            config = await self.api_params_handler.build_api_params(messages, tools, all_params)

            # Extract model name
            model_name = all_params.get("model")

            # ====================================================================
            # Tool Registration Phase: Convert and register tools for manual execution
            # ====================================================================
            tools_to_apply = []

            # Add custom tools if available
            if using_custom_tools:
                try:
                    # Get custom tools schemas (in OpenAI format)
                    custom_tools_schemas = self._get_custom_tools_schemas()
                    if custom_tools_schemas:
                        # Convert to Gemini SDK format using formatter
                        custom_tools_functions = self.formatter.format_custom_tools(
                            custom_tools_schemas,
                            return_sdk_objects=True,
                        )

                        if custom_tools_functions:
                            # Wrap FunctionDeclarations in a Tool object for Gemini SDK
                            custom_tool = types.Tool(function_declarations=custom_tools_functions)
                            tools_to_apply.append(custom_tool)

                            logger.debug(f"[Gemini] Registered {len(custom_tools_functions)} custom tools for manual execution")

                            yield StreamChunk(
                                type="custom_tool_status",
                                status="custom_tools_registered",
                                content=f"🔧 [Custom Tools] Registered {len(custom_tools_functions)} tools",
                                source="custom_tools",
                            )
                except Exception as e:
                    logger.warning(f"[Gemini] Failed to register custom tools: {e}")

            # Add MCP tools if available (unless blocked by planning mode)
            if self._mcp_initialized and self._mcp_functions:
                # Check planning mode
                if self.is_planning_mode_enabled():
                    blocked_tools = self.get_planning_mode_blocked_tools()

                    if not blocked_tools:
                        # Empty set means block ALL MCP tools (backward compatible)
                        logger.info("[Gemini] Planning mode enabled - blocking ALL MCP tools during coordination")
                        yield StreamChunk(
                            type="mcp_status",
                            status="planning_mode_blocked",
                            content="🚫 [MCP] Planning mode active - all MCP tools blocked during coordination",
                            source="planning_mode",
                        )

                    else:
                        # Selective blocking - register all MCP tools, execution layer will block specific ones
                        logger.info(f"[Gemini] Planning mode enabled - registering all MCP tools, will block {len(blocked_tools)} at execution")
                        try:
                            # Convert MCP tools using formatter
                            mcp_tools_functions = self.formatter.format_mcp_tools(self._mcp_functions, return_sdk_objects=True)

                            if mcp_tools_functions:
                                # Wrap in Tool object
                                mcp_tool = types.Tool(function_declarations=mcp_tools_functions)
                                tools_to_apply.append(mcp_tool)

                                # Mark MCP as used since tools are registered (even with selective blocking)
                                mcp_used = True

                                logger.debug(f"[Gemini] Registered {len(mcp_tools_functions)} MCP tools for selective blocking")

                                yield StreamChunk(
                                    type="mcp_status",
                                    status="mcp_tools_registered",
                                    content=f"🔧 [MCP] Registered {len(mcp_tools_functions)} tools (selective blocking enabled)",
                                    source="mcp_tools",
                                )
                        except Exception as e:
                            logger.warning(f"[Gemini] Failed to register MCP tools: {e}")
                else:
                    # No planning mode - register all MCP tools
                    try:
                        # Convert MCP tools using formatter
                        mcp_tools_functions = self.formatter.format_mcp_tools(self._mcp_functions, return_sdk_objects=True)

                        if mcp_tools_functions:
                            # Wrap in Tool object
                            mcp_tool = types.Tool(function_declarations=mcp_tools_functions)
                            tools_to_apply.append(mcp_tool)

                            # Mark MCP as used since tools are registered
                            mcp_used = True

                            logger.debug(f"[Gemini] Registered {len(mcp_tools_functions)} MCP tools for manual execution")

                            yield StreamChunk(
                                type="mcp_status",
                                status="mcp_tools_registered",
                                content=f"🔧 [MCP] Registered {len(mcp_tools_functions)} tools",
                                source="mcp_tools",
                            )
                    except Exception as e:
                        logger.warning(f"[Gemini] Failed to register MCP tools: {e}")

            # Apply tools to config
            if tools_to_apply:
                config["tools"] = tools_to_apply
                # Disable automatic function calling for manual execution
                config["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
                logger.debug("[Gemini] Disabled automatic function calling for manual execution")
            else:
                # No custom/MCP tools, add builtin tools if any
                if builtin_tools:
                    config["tools"] = builtin_tools

            # For coordination/post-evaluation requests, use JSON response format when no tools present
            if not tools_to_apply and not builtin_tools:
                if is_coordination:
                    config["response_mime_type"] = "application/json"
                    # Use vote-only schema if agent has reached answer limit
                    vote_only = kwargs.get("vote_only", False)
                    if vote_only:
                        config["response_schema"] = VoteOnlyCoordinationResponse.model_json_schema()
                        logger.info(f"[Gemini] Using vote-only schema for agent {agent_id} (answer limit reached)")
                    elif is_decomposition:
                        config["response_schema"] = DecompositionCoordinationResponse.model_json_schema()
                        logger.info(f"[Gemini] Using decomposition schema for agent {agent_id} (stop instead of vote)")
                    else:
                        config["response_schema"] = CoordinationResponse.model_json_schema()
                elif is_post_evaluation:
                    config["response_mime_type"] = "application/json"
                    config["response_schema"] = PostEvaluationResponse.model_json_schema()

            # Log messages being sent
            log_backend_agent_message(
                agent_id or "default",
                "SEND",
                {
                    "content": full_content,
                    "custom_tools": len(tools_to_apply) if tools_to_apply else 0,
                },
                backend_name="gemini",
            )

            # ====================================================================
            # Streaming Phase: Stream with simple function call detection
            # ====================================================================
            # Simple list accumulation for function calls (no trackers)
            captured_function_calls = []
            full_content_text = ""
            last_response_with_candidates = None

            cfg = self.backoff_config

            # Circuit breaker gate
            if self.circuit_breaker.should_block():
                raise CircuitBreakerOpenError("Circuit breaker is open for gemini")

            first_token_recorded = False
            for stream_attempt in range(1, cfg.max_attempts + 1):
                try:
                    # Start API call timing
                    self.start_api_call_timing(model_name)

                    # Use async streaming call with sessions/tools (with rate limiting)
                    async with self._get_rate_limiter_context():
                        stream = await client.aio.models.generate_content_stream(
                            model=model_name,
                            contents=full_content,
                            config=config,
                        )

                    # Stream chunks and capture function calls
                    async for chunk in stream:
                        # Detect function calls in candidates
                        if hasattr(chunk, "candidates") and chunk.candidates:
                            for candidate in chunk.candidates:
                                if hasattr(candidate, "content") and candidate.content:
                                    if hasattr(candidate.content, "parts") and candidate.content.parts:
                                        for part in candidate.content.parts:
                                            # Check for function_call part
                                            if hasattr(part, "function_call") and part.function_call:
                                                # Normalize provider prefixes and map MCP aliases.
                                                tool_name = self._normalize_and_resolve_tool_name(part.function_call.name)
                                                tool_args = dict(part.function_call.args) if part.function_call.args else {}

                                                # Create call record with globally unique ID
                                                call_id = f"call_{self._tool_call_counter}"
                                                self._tool_call_counter += 1
                                                call_record = {
                                                    "call_id": call_id,
                                                    "name": tool_name,
                                                    "arguments": json.dumps(tool_args),
                                                }

                                                # Capture thought_signature if present (required for Gemini 3.x models)
                                                if hasattr(part, "thought_signature") and part.thought_signature:
                                                    call_record["thought_signature"] = part.thought_signature

                                                captured_function_calls.append(call_record)

                                                logger.info(f"[Gemini] Function call detected: {tool_name}")

                        # Process text content - check for thinking parts first
                        # Gemini 2.5+ thinking models return parts with thought=true
                        has_thinking_content = False
                        if hasattr(chunk, "candidates") and chunk.candidates:
                            for candidate in chunk.candidates:
                                if hasattr(candidate, "content") and candidate.content:
                                    if hasattr(candidate.content, "parts") and candidate.content.parts:
                                        for part in candidate.content.parts:
                                            if hasattr(part, "thought") and part.thought and hasattr(part, "text") and part.text:
                                                # This is thinking/reasoning content
                                                has_thinking_content = True
                                                thinking_text = part.text
                                                self._append_reasoning_to_buffer(thinking_text)
                                                log_stream_chunk("backend.gemini", "reasoning", thinking_text, agent_id)
                                                yield StreamChunk(type="reasoning", reasoning_delta=thinking_text)

                        # Process regular text content (if not thinking)
                        if not has_thinking_content and hasattr(chunk, "text") and chunk.text:
                            # Record TTFT on first content
                            if not first_token_recorded:
                                self.record_first_token()
                                first_token_recorded = True

                            chunk_text = chunk.text
                            full_content_text += chunk_text
                            log_backend_agent_message(
                                agent_id,
                                "RECV",
                                {"content": chunk_text},
                                backend_name="gemini",
                            )
                            log_stream_chunk("backend.gemini", "content", chunk_text, agent_id)
                            self._append_to_streaming_buffer(chunk_text)
                            yield StreamChunk(type="content", content=chunk_text)

                        # Buffer last chunk with candidates
                        if hasattr(chunk, "candidates") and chunk.candidates:
                            last_response_with_candidates = chunk

                    # End API call timing on successful completion
                    self.end_api_call_timing(success=True)
                    self.circuit_breaker.record_success()
                    break

                except Exception as stream_exc:
                    # End API call timing with failure
                    self.end_api_call_timing(success=False, error=str(stream_exc))

                    is_retryable, status_code, error_msg = _is_retryable_gemini_error(stream_exc, cfg.retry_statuses)

                    if not is_retryable or stream_attempt >= cfg.max_attempts:
                        if is_retryable:
                            self.circuit_breaker.record_failure(
                                error_type=f"exhausted_{status_code or 'unknown'}",
                                error_message=f"Max retries exhausted: {error_msg[:200]}",
                            )
                            yield StreamChunk(
                                type="error",
                                error=f"⚠️ Rate limit exceeded after {cfg.max_attempts} retries. Please try again later.",
                            )
                        raise

                    retry_status_code = status_code or "unknown"
                    retry_notice = f"⚠️ [Gemini] Rate limited (HTTP {retry_status_code}) " f"after partial output. Retrying attempt {stream_attempt + 1}/{cfg.max_attempts}..."
                    log_stream_chunk("backend.gemini", "content", retry_notice, agent_id)
                    yield StreamChunk(type="content", content=f"{retry_notice}\n")

                    logger.warning(
                        f"[Gemini] Rate limit (HTTP {status_code}) in initial_stream. " f"Retry {stream_attempt}/{cfg.max_attempts}, backing off...",
                    )
                    captured_function_calls = []
                    full_content_text = ""
                    last_response_with_candidates = None
                    first_token_recorded = False  # Reset for retry

                    retry_after = _extract_retry_after(stream_exc)
                    if retry_after is not None:
                        delay = min(retry_after, cfg.max_delay)
                    else:
                        delay = min(cfg.initial_delay * (cfg.multiplier ** (stream_attempt - 1)), cfg.max_delay)
                    if cfg.jitter > 0:
                        delay *= random.uniform(1 - cfg.jitter, 1 + cfg.jitter)

                    self.backoff_retry_count += 1
                    self.backoff_total_delay += delay
                    await asyncio.sleep(delay)

            # Helper to track tokens from a response chunk
            def track_usage_from_chunk(chunk) -> None:
                """Extract and track token usage from a Gemini response chunk."""
                if not model_name:
                    raise ValueError("[Gemini] model_name is required for token tracking")
                if chunk and hasattr(chunk, "usage_metadata"):
                    usage_meta = chunk.usage_metadata
                    if usage_meta:
                        usage = {
                            "prompt_token_count": getattr(usage_meta, "prompt_token_count", 0) or 0,
                            "candidates_token_count": getattr(usage_meta, "candidates_token_count", 0) or 0,
                            # Gemini 2.5 thinking models
                            "thoughts_token_count": getattr(usage_meta, "thoughts_token_count", 0) or 0,
                            # Gemini 2.5 implicit caching
                            "cached_content_token_count": getattr(usage_meta, "cached_content_token_count", 0) or 0,
                        }
                        # Only update if we have actual token counts
                        if usage["prompt_token_count"] > 0 or usage["candidates_token_count"] > 0:
                            self._update_token_usage_from_api_response(usage, model_name)
                            logger.info(
                                f"[Gemini] Token usage tracked: "
                                f"input={usage['prompt_token_count']}, "
                                f"output={usage['candidates_token_count']}, "
                                f"thinking={usage['thoughts_token_count']}, "
                                f"cached={usage['cached_content_token_count']}",
                            )

            # Track usage metadata from the last response (Gemini provides cumulative totals)
            track_usage_from_chunk(last_response_with_candidates)

            # ====================================================================
            # Structured Coordination Output Parsing
            # ====================================================================
            # Check for structured coordination output - ALWAYS check in coordination mode
            # Structured output (vote, new_answer, ask_others) takes priority over MCP tool calls
            # Note: Gemini may output both structured JSON AND MCP tool calls in the same response
            # (e.g., ask_others JSON plus weird file creation attempts). We prioritize the structured output.
            if is_coordination and full_content_text:
                # Try to parse structured response from text content
                parsed = self.formatter.extract_structured_response(full_content_text)

                if parsed and isinstance(parsed, dict):
                    # Convert structured response to tool calls
                    tool_calls = self.formatter.convert_structured_to_tool_calls(parsed)

                    if tool_calls:
                        # Valid structured output found - clear any spurious MCP calls from captured_function_calls
                        # Gemini sometimes outputs both structured JSON AND MCP tool calls, but the structured
                        # output is the intended coordination action - the MCP calls are erroneous
                        if captured_function_calls:
                            logger.warning(
                                f"[Gemini] Structured coordination output found, clearing {len(captured_function_calls)} "
                                "spurious MCP tool calls that were issued alongside the structured JSON response",
                            )
                            captured_function_calls.clear()

                        # Categorize the tool calls
                        mcp_calls, custom_calls, provider_calls = self._categorize_tool_calls(tool_calls)

                        # If there are custom_calls (like ask_others), add them to captured_function_calls
                        # so they get executed in the Tool Execution Phase
                        # Mark them as from structured output - these don't have thought_signature
                        # and need special handling when sending results back to Gemini
                        if custom_calls:
                            for call in custom_calls:
                                call["_from_structured_output"] = True
                            captured_function_calls.extend(custom_calls)
                            logger.info(f"[Gemini] Added {len(custom_calls)} custom tool(s) from structured output for execution")

                        # Handle provider (workflow) calls - these are coordination actions
                        # We yield StreamChunk entries but do NOT execute them
                        if provider_calls:
                            # Convert provider calls to tool_calls format for orchestrator
                            workflow_tool_calls = []
                            hallucinated_mcp_calls = []  # Track MCP-prefixed tools that don't exist
                            for call in provider_calls:
                                tool_name = call.get("name", "")
                                tool_args_str = call.get("arguments", "{}")

                                # Check for hallucinated MCP tools
                                if tool_name.startswith("mcp__") and tool_name not in self._mcp_functions:
                                    hallucinated_mcp_calls.append(call)
                                    continue

                                # Parse arguments if they're a string
                                if isinstance(tool_args_str, str):
                                    try:
                                        tool_args = json.loads(tool_args_str)
                                    except json.JSONDecodeError:
                                        tool_args = {}
                                else:
                                    tool_args = tool_args_str

                                # Log the coordination action
                                logger.info(f"[Gemini] Structured coordination action: {tool_name}")
                                log_tool_call(
                                    agent_id,
                                    tool_name,
                                    tool_args,
                                    None,
                                    backend_name="gemini",
                                )

                                # Build tool call in standard format
                                workflow_tool_calls.append(
                                    {
                                        "id": call.get("call_id", f"call_{len(workflow_tool_calls)}"),
                                        "type": "function",
                                        "function": {
                                            "name": tool_name,
                                            "arguments": tool_args,
                                        },
                                    },
                                )

                            # Handle hallucinated MCP calls - return error for retry
                            if hallucinated_mcp_calls:
                                for bad_call in hallucinated_mcp_calls:
                                    bad_tool_name = bad_call.get("name", "")
                                    parts = bad_tool_name.split("__")
                                    actual_tool_name = parts[-1] if len(parts) >= 3 else bad_tool_name

                                    error_msg = f"Tool '{bad_tool_name}' does not exist. " f"Use the direct tool '{actual_tool_name}' instead (without MCP prefix)."
                                    logger.warning(f"[Gemini] Hallucinated MCP tool in structured output: {bad_tool_name} -> suggesting {actual_tool_name}")

                                    self._append_tool_error_message(
                                        messages,
                                        bad_call,
                                        error_msg,
                                        "mcp",
                                    )

                                    yield StreamChunk(
                                        type="mcp_status",
                                        status="mcp_tool_error",
                                        content=f"❌ {error_msg}",
                                        source="mcp_tools",
                                    )

                                # If only hallucinated calls, add them to captured_function_calls
                                # so the continuation loop can retry
                                if not workflow_tool_calls and not captured_function_calls:
                                    # No valid workflow calls and no custom calls - continue to allow retry
                                    pass  # Fall through - don't return early

                            # Emit tool_calls chunk for orchestrator to process
                            if workflow_tool_calls:
                                log_stream_chunk("backend.gemini", "tool_calls", workflow_tool_calls, agent_id)
                                yield StreamChunk(
                                    type="tool_calls",
                                    tool_calls=workflow_tool_calls,
                                    source="gemini",
                                )

                        # Do not execute workflow tools - just return after yielding
                        # The orchestrator will handle these coordination actions
                        # BUT: if there are custom_calls (like ask_others), don't return yet
                        # - let them be executed in the Tool Execution Phase
                        if provider_calls and not captured_function_calls:
                            # Only return early if there are NO custom tools to execute
                            # Track tokens before returning
                            track_usage_from_chunk(last_response_with_candidates)

                            # Emit completion status if MCP was actually used
                            if mcp_used:
                                yield StreamChunk(
                                    type="mcp_status",
                                    status="mcp_session_complete",
                                    content="✅ [MCP] Session completed",
                                    source="mcp_tools",
                                )

                            yield StreamChunk(type="done")
                            return

            # ====================================================================
            # Tool Execution Phase: Execute captured function calls using base class
            # ====================================================================
            if captured_function_calls:
                # Categorize function calls using base class helper
                mcp_calls, custom_calls, provider_calls = self._categorize_tool_calls(captured_function_calls)

                # ====================================================================
                # Handle provider (workflow) calls - emit as StreamChunks but do NOT execute
                # ====================================================================
                if provider_calls:
                    # Convert provider calls to tool_calls format for orchestrator
                    workflow_tool_calls = []
                    hallucinated_mcp_calls = []  # Track MCP-prefixed tools that don't exist
                    for call in provider_calls:
                        tool_name = call.get("name", "")
                        tool_args_str = call.get("arguments", "{}")

                        # Check for hallucinated MCP tools - tools that look like MCP calls
                        # but aren't in our registered MCP functions
                        if tool_name.startswith("mcp__") and tool_name not in self._mcp_functions:
                            hallucinated_mcp_calls.append(call)
                            continue  # Don't add to workflow_tool_calls

                        # Parse arguments if they're a string
                        if isinstance(tool_args_str, str):
                            try:
                                tool_args = json.loads(tool_args_str)
                            except json.JSONDecodeError:
                                tool_args = {}
                        else:
                            tool_args = tool_args_str

                        # Log the coordination action
                        logger.info(f"[Gemini] Function call coordination action: {tool_name}")
                        log_tool_call(
                            agent_id,
                            tool_name,
                            tool_args,
                            None,
                            backend_name="gemini",
                        )

                        # Build tool call in standard format
                        workflow_tool_calls.append(
                            {
                                "id": call.get("call_id", f"call_{len(workflow_tool_calls)}"),
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": tool_args,
                                },
                            },
                        )

                    # Handle hallucinated MCP calls - return error and continue for retry
                    if hallucinated_mcp_calls:
                        for bad_call in hallucinated_mcp_calls:
                            bad_tool_name = bad_call.get("name", "")
                            # Extract the actual tool name from MCP prefix (e.g., "mcp__planning_agent_a__new_answer" -> "new_answer")
                            parts = bad_tool_name.split("__")
                            actual_tool_name = parts[-1] if len(parts) >= 3 else bad_tool_name

                            error_msg = f"Tool '{bad_tool_name}' does not exist. " f"Use the direct tool '{actual_tool_name}' instead (without MCP prefix)."
                            logger.warning(f"[Gemini] Hallucinated MCP tool: {bad_tool_name} -> suggesting {actual_tool_name}")

                            # Add error to messages for retry
                            self._append_tool_error_message(
                                messages,
                                bad_call,
                                error_msg,
                                "mcp",
                            )

                            yield StreamChunk(
                                type="mcp_status",
                                status="mcp_tool_error",
                                content=f"❌ {error_msg}",
                                source="mcp_tools",
                            )

                        # Don't return - continue streaming to allow agent to retry
                        # Fall through to execute any other pending tools or continue generation

                    # Emit tool_calls chunk for orchestrator to process
                    if workflow_tool_calls:
                        log_stream_chunk("backend.gemini", "tool_calls", workflow_tool_calls, agent_id)
                        yield StreamChunk(
                            type="tool_calls",
                            tool_calls=workflow_tool_calls,
                            source="gemini",
                        )

                        # Track tokens before returning
                        track_usage_from_chunk(last_response_with_candidates)

                        if mcp_used:
                            yield StreamChunk(
                                type="mcp_status",
                                status="mcp_session_complete",
                                content="✅ [MCP] Session completed",
                                source="mcp_tools",
                            )

                        yield StreamChunk(type="done")
                        return

                    # If only hallucinated calls (no valid workflow calls), continue to let agent retry
                    if hallucinated_mcp_calls and not workflow_tool_calls:
                        # Continue streaming - agent should retry with correct tool name
                        pass  # Fall through to continuation logic

                # Initialize for execution
                updated_messages = messages.copy()
                processed_call_ids = set()

                # Configuration for custom tool execution
                CUSTOM_TOOL_CONFIG = ToolExecutionConfig(
                    tool_type="custom",
                    chunk_type="custom_tool_status",
                    emoji_prefix="🔧 [Custom Tool]",
                    success_emoji="✅ [Custom Tool]",
                    error_emoji="❌ [Custom Tool Error]",
                    source_prefix="custom_",
                    status_called="custom_tool_called",
                    status_response="custom_tool_response",
                    status_error="custom_tool_error",
                    execution_callback=self._execute_custom_tool,
                )

                # Configuration for MCP tool execution
                MCP_TOOL_CONFIG = ToolExecutionConfig(
                    tool_type="mcp",
                    chunk_type="mcp_status",
                    emoji_prefix="🔧 [MCP Tool]",
                    success_emoji="✅ [MCP Tool]",
                    error_emoji="❌ [MCP Tool Error]",
                    source_prefix="mcp_",
                    status_called="mcp_tool_called",
                    status_response="mcp_tool_response",
                    status_error="mcp_tool_error",
                    execution_callback=self._execute_mcp_function_with_retry,
                )

                # Capture tool execution results for continuation loop
                tool_results: dict[str, str] = {}
                self._active_tool_result_store = tool_results

                try:
                    if mcp_calls and not await self._check_circuit_breaker_before_execution():
                        logger.warning("[Gemini] All MCP servers blocked by circuit breaker")
                        yield StreamChunk(
                            type="mcp_status",
                            status="mcp_blocked",
                            content="⚠️ [MCP] All servers blocked by circuit breaker",
                            source="circuit_breaker",
                        )
                        mcp_calls = []

                    def chunk_adapter(chunk: StreamChunk) -> StreamChunk:
                        return chunk

                    nlip_available = self._nlip_enabled and self._nlip_router

                    pending_custom_calls: list[dict[str, Any]] = []
                    for call in custom_calls:
                        handled_via_nlip = False
                        if nlip_available:
                            logger.info(f"[NLIP] Using NLIP routing for custom tool {call['name']}")
                            try:
                                async for chunk in self._stream_tool_execution_via_nlip(
                                    call,
                                    CUSTOM_TOOL_CONFIG,
                                    updated_messages,
                                    processed_call_ids,
                                ):
                                    yield chunk_adapter(chunk)
                                handled_via_nlip = True
                            except Exception as exc:
                                logger.warning(
                                    f"[NLIP] Routing failed for {call['name']}: {exc}. Falling back to direct execution.",
                                )
                                async for chunk in self._execute_tool_with_logging(
                                    call,
                                    CUSTOM_TOOL_CONFIG,
                                    updated_messages,
                                    processed_call_ids,
                                ):
                                    yield chunk_adapter(chunk)
                                handled_via_nlip = True

                        if handled_via_nlip:
                            continue

                        reason = "disabled" if not self._nlip_enabled else "router unavailable"
                        logger.info(
                            f"[Custom Tool] Direct execution for {call['name']} (NLIP {reason})",
                        )
                        pending_custom_calls.append(call)

                    pending_mcp_calls: list[dict[str, Any]] = []
                    for call in mcp_calls:
                        handled_via_nlip = False
                        if nlip_available:
                            logger.info(f"[NLIP] Using NLIP routing for MCP tool {call['name']}")
                            try:
                                async for chunk in self._stream_tool_execution_via_nlip(
                                    call,
                                    MCP_TOOL_CONFIG,
                                    updated_messages,
                                    processed_call_ids,
                                ):
                                    mcp_used = True
                                    yield chunk_adapter(chunk)
                                handled_via_nlip = True
                            except Exception as exc:
                                logger.warning(
                                    f"[NLIP] Routing failed for {call['name']}: {exc}. Falling back to direct execution.",
                                )
                                async for chunk in self._execute_tool_with_logging(
                                    call,
                                    MCP_TOOL_CONFIG,
                                    updated_messages,
                                    processed_call_ids,
                                ):
                                    yield chunk_adapter(chunk)
                                mcp_used = True
                                handled_via_nlip = True

                        if handled_via_nlip:
                            continue

                        reason = "disabled" if not self._nlip_enabled else "router unavailable"
                        logger.info(
                            f"[MCP Tool] Direct execution for {call['name']} (NLIP {reason})",
                        )
                        pending_mcp_calls.append(call)

                    all_calls = pending_custom_calls + pending_mcp_calls

                    def tool_config_for_call(call: dict[str, Any]) -> ToolExecutionConfig:
                        tool_name = call.get("name", "")
                        return CUSTOM_TOOL_CONFIG if tool_name in (self._custom_tool_names or set()) else MCP_TOOL_CONFIG

                    if all_calls:
                        if pending_mcp_calls:
                            mcp_used = True

                        async for adapted_chunk in self._execute_tool_calls(
                            all_calls=all_calls,
                            tool_config_for_call=tool_config_for_call,
                            all_params=all_params,
                            updated_messages=updated_messages,
                            processed_call_ids=processed_call_ids,
                            log_prefix="[Gemini]",
                            chunk_adapter=chunk_adapter,
                        ):
                            yield adapted_chunk
                finally:
                    self._active_tool_result_store = None

                executed_calls = custom_calls + mcp_calls

                # Build initial conversation history using SDK Content objects
                conversation_history: list[types.Content] = [
                    types.Content(parts=[types.Part(text=full_content)], role="user"),
                ]

                if executed_calls:
                    # Separate calls that came from structured output (no thought_signature)
                    # from real function calls (have thought_signature)
                    structured_output_calls = [c for c in executed_calls if c.get("_from_structured_output")]
                    real_function_calls = [c for c in executed_calls if not c.get("_from_structured_output")]

                    # For real function calls, use the standard function call/response format
                    if real_function_calls:
                        model_parts = []
                        for call in real_function_calls:
                            args_payload: Any = call.get("arguments", {})
                            if isinstance(args_payload, str):
                                try:
                                    args_payload = json.loads(args_payload)
                                except json.JSONDecodeError:
                                    args_payload = {}
                            if not isinstance(args_payload, dict):
                                args_payload = {}
                            part = types.Part.from_function_call(
                                name=call.get("name", ""),
                                args=args_payload,
                            )
                            # Preserve thought_signature if present (required for Gemini 3.x models)
                            if "thought_signature" in call:
                                part.thought_signature = call["thought_signature"]
                            model_parts.append(part)
                        if model_parts:
                            conversation_history.append(types.Content(parts=model_parts, role="model"))

                        response_parts = []
                        for call in real_function_calls:
                            call_id = call.get("call_id")
                            result_data = tool_results.get(call_id or "", "No result")

                            rd_type = type(result_data).__name__
                            rd_is_dict = isinstance(result_data, dict)
                            rd_keys = result_data.keys() if rd_is_dict else "N/A"
                            logger.info(
                                f"[Gemini MM] result_data type={rd_type}, " f"is_dict={rd_is_dict}, keys={rd_keys}",
                            )

                            # Plain text result
                            result_text = result_data if isinstance(result_data, str) else str(result_data)
                            response_parts.append(
                                types.Part.from_function_response(
                                    name=call.get("name", ""),
                                    response={"result": result_text},
                                ),
                            )
                        logger.info(f"[Gemini MM] real_function_calls={len(real_function_calls)}, response_parts={len(response_parts)}")
                        if response_parts:
                            conversation_history.append(types.Content(parts=response_parts, role="user"))

                    # For structured output calls (like ask_others from JSON), inject results as text
                    # These don't have thought_signature and can't use function call/response format
                    if structured_output_calls:
                        logger.info(f"[Gemini MM] structured_output_calls={len(structured_output_calls)}")
                        # Build text representation of tool results
                        text_results = []
                        for call in structured_output_calls:
                            call_id = call.get("call_id")
                            tool_name = call.get("name", "unknown")
                            result_data = tool_results.get(call_id or "", "No result")
                            # Extract text from result
                            if isinstance(result_data, dict) and "text" in result_data:
                                result_text = result_data["text"]
                            else:
                                result_text = result_data if isinstance(result_data, str) else str(result_data)
                            text_results.append(f"[Tool Result: {tool_name}]\n{result_text}")

                        # Add as model response (assistant acknowledging tool execution)
                        model_text = "I executed the following tool(s) and received these results:\n\n" + "\n\n".join(text_results)
                        conversation_history.append(types.Content(parts=[types.Part(text=model_text)], role="model"))

                        # Add user message prompting continuation
                        user_parts = [
                            types.Part(
                                text=(
                                    "Based on the tool results above, please continue with your response. "
                                    "Remember to use the appropriate coordination action "
                                    "(vote, new_answer, or ask_others) when ready."
                                ),
                            ),
                        ]
                        conversation_history.append(
                            types.Content(parts=user_parts, role="user"),
                        )

                last_continuation_chunk = None

                while True:
                    new_function_calls = []
                    continuation_text = ""
                    cont_first_token_recorded = False

                    # Retry for continuation with backoff
                    # Circuit breaker gate
                    if self.circuit_breaker.should_block():
                        raise CircuitBreakerOpenError("Circuit breaker is open for gemini")

                    for cont_attempt in range(1, cfg.max_attempts + 1):
                        try:
                            # Start API call timing for continuation
                            self.start_api_call_timing(model_name)

                            # Use same config as before
                            async with self._get_rate_limiter_context():
                                continuation_stream = await client.aio.models.generate_content_stream(
                                    model=model_name,
                                    contents=conversation_history,
                                    config=config,
                                )
                            stream = continuation_stream

                            async for chunk in continuation_stream:
                                if hasattr(chunk, "candidates") and chunk.candidates:
                                    last_continuation_chunk = chunk
                                    for candidate in chunk.candidates:
                                        if hasattr(candidate, "content") and candidate.content:
                                            if hasattr(candidate.content, "parts") and candidate.content.parts:
                                                for part in candidate.content.parts:
                                                    if hasattr(part, "function_call") and part.function_call:
                                                        # Normalize provider prefixes and map MCP aliases.
                                                        tool_name = self._normalize_and_resolve_tool_name(part.function_call.name)
                                                        tool_args = dict(part.function_call.args) if part.function_call.args else {}
                                                        call_id = f"call_{self._tool_call_counter}"
                                                        self._tool_call_counter += 1
                                                        call_record = {
                                                            "call_id": call_id,
                                                            "name": tool_name,
                                                            "arguments": json.dumps(tool_args),
                                                        }

                                                        # Capture thought_signature if present (required for Gemini 3.x models)
                                                        if hasattr(part, "thought_signature") and part.thought_signature:
                                                            call_record["thought_signature"] = part.thought_signature

                                                        new_function_calls.append(call_record)

                                # Process text content - check for thinking parts first
                                # Gemini 2.5+ thinking models return parts with thought=true
                                has_thinking_content = False
                                if hasattr(chunk, "candidates") and chunk.candidates:
                                    for candidate in chunk.candidates:
                                        if hasattr(candidate, "content") and candidate.content:
                                            if hasattr(candidate.content, "parts") and candidate.content.parts:
                                                for part in candidate.content.parts:
                                                    if hasattr(part, "thought") and part.thought and hasattr(part, "text") and part.text:
                                                        # This is thinking/reasoning content
                                                        has_thinking_content = True
                                                        thinking_text = part.text
                                                        self._append_reasoning_to_buffer(thinking_text)
                                                        log_stream_chunk("backend.gemini", "reasoning", thinking_text, agent_id)
                                                        yield StreamChunk(type="reasoning", reasoning_delta=thinking_text)

                                # Process regular text content (if not thinking)
                                if not has_thinking_content and hasattr(chunk, "text") and chunk.text:
                                    # Record TTFT on first content
                                    if not cont_first_token_recorded:
                                        self.record_first_token()
                                        cont_first_token_recorded = True

                                    chunk_text = chunk.text
                                    continuation_text += chunk_text
                                    log_backend_agent_message(
                                        agent_id,
                                        "RECV",
                                        {"content": chunk_text},
                                        backend_name="gemini",
                                    )
                                    log_stream_chunk("backend.gemini", "content", chunk_text, agent_id)
                                    self._append_to_streaming_buffer(chunk_text)
                                    yield StreamChunk(type="content", content=chunk_text)

                            # End API call timing on successful completion
                            self.end_api_call_timing(success=True)
                            self.circuit_breaker.record_success()
                            break

                        except Exception as cont_exc:
                            # End API call timing with failure
                            self.end_api_call_timing(success=False, error=str(cont_exc))
                            is_retryable, status_code, error_msg = _is_retryable_gemini_error(cont_exc, cfg.retry_statuses)

                            if not is_retryable or cont_attempt >= cfg.max_attempts:
                                # Yield user-friendly error before raising
                                if is_retryable:
                                    self.circuit_breaker.record_failure(
                                        error_type=f"exhausted_{status_code or 'unknown'}",
                                        error_message=f"Max retries exhausted: {error_msg[:200]}",
                                    )
                                    yield StreamChunk(
                                        type="error",
                                        error=f"⚠️ Rate limit exceeded after {cfg.max_attempts} retries. Please try again later.",
                                    )
                                raise

                            retry_status_code = status_code or "unknown"
                            retry_notice = (
                                f"⚠️ [Gemini] Rate limited (HTTP {retry_status_code}) " f"during continuation after partial output. Retrying attempt " f"{cont_attempt + 1}/{cfg.max_attempts}..."
                            )
                            log_stream_chunk("backend.gemini", "content", retry_notice, agent_id)
                            yield StreamChunk(type="content", content=f"{retry_notice}\n")

                            logger.warning(
                                f"[Gemini] Rate limit (HTTP {status_code}) in continuation_stream. " f"Retry {cont_attempt}/{cfg.max_attempts}, backing off...",
                            )
                            new_function_calls = []
                            continuation_text = ""
                            last_continuation_chunk = None
                            cont_first_token_recorded = False  # Reset for retry

                            retry_after = _extract_retry_after(cont_exc)
                            if retry_after is not None:
                                delay = min(retry_after, cfg.max_delay)
                            else:
                                delay = min(cfg.initial_delay * (cfg.multiplier ** (cont_attempt - 1)), cfg.max_delay)
                            if cfg.jitter > 0:
                                delay *= random.uniform(1 - cfg.jitter, 1 + cfg.jitter)

                            self.backoff_retry_count += 1
                            self.backoff_total_delay += delay
                            await asyncio.sleep(delay)

                    # Track usage metadata from continuation stream
                    track_usage_from_chunk(last_continuation_chunk)

                    if continuation_text:
                        conversation_history.append(
                            types.Content(parts=[types.Part(text=continuation_text)], role="model"),
                        )
                        full_content_text += continuation_text

                    if last_continuation_chunk:
                        last_response_with_candidates = last_continuation_chunk

                    if not new_function_calls:
                        # ====================================================================
                        # Continuation Structured Coordination Output Parsing
                        # ====================================================================
                        # Check for structured coordination output when no function calls in continuation
                        if is_coordination and full_content_text:
                            # Try to parse structured response from accumulated text content
                            parsed = self.formatter.extract_structured_response(full_content_text)

                            if parsed and isinstance(parsed, dict):
                                # Convert structured response to tool calls
                                tool_calls = self.formatter.convert_structured_to_tool_calls(parsed)

                                if tool_calls:
                                    # Categorize the tool calls
                                    cont_mcp_calls, cont_custom_calls, cont_provider_calls = self._categorize_tool_calls(tool_calls)

                                    # Handle custom_calls (like ask_others) - add to execution queue
                                    # Mark them as from structured output - no thought_signature
                                    if cont_custom_calls:
                                        for call in cont_custom_calls:
                                            call["_from_structured_output"] = True
                                            tool_name = call.get("name", "")
                                            tool_args_str = call.get("arguments", "{}")

                                            if isinstance(tool_args_str, str):
                                                try:
                                                    tool_args = json.loads(tool_args_str)
                                                except json.JSONDecodeError:
                                                    tool_args = {}
                                            else:
                                                tool_args = tool_args_str

                                            logger.info(f"[Gemini] Continuation custom tool from structured output: {tool_name}")
                                            log_tool_call(
                                                agent_id,
                                                tool_name,
                                                tool_args,
                                                None,
                                                backend_name="gemini",
                                            )

                                            # Execute the custom tool
                                            async for chunk in self._execute_tool_with_logging(
                                                call,
                                                CUSTOM_TOOL_CONFIG,
                                                updated_messages,
                                                processed_call_ids,
                                            ):
                                                yield chunk_adapter(chunk)

                                            executed_calls.append(call)

                                    if cont_provider_calls:
                                        # Convert provider calls to tool_calls format for orchestrator
                                        workflow_tool_calls = []
                                        hallucinated_mcp_calls = []  # Track MCP-prefixed tools that don't exist
                                        for call in cont_provider_calls:
                                            tool_name = call.get("name", "")
                                            tool_args_str = call.get("arguments", "{}")

                                            # Check for hallucinated MCP tools
                                            if tool_name.startswith("mcp__") and tool_name not in self._mcp_functions:
                                                hallucinated_mcp_calls.append(call)
                                                continue

                                            # Parse arguments if they're a string
                                            if isinstance(tool_args_str, str):
                                                try:
                                                    tool_args = json.loads(tool_args_str)
                                                except json.JSONDecodeError:
                                                    tool_args = {}
                                            else:
                                                tool_args = tool_args_str

                                            # Log the coordination action
                                            logger.info(f"[Gemini] Continuation structured coordination action: {tool_name}")
                                            log_tool_call(
                                                agent_id,
                                                tool_name,
                                                tool_args,
                                                None,
                                                backend_name="gemini",
                                            )

                                            # Build tool call in standard format
                                            workflow_tool_calls.append(
                                                {
                                                    "id": call.get("call_id", f"call_{len(workflow_tool_calls)}"),
                                                    "type": "function",
                                                    "function": {
                                                        "name": tool_name,
                                                        "arguments": tool_args,
                                                    },
                                                },
                                            )

                                        # Handle hallucinated MCP calls - return error for retry
                                        if hallucinated_mcp_calls:
                                            for bad_call in hallucinated_mcp_calls:
                                                bad_tool_name = bad_call.get("name", "")
                                                parts = bad_tool_name.split("__")
                                                actual_tool_name = parts[-1] if len(parts) >= 3 else bad_tool_name

                                                error_msg = f"Tool '{bad_tool_name}' does not exist. " f"Use the direct tool '{actual_tool_name}' instead (without MCP prefix)."
                                                logger.warning(f"[Gemini] Hallucinated MCP tool in continuation structured output: {bad_tool_name} -> suggesting {actual_tool_name}")

                                                self._append_tool_error_message(
                                                    updated_messages,
                                                    bad_call,
                                                    error_msg,
                                                    "mcp",
                                                )

                                                yield StreamChunk(
                                                    type="mcp_status",
                                                    status="mcp_tool_error",
                                                    content=f"❌ {error_msg}",
                                                    source="mcp_tools",
                                                )

                                            # If only hallucinated calls, continue the loop to allow retry
                                            if not workflow_tool_calls:
                                                continue  # Continue the continuation loop

                                        # Emit tool_calls chunk for orchestrator to process
                                        if workflow_tool_calls:
                                            log_stream_chunk("backend.gemini", "tool_calls", workflow_tool_calls, agent_id)
                                            yield StreamChunk(
                                                type="tool_calls",
                                                tool_calls=workflow_tool_calls,
                                                source="gemini",
                                            )

                                            # Track tokens before returning
                                            track_usage_from_chunk(last_continuation_chunk)

                                            if mcp_used:
                                                yield StreamChunk(
                                                    type="mcp_status",
                                                    status="mcp_session_complete",
                                                    content="✅ [MCP] Session completed",
                                                    source="mcp_tools",
                                                )

                                            yield StreamChunk(type="done")
                                            return

                        # No structured output found, break continuation loop
                        break

                    next_mcp_calls, next_custom_calls, provider_calls = self._categorize_tool_calls(new_function_calls)

                    # Handle provider calls emitted during continuation
                    if provider_calls:
                        workflow_tool_calls = []
                        hallucinated_mcp_calls = []  # Track MCP-prefixed tools that don't exist
                        for call in provider_calls:
                            tool_name = call.get("name", "")
                            tool_args_str = call.get("arguments", "{}")

                            # Check for hallucinated MCP tools
                            if tool_name.startswith("mcp__") and tool_name not in self._mcp_functions:
                                hallucinated_mcp_calls.append(call)
                                continue

                            if isinstance(tool_args_str, str):
                                try:
                                    tool_args = json.loads(tool_args_str)
                                except json.JSONDecodeError:
                                    tool_args = {}
                            else:
                                tool_args = tool_args_str

                            logger.info(f"[Gemini] Continuation coordination action: {tool_name}")
                            log_tool_call(
                                agent_id,
                                tool_name,
                                tool_args,
                                None,
                                backend_name="gemini",
                            )

                            workflow_tool_calls.append(
                                {
                                    "id": call.get("call_id", f"call_{len(workflow_tool_calls)}"),
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": tool_args,
                                    },
                                },
                            )

                        # Handle hallucinated MCP calls - return error for retry
                        if hallucinated_mcp_calls:
                            for bad_call in hallucinated_mcp_calls:
                                bad_tool_name = bad_call.get("name", "")
                                parts = bad_tool_name.split("__")
                                actual_tool_name = parts[-1] if len(parts) >= 3 else bad_tool_name

                                error_msg = f"Tool '{bad_tool_name}' does not exist. " f"Use the direct tool '{actual_tool_name}' instead (without MCP prefix)."
                                logger.warning(f"[Gemini] Hallucinated MCP tool in continuation: {bad_tool_name} -> suggesting {actual_tool_name}")

                                self._append_tool_error_message(
                                    updated_messages,
                                    bad_call,
                                    error_msg,
                                    "mcp",
                                )

                                yield StreamChunk(
                                    type="mcp_status",
                                    status="mcp_tool_error",
                                    content=f"❌ {error_msg}",
                                    source="mcp_tools",
                                )

                            # If only hallucinated calls, continue to let agent retry
                            if not workflow_tool_calls:
                                continue  # Continue the continuation loop

                        if workflow_tool_calls:
                            log_stream_chunk("backend.gemini", "tool_calls", workflow_tool_calls, agent_id)
                            yield StreamChunk(
                                type="tool_calls",
                                tool_calls=workflow_tool_calls,
                                source="gemini",
                            )

                            # Track tokens before returning
                            track_usage_from_chunk(last_continuation_chunk)

                            if mcp_used:
                                yield StreamChunk(
                                    type="mcp_status",
                                    status="mcp_session_complete",
                                    content="✅ [MCP] Session completed",
                                    source="mcp_tools",
                                )

                            yield StreamChunk(type="done")
                            return

                    new_tool_results: dict[str, str] = {}
                    self._active_tool_result_store = new_tool_results

                    # Check circuit breaker before MCP tool execution
                    if next_mcp_calls and not await self._check_circuit_breaker_before_execution():
                        logger.warning("[Gemini] All MCP servers blocked by circuit breaker during continuation")
                        yield StreamChunk(
                            type="mcp_status",
                            status="mcp_blocked",
                            content="⚠️ [MCP] All servers blocked by circuit breaker",
                            source="circuit_breaker",
                        )
                        next_mcp_calls = []

                    # Combine all continuation tool calls
                    next_all_calls = next_custom_calls + next_mcp_calls

                    try:
                        # Execute tools based on configuration (same scheduler as initial execution)
                        def tool_config_for_call(call: dict[str, Any]) -> ToolExecutionConfig:
                            tool_name = call.get("name", "")
                            return CUSTOM_TOOL_CONFIG if tool_name in (self._custom_tool_names or set()) else MCP_TOOL_CONFIG

                        def chunk_adapter(chunk: StreamChunk) -> StreamChunk:
                            return chunk

                        async for adapted_chunk in self._execute_tool_calls(
                            all_calls=next_all_calls,
                            tool_config_for_call=tool_config_for_call,
                            all_params=all_params,
                            updated_messages=updated_messages,
                            processed_call_ids=processed_call_ids,
                            log_prefix="[Gemini] Continuation:",
                            chunk_adapter=chunk_adapter,
                        ):
                            if next_mcp_calls:
                                mcp_used = True
                            yield adapted_chunk
                    finally:
                        self._active_tool_result_store = None

                    if new_tool_results:
                        tool_results.update(new_tool_results)

                    executed_calls = next_custom_calls + next_mcp_calls

                    if executed_calls:
                        # Separate calls that came from structured output (no thought_signature)
                        # from real function calls (have thought_signature)
                        structured_output_calls = [c for c in executed_calls if c.get("_from_structured_output")]
                        real_function_calls = [c for c in executed_calls if not c.get("_from_structured_output")]

                        # For real function calls, use the standard function call/response format
                        if real_function_calls:
                            model_parts = []
                            for call in real_function_calls:
                                args_payload: Any = call.get("arguments", {})
                                if isinstance(args_payload, str):
                                    try:
                                        args_payload = json.loads(args_payload)
                                    except json.JSONDecodeError:
                                        args_payload = {}
                                if not isinstance(args_payload, dict):
                                    args_payload = {}
                                part = types.Part.from_function_call(
                                    name=call.get("name", ""),
                                    args=args_payload,
                                )
                                # Preserve thought_signature if present (required for Gemini 3.x models)
                                if "thought_signature" in call:
                                    part.thought_signature = call["thought_signature"]
                                model_parts.append(part)
                            if model_parts:
                                conversation_history.append(types.Content(parts=model_parts, role="model"))

                            response_parts = []
                            for call in real_function_calls:
                                call_id = call.get("call_id")
                                result_data = new_tool_results.get(call_id or "", "No result")

                                # Plain text result
                                result_text = result_data if isinstance(result_data, str) else str(result_data)
                                response_parts.append(
                                    types.Part.from_function_response(
                                        name=call.get("name", ""),
                                        response={"result": result_text},
                                    ),
                                )
                            if response_parts:
                                conversation_history.append(types.Content(parts=response_parts, role="user"))

                        # For structured output calls (like ask_others from JSON), inject results as text
                        # These don't have thought_signature and can't use function call/response format
                        if structured_output_calls:
                            text_results = []
                            for call in structured_output_calls:
                                call_id = call.get("call_id")
                                tool_name = call.get("name", "unknown")
                                result_data = new_tool_results.get(call_id or "", "No result")
                                # Extract text from result
                                if isinstance(result_data, dict) and "text" in result_data:
                                    result_text = result_data["text"]
                                else:
                                    result_text = result_data if isinstance(result_data, str) else str(result_data)
                                text_results.append(f"[Tool Result: {tool_name}]\n{result_text}")

                            model_text = "I executed the following tool(s) and received these results:\n\n" + "\n\n".join(text_results)
                            conversation_history.append(types.Content(parts=[types.Part(text=model_text)], role="model"))

                            # Add user message prompting continuation
                            user_parts = [
                                types.Part(
                                    text="Based on the tool results above, please continue with your response. "
                                    "Remember to use the appropriate coordination action (vote/stop, new_answer, or ask_others) when ready.",
                                ),
                            ]
                            conversation_history.append(
                                types.Content(parts=user_parts, role="user"),
                            )

            # ====================================================================
            # Completion Phase: Process structured tool calls and builtin indicators
            # ====================================================================
            final_response = last_response_with_candidates

            tool_calls_detected: list[dict[str, Any]] = []

            if (is_coordination or is_post_evaluation) and full_content_text.strip():
                content = full_content_text
                structured_response = None

                try:
                    structured_response = json.loads(content.strip())
                except json.JSONDecodeError:
                    structured_response = self.formatter.extract_structured_response(content)

                if structured_response and isinstance(structured_response, dict) and structured_response.get("action_type"):
                    raw_tool_calls = self.formatter.convert_structured_to_tool_calls(structured_response)

                    if raw_tool_calls:
                        tool_type = "post_evaluation" if is_post_evaluation else "coordination"
                        workflow_tool_calls: list[dict[str, Any]] = []

                        for call in raw_tool_calls:
                            tool_name = call.get("name", "")
                            tool_args_str = call.get("arguments", "{}")

                            if isinstance(tool_args_str, str):
                                try:
                                    tool_args = json.loads(tool_args_str)
                                except json.JSONDecodeError:
                                    tool_args = {}
                            else:
                                tool_args = tool_args_str

                            try:
                                log_tool_call(
                                    agent_id,
                                    tool_name or f"unknown_{tool_type}_tool",
                                    tool_args,
                                    result=f"{tool_type}_tool_called",
                                    backend_name="gemini",
                                )
                            except Exception:
                                pass

                            workflow_tool_calls.append(
                                {
                                    "id": call.get("call_id", f"call_{len(workflow_tool_calls)}"),
                                    "type": "function",
                                    "function": {
                                        "name": tool_name,
                                        "arguments": tool_args,
                                    },
                                },
                            )

                        if workflow_tool_calls:
                            tool_calls_detected = workflow_tool_calls
                            log_stream_chunk("backend.gemini", "tool_calls", workflow_tool_calls, agent_id)

            if tool_calls_detected:
                self._append_tool_call_to_buffer(tool_calls_detected)
                yield StreamChunk(type="tool_calls", tool_calls=tool_calls_detected, source="gemini")

                if mcp_used:
                    yield StreamChunk(
                        type="mcp_status",
                        status="mcp_session_complete",
                        content="✅ [MCP] Session completed",
                        source="mcp_tools",
                    )

                yield StreamChunk(type="done")
                return

            if builtin_tools and final_response and hasattr(final_response, "candidates") and final_response.candidates:
                candidate = final_response.candidates[0]

                if hasattr(candidate, "grounding_metadata") and candidate.grounding_metadata:
                    search_actually_used = False
                    search_queries: list[str] = []

                    if hasattr(candidate.grounding_metadata, "web_search_queries") and candidate.grounding_metadata.web_search_queries:
                        try:
                            for query in candidate.grounding_metadata.web_search_queries:
                                if query and isinstance(query, str) and query.strip():
                                    trimmed_query = query.strip()
                                    search_queries.append(trimmed_query)
                                    search_actually_used = True
                        except (TypeError, AttributeError):
                            pass

                    if hasattr(candidate.grounding_metadata, "grounding_chunks") and candidate.grounding_metadata.grounding_chunks:
                        try:
                            if len(candidate.grounding_metadata.grounding_chunks) > 0:
                                search_actually_used = True
                        except (TypeError, AttributeError):
                            pass

                    if search_actually_used:
                        log_stream_chunk(
                            "backend.gemini",
                            "web_search_result",
                            {"queries": search_queries, "results_integrated": True},
                            agent_id,
                        )
                        log_tool_call(
                            agent_id,
                            "google_search_retrieval",
                            {
                                "queries": search_queries,
                                "chunks_found": len(getattr(candidate.grounding_metadata, "grounding_chunks", []) or []),
                            },
                            result="search_completed",
                            backend_name="gemini",
                        )

                        yield StreamChunk(
                            type="content",
                            content="🔍 [Builtin Tool: Web Search] Results integrated\n",
                        )

                        for query in search_queries:
                            log_stream_chunk(
                                "backend.gemini",
                                "web_search_result",
                                {"queries": search_queries, "results_integrated": True},
                                agent_id,
                            )
                            yield StreamChunk(type="content", content=f"🔍 [Search Query] '{query}'\n")

                        self.search_count += 1

                enable_code_execution = bool(
                    all_params.get("enable_code_execution") or all_params.get("code_execution"),
                )

                if enable_code_execution and hasattr(candidate, "content") and hasattr(candidate.content, "parts"):
                    code_parts: list[str] = []

                    for part in candidate.content.parts:
                        if hasattr(part, "executable_code") and part.executable_code:
                            code_content = getattr(part.executable_code, "code", str(part.executable_code))
                            code_parts.append(f"Code: {code_content}")
                        elif hasattr(part, "code_execution_result") and part.code_execution_result:
                            result_content = getattr(part.code_execution_result, "output", str(part.code_execution_result))
                            code_parts.append(f"Result: {result_content}")

                    if code_parts:
                        log_stream_chunk(
                            "backend.gemini",
                            "code_execution",
                            "Code executed",
                            agent_id,
                        )
                        log_tool_call(
                            agent_id,
                            "code_execution",
                            {"details": code_parts},
                            result="code_execution_completed",
                            backend_name="gemini",
                        )

                        yield StreamChunk(
                            type="content",
                            content="🧮 [Builtin Tool: Code Execution] Results integrated\n",
                        )

                        for entry in code_parts:
                            yield StreamChunk(type="content", content=f"🧮 {entry}\n")

                        self.code_execution_count += 1

            elif final_response and hasattr(final_response, "candidates") and final_response.candidates:
                for candidate in final_response.candidates:
                    if hasattr(candidate, "grounding_metadata"):
                        self.search_count += 1
                        logger.debug(f"[Gemini] Grounding (web search) used, count: {self.search_count}")

                    if hasattr(candidate, "content") and candidate.content:
                        if hasattr(candidate.content, "parts") and candidate.content.parts:
                            for part in candidate.content.parts:
                                if hasattr(part, "executable_code") or hasattr(part, "code_execution_result"):
                                    self.code_execution_count += 1
                                    logger.debug(f"[Gemini] Code execution used, count: {self.code_execution_count}")
                                    break

            # Emit completion status
            if mcp_used:
                yield StreamChunk(
                    type="mcp_status",
                    status="mcp_session_complete",
                    content="✅ [MCP] Session completed",
                    source="mcp_tools",
                )

            yield StreamChunk(type="done")

        except Exception as e:
            # Check if this is a context length error that we can recover from via compression
            from ._context_errors import is_context_length_error

            # Use the flag extracted at the start of stream_with_tools (before kwargs was modified)
            _compression_retry = getattr(self, "_compression_retry_flag", False)

            if is_context_length_error(e) and not _compression_retry:
                logger.warning(
                    "[Gemini] Context length exceeded, attempting compression recovery...",
                )

                # Notify user that compression is starting
                yield StreamChunk(
                    type="compression_status",
                    status="compressing",
                    content=f"\n📦 [Compression] Context limit exceeded - summarizing {len(messages)} messages...",
                    source=agent_id,
                )

                # Compress messages using the inherited method
                compressed_messages = await self._compress_messages_for_context_recovery(
                    messages,
                    buffer_content=None,
                )

                # Notify user that compression succeeded
                yield StreamChunk(
                    type="compression_status",
                    status="compression_complete",
                    content=f"✅ [Compression] Recovered with {len(compressed_messages)} messages - continuing...",
                    source=agent_id,
                )

                # Retry with compressed messages (with flag to prevent infinite loops)
                retry_kwargs = {**kwargs, "_compression_retry": True}
                async for chunk in self.stream_with_tools(compressed_messages, tools, **retry_kwargs):
                    yield chunk

                logger.info("[Gemini] Compression recovery successful")
            else:
                logger.error(f"[Gemini] Error in stream_with_tools: {e}")
                raise

        finally:
            # Save streaming buffer before cleanup
            self._finalize_streaming_buffer(agent_id=agent_id)
            await self._cleanup_genai_resources(stream, client)

    async def _try_close_resource(
        self,
        resource: Any,
        method_names: tuple,
        resource_label: str,
    ) -> bool:
        """Try to close a resource using one of the provided method names.

        Args:
            resource: Object to close
            method_names: Method names to try (e.g., ("aclose", "close"))
            resource_label: Label for error logging

        Returns:
            True if closed successfully, False otherwise
        """
        if resource is None:
            return False

        for method_name in method_names:
            close_method = getattr(resource, method_name, None)
            if close_method is not None:
                try:
                    result = close_method()
                    if hasattr(result, "__await__"):
                        await result
                    return True
                except Exception as e:
                    log_backend_activity(
                        "gemini",
                        f"{resource_label} cleanup failed",
                        {"error": str(e), "method": method_name},
                        agent_id=self.agent_id,
                    )
                    return False
        return False

    async def _cleanup_genai_resources(self, stream, client) -> None:
        """Cleanup google-genai resources to avoid unclosed aiohttp sessions.

        Cleanup order is critical: stream → session → transport → client.
        Each resource is cleaned independently with error isolation.
        """
        # 1. Close stream
        await self._try_close_resource(stream, ("aclose", "close"), "Stream")

        # 2. Close internal aiohttp session (requires special handling)
        if client is not None:
            base_client = getattr(client, "_api_client", None)
            if base_client is not None:
                session = getattr(base_client, "_aiohttp_session", None)
                if session is not None and not getattr(session, "closed", True):
                    try:
                        await session.close()
                        log_backend_activity(
                            "gemini",
                            "Closed google-genai aiohttp session",
                            {},
                            agent_id=self.agent_id,
                        )
                        base_client._aiohttp_session = None
                        # Yield control to allow connector cleanup
                        await asyncio.sleep(0)
                    except Exception as e:
                        log_backend_activity(
                            "gemini",
                            "Failed to close google-genai aiohttp session",
                            {"error": str(e)},
                            agent_id=self.agent_id,
                        )

        # 3. Close internal async transport
        if client is not None:
            aio_obj = getattr(client, "aio", None)
            await self._try_close_resource(aio_obj, ("close", "stop"), "Client AIO")

        # 4. Close client
        await self._try_close_resource(client, ("aclose", "close"), "Client")

    def _append_tool_result_message(
        self,
        updated_messages: list[dict[str, Any]],
        call: dict[str, Any],
        result: Any,
        tool_type: str,
    ) -> None:
        """Append tool result to messages in Gemini conversation format.

        Gemini uses a different message format than OpenAI/Response API.
        We need to append messages in a format that Gemini SDK can understand
        when making recursive calls.

        Args:
            updated_messages: Message list to append to
            call: Tool call dictionary with call_id, name, arguments
            result: Tool execution result
            tool_type: "custom" or "mcp"

        """
        # Extract text from result - handle MCP CallToolResult objects properly
        if hasattr(result, "content") and not isinstance(result, (dict, str)):
            # MCP CallToolResult - extract text from content list
            extracted = self._extract_text_from_content(result.content)
            result_text = extracted if extracted is not None else str(result)
        else:
            result_text = getattr(result, "text", None) or str(result)

        tool_result_msg = {
            "role": "tool",
            "name": call.get("name", ""),
            "content": result_text,
        }
        updated_messages.append(tool_result_msg)

        tool_results_store = getattr(self, "_active_tool_result_store", None)
        call_id = call.get("call_id")
        if isinstance(tool_results_store, dict) and call_id:
            tool_results_store[call_id] = result_text

        # Track in streaming buffer for compression recovery
        tool_name = call.get("name", "unknown")
        self._append_tool_to_buffer(tool_name, result_text)

    def _append_tool_error_message(
        self,
        updated_messages: list[dict[str, Any]],
        call: dict[str, Any],
        error_msg: str,
        tool_type: str,
    ) -> None:
        """Append tool error to messages in Gemini conversation format.

        Args:
            updated_messages: Message list to append to
            call: Tool call dictionary with call_id, name, arguments
            error_msg: Error message string
            tool_type: "custom" or "mcp"
        """
        # Append error as function result
        error_result_msg = {
            "role": "tool",
            "name": call.get("name", ""),
            "content": f"Error: {error_msg}",
        }
        updated_messages.append(error_result_msg)

        tool_results_store = getattr(self, "_active_tool_result_store", None)
        call_id = call.get("call_id")
        if isinstance(tool_results_store, dict) and call_id:
            tool_results_store[call_id] = f"Error: {error_msg}"

        # Track in streaming buffer for compression recovery
        tool_name = call.get("name", "unknown")
        self._append_tool_to_buffer(tool_name, error_msg, is_error=True)

    async def _execute_custom_tool(self, call: dict[str, Any]) -> AsyncGenerator[CustomToolChunk, None]:
        """Execute custom tool with streaming support - async generator for base class.

        This method is called by _execute_tool_with_logging and yields CustomToolChunk
        objects for intermediate streaming output. The base class detects the async
        generator and streams intermediate results to users in real-time.

        Args:
            call: Tool call dictionary with name and arguments

        Yields:
            CustomToolChunk objects with streaming data

        Note:
            - Intermediate chunks (completed=False) are streamed to users in real-time
            - Final chunk (completed=True) contains the accumulated result for message history
            - The base class automatically handles extracting and displaying intermediate chunks
        """
        async for chunk in self.stream_custom_tool_execution(call):
            yield chunk

    def get_provider_name(self) -> str:
        """Get the provider name."""
        return "Gemini"

    def get_filesystem_support(self) -> FilesystemSupport:
        """Gemini supports filesystem through MCP servers."""
        return FilesystemSupport.MCP

    def get_supported_builtin_tools(self) -> list[str]:
        """Get list of builtin tools supported by Gemini."""
        return ["google_search_retrieval", "code_execution"]

    def reset_tool_usage(self):
        """Reset tool usage tracking."""
        self.search_count = 0
        self.code_execution_count = 0
        # Reset backoff telemetry
        self.backoff_retry_count = 0
        self.backoff_total_delay = 0.0
        # Reset MCP monitoring metrics when available
        for attr in (
            "_mcp_tool_calls_count",
            "_mcp_tool_failures",
            "_mcp_tool_successes",
            "_mcp_connection_retries",
        ):
            if hasattr(self, attr):
                setattr(self, attr, 0)
        super().reset_token_usage()

    async def cleanup_mcp(self):
        """Cleanup MCP connections - override parent class to use Gemini-specific cleanup."""
        if MCPResourceManager:
            try:
                await super().cleanup_mcp()
                return
            except Exception as error:
                log_backend_activity(
                    "gemini",
                    "MCP cleanup via resource manager failed",
                    {"error": str(error)},
                    agent_id=self.agent_id,
                )
                # Fall back to manual cleanup below

        if not self._mcp_client:
            return

        try:
            await self._mcp_client.disconnect()
            log_backend_activity("gemini", "MCP client disconnected", {}, agent_id=self.agent_id)
        except (
            MCPConnectionError,
            MCPTimeoutError,
            MCPServerError,
            MCPError,
            Exception,
        ) as e:
            if MCPErrorHandler:
                MCPErrorHandler.get_error_details(e, "disconnect", log=True)
            else:
                logger.exception("[Gemini] MCP disconnect error during cleanup")
        finally:
            self._mcp_client = None
            self._mcp_initialized = False
            if hasattr(self, "_mcp_functions"):
                self._mcp_functions.clear()
            if hasattr(self, "_mcp_function_names"):
                self._mcp_function_names.clear()

    async def __aenter__(self) -> "GeminiBackend":
        """Async context manager entry."""
        # Call parent class __aenter__ which handles MCP setup
        await super().__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Async context manager exit with automatic resource cleanup."""
        # Parameters are required by context manager protocol but not used
        _ = (exc_type, exc_val, exc_tb)
        try:
            await super().__aexit__(exc_type, exc_val, exc_tb)
        finally:
            if not MCPResourceManager:
                try:
                    await self.cleanup_mcp()
                except Exception as e:
                    log_backend_activity(
                        "gemini",
                        "Backend cleanup error",
                        {"error": str(e)},
                        agent_id=self.agent_id,
                    )
