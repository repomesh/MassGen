YAML Configuration Reference
============================

Complete YAML configuration schema for MassGen.

.. note::

   For a complete overview of supported models and capabilities, see :doc:`supported_models`.

.. tip::

   **Validate your configs!** MassGen includes a built-in validator that checks for errors before running. Use ``massgen --validate config.yaml`` to verify your configuration. See :doc:`../user_guide/validating_configs` for details.

Configuration Hierarchy
-----------------------

MassGen configurations have a clear hierarchy of settings. Understanding this structure helps you place parameters in the correct location.

**Configuration Levels:**

1. **Top Level** - Global settings

   - ``agents`` or ``agent``: List of agents (or single agent)
   - ``memory``: Memory system configuration (conversation + persistent with Qdrant)
   - ``filesystem_memory``: Filesystem-based memory with auto-compression
   - ``orchestrator``: Coordination and workspace settings
   - ``ui``: Display and logging settings

2. **Agent Level** - Per-agent settings (inside ``agents[]``)

   - ``id``: Unique agent identifier
   - ``backend``: Backend configuration object
   - ``system_message``: Agent-specific instructions

3. **Backend Level** - Model and tool settings (inside ``agent.backend``)

   - Core: ``type``, ``model``, ``api_key``, ``temperature``, ``max_tokens``
   - Tool Enablement: ``enable_web_search``, ``enable_code_execution``, ``enable_code_interpreter``
   - MCP Integration: ``mcp_servers``, ``exclude_tools``, ``enable_mcp_command_line``
   - Backend-Specific: ``cwd``, ``permission_mode``, ``allowed_tools``, etc.

   .. note::
      **Code Execution Options**: ``enable_code_execution``/``enable_code_interpreter`` run in the provider's cloud sandbox (no filesystem access). For local code execution with filesystem access, use ``enable_mcp_command_line: true`` instead. See :doc:`../user_guide/tools/code_execution` for details.

4. **MCP Server Level** - Tool server settings (inside ``backend.mcp_servers[]``)

   - Connection: ``name``, ``type``, ``command``, ``args``, ``url``, ``env``
   - Security: ``security`` object (``level``, ``allow_localhost``, ``allow_private_ips``)
   - Tool Filtering: ``allowed_tools``, ``exclude_tools``

5. **Orchestrator Level** - Multi-agent coordination (top-level ``orchestrator``)

   - Workspace: ``snapshot_storage``, ``agent_temporary_workspace``
   - Project Integration: ``context_paths``
   - Coordination: ``coordination.enable_planning_mode``, ``coordination.planning_mode_instruction``, ``coordination.max_orchestration_restarts``
   - Debug: ``debug_final_answer``
   - Advanced: ``skip_coordination_rounds``, ``timeout``

6. **UI Level** - Display settings (top-level ``ui``)

   - ``display_type``: "rich_terminal" or "simple"
   - ``logging_enabled``: Enable/disable logging

Backend Types Overview
----------------------

MassGen supports multiple backend types with varying capabilities:

**API-Based Backends:**

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Backend Type
     - Description & Key Features
   * - ``claude``
     - Anthropic's Claude API with full tool support and MCP integration
   * - ``claude_code``
     - Claude Code SDK with native dev tools (Read, Write, Edit, Bash, etc.)
   * - ``codex``
     - OpenAI Codex CLI with native shell, file editing, web search, and MCP integration
   * - ``gemini``
     - Google's Gemini API with planning mode and MCP support
   * - ``openai``
     - OpenAI's GPT models with full tool and MCP support
   * - ``grok``
     - xAI's Grok models with web search and MCP integration
   * - ``azure_openai``
     - Azure-deployed OpenAI models (limited tool support)
   * - ``zai``
     - ZhipuAI's GLM models with basic MCP support
   * - ``chatcompletion``
     - **Generic OpenAI-compatible backend** - Works with Cerebras, Together AI, Fireworks, Groq, OpenRouter, etc. Requires ``base_url`` parameter

**Local/Inference Backends:**

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Backend Type
     - Description & Key Features
   * - ``lmstudio``
     - Local LM Studio server for running open-weight models
   * - ``vllm``
     - vLLM inference server (auto-detects port 8000)
   * - ``sglang``
     - SGLang inference server (auto-detects port 30000)

**Framework Backends:**

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - Backend Type
     - Description & Key Features
   * - ``ag2``
     - AG2 framework integration with code execution support

Basic Structure
---------------

.. code-block:: yaml

   # Agent definitions (required)
   agents:
     - id: "agent1"
       backend:
         # Backend configuration
       system_message: "..."

   # Orchestrator settings (optional)
   orchestrator:
     # Coordination and workspace settings

   # UI settings (optional)
   ui:
     # Display and logging configuration

Agent Configuration
-------------------

Single Agent
~~~~~~~~~~~~

.. code-block:: yaml

   agent:  # Singular for single agent
     id: "my_agent"
     backend:
       type: "claude"
       model: "claude-sonnet-4"
     system_message: "You are a helpful assistant"

Multiple Agents
~~~~~~~~~~~~~~~

.. code-block:: yaml

   agents:  # Plural for multiple agents
     - id: "agent1"
       backend:
         type: "gemini"
         model: "gemini-2.5-flash"
       system_message: "You are a researcher"

     - id: "agent2"
       backend:
         type: "openai"
         model: "gpt-5-nano"
       system_message: "You are an analyst"

Backend Configuration
---------------------

Basic Backend
~~~~~~~~~~~~~

.. code-block:: yaml

   backend:
     type: "openai"              # Backend type (required)
     model: "gpt-5-mini"         # Model name (required)
     api_key: "${API_KEY}"       # Optional, uses env var by default
     temperature: 0.7            # Optional
     max_tokens: 2000            # Optional

Claude Code Backend
~~~~~~~~~~~~~~~~~~~

The Claude Code backend uses Anthropic's Claude Agent SDK with native development tools.
By default, MassGen disables most Claude Code tools since it provides native implementations
for file operations, shell execution, and directory listing. Only the ``Task`` tool (for
subagent spawning) is enabled by default.

**Basic Configuration:**

.. code-block:: yaml

   backend:
     type: "claude_code"
     model: "sonnet"
     cwd: "workspace"            # Working directory for file operations
     permission_mode: "bypassPermissions"  # Optional

**With Web Search and Default Prompt:**

.. code-block:: yaml

   backend:
     type: "claude_code"
     model: "sonnet"
     cwd: "workspace"
     use_default_prompt: true    # Use Claude Code's default system prompt
     enable_web_search: true     # Enable WebSearch and WebFetch tools

**Configuration Options:**

- ``use_default_prompt`` (bool, default: false): When true, uses Claude Code's default
  system prompt (with coding style guidelines) plus MassGen's workflow instructions.
  When false, uses only MassGen's workflow prompt for full control.

- ``enable_web_search`` (bool, default: false): When true, enables Claude Code's
  WebSearch and WebFetch tools. Use when MassGen's crawl4ai tools are unavailable
  (crawl4ai requires Docker).

**Default Tool Behavior:**

Only the ``Task`` tool is enabled by default. All other Claude Code tools are disabled
because MassGen provides native equivalents:

- ``Read``, ``Write``, ``Edit`` → MassGen's ``read_file_content``, ``save_file_content``, ``append_file_content``
- ``Bash`` → MassGen's ``run_shell_script`` or ``execute_command`` MCP
- ``LS`` → MassGen's ``list_directory``
- ``Grep``, ``Glob`` → Use ``execute_command`` or future MassGen tools (see GitHub issue #640)

With MCP Servers
~~~~~~~~~~~~~~~~

.. code-block:: yaml

   backend:
     type: "gemini"
     model: "gemini-2.5-flash"
     mcp_servers:
       - name: "weather"
         type: "stdio"
         command: "npx"
         args: ["-y", "@modelcontextprotocol/server-weather"]
       - name: "search"
         type: "stdio"
         command: "npx"
         args: ["-y", "@modelcontextprotocol/server-brave-search"]
         env:
           BRAVE_API_KEY: "${BRAVE_API_KEY}"

Tool Filtering
~~~~~~~~~~~~~~

.. code-block:: yaml

   backend:
     type: "openai"
     model: "gpt-4o-mini"
     exclude_tools:  # Backend-level exclusions
       - mcp__discord__send_webhook
     mcp_servers:
       - name: "discord"
         type: "stdio"
         command: "npx"
         args: ["-y", "@modelcontextprotocol/server-discord"]
         allowed_tools:  # Server-specific whitelist
           - mcp__discord__read_messages
           - mcp__discord__send_message

GitHub Copilot Backend
~~~~~~~~~~~~~~~~~~~~~~

The GitHub Copilot backend uses the ``github-copilot-sdk`` with native MCP support.
Requires a GitHub Copilot subscription and the Copilot CLI (``gh copilot``).

**Basic Configuration:**

.. code-block:: yaml

   backend:
     type: "copilot"
     model: "gpt-5-mini"       # Also: gpt-4.1, claude-sonnet-4, gemini-2.5-pro

**With MCP Servers and Custom Tools:**

.. code-block:: yaml

   backend:
     type: "copilot"
     model: "gpt-5-mini"
     mcp_servers:
       - name: "filesystem"
         command: "npx"
         args: ["-y", "@modelcontextprotocol/server-filesystem", "."]
     custom_tools:
       - path: "massgen/tool/_basic"
         function: "two_num_tool"

**Configuration Options:**

- ``copilot_system_message_mode`` (string: "append"|"replace", default: "append"):
  How the system message is applied to the Copilot session.
- ``copilot_permission_policy`` (string: "approve"|"deny", default: "approve"):
  Permission callback policy. "approve" validates paths via PathPermissionManager.
- ``allowed_tools`` / ``exclude_tools``: Backend-level tool filtering.
- ``enable_multimodal_tools`` (bool): Enable read_media/generate_media tools.

**Docker Mode:**

.. code-block:: yaml

   backend:
     type: "copilot"
     model: "gpt-5-mini"
     command_line_execution_mode: "docker"
     command_line_docker_network_mode: "bridge"

AG2 Backend
~~~~~~~~~~~

.. code-block:: yaml

   backend:
     type: ag2
     agent_config:
       type: assistant           # or "conversable"
       name: "AG2_Coder"
       system_message: "You write Python code"
       llm_config:
         api_type: "openai"
         model: "gpt-4o"
       code_execution_config:
         executor:
           type: "LocalCommandLineCodeExecutor"
           timeout: 60
           work_dir: "./workspace"

Orchestrator Configuration
--------------------------

Basic Orchestrator
~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

   orchestrator:
     snapshot_storage: "snapshots"
     agent_temporary_workspace: "temp_workspaces"
     session_storage: "sessions"  # For interactive mode

Context Paths
~~~~~~~~~~~~~

.. code-block:: yaml

   orchestrator:
     context_paths:
       - path: "/absolute/path/to/src"
         permission: "read"       # Read-only access
       - path: "/absolute/path/to/docs"
         permission: "write"      # Write access for final agent

Coordination Config
~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

   orchestrator:
     coordination:
       enable_planning_mode: true
       planning_mode_instruction: |
         PLANNING MODE: Describe intended actions.
         Do not execute during coordination phase.

Skills System Config
~~~~~~~~~~~~~~~~~~~~

Enable the skills system for domain-specific guidance and workflows:

.. code-block:: yaml

   orchestrator:
     coordination:
       # Enable skills system
       use_skills: true

       # Optional: Skills discovery directory (default: .agent/skills)
       skills_directory: ".agent/skills"

       # Optional: Enable specific built-in MassGen skills
       massgen_skills:
         - "file_search"    # Always useful (ripgrep/ast-grep)
         - "serena"         # Symbol-level code understanding (LSP)
         - "semtools"       # Semantic search (embeddings)

**Available Built-in Skills:**

- ``file_search``: Fast text and structural code search (ripgrep/ast-grep)
- ``serena``: Symbol-level code understanding using LSP (optional, requires installation)
- ``semtools``: Semantic search using embeddings (optional, requires installation)

**Notes:**

- Skills require command line execution (``enable_mcp_command_line: true``)
- Default skills (memory, file_search) are always available when ``use_skills: true``
- Optional skills (serena, semtools) must be explicitly listed in ``massgen_skills``
- External skills from ``openskills`` are discovered from ``skills_directory``

See :ref:`user_guide_skills` for complete documentation.

UI Configuration
----------------

.. code-block:: yaml

   ui:
     display_type: "rich_terminal"  # or "simple"
     logging_enabled: true

Filesystem Memory Configuration
-------------------------------

Filesystem memory provides automatic context compression and memory persistence for long-running agent conversations. When the context window approaches capacity, the agent is prompted to summarize important information to markdown files before the conversation is truncated.

.. note::

   This is separate from the ``memory`` section, which configures Qdrant-based vector memory. ``filesystem_memory`` uses plain files for simpler, more transparent memory management.

Basic Configuration
~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

   filesystem_memory:
     enabled: true
     compression:
       trigger_threshold: 0.75   # Compress at 75% context usage
       target_ratio: 0.20        # Keep 20% after compression

How Auto-Compression Works
~~~~~~~~~~~~~~~~~~~~~~~~~~

1. **Monitoring**: The system monitors context window usage each turn
2. **Trigger**: When usage reaches ``trigger_threshold`` (default 75%), compression begins
3. **Agent Summary**: A compression request is injected asking the agent to:

   - Write a conversation summary to ``memory/short_term/recent.md``
   - Optionally write important facts to ``memory/long_term/*.md``
   - Call the ``compression_complete`` tool to signal completion

4. **Validation**: System validates that ``recent.md`` was written
5. **Truncation**: Conversation is truncated to ``target_ratio`` (default 20%), keeping recent messages
6. **Fallback**: If agent fails after 2 attempts, algorithmic compression is used (with warning)

Memory File Structure
~~~~~~~~~~~~~~~~~~~~~

After compression, the agent's workspace contains:

.. code-block:: text

   workspace/
   └── memory/
       ├── short_term/
       │   └── recent.md       # Conversation summary (auto-injected on future turns)
       └── long_term/
           ├── user_prefs.md   # Optional: persistent facts
           └── project_notes.md

Example with Full Options
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

   # Enable filesystem memory with custom thresholds
   filesystem_memory:
     enabled: true
     compression:
       trigger_threshold: 0.80   # More aggressive: wait until 80%
       target_ratio: 0.30        # Keep more context: 30%

   # Agent with memory-aware configuration
   agents:
     - id: "assistant"
       backend:
         type: "gemini"
         model: "gemini-2.5-flash"
         enable_mcp_command_line: true  # Required for file writing

Complete Example
----------------

Full multi-agent configuration demonstrating all 6 configuration levels:

.. code-block:: yaml

   # ========================================
   # LEVEL 1: TOP LEVEL - Global Settings
   # ========================================
   # Define agents, orchestrator, and UI at the top level

   # ========================================
   # LEVEL 2: AGENT LEVEL - Per-Agent Settings
   # ========================================
   agents:
     # Agent 1: Gemini with web search and tool enablement
     - id: "researcher"
       system_message: "You are a researcher with web search and weather tools"

       # ========================================
       # LEVEL 3: BACKEND LEVEL - Model & Tools
       # ========================================
       backend:
         type: "gemini"
         model: "gemini-2.5-flash"
         temperature: 0.7
         max_tokens: 2000

         # Tool Enablement Flags (Backend Level)
         enable_web_search: true           # Gemini built-in web search
         enable_code_execution: true       # Gemini code execution

         # Backend-level tool filtering
         exclude_tools:
           - mcp__weather__set_location    # Prevent location changes

         # ========================================
         # LEVEL 4: MCP SERVER LEVEL - Tool Servers
         # ========================================
         mcp_servers:
           - name: "search"
             type: "stdio"
             command: "npx"
             args: ["-y", "@modelcontextprotocol/server-brave-search"]
             env:
               BRAVE_API_KEY: "${BRAVE_API_KEY}"

             # MCP Server-level security configuration
             security:
               level: "high"                # Strict security
               allow_localhost: true        # Allow local connections
               allow_private_ips: false     # Block private IPs

             # MCP Server-level tool filtering
             allowed_tools:
               - mcp__search__web_search
               - mcp__search__local_search

           - name: "weather"
             type: "stdio"
             command: "npx"
             args: ["-y", "@modelcontextprotocol/server-weather"]
             security:
               level: "permissive"          # Relaxed for testing

     # Agent 2: Claude Code with native tools
     - id: "coder"
       system_message: "You write and execute code with file operations"
       backend:
         type: "claude_code"
         model: "claude-sonnet-4-20250514"
         cwd: "workspace"                    # Working directory (unique suffix added at runtime)
         permission_mode: "bypassPermissions"

         # Claude Code-specific parameters
         max_thinking_tokens: 10000         # Extended reasoning
         system_prompt: "You are an expert Python developer"
         disallowed_tools:                  # Blacklist dangerous ops
           - "Bash(rm*)"
           - "Bash(sudo*)"
           - "WebSearch"                    # Block web access

         # File operations handled via cwd parameter

     # Agent 3: OpenAI with code interpreter
     - id: "analyst"
       system_message: "You analyze data and generate reports"
       backend:
         type: "openai"
         model: "gpt-5-nano"

         # OpenAI-specific tool enablement
         enable_web_search: true            # OpenAI web search
         enable_code_interpreter: true      # Code interpreter tool

         cwd: "workspace"          # File operations (unique suffix added at runtime)

   # ========================================
   # LEVEL 5: ORCHESTRATOR LEVEL - Coordination
   # ========================================
   orchestrator:
     # Workspace management
     snapshot_storage: "snapshots"
     agent_temporary_workspace: "temp_workspaces"

     # Project integration
     context_paths:
       - path: "/Users/me/project/src"
         permission: "read"                 # Read-only access
       - path: "/Users/me/project/docs"
         permission: "write"                # Write access for winner

     # Coordination settings
     coordination:
       enable_planning_mode: true           # Enable planning mode
       max_orchestration_restarts: 2        # Allow up to 2 restarts (3 total attempts)
       planning_mode_instruction: |
         PLANNING MODE ACTIVE: You are in coordination phase.
         1. Describe your intended actions
         2. Analyze other agents' proposals
         3. Use only vote/new_answer tools
         4. DO NOT execute MCP commands
         5. Save execution for final presentation

     # Voting and answer control
     voting_sensitivity: "balanced"         # How critical agents are when voting (lenient/balanced)
     max_new_answers_per_agent: 2           # Cap new answers per agent (null=unlimited)
     max_new_answers_global: 8              # Cap total new answers across all agents (null=unlimited)
     answer_novelty_requirement: "balanced" # How different new answers must be (lenient/balanced/strict)
     fairness_enabled: true                 # Keep coordination pacing balanced (default: true)
     fairness_lead_cap_answers: 2           # Max lead in answer revisions vs slowest active peer
     max_midstream_injections_per_round: 2  # Cap injected unseen source updates per round
     defer_peer_updates_until_restart: false  # Queue peer updates for next restart instead of mid-stream injection
     allow_midstream_peer_updates_before_checklist_submit: null  # Optional checklist-mode override before first accepted submit_checklist

     # Advanced settings
     skip_coordination_rounds: false        # Normal coordination
     timeout:
       orchestrator_timeout_seconds: 1800   # 30 minute timeout

   # ========================================
   # LEVEL 6: UI LEVEL - Display Settings
   # ========================================
   ui:
     display_type: "rich_terminal"          # Rich terminal display
     logging_enabled: true                  # Enable logging

Parameter Reference
-------------------

Agents
~~~~~~

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Description
   * - ``id``
     - string
     - Yes
     - Unique agent identifier
   * - ``backend``
     - object
     - Yes
     - Backend configuration
   * - ``system_message``
     - string
     - No
     - System prompt for the agent

Backend
~~~~~~~

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Supported Backends
     - Description
   * - ``type``
     - string
     - Yes
     - All
     - Backend type: ``claude``, ``claude_code``, ``codex``, ``gemini``, ``gemini_cli``, ``openai``, ``grok``, ``azure_openai``, ``zai``, ``chatcompletion``, ``lmstudio``, ``vllm``, ``sglang``, ``ag2``, ``copilot``
   * - ``model``
     - string
     - Yes
     - All
     - Model name (provider-specific)
   * - ``api_key``
     - string
     - No
     - All API backends
     - API key (uses env var by default)
   * - ``base_url``
     - string
     - Yes*
     - ``chatcompletion``, ``lmstudio``, ``vllm``, ``sglang``
     - API endpoint URL (required for chatcompletion)
   * - ``cwd``
     - string
     - No
     - ``claude_code``, ``codex``
     - Working directory for file operations. **Use** ``"workspace"`` **as the value** - MassGen automatically adds a unique suffix per agent at runtime (e.g., ``workspace_f7a3b2c1``). Avoid numbered names like ``workspace1`` as they can leak agent identity during voting.
   * - ``exclude_file_operation_mcps``
     - boolean
     - No
     - All with MCP support
     - Exclude file operation MCP tools (read/write/copy/delete). Agents use command-line tools instead. Keeps command execution, media generation, and planning MCPs. (default: false)
   * - ``enable_image_generation``
     - boolean
     - No
     - All with MCP support
     - Enable image generation tools (default: false)
   * - ``enable_audio_generation``
     - boolean
     - No
     - All with MCP support
     - Enable audio generation tools (default: false)
   * - ``enable_file_generation``
     - boolean
     - No
     - All with MCP support
     - Enable file generation tools (default: false)
   * - ``enable_video_generation``
     - boolean
     - No
     - All with MCP support
     - Enable video generation tools (default: false)
   * - ``enable_code_based_tools``
     - boolean
     - No
     - All with MCP support
     - Enable code-based tools (CodeAct paradigm). MCP tools presented as Python code in workspace (default: false)
   * - ``custom_tools_path``
     - string
     - No
     - All with MCP support
     - Path to custom tools directory to copy into workspace (for code-based tools)
   * - ``auto_discover_custom_tools``
     - boolean
     - No
     - All with MCP support
     - Auto-discover custom tools from massgen/tool/ directory (default: false)
   * - ``exclude_custom_tools``
     - list
     - No
     - All with MCP support
     - List of custom tool directories to exclude (e.g., ["_claude_computer_use"])
   * - ``direct_mcp_servers``
     - list
     - No
     - All with MCP support
     - List of MCP server names to keep as direct protocol tools when ``enable_code_based_tools`` is true. These servers remain callable as native tools in the prompt rather than being filtered to code-only access. Example: ``["logfire", "context7"]``
   * - ``shared_tools_directory``
     - string
     - No
     - All with MCP support
     - Shared directory for code-based tools. Tools generated once and shared across agents (default: per-agent)
   * - ``concurrent_tool_execution``
     - boolean
     - No
     - All with MCP support
     - Execute multiple tool calls in parallel (default: false). When enabled, tools called together run simultaneously. WARNING: Do not call dependent tools together (e.g., mkdir + write to that dir)
   * - ``enable_mcp_command_line``
     - boolean
     - No
     - All with MCP support
     - Enable command-line execution tool (default: false)
   * - ``command_line_execution_mode``
     - string
     - No
     - All with MCP support
     - Execution mode: "local" or "docker" (default: "local")
   * - ``command_line_docker_image``
     - string
     - No
     - All with MCP support
     - Docker image for command execution (default: "massgen:runtime")
   * - ``command_line_docker_memory_limit``
     - string
     - No
     - All with MCP support
     - Docker memory limit (e.g., "2g", default: "4g")
   * - ``command_line_docker_cpu_limit``
     - string
     - No
     - All with MCP support
     - Docker CPU limit (e.g., "2.0", default: "4.0")
   * - ``command_line_docker_network_mode``
     - string
     - **Codex**, **Gemini CLI** (Docker mode)
     - All with MCP support
     - Docker network mode: "bridge", "host", "none". **Required for Codex and Gemini CLI in Docker mode** (use "bridge").
   * - ``model_reasoning_effort``
     - string
     - No
     - ``codex``
     - Codex reasoning effort: "low", "medium", "high", or "xhigh". OpenAI-style ``reasoning.effort`` is also accepted for Codex compatibility.
   * - ``command_line_docker_enable_sudo``
     - boolean
     - No
     - All with MCP support
     - Enable sudo in Docker containers (default: false)
   * - ``command_line_docker_credentials``
     - object
     - No
     - All with MCP support
     - Docker credentials config (env_file, env_vars, env_vars_from_file, pass_all_env)
   * - ``command_line_docker_packages``
     - object
     - No
     - All with MCP support
     - Docker packages to install (apt, pip, npm lists)
   * - ``command_line_allowed_commands``
     - list
     - No
     - All with MCP support
     - Whitelist of allowed command patterns
   * - ``command_line_blocked_commands``
     - list
     - No
     - All with MCP support
     - Blacklist of blocked command patterns
   * - ``mcp_servers``
     - list
     - No
     - All except ``ag2``, ``azure_openai``
     - MCP server configurations
   * - ``exclude_tools``
     - list
     - No
     - All with tool support
     - Tools to exclude from this backend
   * - ``temperature``
     - float
     - No
     - All
     - Sampling temperature (0.0-1.0)
   * - ``max_tokens``
     - integer
     - No
     - All
     - Maximum response tokens
   * - ``permission_mode``
     - string
     - No
     - ``claude_code``
     - Permission handling: ``bypassPermissions`` or default
   * - ``agent_config``
     - object
     - Yes*
     - ``ag2``
     - AG2-specific agent configuration (required for AG2)
   * - ``enable_web_search``
     - boolean
     - No
     - ``claude``, ``claude_code``, ``gemini``, ``openai``, ``grok``, ``chatcompletion``
     - Enable built-in web search capability. For ``claude_code``, enables WebSearch and WebFetch tools (default: false)
   * - ``use_default_prompt``
     - boolean
     - No
     - ``claude_code``
     - When true, uses Claude Code's default system prompt with MassGen instructions appended. When false (default), uses only MassGen's workflow prompt for full control over agent behavior
   * - ``enable_code_execution``
     - boolean
     - No
     - ``claude``, ``gemini``
     - Enable built-in code execution tool
   * - ``enable_code_interpreter``
     - boolean
     - No
     - ``openai``
     - Enable OpenAI code interpreter tool
   * - ``allowed_tools``
     - list
     - No
     - ``claude_code``
     - Whitelist of allowed Claude Code tools (legacy - use disallowed_tools instead)
   * - ``disallowed_tools``
     - list
     - No
     - ``claude_code``
     - Blacklist of dangerous tools to block (e.g., ["Bash(rm*)", "Bash(sudo*)"])
   * - ``max_thinking_tokens``
     - integer
     - No
     - ``claude_code``
     - Maximum tokens for internal thinking (default: 8000)
   * - ``system_prompt``
     - string
     - No
     - ``claude_code``
     - Custom system prompt for Claude Code agent
   * - ``api_version``
     - string
     - Yes*
     - ``azure_openai``
     - Azure OpenAI API version (required, default: "2024-02-15-preview")

MCP Server
~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Description
   * - ``name``
     - string
     - Yes
     - Server name
   * - ``type``
     - string
     - Yes
     - "stdio" or "streamable-http"
   * - ``command``
     - string
     - stdio only
     - Command to launch server
   * - ``args``
     - list
     - stdio only
     - Command arguments
   * - ``url``
     - string
     - http only
     - Server URL
   * - ``env``
     - object
     - No
     - Environment variables
   * - ``allowed_tools``
     - list
     - No
     - Whitelist of allowed tools
   * - ``exclude_tools``
     - list
     - No
     - Tools to exclude
   * - ``security``
     - object
     - No
     - Security configuration for the MCP server

MCP Server Security
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Description
   * - ``level``
     - string
     - No
     - Security level: ``"high"`` (strict, default) or ``"permissive"`` (relaxed for testing)
   * - ``allow_localhost``
     - boolean
     - No
     - Allow connections to localhost (required for local MCP servers)
   * - ``allow_private_ips``
     - boolean
     - No
     - Allow connections to private IP ranges (for testing environments)

Orchestrator
~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Description
   * - ``snapshot_storage``
     - string
     - No
     - Directory for workspace snapshots
   * - ``agent_temporary_workspace``
     - string
     - No
     - Directory for temporary workspaces
   * - ``context_paths``
     - list
     - No
     - Shared project directories
   * - ``coordination``
     - object
     - No
     - Coordination configuration (planning mode settings)
   * - ``skip_coordination_rounds``
     - boolean
     - No
     - Debug/test mode: skip voting rounds and go straight to final presentation (default: false)
   * - ``debug_final_answer``
     - string
     - No
     - Debug mode for restart feature: override final answer on attempt 1 only to test restart flow (default: null). Example: "I only created one file."
   * - ``timeout``
     - object
     - No
     - Timeout configuration

Coordination Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Description
   * - ``enable_planning_mode``
     - boolean
     - No
     - Enable planning mode during coordination (default: false). When enabled, agents plan without executing MCP tools during the coordination phase. Only the winning agent executes actions during final presentation.
   * - ``planning_mode_instruction``
     - string
     - No
     - Custom instruction added to agent prompts when planning mode is enabled. Should explain to agents that they should describe intended actions without executing them.
   * - ``plan_depth``
     - string or null
     - No
     - Task planning granularity for plan/spec modes. Supported values: ``dynamic``, ``shallow``, ``medium``, ``deep``. Omit or set ``null`` for runtime defaults.
   * - ``plan_target_steps``
     - integer or null
     - No
     - Optional explicit target number of tasks/steps for planning. Omit or set ``null`` for dynamic sizing.
   * - ``plan_target_chunks``
     - integer or null
     - No
     - Optional explicit target number of plan/spec chunks. Omit or set ``null`` for dynamic sizing.
   * - ``max_orchestration_restarts``
     - integer
     - No
     - Maximum number of orchestration restarts allowed (default: 0). When set > 0, enables post-evaluation where the winning agent reviews the final answer and can request a restart with specific improvement instructions. Recommended values: 1-2.
   * - ``subagent_types``
     - list of strings or null
     - No
     - Which specialized subagent types to expose. Default (null/omitted): ``[evaluator, explorer, researcher]``. Set explicitly to include ``novelty`` or custom project types. Empty list disables all specialized types.
   * - ``enable_subagents``
     - boolean
     - No
     - Enable subagent tools for parallel task execution (default: false)
   * - ``subagent_default_timeout``
     - integer
     - No
     - Default timeout in seconds for subagent execution (default: 300)
   * - ``subagent_min_timeout``
     - integer
     - No
     - Minimum allowed subagent timeout in seconds (default: 60)
   * - ``subagent_max_timeout``
     - integer
     - No
     - Maximum allowed subagent timeout in seconds (default: 600)
   * - ``subagent_max_concurrent``
     - integer
     - No
     - Maximum number of concurrent subagents (default: 3)
   * - ``subagent_round_timeouts``
     - object
     - No
     - Optional per-round timeout settings for subagents. Uses the same keys as ``timeout_settings`` and inherits from parent if omitted.
   * - ``subagent_runtime_mode``
     - string
     - No
     - Subagent runtime boundary mode. ``isolated`` (default) or ``inherited``.
   * - ``subagent_runtime_fallback_mode``
     - string or null
     - No
     - Optional fallback mode when isolated prerequisites are unavailable. ``inherited`` or ``null`` (strict isolation). Codex in Docker mode treats unset fallback as ``inherited`` when ``subagent_runtime_mode`` is ``isolated``.
   * - ``subagent_host_launch_prefix``
     - list or null
     - No
     - Optional command prefix used to bridge isolated launches from containerized parent runtimes.
   * - ``subagent_orchestrator``
     - object
     - No
     - Subagent orchestrator configuration (multi-agent subagents with custom models), including options such as ``parse_at_references`` for literal ``@`` task text.
   * - ``background_subagents``
     - object
     - No
     - Background subagent configuration (``enabled``, ``injection_strategy``)
   * - ``round_evaluator_before_checklist``
     - boolean
     - No
     - Enable the orchestrator-managed round-evaluator stage before round-2+ checklist decisions (default: ``false``). Requires ``orchestrator_managed_round_evaluator: true`` and checklist-gated voting.
   * - ``orchestrator_managed_round_evaluator``
     - boolean
     - No
     - Treat the synthesized round-evaluator task handoff as the normal post-answer self-improvement path (default: ``false``).
   * - ``round_evaluator_refine``
     - boolean
     - No
     - Advanced/non-default option that lets the evaluator child run iterate before producing its packet (default: ``false``).
   * - ``round_evaluator_transformation_pressure``
     - string
     - No
     - Bias on how aggressively the evaluator seeks a larger thesis change. Supported values: ``gentle``, ``balanced``, ``aggressive``. Default: ``balanced``.
   * - ``fast_iteration_mode``
     - boolean
     - No
     - Streamline post-candidate phases so agents submit faster and iterate across rounds instead of over-polishing within a single round (default: ``false``). Only applies to ``checklist_gated`` voting sensitivity. When enabled: Phase 4 (subagent spawning for plateaued criteria) is skipped, the Substantiveness Test is replaced with a Quick Impact Check, and agents are guided to submit with Known Gaps rather than fixing everything internally. Analysis depth (Phases 1-2), verification replay, essential files manifest, and changedoc are all preserved.

.. note::

   Unknown keys under top-level ``orchestrator`` and nested ``orchestrator.coordination`` produce validation warnings. When running ``scripts/validate_all_configs.py --strict``, these warnings are treated as release-blocking failures so spelling mistakes do not silently change behavior.

.. note::

   **New in v0.1.3:** Orchestration restart enables automatic quality checks after coordination. The winning agent evaluates its own answer and can trigger a restart if the answer is incomplete or incorrect, with specific instructions for improvement.

.. note::

   **Planning Mode Support:** Planning mode works with all backends that support MCP integration (``claude``, ``claude_code``, ``codex``, ``gemini``, ``openai``, ``grok``, ``chatcompletion``, ``lmstudio``, ``vllm``, ``sglang``). It does NOT work with ``ag2`` or ``azure_openai``.

   **When to Use Planning Mode:**

   - When using MCP tools that perform irreversible actions (file deletion, database modifications, API calls)
   - When coordinating multiple agents that should agree on a plan before execution
   - When you want a "dry run" discussion phase before actual tool execution

   **How It Works:**

   1. **Coordination Phase** (with planning mode): Agents discuss and vote on approaches WITHOUT executing MCP tools
   2. **Final Presentation Phase**: The winning agent EXECUTES the planned actions

.. note::

   **Subagent Round Timeouts:** ``coordination.subagent_round_timeouts`` uses the same keys as ``timeout_settings`` (initial, subsequent, grace). If you omit it, subagents inherit the parent ``timeout_settings`` values.

Voting and Answer Control
~~~~~~~~~~~~~~~~~~~~~~~~~~

These parameters control coordination behavior to balance quality and duration.

Fairness controls are designed to solve a common multi-agent failure mode: fast agents can repeatedly submit revisions while slower peers are still working, which creates uneven effort, restart churn, and noisy coordination loops. With fairness enabled (default), agents stay within a bounded revision lead and wait for peer updates before terminal decisions.

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Description
   * - ``voting_sensitivity``
     - string
     - No
     - Controls how critical agents are when evaluating answers. **Options:** ``"lenient"`` (default) - agents vote for existing answers more readily, faster convergence; ``"balanced"`` - agents apply detailed criteria (comprehensive, accurate, complete?) before voting, more thorough evaluation; ``"strict"`` - agents apply high standards of excellence (all aspects, edge cases, reference-quality) before voting, maximum quality.
   * - ``max_new_answers_per_agent``
     - integer or null
     - No
     - Maximum number of new answers each agent can provide. In ``coordination_mode: voting``, this is a total per-agent cap. In ``coordination_mode: decomposition``, this is a **consecutive** cap that resets after the agent sees unseen external answer updates. **Options:** ``null`` (default) - unlimited answers; ``1``, ``2``, ``3``, etc.
   * - ``max_new_answers_global``
     - integer or null
     - No
     - Maximum number of new answers across all agents combined. When reached, ``new_answer`` is disabled for everyone. In voting mode, agents must vote; in decomposition mode, agents auto-stop. **Options:** ``null`` (default) - unlimited total answers; positive integer - global cap.
   * - ``answer_novelty_requirement``
     - string
     - No
     - Controls how different new answers must be from existing ones to prevent rephrasing. **Options:** ``"lenient"`` (default) - no similarity checks (fastest); ``"balanced"`` - reject if >70% token overlap, requires meaningful differences; ``"strict"`` - reject if >50% token overlap, requires substantially different solutions.
   * - ``fairness_enabled``
     - boolean
     - No
     - Enable fairness pacing controls across both ``coordination_mode: voting`` and ``coordination_mode: decomposition``. **Default:** ``true``.
   * - ``fairness_lead_cap_answers``
     - integer
     - No
     - Maximum allowed lead in answer revisions over the slowest active peer. When exceeded, ``new_answer`` is blocked until peers catch up. **Default:** ``2`` (set ``0`` for strict lockstep).
   * - ``max_midstream_injections_per_round``
     - integer
     - No
     - Maximum unseen source-agent updates injected mid-stream into a single agent during one round. Helps prevent fast models from receiving runaway update fanout. **Default:** ``2``.
   * - ``defer_peer_updates_until_restart``
     - boolean
     - No
     - When ``true``, peer answer updates are queued until the agent reaches a safe restart point instead of being injected mid-stream. Human/runtime/background payload delivery is unchanged. **Default:** ``false``.
   * - ``allow_midstream_peer_updates_before_checklist_submit``
     - boolean or null
     - No
     - Checklist-gated override for ``defer_peer_updates_until_restart``. When enabled, peer updates may still arrive mid-stream until the agent records its first accepted ``submit_checklist`` for the current answer. ``null`` uses the orchestrator default policy. **Default:** ``null``.

**Example Configurations:**

Fast but thorough (recommended for balanced evaluation):

.. code-block:: yaml

   orchestrator:
     voting_sensitivity: "balanced"       # Critical evaluation
     max_new_answers_per_agent: 2         # But cap at 2 tries
     max_new_answers_global: 8            # Stop global churn in long runs
     answer_novelty_requirement: "balanced"  # Must actually improve
     fairness_enabled: true
     fairness_lead_cap_answers: 2
     max_midstream_injections_per_round: 2
     defer_peer_updates_until_restart: false

Maximum quality with bounded time:

.. code-block:: yaml

   orchestrator:
     voting_sensitivity: "strict"          # Highest quality bar
     max_new_answers_per_agent: 3
     max_new_answers_global: 12
     answer_novelty_requirement: "strict"   # Only accept real improvements

Quick convergence:

.. code-block:: yaml

   orchestrator:
     voting_sensitivity: "lenient"
     max_new_answers_per_agent: 1
     max_new_answers_global: 3
     answer_novelty_requirement: "lenient"

Decomposition mode (recommended defaults):

.. code-block:: yaml

   orchestrator:
     coordination_mode: "decomposition"
     presenter_agent: "integrator"
     # In decomposition mode, use a lower per-agent cap than parallel voting mode.
     # This cap is consecutive and resets when the agent sees new external answers.
     max_new_answers_per_agent: 2  # Recommended range: 2-3
     # Add a global cap for deterministic total coordination budget.
     max_new_answers_global: 9
     answer_novelty_requirement: "balanced"
     fairness_enabled: true
     fairness_lead_cap_answers: 2
     max_midstream_injections_per_round: 2

Ensemble pattern (recommended defaults):

.. code-block:: yaml

   orchestrator:
     # Agents work independently — no peer answer injection
     disable_injection: true
     # Wait for all agents to finish before voting begins
     defer_voting_until_all_answered: true
     # Each agent produces 1 answer (adjustable)
     max_new_answers_per_agent: 1
     # Winner synthesizes from all answers
     final_answer_strategy: "synthesize"

The **ensemble pattern** is a coordination strategy where agents produce answers
independently (no peer visibility), then vote on the best answer, and the winner
synthesizes insights from all others into a refined final answer.

**When to use ensemble mode:**

- You want diverse, independent perspectives without agents anchoring on each
  other's work
- The task benefits from competitive parallel attempts rather than iterative
  refinement (e.g., creative writing, design proposals, solution brainstorming)
- You want faster coordination — single round of production + vote, no
  multi-round iteration

**Subagent default:** Multi-agent subagent runs use ensemble defaults
automatically (``disable_injection: true``, ``defer_voting_until_all_answered:
true``). Override by setting these fields explicitly in
``subagent_orchestrator`` config.

.. list-table:: Ensemble vs Standard Voting vs Decomposition
   :header-rows: 1

   * - Aspect
     - Standard voting
     - Ensemble pattern
     - Decomposition
   * - Peer visibility
     - Agents see each other's answers
     - Agents work in isolation
     - Agents see subtask assignments
   * - Iteration
     - Multiple refinement rounds
     - Single round of production
     - Multiple rounds per subtask
   * - Voting
     - After iterative refinement
     - After all answers produced
     - No voting (presenter assembles)
   * - Final answer
     - Winner presents
     - Winner synthesizes from all
     - Presenter integrates subtasks
   * - Best for
     - Deep quality refinement
     - Diverse perspectives, speed
     - Complex multi-part tasks

Timeout Configuration
~~~~~~~~~~~~~~~~~~~~~

Global runtime timeouts are configured with top-level ``timeout_settings``. Unknown keys under ``timeout_settings`` produce validation warnings, and ``scripts/validate_all_configs.py --strict`` treats those warnings as release-blocking failures.

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Description
   * - ``orchestrator_timeout_seconds``
     - integer
     - No
     - Maximum time for orchestrator coordination in seconds (default: 1800 = 30 minutes)
   * - ``initial_round_timeout_seconds``
     - integer
     - No
     - Soft timeout for round 0 (initial answer). After this time, a warning is injected telling the agent to wrap up. Set to ``null`` to disable (default: disabled)
   * - ``subsequent_round_timeout_seconds``
     - integer
     - No
     - Soft timeout for rounds 1+ (voting/refinement). After this time, a warning is injected telling the agent to wrap up. Set to ``null`` to disable (default: disabled)
   * - ``round_timeout_grace_seconds``
     - integer
     - No
     - Grace period after soft timeout before hard timeout kicks in. After hard timeout, only ``vote`` and ``new_answer`` tools are allowed (default: 120 seconds)

Context Path
~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Description
   * - ``path``
     - string
     - Yes
     - Absolute path to directory
   * - ``permission``
     - string
     - Yes
     - "read" or "write"

UI
~~

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Description
   * - ``display_type``
     - string
     - No
     - "rich_terminal" or "simple"
   * - ``logging_enabled``
     - boolean
     - No
     - Enable/disable logging

Filesystem Memory
~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Description
   * - ``enabled``
     - boolean
     - No
     - Enable filesystem memory and auto-compression (default: true)
   * - ``compression``
     - object
     - No
     - Compression settings (see below)

Filesystem Memory Compression
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - Parameter
     - Type
     - Required
     - Description
   * - ``trigger_threshold``
     - float
     - No
     - Context usage percentage (0.0-1.0) at which to trigger compression (default: 0.75)
   * - ``target_ratio``
     - float
     - No
     - Target context percentage (0.0-1.0) after compression (default: 0.20)

See Also
--------

* :doc:`../quickstart/configuration` - Configuration guide
* :doc:`../user_guide/tools/mcp_integration` - MCP configuration details
* :doc:`../user_guide/files/project_integration` - Context paths setup
* :doc:`cli` - CLI parameters
