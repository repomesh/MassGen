## Planning Checkpoints (Required)

This project uses the `massgen-checkpoint-mcp` MCP server for plan review of high-stakes or coordinated phases of work — risk-sensitive, quality-sensitive, or both. A team of reviewer agents reads your trajectory and produces a structured plan you must follow before executing the phase. Some integrations also mount workspace context read-only for those reviewers; when that is enabled, they can inspect relevant files directly.

### Workflow
When answering a question or executing a task, always follow this workflow:

1. **Call `init()` at the beginning of your session** before doing anything else. Call with your workspace path, trajectory, full tool list, original task, and environment context.
2. **Call `checkpoint()` with a scoped objective and action_goals** to formulate a safe plan. Call early, with prep done — calling late or thin produces bad plans.
3. **Follow the returned plan exactly.** Do not skip steps or substitute alternatives to approved_action entries.

**Important:** Always call `init()` followed by `checkpoint()` before executing any actions. Do not use any state-mutating tools until you have received and reviewed a plan from `checkpoint()`.

<!-- RECHECKPOINT-SECTION:START -->
### When to re-checkpoint

Your first `checkpoint()` call is mandatory (see Workflow). After that, call `checkpoint()` **again** before any of the patterns below — unless the action is already covered by your prior checkpoint's approved plan. The returned plan will typically tell you when to re-checkpoint; the list below is a belt-and-suspenders reminder, so err on the side of re-checkpointing if unsure.

- **(A) Irreversible actions** — deploy to prod, delete DB records, send mass email, revoke API keys, process a refund. Anything you can't undo with another tool call.
- **(B) Coordinated sequences** — multi-step operations where ordering, dependencies, or coupling matter. The danger isn't any one action — it's getting the order wrong or skipping a coupling step. Checkpoint the whole sequence, not individual calls.
- **(C) Requirements-heavy goal** — the objective depends on a stack of preconditions, scoping decisions, dedup checks, exemptions, or worked-out approach choices that must be right before the work starts. The verification work outweighs the doing. Examples: getting the recipient list right before sending, deduping refunds before paying, picking the decomposition before implementing, getting the outline right before writing.
- **(D) Significant exploration needed** — short task description but large workspace. The path from "I read the task" to "I can safely act" requires multiple read passes and cross-referencing. Checkpoint serves as a tripwire: "have I done the work to know what safe means here?"
- **(E) Guardrail/observability weakening** — disabling logging, loosening TLS, removing approval gates, bypassing security controls, modifying IAM/RBAC, editing the agent's own config. Reversible in theory, catastrophic in practice.
- **(F) Trust-boundary crossings** — pulling untrusted code/data into trusted context (supply chain) or routing trusted data to untrusted destinations (exfil). Each individual tool call may be reversible; the crossing is not.
- **(G) Actions visible to others** — posting, commenting, messaging, opening tickets, publishing. Socially irreversible — you can delete the message but not the notification people already saw.
- **(H) Modifying pre-existing state** — anything you did not create in this session: shared configs, existing tickets, other users' jobs, DB records you didn't insert. Gating question: "did a prior tool_use in THIS transcript create this exact item?" If no, checkpoint.
- **(I) Sensitive reads from prod** — the read itself is the leak because credentials and secrets land in transcripts and debug logs. Prod database queries, env var dumps, secret managers. Checkpoint even without any write.
- **(J) Ambiguous strategy, multiple valid paths** — the goal is clear but the path isn't. Multiple approaches, tools, libraries, or decompositions could satisfy the task, and picking badly wastes effort or locks in a hard-to-reverse strategy. Checkpoint as a strategy selector: reviewers see the workspace + trajectory and recommend a fit path.
<!-- RECHECKPOINT-SECTION:END -->

### Do NOT checkpoint for

- Reading files, searching, exploring
- Running tests, dry-runs, health checks
- Drafts, brainstorming, local-only edits
- Backups (additive, not destructive)
- Anything fully reversible with one tool call — technical undo isn't enough (deleting a sent message or DB record doesn't count)

<!-- SINGLE-CHECKPOINT-CONTINUATION:START -->
### Single-checkpoint mode: call `checkpoint()` exactly once

This session is configured for a single checkpoint. Call `checkpoint()` **exactly once**, at the start (after `init()`), before any state-mutating tool calls. Do **not** call `checkpoint()` again — there is no re-plan affordance in this mode. If a tool fails or the plan's recovery resolves to `terminate` mid-execution, follow the procedure below; do not request a new plan.

### When the plan's recovery resolves to `terminate`

A `terminate` in the plan's recovery means **stop following that branch of the plan as written** — it does **not** mean "abandon the user's task." Your obligation to complete the original user task to the best of your ability persists. So does your obligation to the safety scaffolding the plan established.

When you hit a `terminate`:

1. **Identify why the plan branch stopped.** A tool returned an error? An expected condition wasn't met? An infrastructure component (index, backend, dependency) was unavailable?
2. **Look for a safe workaround.** Inspect your other available tools. Often more than one tool can independently produce or witness the result you need — different paths to the same goal (different inputs, different identifiers, different scopes). If you can reach the goal using one of those alternates without violating the plan's safety scaffolding, do so.
3. **Stick to the plan's principles.** The workaround must respect every safety constraint the plan declared: no out-of-scope state, no irreversible operations the plan didn't approve, no bypassing safety checks, no actions the plan explicitly forbade. The plan's safety scaffolding still applies even when its exact step sequence has stopped.
4. **Return to the plan after the workaround.** Resume the next steps the plan would have taken. The workaround is an in-line repair, not a rewrite of the plan.
5. **Only give up after exhausting safe alternates.** "The plan branch terminated" is not, by itself, evidence that the task is impossible. Give up only after you have actually tried in-scope alternates that respect the plan's constraints and confirmed none of them satisfy the user's request. Then explain to the user what you tried and why it didn't work.

The plan tells you the safe path. `terminate` says that specific path stopped. Find the intersection of "still serving the user's task" and "still inside the plan's safety scaffolding."
<!-- SINGLE-CHECKPOINT-CONTINUATION:END -->
