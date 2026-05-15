==========================
MassGen vs AutoGen / AG2
==========================

`AutoGen <https://github.com/microsoft/autogen>`_ is Microsoft's multi-agent conversation framework (CC-BY-4.0 docs / MIT code, ~58K GitHub stars as of May 2026). It pioneered the "agents that chat with each other and tools" pattern that much of the field now builds on. `AG2 <https://github.com/ag2ai/ag2>`_ is the community-governed continuation of AutoGen (Apache 2.0 with original MIT components, ~4.6K stars, hosted under the new ``ag2ai`` organization). Both descend from the same codebase but have diverged in stewardship and roadmap.

.. note::

   **Maintenance status — read this first.**

   - **Microsoft AutoGen** is in maintenance mode. Microsoft has positioned `microsoft/agent-framework <https://github.com/microsoft/agent-framework>`_ as the enterprise successor, with documented migration paths from both AutoGen and Semantic Kernel, supporting Python + .NET with graph-based orchestration. AutoGen continues to receive bug fixes but no new features are planned.
   - **AG2** is actively developed and serves as the community continuation of the AutoGen lineage. It is the project MassGen's own README cites as a direct predecessor — the "multi-agent conversation" idea in AG2 is part of what MassGen builds on.

   If you are choosing today: AG2 for the AutoGen-style API with active development, Microsoft Agent Framework for the new Microsoft-stack story, and AutoGen itself only for existing codebases pinned to it.

This page compares MassGen with the AutoGen / AG2 lineage. Where AutoGen and AG2 differ, the differences are called out.

.. contents:: On This Page
   :local:
   :depth: 2

Overview
--------

.. list-table::
   :header-rows: 1
   :widths: 18 41 41

   * - Aspect
     - MassGen
     - AutoGen / AG2
   * - **Primary Goal**
     - Parallel coordination of agents on the same task with voting and consensus
     - Multi-agent conversation: agents and tools exchange messages to solve a task
   * - **Architecture**
     - All agents tackle the full task in parallel and converge through voting
     - ``ConversableAgent`` base + group chat / swarm / nested chats / society-of-mind patterns
   * - **Maintenance**
     - Actively developed with regular releases
     - **AutoGen:** maintenance only (successor: Microsoft Agent Framework). **AG2:** actively developed.

Architecture & Coordination Model
---------------------------------

Both **AutoGen** and **AG2** model multi-agent work as a *conversation*. The shared lineage gives them a common shape:

- ``ConversableAgent`` is the base abstraction — agents send and receive messages.
- Group chat coordinates multiple agents through a *speaker selection* policy (round-robin, manager-chosen, etc.).
- Higher-level patterns (swarms, nested chats, society-of-mind) compose conversations into richer flows.
- Tools are registered as Python functions and exposed to agents; MCP servers are supported via extensions.
- Termination is rule-based (max turns, sentinel message, predicate) — there is no native voting / consensus primitive.

AutoGen layers this as Core / AgentChat / Extensions APIs and also ships AutoGen Studio (a no-code GUI). AG2 keeps the same conceptual model but emphasizes open governance ("AgentOS" branding) and is iterating on the API independently of Microsoft.

**MassGen** runs all agents in parallel on the *same* task. Coordination is voting-based: at each step every agent decides between submitting a new answer or voting for an existing one. The orchestrator detects consensus automatically and the winner presents.

In one line: AutoGen / AG2 model multi-agent work as a *conversation* where turn-taking is the control primitive. MassGen models it as *parallel attempts with collective validation* where voting is the control primitive. Both are valid; they optimize for different shapes of problem.

Feature Comparison
------------------

.. list-table::
   :header-rows: 1
   :widths: 22 22 22 34

   * - Feature
     - MassGen
     - AutoGen / AG2
     - Notes
   * - **License**
     - Apache 2.0
     - AutoGen: MIT (code) / CC-BY-4.0 (docs). AG2: Apache 2.0 with original MIT components.
     - Both lineages fully open source for self-hosted use
   * - **Languages**
     - Python
     - AutoGen: Python, .NET / C#. AG2: Python.
     - AutoGen's .NET track is one reason to prefer it on the Microsoft stack
   * - **CLI**
     - ✅ ``massgen``, ``massgen --automation``, ``massgen --web``
     - AutoGen: ``autogenstudio ui``. AG2: Python-first; CLI present but less emphasized.
     - Different focuses
   * - **Python API**
     - ✅ Async API
     - ✅ Core, AgentChat, Extensions (AutoGen); ``ConversableAgent`` + orchestration patterns (AG2)
     - Both layered; pick the level you want
   * - **WebUI / Studio**
     - ✅ Side-by-side agent panels with live streaming and vote/consensus view
     - AutoGen Studio (no-code GUI; docs note it is not production-ready without extra hardening)
     - Different roles
   * - **MCP tools**
     - ✅ First-class on every backend (Claude, Codex, Gemini, OpenAI-compatible, Grok, Claude Code SDK)
     - ✅ MCP server support via extensions in both AutoGen and AG2
     - Both work
   * - **Model providers**
     - 10+ direct backends with per-agent heterogeneity (Claude, Gemini, GPT, Grok, Azure, LM Studio, OpenRouter, Codex, Claude Code SDK)
     - OpenAI primary; other providers via extension clients / generic ``LLMConfig``
     - MassGen's backend matrix is broader and first-class
   * - **Voting / consensus**
     - ✅ Core mechanism; agents vote, winner presents
     - ❌ Not built in (group chat uses speaker selection + termination, not voting)
     - This is the central design difference
   * - **Maintenance**
     - Active development
     - AutoGen: maintenance only. AG2: active.
     - Affects long-term roadmap, not current functionality
   * - **Successor / continuation**
     - n/a
     - AutoGen → `microsoft/agent-framework <https://github.com/microsoft/agent-framework>`_ (Python + .NET, graph-based; migration paths from both AutoGen and Semantic Kernel). AG2 is the community continuation.
     - For new work, evaluate AG2 (Python-first) or Microsoft Agent Framework (Python + .NET)

Voting and Consensus (the MassGen Differentiator)
-------------------------------------------------

AutoGen and AG2 group chats pick the *next speaker*; MassGen's protocol picks the *winner*. The two are not the same:

- Speaker selection is a *turn-taking* mechanism — useful when one agent's output is the input to the next.
- MassGen's voting is a *selection* mechanism — useful when you want N agents to attempt the same thing and the system to identify the strongest answer.

If your task is genuinely conversational (an agent asks another agent to do something, they trade messages, the chat terminates on a condition), AutoGen / AG2 is well-shaped for it. If your task benefits from many parallel attempts converging on the best answer, MassGen is purpose-built for it.

When to Use Each
----------------

**Choose AG2 when you need:**

- An *AutoGen-style API* (``ConversableAgent``, group chats, swarms, nested chats) with active community-led development.
- An open governance model independent of any single corporate steward.
- Compatibility with the broader AutoGen ecosystem of notebooks and patterns.

**Choose Microsoft AutoGen when you need:**

- Compatibility with an existing AutoGen codebase you cannot migrate.
- The .NET / C# code path alongside Python on the Microsoft stack. (Note: for new Microsoft-stack work, Microsoft Agent Framework is the recommended forward path.)

**Choose MassGen when you need:**

- *Parallel attempts + voting* as a first-class control flow with iterative refinement.
- Side-by-side live visualization of every agent's reasoning and answer.
- Heterogeneous backends per agent (Claude + Gemini + GPT + Grok all on the same task).
- An actively developed open-source project with regular releases and a broad backend matrix.

Related
-------

- :doc:`crewai` — role-based decomposition framework
- :doc:`langgraph` — graph-based orchestration substrate
- :doc:`../comparisons` — back to comparisons hub
