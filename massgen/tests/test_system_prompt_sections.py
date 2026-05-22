"""Tests for agent identity isolation in system prompt sections."""

from massgen.system_prompt_sections import (
    _CHECKLIST_ITEMS,
    CommandExecutionSection,
    FilesystemBestPracticesSection,
    FilesystemOperationsSection,
    MemorySection,
    OutputFirstVerificationSection,
    TaskContextSection,
    TaskPlanningSection,
    _build_checklist_analysis,
    _build_checklist_gated_decision,
)


def test_workspace_tree_hides_real_agent_id():
    """Shared reference path should not contain real agent_id."""
    section = FilesystemOperationsSection(
        main_workspace="/ws/token_abc123",
        temp_workspace="/tmp/token_abc123",
        agent_answers={"agent_a": "answer"},
        agent_mapping={"agent_a": "agent1"},
    )
    content = section.build_content()
    assert "agent_a" not in content


def test_hardcoded_examples_do_not_reference_workspace_agent_labels():
    """Example text about 'building on others work' should not say agent1's/agent2's."""
    section = FilesystemOperationsSection(
        main_workspace="/ws/abc",
        temp_workspace="/tmp/abc",
        agent_answers={"agent_a": "x", "agent_b": "y"},
        agent_mapping={"agent_a": "agent1", "agent_b": "agent2"},
    )
    content = section.build_content()
    # Should not have "agent1's" or "agent2's" in the building-on-others section
    assert "agent1's" not in content
    assert "agent2's" not in content


def test_checklist_analysis_includes_visual_comparison_guidance():
    """Cross-answer synthesis should instruct agents to compare visual outputs
    with read_media using named multi-image inputs rather than text summaries."""
    content = _build_checklist_analysis()
    assert "read_media" in content
    assert "visual" in content.lower()
    # Must reference the multi-image files dict pattern
    assert '"files"' in content


def test_checklist_gated_decision_evaluator_guidance_includes_visual_comparison():
    """Evaluator spawn guidance in gated checklist should instruct passing all
    agents' images in one read_media call for grounded cross-agent comparison."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    assert "read_media" in content
    assert "visual" in content.lower()


def test_checklist_gated_decision_requires_blocking_evaluator_execution():
    """Checklist gated flow should require blocking evaluator execution before scoring."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        evaluator_available=True,
    )
    lower = content.lower()
    assert "background=false, refine=false" in lower
    assert "required before scoring" in lower


def test_checklist_gated_decision_round_evaluator_mode_requires_managed_packet_before_submit():
    """Round evaluator mode should consistently describe the orchestrator-managed packet workflow."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        round_evaluator_before_checklist=True,
    )
    lower = content.lower()
    assert "round_evaluator" in content
    assert "criteria_interpretation" in content
    assert "improvement_spec" in content
    assert "very critical" in lower
    assert "sole diagnostic basis" in lower
    assert "before round 2" in lower
    assert "orchestrator" in lower
    assert "do not spawn another round_evaluator yourself" in lower
    assert "do not run a separate self-evaluation pass" in lower
    assert "report_path" in content
    assert "save or copy that round-evaluator report into your workspace" not in lower
    assert "spawn_subagents" not in content
    assert "submit_checklist_args" not in content
    assert "expected_verdict" not in content
    assert "draft_approach_args" not in content
    assert "submit_checklist" in lower


def test_checklist_gated_decision_orchestrator_managed_round_evaluator_mode_requires_packet_before_submit():
    """Managed mode should explicitly say the orchestrator supplies the round-evaluator packet."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        round_evaluator_before_checklist=True,
        orchestrator_managed_round_evaluator=True,
    )
    lower = content.lower()
    assert "orchestrator" in lower
    assert "do not spawn another round_evaluator yourself" in lower
    assert "do not run a separate self-evaluation pass" in lower
    assert "pass that exact path as report_path" in lower
    assert "save or copy that round-evaluator report into your workspace" not in lower


def test_checklist_gated_decision_orchestrator_managed_auto_injection_is_task_driven():
    """Managed mode should teach the auto-injected branch as get_task_plan -> implement -> new_answer."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        round_evaluator_before_checklist=True,
        orchestrator_managed_round_evaluator=True,
    )
    lower = content.lower()
    assert "auto-injected into your task plan" in lower
    assert "get_task_plan" in content
    assert "do not call `submit_checklist`" in content
    assert "do not call `draft_approach`" in content
    assert "do not write a second diagnostic report" in lower
    assert "pure text artifact" in lower
    assert "multiple independent critiques" not in lower


def test_checklist_gated_decision_managed_round_evaluator_declares_primary_path_and_fallback():
    """Managed mode should describe the task-driven branch as the normal path and checklist as degraded fallback."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        round_evaluator_before_checklist=True,
        orchestrator_managed_round_evaluator=True,
    )
    lower = content.lower()
    assert "normal path" in lower
    assert "task-driven" in lower
    assert "degraded fallback" in lower
    assert "fallback" in lower and "submit_checklist" in lower


def test_checklist_gated_decision_managed_round_evaluator_targets_material_self_improvement():
    """Managed mode should frame the evaluator as material self-improvement, not cleanup churn."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        round_evaluator_before_checklist=True,
        orchestrator_managed_round_evaluator=True,
    )
    lower = content.lower()
    assert "material self-improvement" in lower
    assert "transformative thesis shift" in lower or "transformative shift" in lower
    assert "low-value polish" in lower or "minor cleanup" in lower
    assert "local convergence" in lower
    assert "open-ended" in lower


def test_checklist_gated_decision_round_evaluator_transformation_pressure_biases_guidance():
    """Pressure settings should bias boldness while preserving correctness-first single-thesis execution."""
    gentle = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        round_evaluator_before_checklist=True,
        orchestrator_managed_round_evaluator=True,
        round_evaluator_transformation_pressure="gentle",
    )
    aggressive = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        round_evaluator_before_checklist=True,
        orchestrator_managed_round_evaluator=True,
        round_evaluator_transformation_pressure="aggressive",
    )

    gentle_lower = gentle.lower()
    aggressive_lower = aggressive.lower()
    assert "transformation pressure" in gentle_lower
    assert "gentle" in gentle_lower
    assert "current thesis" in gentle_lower
    assert "aggressive" in aggressive_lower
    assert "higher-leverage thesis" in aggressive_lower or "frontier" in aggressive_lower
    assert "stronger justification" in aggressive_lower
    for lower in (gentle_lower, aggressive_lower):
        assert "correctness-critical" in lower
        assert "one committed next-round thesis" in lower or "one committed thesis" in lower


def test_checklist_gated_decision_auto_injection_prioritizes_correctness_then_regression_check():
    """Auto-injected round-evaluator guidance should make correctness-first execution order explicit."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        round_evaluator_before_checklist=True,
        orchestrator_managed_round_evaluator=True,
    )
    lower = content.lower()
    assert "if the task plan includes correctness-critical tasks" in lower
    assert "do those first" in lower
    assert "then execute the remaining higher-order work" in lower
    assert "use explicit correctness criteria when they exist" in lower
    assert "finish with the final preserve/regression verification" in lower


def test_checklist_gated_decision_auto_injection_prefers_background_builder_batches():
    """Managed round-evaluator guidance should prefer async builder batches over blocking launches."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        round_evaluator_before_checklist=True,
        orchestrator_managed_round_evaluator=True,
    )
    lower = content.lower()
    assert "background=true, refine=false" in lower
    assert "independent builder tasks" in lower
    assert "use blocking mode only for evaluator work" in lower
    assert "not for normal builder batches" in lower


def test_checklist_gated_decision_includes_peer_build_copy_guidance():
    """Checklist workflow should explain how to evaluate peer build outputs
    without mutating read-only shared snapshots."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        evaluator_available=True,
    )
    assert "temp_workspaces" in content
    assert ".massgen_scratch/peer_eval/" in content
    assert "npm install" in content


def test_filesystem_best_practices_includes_visual_comparison_guidance():
    """Evaluation bullet in FilesystemBestPracticesSection should guide agents
    to compare peer visual outputs directly rather than from text descriptions."""
    section = FilesystemBestPracticesSection()
    content = section.build_content()
    assert "read_media" in content
    assert "visual" in content.lower()


def test_filesystem_operations_includes_peer_build_copy_guidance():
    """Filesystem operations guidance should instruct copying peer artifacts into
    local scratch before running mutable install/build commands."""
    section = FilesystemOperationsSection(
        main_workspace="/ws/abc",
        temp_workspace="/tmp/abc",
        agent_answers={"agent_a": "x"},
        agent_mapping={"agent_a": "agent1"},
    )
    content = section.build_content()
    assert ".massgen_scratch/peer_eval/" in content
    assert "read-only snapshots" in content
    assert "build in your own workspace copy" in content


def test_task_planning_section_no_subagents_omits_classification_step():
    """Without subagents, STEP 2 classification block should be absent."""
    content = TaskPlanningSection().build_content()
    assert "Classify Every Task for Delegation" not in content
    assert "Available subagent types" not in content
    assert "subagent_type" not in content
    assert '"mode": "delegate"' not in content
    # Step numbering should not reference STEP 3/4 when subagents are absent
    assert "STEP 2 — Execute Every Task" in content
    assert "STEP 3 — Include Task Summary" in content


def test_task_planning_section_with_subagents_includes_classification_step():
    """With subagents present, STEP 2 classification block should appear with type names."""
    from types import SimpleNamespace

    fake_types = [
        SimpleNamespace(name="builder"),
        SimpleNamespace(name="evaluator"),
    ]
    content = TaskPlanningSection(specialized_subagents=fake_types).build_content()
    assert "Classify Every Task for Delegation" in content
    assert "Available subagent types" in content
    assert '"builder"' in content
    assert '"evaluator"' in content
    assert '"mode": "inline"' in content
    assert '"mode": "delegate"' in content
    assert "subagent_type" in content
    assert "subagent_id" in content
    assert "Inline means you execute the task yourself" in content
    # novelty guidance should appear in the classification step
    assert "novelty" in content.lower()
    # Step numbering should use STEP 3/4 when subagents are present
    assert "STEP 3 — Execute Every Task" in content
    assert "STEP 4 — Include Task Summary" in content


def test_checklist_gated_decision_without_subagents_does_not_offer_delegate_execution():
    """Managed round-evaluator guidance should stay inline-only when no subagents are available."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
        round_evaluator_before_checklist=True,
        orchestrator_managed_round_evaluator=True,
        specialized_subagents_available=False,
    )
    lower = content.lower()
    assert "execution.mode" not in content
    assert "spawn_subagents()" not in content
    assert "all injected tasks are inline in this run" in lower


def test_task_planning_section_is_mandatory_for_complex_tasks():
    """Task planning section must state planning is required, not optional."""
    content = TaskPlanningSection().build_content()
    assert "REQUIRED" in content
    assert "draft_approach" in content


def test_task_planning_section_prioritizes_correctness_and_final_regression_verification():
    """Shared planning guidance should order blocker correctness before polish and re-check it at the end."""
    content = TaskPlanningSection().build_content()
    lower = content.lower()
    assert "if the plan includes correctness-critical tasks" in lower
    assert "complete those first" in lower
    assert "then move to the remaining quality, novelty, or polish tasks" in lower
    assert "use explicit correctness criteria when they exist" in lower
    assert "final preserve/regression pass" in lower
    assert "correctness fixes still pass after later changes" in lower


def test_checklist_gated_decision_requires_verification_replay_memory_capture():
    """Phase 5 guidance should require writing a verification replay memo before submit."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    assert "memory/short_term/verification_latest.md" in content
    assert "verification replay" in content.lower()
    assert "## Verification Contract" in content
    assert "## Inputs and Artifacts" in content
    assert "## Replay Steps" in content
    assert "## Latest Verification Result" in content
    assert "## Stale If" in content
    assert "Key assertions" not in content
    assert "concrete value extracted" not in content.lower()


def test_memory_section_verification_replay_requirements_drop_output_assertion_rule():
    """Saving Memories guidance should not require concrete output assertions."""
    section = MemorySection(
        memory_config={
            "short_term": {"content": ""},
            "long_term": [],
            "temp_workspace_memories": [],
            "archived_memories": {"short_term": {}, "long_term": {}},
        },
    )

    content = section.build_content()
    assert "memory/short_term/verification_latest.md" in content
    assert "## Verification Contract" in content
    assert "## Replay Steps" in content
    assert "## Latest Verification Result" in content
    assert "## Stale If" in content
    assert "concrete assertion" not in content.lower()


def test_memory_section_renders_dedicated_verification_replay_block():
    """Verification replay memories should appear in a dedicated auto-injected section."""
    section = MemorySection(
        memory_config={
            "short_term": {"content": ""},
            "long_term": [],
            "temp_workspace_memories": [
                {
                    "agent_label": "agent1",
                    "memories": {
                        "short_term": {
                            "verification_latest": {
                                "name": "verification_latest",
                                "content": "## Verify\n- uv run pytest massgen/tests/test_planning_tools.py -q",
                            },
                        },
                        "long_term": {},
                    },
                },
            ],
            "archived_memories": {"short_term": {}, "long_term": {}},
        },
    )
    content = section.build_content()
    assert "Verification Replay Memories (Auto-Injected)" in content
    assert "verification_latest.md" in content
    assert "uv run pytest" in content


def test_checklist_gated_decision_requires_saving_script_outputs():
    """Phase 5 guidance should instruct agents to save verification script outputs."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    # Must tell agents to save stdout/stderr output files under verification dir
    assert ".massgen_scratch/verification/" in content
    assert "exit code" in content.lower() or "stdout" in content.lower()
    # Must index output files in the memo
    assert "output" in content.lower()


def test_checklist_gated_decision_output_file_format():
    """Phase 5 guidance should give a concrete format example for output files."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    lower = content.lower()
    # Must show the concrete key-value format (Command:, Exit code:, Output:)
    assert "command:" in lower
    assert "exit code:" in lower
    assert "output:" in lower
    # Must specify the output_<name>.txt naming convention
    assert "output_" in content


def test_checklist_gated_decision_includes_media_call_ledger_read_first_guidance():
    """Checklist guidance should direct agents to consult the media ledger before new media calls."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    lower = content.lower()
    assert ".massgen_scratch/verification/media_call_ledger.json" in content
    assert "read_media" in content
    assert "generate_media" in content
    assert "before making new media calls" in lower or "before issuing new" in lower


def test_checklist_gated_decision_media_ledger_non_blocking_side_by_side():
    """Ledger instructions should remain advisory and allow fresh side-by-side comparisons."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    lower = content.lower()
    assert "advisory" in lower or "informational" in lower
    assert "side-by-side" in content or "side by side" in lower
    assert "may still run fresh calls" in lower or "still run fresh" in lower


def test_checklist_gated_decision_requires_media_map_finalization_reconciliation():
    """Phase 5 should reference media map and media call ledger for artifact tracking."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    lower = content.lower()
    assert "current media map" in lower
    assert "media_call_ledger" in lower


def test_checklist_gated_decision_mentions_context_snapshot_provenance():
    """Ledger guidance should reference CONTEXT.md snapshot tracking for media calls."""
    content = _build_checklist_gated_decision(
        checklist_items=_CHECKLIST_ITEMS,
    )
    assert "CONTEXT.md" in content
    assert "context_snapshots" in content


def test_output_first_verification_requires_capture_coverage_before_diagnosis():
    """Output-first guidance should require checking capture completeness before
    concluding an answer is broken."""
    content = OutputFirstVerificationSection().build_content()
    lower = content.lower()

    assert "capture the full artifact" in lower
    assert "scroll through long pages" in lower
    assert "capture artifacts" in lower
    assert "verification issue first" in lower


def test_filesystem_best_practices_evaluator_uses_prior_outputs_as_starting_point():
    """Evaluator guidance should direct agents to use prior verification outputs, not repeat blindly."""
    section = FilesystemBestPracticesSection()
    content = section.build_content()
    lower = content.lower()
    # Must reference where prior outputs are available (under .massgen_scratch, not .scratch_archive)
    assert "scratch_archive" not in content
    assert ".massgen_scratch/verification/" in content
    # Must tell evaluators they can read artifact files directly and add their own
    assert "read" in lower
    # Must direct focus toward new/unverified/failing rather than blind re-running
    assert "new" in lower or "unverified" in lower or "failing" in lower
    # Must not say "always verify independently" (that discourages reuse)
    assert "always verify independently" not in content


def test_evaluation_guidance_reuse_existing_verification_artifacts():
    """Evaluation guidance should tell agents to reuse prior round's verification
    artifacts rather than re-rendering from scratch."""
    section = FilesystemBestPracticesSection()
    content = section.build_content()
    lower = content.lower()
    assert "reuse existing verification artifacts" in lower
    assert "re-rendering from scratch" in lower
    assert "only re-capture if" in lower


def test_verification_replay_memories_discourage_redundant_recapture():
    """Verification replay injection should tell agents not to re-render
    artifacts that were already captured in the prior round."""
    section = MemorySection(
        memory_config={
            "short_term": {"content": ""},
            "long_term": [],
            "temp_workspace_memories": [
                {
                    "agent_label": "agent1",
                    "memories": {
                        "short_term": {
                            "verification_latest": {
                                "name": "verification_latest",
                                "content": "## Verify\n- rendered SVG and captured screenshots",
                            },
                        },
                        "long_term": {},
                    },
                },
            ],
            "archived_memories": {"short_term": {}, "long_term": {}},
        },
    )
    content = section.build_content()
    lower = content.lower()
    assert "do not re-render or re-capture" in lower
    assert "unless you spot a gap" in lower


def test_background_tool_guidance_discourages_immediate_wait():
    """Background tool section should tell agents to continue working
    after starting a background job, not immediately wait."""
    section = CommandExecutionSection(docker_mode=False)
    content = section.build_content()
    lower = content.lower()
    assert "continue with your next task" in lower
    assert "do not immediately call" in lower
    assert "exhausted all" in lower or "genuinely need the result" in lower


def test_task_context_section_omits_subagent_affordances_when_disabled():
    """When `subagents_enabled=False` (multimodal-only agents), the section
    must not mention `spawn_subagents` or imply subagent capabilities exist.

    Regression for the phantom-MCP bug: models with subagent affordances in
    their prompt but no connected subagent server hallucinate calls to
    `mcp__subagent_<8hex>__list_subagents` and retry-loop against an
    unconnected server. The section is the affordance-source per the
    "remove affordances at the source" rule.
    """
    content = TaskContextSection(subagents_enabled=False).build_content()
    assert "spawn_subagents" not in content
    # The word "subagent" itself can still appear historically in titles, but
    # the inheritance bullet must not — that's what hallucinations latch onto.
    assert "subagents will inherit" not in content
    # CONTEXT.md / read_media guidance must remain — that's the actual use
    # case for multimodal-only agents.
    assert "CONTEXT.md" in content
    assert "read_media" in content


def test_task_context_section_includes_subagent_affordances_when_enabled():
    """When subagents are actually wired, the prompt should advertise them."""
    content = TaskContextSection(subagents_enabled=True).build_content()
    assert "spawn_subagents" in content
    assert "subagents will inherit this context" in content


def test_task_context_section_defaults_to_subagents_disabled():
    """Safe default: a bare TaskContextSection() must not leak subagent
    affordances. The caller must opt in via subagents_enabled=True.
    """
    default_content = TaskContextSection().build_content()
    explicit_content = TaskContextSection(subagents_enabled=False).build_content()
    assert default_content == explicit_content
    assert "spawn_subagents" not in default_content
