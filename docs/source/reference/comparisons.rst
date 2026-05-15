==================================
MassGen vs Other Multi-Agent Tools
==================================

This page compares MassGen with other multi-agent and multi-LLM tools to help you understand when MassGen is the right choice for your use case.

.. contents:: On This Page
   :local:
   :depth: 2

MassGen vs LLM Council
----------------------

`LLM Council <https://github.com/karpathy/llm-council>`_ is a weekend project by Andrej Karpathy that queries multiple LLMs and synthesizes their responses through peer review.

Overview
^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * - Aspect
     - MassGen
     - LLM Council
   * - **Primary Goal**
     - Multi-agent coordination with tools, voting, and consensus
     - Multi-model response aggregation with peer review
   * - **Architecture**
     - Agents work in parallel, observe each other, vote on answers
     - 3-stage pipeline: individual responses → peer ranking → chairman synthesis
   * - **Maintenance**
     - Actively maintained with regular releases
     - Self-described "weekend hack", no ongoing support

Feature Comparison
^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1
   :widths: 25 20 20 35

   * - Feature
     - MassGen
     - LLM Council
     - Notes
   * - **Web UI**
     - ✅ Side-by-side agent panels
     - ✅ Tabbed responses
     - MassGen shows all agents simultaneously; LLM Council uses tabs
   * - **CLI Interface**
     - ✅ Rich terminal UI
     - ❌
     - MassGen has interactive terminal
   * - **Python API**
     - ✅ Full async API
     - ❌
     - MassGen integrates with LiteLLM as a custom provider
   * - **Tool Use (MCP)**
     - ✅ Web search, code execution, file ops
     - ❌
     - MassGen agents can use tools to solve complex tasks
   * - **Voting/Consensus**
     - ✅ Natural voting mechanism
     - ✅ Peer ranking
     - Different approaches: MassGen uses voting; LLM Council uses rankings
   * - **Model Backends**
     - ✅ 10+ backends (OpenRouter, OpenAI, Claude, Gemini, Grok, Azure, LM Studio, etc.)
     - ✅ OpenRouter only
     - MassGen supports direct API calls + local models; LLM Council routes everything through OpenRouter
   * - **Code Execution**
     - ✅ Sandboxed Python/Bash
     - ❌
     - MassGen can run and verify code
   * - **File Operations**
     - ✅ Project integration with permissions
     - ❌
     - MassGen can read/write files in your codebase
   * - **Custom Tools**
     - ✅ YAML or code-based
     - ❌
     - Define your own tools for agents to use
   * - **Real-time Streaming**
     - ✅ Live token streaming
     - ⚠️ Stage-level SSE
     - MassGen streams tokens as generated; LLM Council streams stage completion events

UI Comparison
^^^^^^^^^^^^^

**LLM Council UI:**

- ChatGPT-style interface with conversation sidebar
- Tabbed view to see individual model responses one at a time
- Sequential stages: Stage 1 (responses) → Stage 2 (rankings) → Stage 3 (synthesis)
- Shows "Running Stage 1: Collecting individual responses..." during processing

**MassGen Web UI:**

- Side-by-side panels showing all agents simultaneously
- Real-time status badges (Working, Done) for each agent
- Live streaming of agent responses as they work
- MCP tool connection status visible per agent
- Answer count and vote tracking in the header
- Toast notifications for new answers
- Dark/light theme support
- Coordination progress indicator with cancel option

When to Use Each
^^^^^^^^^^^^^^^^

**Choose MassGen when you need:**

- Agents that can use tools (web search, code execution, file operations)
- Side-by-side visualization of all agents working simultaneously
- Integration with your codebase or external systems
- A CLI interface or Python API
- Active development and support
- Complex multi-step problem solving

**Choose LLM Council when you need:**

- Simple multi-model response comparison
- Quick anonymous peer ranking of responses
- A lightweight "vibe coded" solution you can fork and modify
- Focus on text-only Q&A without tool requirements

Technical Architecture Differences
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**LLM Council's 3-Stage Pipeline:**

1. **Stage 1**: All models receive the query independently
2. **Stage 2**: Each model ranks other responses (anonymized as "Response A, B, C...")
3. **Stage 3**: A "Chairman" model synthesizes the final answer

**MassGen's Parallel Coordination:**

1. All agents receive the query and work in parallel
2. Agents can see recent answers from other agents at each step
3. Agents choose to provide a new answer OR vote for an existing answer
4. When agents provide answers, their workspace is shared
5. Coordination continues until consensus (all agents vote)
6. The agent with the most votes presents the final answer

The key difference: LLM Council uses a fixed 3-stage pipeline with a designated chairman, while MassGen uses dynamic coordination where agents naturally converge on the best solution through voting.

More Comparisons
----------------

Dedicated comparison pages for the most common "MassGen vs …" questions:

- :doc:`comparisons/crewai` — role-based decomposition with a hosted control plane
- :doc:`comparisons/langgraph` — low-level graph orchestration with the LangChain stack
- :doc:`comparisons/autogen` — multi-agent conversations (Microsoft AutoGen and the community AG2 continuation)

.. toctree::
   :hidden:
   :maxdepth: 1

   comparisons/crewai
   comparisons/langgraph
   comparisons/autogen
