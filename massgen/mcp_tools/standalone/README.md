# Standalone MCP Servers

Self-contained MCP tool servers that register as subprocesses with an
MCP-compatible harness (Claude Code, Claude Desktop, Codex, etc.) to add
capabilities to the main agent.

| Server | Purpose |
|---|---|
| `checkpoint_mcp_server.py` | **Checkpoint planner.** Delegates plan review to a MassGen reviewer team before the main agent enters a high-stakes or coordinated phase (risk-sensitive, quality-sensitive, or both). Returns a structured plan with constraints, approved actions, and recovery trees. See full guide below. |
| `media_server.py` | Exposes MassGen's multimodal generation tools (`generate_media`, `read_media`) with explicit parameters. |
| `quality_server.py` | Exposes MassGen quality-evaluation tools (`generate_eval_criteria`, `submit_checklist`, `draft_approach`, `reset_evaluation`). |
| `workflow_server.py` | Exposes MassGen's `new_answer` and `vote` workflow tools. `new_answer` snapshots deliverables per round. |

---

# Checkpoint MCP (`massgen-checkpoint-mcp`)

## What it does

Sits between a main agent (the "executor") and its high-stakes tool calls. When the executor is about to enter a coordinated or consequential phase — deploy to production, delete records, send a mass email, issue a refund, or pick the strategy/decomposition for a complex task — it calls `checkpoint()` with an objective. The checkpoint server spawns a MassGen sub-run: a small team of reviewer agents (configurable, typically 3) reads the executor's trajectory, explores the workspace read-only, and collectively produces a structured plan the executor must follow.

The returned plan is a list of steps with: `description`, optional `constraints`, optional `approved_action` (tool name + exact args), and an optional `recovery` tree (`if`/`then`/`else` with bare terminals: `proceed` / `recheckpoint` / `refuse`). The executor is expected to follow the plan step-by-step.

## Flow

```
Executor agent
    │
    ├─ init(workspace_dir, trajectory_path, available_tools[, safety_policy])
    │       ↓
    │   (server stores session context)
    │
    └─ checkpoint(objective, action_goals?, eval_criteria?)
            │
            ├─ merge eval_criteria with session safety_policy
            │
            ├─ build per-call USER prompt (objective + tools + action_goals + schema)
            │
            ├─ write subrun config YAML with:
            │     ─ checklist_criteria_inline  ← merged criteria
            │     ─ context_paths               ← read-only mount of workspace
            │     ─ checkpoint_enabled: false   ← no recursion
            │
            ├─ spawn `uv run massgen --automation ...` as subprocess
            │     │
            │     ├─ reviewer agents read trajectory + explore workspace
            │     ├─ each produces a plan draft
            │     ├─ vote via checklist_gated flow against the criteria
            │     └─ winner's `checkpoint_result.json` becomes the returned plan
            │
            └─ return validated plan to executor
```

## Installation (Claude Code)

Register the server once per project (or once globally) with `claude mcp add`. Environment variables go inline via `-e KEY=VALUE`.

### Minimal setup

```bash
claude mcp add massgen-checkpoint-mcp -- \
  uv --directory /path/to/MassGen run massgen-checkpoint-mcp \
     --config /path/to/your/checkpoint_config.yaml
```

Replace `/path/to/MassGen` with the MassGen checkout and `/path/to/your/checkpoint_config.yaml` with a config that defines the reviewer agents (see [Config file](#config-file-checkpoint_configyaml) below).

### With live web UI (auto-open browser)

```bash
claude mcp add massgen-checkpoint-mcp \
  -e MASSGEN_CHECKPOINT_WEB_UI=auto \
  -- uv --directory /path/to/MassGen run massgen-checkpoint-mcp \
     --config /path/to/your/checkpoint_config.yaml
```

Every checkpoint call will spawn a MassGen sub-run that serves the live coordination view at `http://127.0.0.1:8000/`, and your default browser will open to it automatically.

### With web UI, no auto-open

```bash
claude mcp add massgen-checkpoint-mcp \
  -e MASSGEN_CHECKPOINT_WEB_UI=view \
  -- uv --directory /path/to/MassGen run massgen-checkpoint-mcp \
     --config /path/to/your/checkpoint_config.yaml
```

The URL is printed to the MCP server's stderr when the sub-run starts; open it manually.

### Changing settings later

`claude mcp add` overwrites the existing entry, so just re-run it with different `-e` flags. Or edit `.mcp.json` directly. Restart Claude Code after any change so the MCP server picks up the new environment.

### Add checkpoint instructions to your project

The MCP tool description tells the model *how* to use checkpoint, but nothing in the model's base instructions makes it a requirement. Run `massgen-checkpoint-setup` to inject a managed instructions block into your project's `CLAUDE.md`:

```bash
# From your project directory (MassGen installed as dependency)
uv run massgen-checkpoint-setup                          # patches ./CLAUDE.md
uv run massgen-checkpoint-setup --target ./AGENTS.md     # or a different file

# From a local MassGen checkout (not installed)
# NOTE: uv --directory changes cwd, so --target with an absolute path is required
uv --directory /path/to/MassGen run massgen-checkpoint-setup --target "$(pwd)/CLAUDE.md"
```

This inserts a `<!-- MASSGEN-CHECKPOINT:START -->` / `<!-- MASSGEN-CHECKPOINT:END -->` managed block with the categories (A–J) that require checkpointing, the correct workflow order (`init` → investigate → `checkpoint` → execute), and the exclusion list. Re-running the command updates the block to the latest version without touching the rest of the file.

---

## Environment variables

All variables are read per-sub-run at spawn time, not at MCP-server startup. Claude Code sets them for the MCP server subprocess via the `env` field in `.mcp.json` (populated by `claude mcp add -e`).

| Variable | Values | Default | Effect |
|---|---|---|---|
| `MASSGEN_CHECKPOINT_WEB_UI` | `auto` / `view` / unset | unset | `auto`: enable the web UI and auto-open the browser. `view`: enable the web UI, print the URL, don't open a browser. unset: no web UI (current terminal UI only). |
| `MASSGEN_CHECKPOINT_WEB_PORT` | integer | `8000` | Port to bind the web UI to. Override when running concurrent sub-runs to avoid collisions. |
| `MASSGEN_CHECKPOINT_WEB_HOST` | string | `127.0.0.1` | Host to bind the web UI to. Localhost-only by default; set to `0.0.0.0` if you need remote access. |

### Caveats

- **Port collision:** multiple concurrent checkpoint calls all try to bind the same port. Either run them serially or override `MASSGEN_CHECKPOINT_WEB_PORT` per shell / per caller.
- **Localhost:** the web UI must be reachable from the machine running `claude mcp add`. If you're running in a container or over SSH, set `MASSGEN_CHECKPOINT_WEB_HOST=0.0.0.0` and tunnel the port.
- **Wizard bypass is automatic:** when the sub-run uses `--automation` (it always does), the server-side `/api/setup/status` endpoint reports `needs_setup: false`. You land directly on the live coordination view instead of the first-run setup wizard.

---

## Config file (`checkpoint_config.yaml`)

The `--config` arg points at a YAML file that defines the reviewer agents and the orchestrator behavior for every checkpoint sub-run. Required pieces:

```yaml
agents:
  - id: agent_a
    backend:
      type: claude_code          # or any other supported backend
      model: claude-sonnet-4-6
      # ... backend-specific config
  - id: agent_b
    backend:
      type: claude_code
      model: claude-sonnet-4-6
  - id: agent_c
    backend:
      type: claude_code
      model: claude-sonnet-4-6

orchestrator:
  voting_sensitivity: checklist_gated     # required — enables native eval criteria
  voting_threshold: 3                     # unanimous for 3 agents
  max_new_answers_per_agent: 1            # one answer per agent per round
  defer_voting_until_all_answered: true   # lockstep rounds
  fairness_enabled: true
  skip_final_presentation: true           # return winner directly, no extra pass
  coordination:
    max_orchestration_restarts: 0
    fast_iteration_mode: true
  context_paths: []                       # checkpoint MCP injects read mount at runtime

timeout_settings:
  orchestrator_timeout_seconds: 3600
  initial_round_timeout_seconds: 1200
  subsequent_round_timeout_seconds: 900
```

**Why `voting_sensitivity: checklist_gated`:** this is what activates MassGen's native `EvaluationSection`, which renders the safety criteria you pass via `eval_criteria` into each agent's system prompt with structured `E1`/`E2` labels and wires them into the `submit_checklist` scoring tool. Without it, the criteria have nowhere to go.

**Why `defer_voting_until_all_answered: true`:** enforces lockstep rounds — the orchestrator waits for every agent to produce an answer before voting starts. Combined with `max_new_answers_per_agent: 1` you get "everyone produces one plan, then we vote", which is the right behavior when the criterion is "the plan is safe" rather than "the plan is the best-scoring".

**`checkpoint_enabled: false`** is forced by the checkpoint MCP at sub-run time to prevent reviewer recursion — you don't need to set it in the file.

The checkpoint MCP injects `checklist_criteria_inline`, `context_paths`, and `checkpoint_enabled: false` into the generated sub-run config automatically. Whatever you put in your base `checkpoint_config.yaml` for those fields will be overwritten per call.

---

## Tool API

The MCP server exposes two tools to the main agent: `init` and `checkpoint`. Both are deliberately brief in parameters — most configuration lives in the YAML and env vars above.

### `init(workspace_dir, trajectory_path, available_tools, safety_policy?)`

Call once per session, before any `checkpoint` calls.

| Param | Type | Purpose |
|---|---|---|
| `workspace_dir` | str | Absolute path to the executor's project directory. Mounted read-only into the reviewer sub-run as a context path so reviewers can explore it. |
| `trajectory_path` | str | Absolute path to a log file containing the executor's tool-call history so far. Reviewers read this to understand what has already happened. For Claude Code, a `SessionStart` hook can write `.claude/current_session.json` with the current session's transcript path. |
| `available_tools` | list[dict] | **The COMPLETE list of every tool the executor can call.** Each entry must have `name`, `description`, and `input_schema` (raw JSON schema dict OR a compact signature string like `(table: str, filter: str, dry_run: bool=False)`). Do NOT include `mcp__massgen-checkpoint-mcp__*` tools — those are the scaffolding itself, not capabilities to review. Under-reporting tools distorts the reviewers' assessment and can hide better strategies. |
| `safety_policy` | list[str or dict] (optional) | Custom safety rules that augment the built-in `DEFAULT_SAFETY_POLICY`. Strings are auto-wrapped as `{text: str, category: "primary"}`; dicts can use the full `checklist_criteria_inline` shape (`text`, `category`, `verify_by`, `anti_patterns`, `score_anchors`). Stored in session state and applied to every subsequent `checkpoint` call. |

### `checkpoint(objective, action_goals?, eval_criteria?)`

Call before any coordinated phase that's risk-sensitive, quality-sensitive, or both.

| Param | Type | Purpose |
|---|---|---|
| `objective` | str | The complete outcome you want to reach and the steps you plan to take for this phase. Include the full sequence — the team needs end-to-end context. **Do NOT restate evaluation criteria here**; use `eval_criteria` for those. |
| `action_goals` | list[dict] (optional) | Specific actions within the objective that need explicit tool-level approval. Each entry: `{id, goal, preferred_tools?, constraints?}`. The returned plan will map each goal to an `approved_action` with concrete tool name + args. |
| `eval_criteria` | list[str or dict] (optional) | Task-specific requirements beyond the session defaults — safety concerns, quality rubrics, strategy constraints, or anything else the reviewers should score against. Merged with the `safety_policy` passed to `init` and injected into the sub-run as `checklist_criteria_inline`. |

Returns a JSON object with `status: "ok"`, the validated `plan` array, `execution_time_seconds`, and `logs_dir` pointing at the preserved sub-run directory under `.massgen/checkpoint_runs/session_<TIMESTAMP>/ckpt_<N>/`.

When to call `checkpoint`, how to scope the phase, and what to put in each parameter is documented in detail in the `checkpoint` tool's own description — read that from the main agent's side.

---

## Artifacts on disk

Each sub-run leaves a complete audit trail at:

```
<workspace_dir>/.massgen/checkpoint_runs/session_<TIMESTAMP>/
  ckpt_001/
    _checkpoint_config.yaml          ← generated subrun config
    .checkpoint/trajectory.log       ← copied-in executor trajectory
    validate_plan.py                 ← schema validator shipped to agents
    .massgen/massgen_logs/.../       ← per-agent logs, snapshots, final answers
       └── turn_*/attempt_*/final/<winner>/workspace/checkpoint_result.json
  ckpt_002/
    ...
```

The `checkpoint_result.json` in the `final/<winner>/workspace/` path is the plan the MCP returns to the executor. Everything else is inspection material.

---

## Common issues

- **"No output produced by checkpoint agents"** — the reviewer team failed to produce a valid `checkpoint_result.json`. Check `logs_dir` in the error response for the per-agent logs. Often caused by a tool list without `input_schema`, which leaves reviewers unable to write concrete `approved_action` entries.
- **Invalid plan output: recovery tree** — an agent wrote a terminal like `"proceed — log result"` instead of the bare `"proceed"`. The validator is strict. The per-agent logs under `snapshots/` will show which agent drifted.
- **Subrun times out** — increase `orchestrator_timeout_seconds` in the config, or split the phase into smaller checkpoints.
- **Web UI shows setup wizard** — pick up recent MassGen; `/api/setup/status` now returns `needs_setup: false` in automation mode. Restart Claude Code to relaunch the MCP server with the updated MassGen.
- **`@commit_sha` parsed as a context path** — fixed in `subrun_utils.py` via `--no-parse-at-references`. Pick up recent MassGen.
