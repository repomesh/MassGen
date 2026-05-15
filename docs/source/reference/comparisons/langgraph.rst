=====================
MassGen vs LangGraph
=====================

`LangGraph <https://github.com/langchain-ai/langgraph>`_ is LangChain's low-level orchestration framework for stateful, graph-based agent workflows (MIT, ~32K GitHub stars as of May 2026). It powers production agents built on the LangChain stack and is paired with the commercial *LangSmith Studio* / *LangGraph Platform* for visual prototyping, deployment, and observability.

This page compares LangGraph with MassGen. The two operate at very different levels of abstraction — LangGraph is a graph runtime, MassGen is a coordination protocol. They are often complementary rather than substitutes.

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
     - LangGraph
   * - **Primary Goal**
     - Parallel multi-agent coordination through voting and consensus on the same task
     - Low-level orchestration of stateful graphs of nodes (agents, tools, branches, retries)
   * - **Architecture**
     - All agents tackle the full task in parallel and converge through voting
     - Explicit ``StateGraph`` of nodes and edges with durable execution and persistent state
   * - **Hosted product**
     - Open source only
     - Open source SDK + *LangGraph Platform* / *LangSmith Studio* for deployment and visual debugging

Architecture & Coordination Model
---------------------------------

**LangGraph** is a graph runtime. You define a typed state, a set of nodes (functions / agents / tools), and edges (conditional branches, parallel fan-outs, loops). The runtime executes the graph, persists state, supports human-in-the-loop interrupts, and can resume from failures. Coordination patterns — supervisor, swarm, plan-and-execute, debate — are *encodings* in the graph, not first-class primitives.

**MassGen** is a coordination *protocol*. Agents run in parallel on the same task, observe each other's most recent answers, and choose between "answer" and "vote." The protocol guarantees the orchestrator can detect consensus and pick a winner deterministically. Refinement is bounded by the protocol, not by a graph the user has to author.

In one line: LangGraph gives you the substrate to build any agent topology. MassGen gives you one specific topology — parallel attempts plus voting — implemented end-to-end with a TUI, WebUI, and backend matrix.

Feature Comparison
------------------

.. list-table::
   :header-rows: 1
   :widths: 25 20 20 35

   * - Feature
     - MassGen
     - LangGraph
     - Notes
   * - **License**
     - Apache 2.0
     - MIT
     - Both fully open source for self-hosted use
   * - **Abstraction level**
     - High — pre-built coordination protocol
     - Low — author your own graph
     - Different products; LangGraph is closer to a workflow runtime than an agent framework
   * - **CLI**
     - ✅ ``massgen``, ``massgen --automation``, ``massgen --web``
     - ✅ ``langgraph`` CLI for the LangGraph Platform / Studio
     - Different focuses
   * - **Python API**
     - ✅ Async API
     - ✅ Python and JS/TS APIs
     - LangGraph's API is broader by virtue of being multi-language
   * - **WebUI**
     - ✅ Side-by-side agent panels, live streaming, vote/consensus view
     - ✅ LangSmith Studio for graph visualization, traces, debugging
     - Studio focuses on *graph* execution; MassGen WebUI focuses on *parallel agents* + voting
   * - **MCP tools**
     - ✅ First-class on every backend
     - ✅ Via the ``langchain-mcp-adapters`` bridge (converts MCP tools to LangChain ``BaseTool``)
     - Both work; LangGraph's path goes through LangChain's tool abstraction
   * - **Model providers**
     - 10+ direct backends including Claude Code SDK + Codex; per-agent heterogeneity
     - Whatever LangChain integrates (extensive)
     - LangChain's integration surface is the largest in the ecosystem
   * - **Voting / consensus**
     - ✅ Core mechanism
     - ❌ Not built in (you can implement it as a node)
     - This is the central design difference
   * - **Durable execution**
     - Workspace snapshots, status files, checkpoint MCP for save/restore
     - ✅ Durable state, checkpoints, resume-after-failure as first-class features
     - LangGraph is the more general purpose runtime here
   * - **Hosted platform**
     - ❌
     - ✅ LangGraph Platform / LangSmith Studio
     - Use LangGraph if you want a managed deployment + observability stack

Voting and Consensus (the MassGen Differentiator)
-------------------------------------------------

LangGraph can *express* a voting topology — define N parallel agent nodes, fan out, then a reducer node that picks a winner. It does not *provide* one. That means:

- You decide when to stop iterating (loop condition vs. quality criteria).
- You write the reducer logic (majority? weighted? based on a verifier?).
- You wire the visualization to surface "this is what each agent said and who won" yourself.

MassGen ships all of the above as a single product: streaming side-by-side panels, vote arrows in the WebUI consensus map, checklist-gated criteria, and a TUI consensus visualization. If parallel + voting is the *primary* thing you want, MassGen is purpose-built for it. If voting is one of many topologies your system needs alongside ETL, branching, and tool-heavy flows, LangGraph is the better substrate.

When to Use Each
----------------

**Choose LangGraph when you need:**

- *Arbitrary agent topologies* you author yourself (supervisor, swarm, plan-execute, custom).
- Durable, resumable execution as a first-class concern (long-running flows, human approvals).
- Tight LangChain ecosystem integration (vector stores, retrievers, evaluators, deployment via LangGraph Platform).

**Choose MassGen when you need:**

- A pre-built *parallel + voting* coordination protocol you don't have to reimplement.
- Heterogeneous backends per agent on the same task (Claude + Gemini + GPT + Grok, etc.).
- A polished TUI / WebUI showing all agents working simultaneously and their consensus path.
- A local-first stack without a managed deployment platform dependency.

LangGraph and MassGen are at different levels and can be combined: MassGen can be invoked as a tool / subgraph from a larger LangGraph workflow when a particular step benefits from parallel attempts and voting.

Related
-------

- :doc:`crewai` — role-based decomposition framework
- :doc:`autogen` — multi-agent conversations (in maintenance mode; see successor)
- :doc:`../comparisons` — back to comparisons hub
