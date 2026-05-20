"""
Single source of truth for backend capabilities.
All documentation and UI should pull from this registry.

This module defines what each backend supports in terms of:
- Built-in tools (web search, code execution, etc.)
- Filesystem support (none, native, or via MCP)
- Model Context Protocol (MCP) support
- Multimodal capabilities (vision, image generation)
- Available models

Usage:
    from massgen.backend.capabilities import BACKEND_CAPABILITIES, get_capabilities

    # Get capabilities for a backend
    caps = get_capabilities("openai")
    if "web_search" in caps.builtin_tools:
        print("Backend supports web search")

IMPORTANT - Maintaining This Registry:
===========================================

When adding a NEW BACKEND:
1. Add a new entry to BACKEND_CAPABILITIES with all fields filled
2. Ensure the backend_type matches the backend's type string
3. Run tests: `uv run pytest massgen/tests/test_backend_capabilities.py`
4. Regenerate docs: `uv run python docs/scripts/generate_backend_tables.py`
5. Commit both the capabilities.py and generated docs

When adding a NEW FEATURE to an existing backend:
1. Update the backend's entry in BACKEND_CAPABILITIES
2. Add to supported_capabilities or builtin_tools as appropriate
3. Run tests: `uv run pytest massgen/tests/test_backend_capabilities.py`
4. Regenerate docs: `uv run python docs/scripts/generate_backend_tables.py`
5. Update the backend implementation to actually support the feature
6. Verify capability validation works: `validate_backend_config(backend_type, config)`

Why This Matters:
- Config wizard reads from here to show available features
- Documentation is auto-generated from here
- Backend validation uses this to prevent invalid configurations
- If this is out of sync with actual backends, users will experience errors

Testing:
Run the capabilities test suite to verify consistency:
    uv run pytest massgen/tests/test_backend_capabilities.py -v

This will verify:
- All backends in BACKEND_CAPABILITIES have valid configurations
- Required fields are present
- Model lists are not empty
- Default models exist in model lists
"""

from dataclasses import dataclass
from enum import Enum


class Capability(Enum):
    """Enumeration of all possible backend capabilities."""

    WEB_SEARCH = "web_search"
    X_SEARCH = "x_search"
    CODE_EXECUTION = "code_execution"
    BASH = "bash"
    MULTIMODAL = "multimodal"  # Legacy - being phased out
    VISION = "vision"  # Legacy - use image_understanding
    MCP = "mcp"
    FILESYSTEM_NATIVE = "filesystem_native"
    FILESYSTEM_MCP = "filesystem_mcp"
    REASONING = "reasoning"
    IMAGE_GENERATION = "image_generation"
    IMAGE_UNDERSTANDING = "image_understanding"
    AUDIO_GENERATION = "audio_generation"
    AUDIO_UNDERSTANDING = "audio_understanding"
    VIDEO_GENERATION = "video_generation"
    VIDEO_UNDERSTANDING = "video_understanding"


@dataclass
class BackendCapabilities:
    """Capabilities for a specific backend."""

    backend_type: str
    provider_name: str
    supported_capabilities: set[str]  # Set of capability strings (e.g., "web_search")
    builtin_tools: list[str]  # Tools native to the backend
    filesystem_support: str  # "none", "native", or "mcp"
    models: list[str]  # Available models
    default_model: str  # Default model for this backend
    env_var: str | None = None  # Required environment variable (e.g., "OPENAI_API_KEY")
    notes: str = ""  # Additional notes about the backend
    model_release_dates: dict[str, str] | None = None  # Model -> "YYYY-MM" release date mapping
    base_url: str | None = None  # API base URL for OpenAI-compatible providers


# THE REGISTRY - Single source of truth for all backend capabilities
BACKEND_CAPABILITIES: dict[str, BackendCapabilities] = {
    "openai": BackendCapabilities(
        backend_type="openai",
        provider_name="OpenAI",
        supported_capabilities={
            "web_search",
            "code_execution",
            "mcp",
            "reasoning",
            "image_generation",
            "image_understanding",
            "audio_generation",
            "audio_understanding",
            "video_generation",
        },
        builtin_tools=["web_search", "code_interpreter"],
        filesystem_support="mcp",
        models=[
            "gpt-5.4",
            "gpt-5.2",
            "gpt-5.1-codex-max",
            "gpt-5.1-codex",
            "gpt-5.1-codex-mini",
            "gpt-5.1",
            "gpt-5-codex",
            "gpt-5",
            "gpt-5-mini",
            "gpt-5-nano",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4.1-nano",
            "gpt-4o",
            "gpt-4o-mini",
            "o4-mini",
        ],
        default_model="gpt-5.4",
        env_var="OPENAI_API_KEY",
        notes=(
            "GPT-5.4 is the recommended default. Codex models (gpt-5.1-codex, gpt-5-codex) are optimized "
            "for shorter system messages and may not work well with MassGen's coordination prompts. "
            "Reasoning support in GPT-5 and o-series models. Audio/video generation (v0.0.30+)."
        ),
        model_release_dates={
            "gpt-5.4": "2026-03",
            "gpt-5.2": "2025-12",
            "gpt-5.1-codex-max": "2025-12",
            "gpt-5.1-codex": "2025-12",
            "gpt-5.1-codex-mini": "2025-12",
            "gpt-5.1": "2025-11",
            "gpt-5-codex": "2025-09",
            "gpt-5": "2025-08",
            "gpt-5-mini": "2025-08",
            "gpt-5-nano": "2025-08",
            "gpt-4.1": "2025-04",
            "gpt-4.1-mini": "2025-04",
            "gpt-4.1-nano": "2025-04",
            "gpt-4o": "2024-05",
            "gpt-4o-mini": "2024-07",
            "o4-mini": "2025-04",
        },
    ),
    "claude": BackendCapabilities(
        backend_type="claude",
        provider_name="Claude",
        supported_capabilities={
            "web_search",
            "code_execution",
            "mcp",
            "tool_search",
            "programmatic_tool_calling",
            "image_understanding",
            "audio_understanding",
            "video_understanding",
        },
        builtin_tools=["web_search", "code_execution"],
        filesystem_support="mcp",
        models=[
            # Alias notation (recommended for experimentation)
            "claude-opus-4-6",
            "claude-opus-4-5",
            "claude-sonnet-4-5",
            "claude-haiku-4-5",
            "claude-opus-4",
            "claude-sonnet-4",
            # Date notation (recommended for production - specific snapshot)
            "claude-opus-4-5-20251101",
            "claude-haiku-4-5-20251001",
            "claude-sonnet-4-5-20250929",
            "claude-opus-4-1-20250805",
            "claude-sonnet-4-20250514",
        ],
        default_model="claude-opus-4-6",
        env_var="ANTHROPIC_API_KEY",
        notes=(
            "Web search and code execution are built-in tools. "
            "Programmatic tool calling and tool search require 4.5 models. "
            "Audio/video understanding support (v0.0.30+). "
            "Model IDs: use alias notation (claude-sonnet-4-5) for experimentation, "
            "date notation (claude-sonnet-4-5-20250929) for production."
        ),
        model_release_dates={
            "claude-opus-4-6": "2026-02",
            "claude-haiku-4-5": "2025-10",
            "claude-haiku-4-5-20251001": "2025-10",
            "claude-sonnet-4-5": "2025-09",
            "claude-sonnet-4-5-20250929": "2025-09",
            "claude-opus-4-5": "2025-11",
            "claude-opus-4-5-20251101": "2025-11",
            "claude-opus-4": "2025-08",
            "claude-opus-4-1-20250805": "2025-08",
            "claude-sonnet-4": "2025-05",
            "claude-sonnet-4-20250514": "2025-05",
        },
    ),
    "claude_code": BackendCapabilities(
        backend_type="claude_code",
        provider_name="Claude Code",
        supported_capabilities={
            "bash",
            "mcp",
            "filesystem_native",
            "image_understanding",
            "web_search",  # WebSearch/WebFetch tools (enabled via enable_web_search config)
            "reasoning",
        },
        builtin_tools=[
            "Read",
            "Write",
            "Edit",
            "MultiEdit",
            "Bash",
            "Grep",
            "Glob",
            "LS",
            "WebSearch",
            "WebFetch",
            "Task",
            "TodoWrite",
            "NotebookEdit",
            "NotebookRead",
        ],
        filesystem_support="native",
        models=[
            # Alias notation (recommended for experimentation)
            "claude-opus-4-6",
            "claude-sonnet-4-6",
            "claude-sonnet-4-5",
            "claude-opus-4-5",
            "claude-opus-4",
            "claude-sonnet-4",
            # Date notation (recommended for production - specific snapshot)
            "claude-sonnet-4-5-20250929",
            "claude-opus-4-5-20251101",
            "claude-opus-4-1-20250805",
            "claude-sonnet-4-20250514",
        ],
        default_model="claude-opus-4-6",
        env_var="ANTHROPIC_API_KEY",
        notes=(
            "⚠️ Works with local Claude Code CLI login (`claude login`), CLAUDE_CODE_API_KEY, or ANTHROPIC_API_KEY. "
            "Native filesystem access via SDK. Extensive built-in tooling for code operations. "
            "Image understanding support. Reasoning effort controls are available for Claude 4.6 quickstart models."
        ),
    ),
    "codex": BackendCapabilities(
        backend_type="codex",
        provider_name="Codex",
        supported_capabilities={
            "bash",
            "mcp",
            "filesystem_native",
            "web_search",
            "image_understanding",
            "reasoning",
        },
        builtin_tools=[
            "shell",
            "file_read",
            "file_write",
            "file_edit",
            "web_search",
        ],
        filesystem_support="native",
        models=[
            "gpt-5.4",
            "gpt-5.3-codex",
            "gpt-5.2-codex",
            "gpt-5.1-codex",
            "gpt-5-codex",
            "gpt-4.1",
        ],
        default_model="gpt-5.4",
        env_var="OPENAI_API_KEY",
        notes=(
            "OpenAI Codex CLI with OAuth support. Run `codex login` and complete the browser "
            "OAuth flow with your ChatGPT Plus/Pro account, or use OPENAI_API_KEY as a fallback. "
            "Native filesystem access via CLI. "
            "GPT-5 quickstart models support reasoning effort controls. "
            "Requires: npm install -g @openai/codex. "
            "SANDBOX LIMITATION: OS-level sandbox (Seatbelt/Landlock) only restricts writes, "
            "NOT reads. For security-sensitive workloads, prefer Docker mode for full isolation."
        ),
        model_release_dates={
            "gpt-5.4": "2026-03",
            "gpt-5.3-codex": "2026-02",
            "gpt-5.2-codex": "2025-12",
            "gpt-5.1-codex": "2025-12",
            "gpt-5-codex": "2025-09",
            "gpt-4.1": "2025-04",
        },
    ),
    "gemini": BackendCapabilities(
        backend_type="gemini",
        provider_name="Gemini",
        supported_capabilities={
            "web_search",
            "code_execution",
            "mcp",
            "image_understanding",
            "image_generation",
            "video_generation",
        },
        builtin_tools=["google_search_retrieval", "code_execution"],
        filesystem_support="mcp",
        models=[
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
            "gemini-3-pro-preview",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ],
        default_model="gemini-3-flash-preview",
        env_var="GEMINI_API_KEY",
        notes="Google Search Retrieval provides web search. Image understanding. Image generation via Imagen 3. Video generation via Veo 2.",
        model_release_dates={
            "gemini-3.1-pro-preview": "2026-02",
            "gemini-3-flash-preview": "2025-12",
            "gemini-3-pro-preview": "2025-11",
            "gemini-2.5-flash": "2025-06",
            "gemini-2.5-pro": "2025-06",
        },
    ),
    "antigravity_cli": BackendCapabilities(
        backend_type="antigravity_cli",
        provider_name="Antigravity CLI",
        supported_capabilities={
            "bash",
            "mcp",
            "filesystem_native",
            "web_search",
        },
        builtin_tools=[
            "shell",
            "filesystem",
            "web_search",
            "subagents",
            "plugins",
        ],
        filesystem_support="native",
        models=[
            "gemini-3.5-flash",
            "gemini-3-flash-preview",
            "gemini-3.1-pro-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ],
        default_model="gemini-3.5-flash",
        env_var="GEMINI_API_KEY",
        model_release_dates={
            "gemini-3.5-flash": "2026-05",
            "gemini-3-flash-preview": "2025-12",
            "gemini-3.1-pro-preview": "2026-02",
            "gemini-2.5-pro": "2025-06",
            "gemini-2.5-flash": "2025-06",
        },
        notes=(
            "Google Antigravity CLI (`agy`) — successor to Gemini CLI for consumer "
            "tiers as of 2026-06-18. agy 1.0.0 selects the model server-side per "
            "tier (default: Gemini 3.5 Flash); the configured `model` value is "
            "informational only. Auth: existing Google OAuth (~/.gemini/google_accounts.json) "
            "or GEMINI_API_KEY/GOOGLE_API_KEY env vars. Install: "
            "curl -fsSL https://antigravity.google/cli/install.sh | bash. "
            "MCP servers are merged into ~/.gemini/config/mcp_config.json at "
            "session start and restored on cleanup (uses `serverUrl` for HTTP)."
        ),
    ),
    "gemini_cli": BackendCapabilities(
        backend_type="gemini_cli",
        provider_name="Gemini CLI",
        supported_capabilities={
            "bash",
            "mcp",
            "filesystem_native",
            "web_search",
        },
        builtin_tools=[
            "run_shell_command",
            "read_file",
            "write_file",
            "replace",
            "glob",
            "grep_search",
            "list_directory",
            "read_many_files",
            "google_web_search",
            "web_fetch",
        ],
        filesystem_support="native",
        models=[
            "gemini-3.1-pro-preview",
            "gemini-3-flash-preview",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ],
        default_model="gemini-3.1-pro-preview",
        env_var="GOOGLE_API_KEY",
        model_release_dates={
            "gemini-3.1-pro-preview": "2026-02",
            "gemini-3-flash-preview": "2025-12",
            "gemini-2.5-pro": "2025-06",
            "gemini-2.5-flash": "2025-06",
            "gemini-2.5-flash-lite": "2025-06",
        },
        notes=(
            "Google Gemini CLI subprocess wrapper. Auth: CLI login (gemini) first, "
            "then GOOGLE_API_KEY or GEMINI_API_KEY. Native filesystem via CLI. "
            "Requires: npm install -g @google/gemini-cli. "
            "Docker mode requires command_line_docker_network_mode."
        ),
    ),
    "grok": BackendCapabilities(
        backend_type="grok",
        provider_name="Grok",
        supported_capabilities={
            "web_search",
            "x_search",
            "code_execution",
            "mcp",
            "image_understanding",
        },
        builtin_tools=["web_search", "x_search", "code_execution"],
        filesystem_support="mcp",
        models=[
            "grok-4.20-0309-reasoning",
            "grok-4-1-fast-reasoning",
            "grok-4-1-fast-non-reasoning",
            "grok-code-fast-1",
            "grok-4",
            "grok-4-fast",
            "grok-3",
            "grok-3-mini",
        ],
        default_model="grok-4.20-0309-reasoning",
        env_var="XAI_API_KEY",
        notes=("Uses xAI's Responses API tooling surface. " "Supports web_search, x_search, and code execution. " "Legacy Chat Completions search_parameters are not supported."),
        model_release_dates={
            "grok-4.20-0309-reasoning": "2026-03",
            "grok-4-1-fast-reasoning": "2025-11",
            "grok-4-1-fast-non-reasoning": "2025-11",
            "grok-code-fast-1": "2025-08",
            "grok-4": "2025-07",
            "grok-4-fast": "2025-09",
            "grok-3": "2025-02",
            "grok-3-mini": "2025-05",
        },
        base_url="https://api.x.ai/v1",
    ),
    "azure_openai": BackendCapabilities(
        backend_type="azure_openai",
        provider_name="Azure OpenAI",
        supported_capabilities={
            "web_search",
            "code_execution",
            "mcp",
            "image_generation",
            "image_understanding",
        },
        builtin_tools=["web_search", "code_execution"],
        filesystem_support="mcp",
        models=["gpt-4", "gpt-4o", "gpt-35-turbo"],
        default_model="gpt-4o",
        env_var="AZURE_OPENAI_API_KEY",
        notes="Capabilities depend on Azure deployment configuration. Image understanding and generation via gpt-4o.",
    ),
    "chatcompletion": BackendCapabilities(
        backend_type="chatcompletion",
        provider_name="Chat Completions (Generic)",
        supported_capabilities={
            "mcp",
            "audio_understanding",
            "video_understanding",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["custom"],
        default_model="custom",
        env_var=None,
        notes="Generic OpenAI-compatible API. Audio/video understanding via providers like OpenRouter, Qwen (v0.0.30+). Capabilities vary by provider.",
    ),
    "lmstudio": BackendCapabilities(
        backend_type="lmstudio",
        provider_name="LM Studio",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["custom"],
        default_model="custom",
        env_var=None,
        notes="Local model hosting. Capabilities depend on loaded model.",
    ),
    "zai": BackendCapabilities(
        backend_type="zai",
        provider_name="ZAI (Z.AI)",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["glm-4.5", "custom"],
        default_model="glm-4.5",
        env_var="ZAI_API_KEY",
        notes="OpenAI-compatible API from Z.AI. Supports GLM models.",
    ),
    "vllm": BackendCapabilities(
        backend_type="vllm",
        provider_name="vLLM",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["custom"],
        default_model="custom",
        env_var=None,
        notes="vLLM inference server. Local model hosting with high throughput.",
    ),
    "sglang": BackendCapabilities(
        backend_type="sglang",
        provider_name="SGLang",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["custom"],
        default_model="custom",
        env_var=None,
        notes="SGLang inference server. Fast local model serving.",
    ),
    "inference": BackendCapabilities(
        backend_type="inference",
        provider_name="Inference (vLLM/SGLang)",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["custom"],
        default_model="custom",
        env_var=None,
        notes="Unified backend for vLLM, SGLang, and custom inference servers.",
    ),
    "ag2": BackendCapabilities(
        backend_type="ag2",
        provider_name="AG2 (AutoGen)",
        supported_capabilities={
            "code_execution",
        },
        builtin_tools=[],
        filesystem_support="none",  # MCP support planned for future
        models=["custom"],  # AG2 uses any OpenAI-compatible backend
        default_model="custom",
        env_var=None,  # Depends on underlying LLM backend
        notes="AutoGen framework integration. Supports code execution with multiple executor types (Local, Docker, Jupyter). Uses any OpenAI-compatible LLM backend. MCP support planned.",
    ),
    # Individual ChatCompletion Provider Backends
    "cerebras": BackendCapabilities(
        backend_type="cerebras",
        provider_name="Cerebras AI",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["llama-3.3-70b", "llama-3.1-70b", "llama-3.1-8b"],
        default_model="llama-3.3-70b",
        env_var="CEREBRAS_API_KEY",
        notes="OpenAI-compatible API. Ultra-fast inference with Cerebras WSE hardware.",
        base_url="https://api.cerebras.ai/v1",
    ),
    "together": BackendCapabilities(
        backend_type="together",
        provider_name="Together AI",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=[
            "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8",
            "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
            "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
            "mistralai/Mixtral-8x7B-Instruct-v0.1",
        ],
        default_model="Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8",
        env_var="TOGETHER_API_KEY",
        notes="OpenAI-compatible API. Access to open-source models at scale.",
        base_url="https://api.together.xyz/v1",
    ),
    "fireworks": BackendCapabilities(
        backend_type="fireworks",
        provider_name="Fireworks AI",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=[
            "accounts/fireworks/models/llama-v3p3-70b-instruct",
            "accounts/fireworks/models/llama-v3p1-405b-instruct",
            "accounts/fireworks/models/qwen2p5-72b-instruct",
        ],
        default_model="accounts/fireworks/models/llama-v3p3-70b-instruct",
        env_var="FIREWORKS_API_KEY",
        notes="OpenAI-compatible API. Fast inference for production workloads.",
        base_url="https://api.fireworks.ai/inference/v1",
    ),
    "groq": BackendCapabilities(
        backend_type="groq",
        provider_name="Groq",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=[
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "mixtral-8x7b-32768",
        ],
        default_model="llama-3.3-70b-versatile",
        env_var="GROQ_API_KEY",
        notes="OpenAI-compatible API. Ultra-fast inference with LPU hardware.",
        base_url="https://api.groq.com/openai/v1",
    ),
    "openrouter": BackendCapabilities(
        backend_type="openrouter",
        provider_name="OpenRouter",
        supported_capabilities={
            "web_search",  # Via plugins array (enable_web_search: true)
            "mcp",
            "audio_understanding",
            "video_understanding",
            "image_generation",
        },
        builtin_tools=[],  # OpenRouter is a routing service, tools depend on underlying models
        filesystem_support="mcp",
        models=["custom"],  # User-specified OpenRouter model ID
        default_model="custom",
        env_var="OPENROUTER_API_KEY",
        notes="OpenAI-compatible API. Unified access to 300+ AI models. Web search via plugins array. Tool support depends on underlying model capabilities.",
        base_url="https://openrouter.ai/api/v1",
    ),
    "moonshot": BackendCapabilities(
        backend_type="moonshot",
        provider_name="Kimi (Moonshot AI)",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"],
        default_model="moonshot-v1-128k",
        env_var="MOONSHOT_API_KEY",
        notes="OpenAI-compatible API. Chinese language optimized models with long context windows.",
        base_url="https://api.moonshot.cn/v1",
    ),
    "nvidia_nim": BackendCapabilities(
        backend_type="nvidia_nim",
        provider_name="Nvidia NIM",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["moonshotai/kimi-k2.5", "custom"],
        default_model="moonshotai/kimi-k2.5",
        env_var="NGC_API_KEY",
        notes="OpenAI-compatible API. Nvidia NIM inference microservices. Access to models like Kimi K2.5, DeepSeek, Llama, and Nemotron via Nvidia's cloud.",
        base_url="https://integrate.api.nvidia.com/v1",
    ),
    "nebius": BackendCapabilities(
        backend_type="nebius",
        provider_name="Nebius AI Studio",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["Qwen/Qwen3-4B-fast", "custom"],
        default_model="Qwen/Qwen3-4B-fast",
        env_var="NEBIUS_API_KEY",
        notes="OpenAI-compatible API. Nebius AI Studio cloud platform.",
        base_url="https://api.studio.nebius.ai/v1",
    ),
    "poe": BackendCapabilities(
        backend_type="poe",
        provider_name="POE",
        supported_capabilities={
            "mcp",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["custom"],
        default_model="custom",
        env_var="POE_API_KEY",
        notes="OpenAI-compatible API via POE platform. Access to various AI models through POE's ecosystem.",
    ),
    "qwen": BackendCapabilities(
        backend_type="qwen",
        provider_name="Qwen (Alibaba Cloud)",
        supported_capabilities={
            "mcp",
            "audio_understanding",
            "video_understanding",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=["qwen-max", "qwen-plus", "qwen-turbo", "qwen3-vl-30b-a3b-thinking", "qwen3-vl-235b-a22b-thinking"],
        default_model="qwen-max",
        env_var="QWEN_API_KEY",
        notes="OpenAI-compatible API. Qwen models from Alibaba Cloud. Audio/video understanding support (v0.0.30+). Computer use support with qwen3-vl-235b-a22b-thinking.",
        base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    ),
    "uitars": BackendCapabilities(
        backend_type="uitars",
        provider_name="UI-TARS (ByteDance)",
        supported_capabilities={
            "image_understanding",
        },
        builtin_tools=[],
        filesystem_support="none",
        models=["ui-tars-1.5"],
        default_model="ui-tars-1.5",
        env_var="UI_TARS_API_KEY",
        notes="OpenAI-compatible API via HuggingFace Inference Endpoints. UI-TARS-1.5-7B model for GUI automation with vision and reasoning. Requires UI_TARS_ENDPOINT environment variable.",
    ),
    "copilot": BackendCapabilities(
        backend_type="copilot",
        provider_name="GitHub Copilot",
        supported_capabilities={
            "mcp",
            "web_search",
        },
        builtin_tools=[],
        filesystem_support="mcp",
        models=[
            "gpt-4.1",
            "gpt-5-mini",
            "claude-sonnet-4",
            "gemini-2.5-pro",
        ],
        default_model="gpt-5-mini",
        env_var=None,
        notes="GitHub Copilot SDK integration. Requires 'copilot' package installed. Auth via GitHub subscription.",
    ),
}

AGENT_FRAMEWORK_BACKENDS = frozenset(
    {
        "claude_code",
        "codex",
        "copilot",
        "gemini_cli",
    },
)


_DISPLAY_NAME_TO_BACKEND_TYPE: dict[str, str] = {
    "openai": "openai",
    "azure openai": "azure_openai",
    "claude": "claude",
    "claude code": "claude_code",
    "claude_code": "claude_code",
    "gemini": "gemini",
    "grok": "grok",
    "chatcompletion": "chatcompletion",
    "chat completion": "chatcompletion",
    "openrouter": "openrouter",
    "cerebras ai": "cerebras",
    "together ai": "together",
    "fireworks ai": "fireworks",
    "groq": "groq",
    "zai": "zai",
    "nebius ai studio": "nebius",
    "kimi": "moonshot",
    "nvidia nim": "nvidia_nim",
    "poe": "poe",
    "qwen": "qwen",
    "vllm": "vllm",
    "sglang": "sglang",
    "copilot": "copilot",
}


def normalize_backend_type(backend_type: str | None) -> str | None:
    """Normalize backend identifiers for capability lookup."""
    if backend_type is None:
        return None

    normalized = str(backend_type).strip()
    if not normalized:
        return None

    normalized_lower = normalized.lower()
    if normalized_lower in BACKEND_CAPABILITIES:
        return normalized_lower

    if normalized_lower in _DISPLAY_NAME_TO_BACKEND_TYPE:
        return _DISPLAY_NAME_TO_BACKEND_TYPE[normalized_lower]

    underscored = normalized_lower.replace(" ", "_").replace("-", "_")
    if underscored in BACKEND_CAPABILITIES:
        return underscored

    return normalized_lower


def get_capabilities(backend_type: str | None) -> BackendCapabilities | None:
    """Get capabilities for a backend type.

    Args:
        backend_type: The backend type (e.g., "openai", "claude")

    Returns:
        BackendCapabilities object if found, None otherwise
    """
    normalized_backend_type = normalize_backend_type(backend_type)
    return BACKEND_CAPABILITIES.get(normalized_backend_type) if normalized_backend_type else None


def is_agent_framework_backend(backend_type: str | None) -> bool:
    """Return True when the backend is an agent framework/CLI integration."""
    normalized_backend_type = normalize_backend_type(backend_type)
    return normalized_backend_type in AGENT_FRAMEWORK_BACKENDS if normalized_backend_type else False


def has_capability(backend_type: str | None, capability: str) -> bool:
    """Check if backend supports a capability.

    Args:
        backend_type: The backend type (e.g., "openai", "claude")
        capability: The capability to check (e.g., "web_search")

    Returns:
        True if backend supports the capability, False otherwise
    """
    caps = get_capabilities(backend_type)
    return capability in caps.supported_capabilities if caps else False


def get_all_backend_types() -> list[str]:
    """Get list of all registered backend types.

    Returns:
        List of backend type strings
    """
    return list(BACKEND_CAPABILITIES.keys())


def get_backends_with_capability(capability: str) -> list[str]:
    """Get all backends that support a given capability.

    Args:
        capability: The capability to search for (e.g., "web_search")

    Returns:
        List of backend types that support the capability
    """
    return [backend_type for backend_type, caps in BACKEND_CAPABILITIES.items() if capability in caps.supported_capabilities]


def validate_backend_config(backend_type: str, config: dict) -> list[str]:
    """Validate a backend configuration against its capabilities.

    Args:
        backend_type: The backend type
        config: The backend configuration dict

    Returns:
        List of validation error messages (empty if valid)
    """
    errors = []
    caps = get_capabilities(backend_type)

    if not caps:
        errors.append(f"Unknown backend type: {backend_type}")
        return errors

    # Check if requested tools are supported
    if "enable_web_search" in config and config["enable_web_search"]:
        if "web_search" not in caps.supported_capabilities:
            errors.append(f"{backend_type} does not support web_search")

    if config.get("enable_x_search"):
        if backend_type != "grok":
            errors.append(
                f"enable_x_search is only supported by Grok backend, not {backend_type}",
            )
        elif "x_search" not in caps.supported_capabilities:
            errors.append(f"{backend_type} does not support x_search")

    if "enable_code_execution" in config and config["enable_code_execution"]:
        if "code_execution" not in caps.supported_capabilities:
            errors.append(f"{backend_type} does not support code_execution")

    if "enable_code_interpreter" in config and config["enable_code_interpreter"]:
        if "code_execution" not in caps.supported_capabilities:
            errors.append(f"{backend_type} does not support code_execution/interpreter")

    # Programmatic tool calling is Claude-specific
    # Note: code_execution is auto-enabled when programmatic flow is enabled (in api_params_handler)
    if config.get("enable_programmatic_flow") and backend_type != "claude":
        errors.append(
            f"enable_programmatic_flow is only supported by Claude backend, not {backend_type}. " f"This setting will be ignored.",
        )

    # Tool search is Claude-specific
    if config.get("enable_tool_search") and backend_type != "claude":
        errors.append(
            f"enable_tool_search is only supported by Claude backend, not {backend_type}. " f"This setting will be ignored.",
        )

    # Check MCP configuration
    if "mcp_servers" in config and config["mcp_servers"]:
        if "mcp" not in caps.supported_capabilities:
            errors.append(f"{backend_type} does not support MCP")

    if backend_type == "grok":
        extra_body = config.get("extra_body")
        if isinstance(extra_body, dict) and "search_parameters" in extra_body:
            errors.append(
                "Grok no longer supports extra_body.search_parameters. " "Use enable_web_search and/or enable_x_search instead.",
            )

    # Check for deprecated system prompt parameters (standardized across all backends)
    if "append_system_prompt" in config:
        errors.append(
            "'append_system_prompt' in backend config is not supported. Use 'system_message' at the agent level (outside backend block) instead.",
        )

    if "system_prompt" in config:
        errors.append(
            "'system_prompt' in backend config is not supported. Use 'system_message' at the agent level (outside backend block) instead.",
        )

    return errors
