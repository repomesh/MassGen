"""
Base class for API parameters handlers.
Provides common functionality for building API parameters across different backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class APIParamsHandlerBase(ABC):
    """Abstract base class for API parameter handlers."""

    def __init__(self, backend_instance: Any):
        """Initialize the API params handler.

        Args:
            backend_instance: The backend instance containing necessary formatters and config
        """
        self.backend = backend_instance
        self.formatter = backend_instance.formatter
        self.custom_tool_manager = backend_instance.custom_tool_manager

    @abstractmethod
    async def build_api_params(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        all_params: dict[str, Any],
    ) -> dict[str, Any]:
        """Build API parameters for the specific backend.

        Args:
            messages: List of messages in framework format
            tools: List of tools in framework format
            all_params: All parameters including config and runtime params

        Returns:
            Dictionary of API parameters ready for the backend
        """

    @abstractmethod
    def get_excluded_params(self) -> set[str]:
        """Get backend-specific parameters to exclude from API calls."""

    @abstractmethod
    def get_provider_tools(self, all_params: dict[str, Any]) -> list[dict[str, Any]]:
        """Get provider-specific tools based on parameters."""

    def get_base_excluded_params(self) -> set[str]:
        """Get common parameters to exclude across all backends."""
        return {
            "upload_files",
            # Filesystem manager parameters (handled by base class)
            "cwd",
            "agent_temporary_workspace",
            "agent_temporary_workspace_parent",
            "context_paths",
            "context_write_access_enabled",
            "enforce_read_before_delete",
            "enable_image_generation",
            "enable_audio_generation",
            "enable_file_generation",
            "enable_video_generation",
            # Generation backend/model preferences (used by generate_media tool)
            "image_generation_backend",
            "image_generation_model",
            "video_generation_backend",
            "video_generation_model",
            "audio_generation_backend",
            "audio_generation_model",
            "multimodal_config",
            "enable_mcp_command_line",
            "command_line_allowed_commands",
            "command_line_blocked_commands",
            "command_line_execution_mode",
            "command_line_docker_image",
            "command_line_docker_memory_limit",
            "command_line_docker_cpu_limit",
            "command_line_docker_network_mode",
            "command_line_docker_enable_sudo",
            # Docker credential and package management (nested dicts)
            "command_line_docker_credentials",
            "command_line_docker_packages",
            "exclude_file_operation_mcps",
            "use_mcpwrapped_for_tool_filtering",
            "use_no_roots_wrapper",
            # Code-based tools (CodeAct paradigm)
            "enable_code_based_tools",
            "custom_tools_path",
            "auto_discover_custom_tools",
            "exclude_custom_tools",
            "direct_mcp_servers",
            "shared_tools_directory",
            # Backend identification (handled by orchestrator)
            "type",
            "agent_id",
            "session_id",  # Memory/conversation session ID from chat_agent
            "filesystem_session_id",  # Docker filesystem session mount
            "session_storage_base",
            # MCP configuration (handled by base class for MCP backends)
            "mcp_servers",
            # Coordination parameters (handled by orchestrator, not passed to API)
            "vote_only",  # Vote-only mode flag for coordination
            "plan_depth",
            "plan_thoroughness",
            "plan_target_steps",
            "plan_target_chunks",
            "use_two_tier_workspace",  # Two-tier workspace (scratch/deliverable) + git versioning
            "write_mode",  # Isolated write context mode (auto/worktree/isolated/legacy)
            "drift_conflict_policy",  # Isolated apply drift resolution policy
            "subagent_types",  # Which subagent types to expose (handled by orchestrator)
            "round_evaluator_before_checklist",  # Coordination-only evaluator-first loop control
            "orchestrator_managed_round_evaluator",  # Gate for orchestrator-owned round_evaluator launch
            "round_evaluator_skip_synthesis",  # Skip synthesis; pass raw critiques to parent directly
            "round_evaluator_refine",  # Allow evaluator agents to iterate (multi-round with voting)
            "round_evaluator_transformation_pressure",  # Coordination-only bias for evaluator thesis boldness
            "enable_quality_rethink_on_iteration",  # Coordination-only quality task injection toggle
            "enable_novelty_on_iteration",  # Coordination-only novelty task injection toggle
            "enable_execution_trace_analyzer",  # Coordination-only execution trace analysis toggle
            "novelty_injection",  # Novelty pressure level (none/gentle/moderate/aggressive)
            "improvements",  # draft_approach gate settings (orchestrator/checklist only)
            "learning_capture_mode",  # Learning capture timing (round/verification_and_final_only/final_only)
            "disable_final_only_round_capture_fallback",  # Coordination-only fallback control for final_only+skip_final_presentation
            # NLIP configuration belongs to MassGen routing, never provider APIs
            "enable_nlip",
            "nlip",
            "nlip_config",
            # Parallelization
            "instance_id",
            # Rate limiting (handled by rate_limiter.py)
            "enable_rate_limit",
            "concurrent_tool_execution",  # Local execution control (not sent to API)
            "max_concurrent_tools",  # Local execution control (not sent to API)
            # Multimodal tools (handled by base_with_custom_tool_and_mcp.py)
            "enable_multimodal_tools",
            "multimodal_config",
            # Hook framework (handled by base class)
            "hooks",
            # Debug options (not passed to API)
            "debug_delay_seconds",
            "debug_delay_after_n_tools",
            # Per-agent voting sensitivity (coordination config, not API param)
            "voting_sensitivity",
            "voting_threshold",
            "checklist_require_gap_report",
            "gap_report_mode",
            # Decomposition mode parameters (handled by orchestrator, not passed to API)
            "coordination_mode",
            "presenter_agent",
            "final_answer_strategy",
            "subtask",
            # Fairness controls (handled by orchestrator, not passed to API)
            "fairness_enabled",
            "fairness_lead_cap_answers",
            "max_midstream_injections_per_round",
            # WebSocket mode (transport control, not an API parameter)
            "websocket_mode",
            "defer_peer_updates_until_restart",
            "allow_midstream_peer_updates_before_checklist_submit",
            "max_checklist_calls_per_round",
            "checklist_first_answer",
            # Checkpoint coordination (handled by orchestrator, not passed to API)
            "main_agent",
            "checkpoint_enabled",
            "checkpoint_mode",
            "checkpoint_guidance",
            "checkpoint_gated_patterns",
            "standalone_checkpoint_enabled",
            "standalone_checkpoint_team_config",
            "standalone_checkpoint_mode",
            "standalone_checkpoint_single",
            "standalone_checkpoint_include_workspace_context",
        }

    def build_base_api_params(
        self,
        messages: list[dict[str, Any]],
        all_params: dict[str, Any],
    ) -> dict[str, Any]:
        """Build base API parameters common to most backends."""
        api_params = {"stream": True}

        # Add filtered parameters
        excluded = self.get_excluded_params()
        for key, value in all_params.items():
            if key not in excluded and value is not None:
                api_params[key] = value

        return api_params

    def get_mcp_tools(self) -> list[dict[str, Any]]:
        """Get MCP tools from backend if available."""
        if hasattr(self.backend, "_mcp_functions") and self.backend._mcp_functions:
            if hasattr(self.backend, "get_mcp_tools_formatted"):
                return self.backend.get_mcp_tools_formatted()
        return []

    def get_custom_tools(self) -> list[dict[str, Any]]:
        """Get custom tools, preferring backend-provided full schemas when available.

        Backends that inherit CustomToolAndMCPBackend expose
        `_get_custom_tools_schemas()`, which includes internal background lifecycle
        management tools in addition to user custom tools. Falling back to
        `custom_tool_manager.registered_tools` keeps compatibility for handlers
        instantiated with mocked backends in tests.
        """
        if hasattr(self.backend, "_get_custom_tools_schemas"):
            try:
                custom_schemas = self.backend._get_custom_tools_schemas()
            except Exception:  # noqa: BLE001
                custom_schemas = []
            if not isinstance(custom_schemas, list):
                custom_schemas = []

            if custom_schemas:
                normalized_schemas: list[dict[str, Any]] = []
                for schema in custom_schemas:
                    if schema.get("type") == "function" and "function" in schema:
                        function_block = dict(schema.get("function", {}))
                        function_block.setdefault("description", "")
                        normalized_schema = dict(schema)
                        normalized_schema["function"] = function_block
                        normalized_schemas.append(normalized_schema)
                    else:
                        normalized_schemas.append(schema)

                if hasattr(self.formatter, "format_tools"):
                    return self.formatter.format_tools(normalized_schemas)
                return normalized_schemas

        custom_tools = getattr(self.custom_tool_manager, "registered_tools", None)
        if custom_tools:
            return self.formatter.format_custom_tools(custom_tools)

        return []
