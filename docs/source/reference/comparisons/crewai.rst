==================
MassGen vs CrewAI
==================

`CrewAI <https://github.com/crewAIInc/crewAI>`_ is a popular open-source framework (MIT, ~51K GitHub stars as of May 2026) for orchestrating role-playing AI agents. It is independent of LangChain and ships with both a Python SDK and the commercial *CrewAI AMP* (Agent Management Platform) for hosted execution and observability.

This page compares CrewAI with MassGen. The intent is fair-handed: both projects are healthy, the right choice depends on what you are trying to build.

.. contents:: On This Page
   :local:
   :depth: 2

Overview
--------

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Aspect
     - MassGen
     - CrewAI
   * - **Primary Goal**
     - Parallel multi-agent coordination through voting and consensus on the *same* task
     - Sequential / hierarchical role-based agent teams ("crews") that *decompose* a task across roles
   * - **Architecture**
     - All agents tackle the full task in parallel, observe each other, then vote on a winning answer
     - "Crews" of role-played agents execute task graphs; "Flows" add event-driven control over multiple crews
   * - **Hosted product**
     - Open source only; runs locally, in CI, or in your infra
     - Open source SDK + hosted *Crew Control Plane* / AMP for managed deployment and observability

Architecture & Coordination Model
---------------------------------

**CrewAI** treats a multi-agent task as a *workflow*. The unit of work is a ``Task``, the unit of work-doing is an ``Agent`` with a role/goal/backstory, and a ``Crew`` is the team plus the process (sequential or hierarchical) that runs the tasks. ``Flow`` adds event-driven orchestration so multiple crews can be triggered and composed deterministically. The mental model is closer to a structured pipeline than a debate: each task is owned by one agent, and the framework's job is to dispatch and chain them.

**MassGen** treats a multi-agent task as a *redundant parallel attempt*. All agents receive the same task and produce candidate answers in parallel. At each step every agent sees other agents' most recent answers and can either submit a new answer or vote for an existing one. Coordination ends when consensus is reached, and the winning answer is the one with the most votes. See :doc:`../../user_guide/concepts` for the full coordination model.

In one line: CrewAI is built for *decomposition* (different roles do different sub-tasks). MassGen is built for *refinement* (many agents attack the same task and converge).

Feature Comparison
------------------

.. list-table::
   :header-rows: 1
   :widths: 25 20 20 35

   * - Feature
     - MassGen
     - CrewAI
     - Notes
   * - **License**
     - Apache 2.0
     - MIT
     - Both fully open source for self-hosted use
   * - **CLI**
     - ✅ ``massgen``, ``massgen --automation``, ``massgen --web``
     - ✅ ``crewai`` (project scaffolding, run, install)
     - Different focuses: MassGen CLI is the primary interactive entry point; CrewAI CLI is mostly project bootstrap
   * - **Python API**
     - ✅ Async API, LiteLLM custom provider
     - ✅ Synchronous API, role-based abstractions
     - CrewAI's API centers on ``Agent``/``Task``/``Crew``; MassGen's centers on parallel runs and votes
   * - **WebUI**
     - ✅ Side-by-side agent panels, live streaming, vote/consensus view
     - ✅ CrewAI AMP for hosted deployment, traces, and observability
     - Different roles: MassGen's WebUI visualizes the *coordination*; CrewAI AMP is more of a *deployment dashboard*
   * - **MCP tools**
     - ✅ First-class on every backend (Claude, Codex, Gemini, OpenAI-compatible, Grok, Claude Code SDK)
     - ✅ First-class via ``mcps`` field on Agent and ``MCPServerAdapter``
     - Both support stdio, SSE, and streamable HTTP transports
   * - **Code execution / filesystem tools**
     - ✅ Sandboxed Python/Bash, filesystem with permissioned context paths
     - ✅ Tool ecosystem (web search, code, files) via ``crewai-tools``
     - Different defaults: MassGen ships filesystem permissions and workspace snapshots; CrewAI relies on its tool library
   * - **Backend / model providers**
     - 10+ direct backends (Claude, Gemini, OpenAI, Grok, Azure, LM Studio, OpenRouter, …) + Claude Code SDK + Codex
     - OpenAI default; Ollama, Anthropic, Gemini, and others via configuration
     - MassGen's backend abstraction is heterogenous-by-design (each agent can use a different provider)
   * - **Voting / consensus**
     - ✅ Core mechanism; agents vote, winner presents
     - ❌ Not built in (the framework is task-decomposition oriented)
     - This is the central design difference
   * - **Live streaming**
     - ✅ Token-level streaming to TUI and WebUI
     - ✅ Event/step streaming
     - Both stream; MassGen also streams per-agent in parallel side by side
   * - **Hosted control plane**
     - ❌
     - ✅ CrewAI AMP (hosted + self-hosted offerings)
     - Use CrewAI if you specifically want a managed deployment surface

Voting and Consensus (the MassGen Differentiator)
-------------------------------------------------

CrewAI does not have a native voting mechanism. A "consensus" pattern in CrewAI is something you build yourself by orchestrating multiple agents and writing a reducer task.

In MassGen voting is *the* coordination protocol, not an optional pattern:

- Every agent sees the most recent answer from every other agent at each step.
- Every agent at each step picks one of: submit a new answer, or vote for an existing answer.
- The orchestrator detects consensus automatically and the winner presents.
- Combined with checklist-gated evaluation criteria (see :doc:`../../user_guide/concepts`), this enforces refinement until quality is genuinely achieved rather than declared.

If your task benefits from diverse parallel attempts with collective validation — e.g. writing, design, math, code synthesis with verifier feedback — voting is what MassGen adds that role-based frameworks don't.

When to Use Each
----------------

**Choose CrewAI when you need:**

- A *role-based decomposition* of a task — clear sub-tasks owned by clearly-named agents.
- A managed control plane (CrewAI AMP) for deployment, tracing, and team ergonomics.
- A large existing community / ecosystem of role recipes and tools.

**Choose MassGen when you need:**

- *Parallel refinement* of one task with multiple agents converging on a best answer.
- Side-by-side live visualization of every agent's reasoning and answer.
- Heterogeneous backends per agent (Claude + Gemini + GPT + Grok all on the same task).
- Voting / consensus as a first-class control flow, not a pattern to re-implement.
- A local-first / Apache 2.0 stack with no managed control plane dependency.

Choosing CrewAI does not exclude MassGen and vice versa — they solve adjacent problems. A common pattern is to use MassGen at decision points where multiple strong attempts and voting genuinely add quality, and CrewAI (or similar) where the work cleanly decomposes into roles.

Related
-------

- :doc:`langgraph` — graph-based orchestration (more low-level than CrewAI)
- :doc:`autogen` — multi-agent conversations (in maintenance mode; see successor)
- :doc:`../comparisons` — back to comparisons hub
