"""
Message templates for MassGen framework following input_cases_reference.md
Implements proven binary decision framework that eliminates perfectionism loops.
"""

from typing import Any


class MessageTemplates:
    """Message templates implementing the proven MassGen approach."""

    def __init__(
        self,
        voting_sensitivity: str = "lenient",
        answer_novelty_requirement: str = "lenient",
        **template_overrides,
    ):
        """Initialize with optional template overrides.

        Args:
            voting_sensitivity: Controls how critical agents are when voting.
                - "lenient": Agents vote YES more easily, fewer new answers (default)
                - "balanced": Agents apply detailed criteria (comprehensive, accurate, complete?)
                - "strict": Agents apply high standards of excellence (all aspects, edge cases, reference-quality)
            answer_novelty_requirement: Controls how different new answers must be.
                - "lenient": No additional checks (default)
                - "balanced": Require meaningful differences
                - "strict": Require substantially different solutions
            **template_overrides: Custom template strings to override defaults
        """
        self._voting_sensitivity = voting_sensitivity
        self._answer_novelty_requirement = answer_novelty_requirement
        self._template_overrides = template_overrides

    # =============================================================================
    # SYSTEM MESSAGE TEMPLATES
    # =============================================================================

    def evaluation_system_message(self) -> str:
        """Standard evaluation system message for coordination rounds."""
        if "evaluation_system_message" in self._template_overrides:
            return str(self._template_overrides["evaluation_system_message"])

        import time

        return f"""You are evaluating answers from multiple agents for final response to a message. Does the best CURRENT ANSWER address the ORIGINAL MESSAGE?

Evaluate existing answers as a critic, not as a collaborator. Your job is to \
determine whether the work is genuinely good — not to find ways to build on it.

If YES, use the `vote` tool to record your vote and skip the `new_answer` tool.
Otherwise, do additional work first, then use the `new_answer` tool to record a better answer to the ORIGINAL MESSAGE. Make sure you actually call `vote` or `new_answer` (in tool call format).

*Note*: The CURRENT TIME is **{time.strftime("%Y-%m-%d %H:%M:%S")}**.
"""

    # =============================================================================
    # USER MESSAGE TEMPLATES
    # =============================================================================

    def format_original_message(self, task: str, paraphrase: str | None = None) -> str:
        """Format the original message section."""
        if "format_original_message" in self._template_overrides:
            override = self._template_overrides["format_original_message"]
            if callable(override):
                try:
                    return override(task, paraphrase=paraphrase)
                except TypeError:
                    return override(task)
            return str(override).format(task=task, paraphrase=paraphrase)

        original_block = f"<ORIGINAL MESSAGE> {task} <END OF ORIGINAL MESSAGE>"
        if paraphrase:
            paraphrase_block = f"<PARAPHRASED MESSAGE> {paraphrase} <END OF PARAPHRASED MESSAGE>"
            return f"{original_block}\n{paraphrase_block}"
        return original_block

    def format_conversation_history(self, conversation_history: list[dict[str, str]]) -> str:
        """Format conversation history for agent context."""
        if "format_conversation_history" in self._template_overrides:
            override = self._template_overrides["format_conversation_history"]
            if callable(override):
                return override(conversation_history)
            return str(override)

        if not conversation_history:
            return ""

        lines = ["<CONVERSATION_HISTORY>"]
        for message in conversation_history:
            role = message.get("role", "unknown")
            content = message.get("content", "")
            if role == "user":
                lines.append(f"User: {content}")
            elif role == "assistant":
                lines.append(f"Assistant: {content}")
            elif role == "system":
                # Skip system messages in history display
                continue
        lines.append("<END OF CONVERSATION_HISTORY>")
        return "\n".join(lines)

    def system_message_with_context(self, conversation_history: list[dict[str, str]] | None = None) -> str:
        """Evaluation system message with conversation context awareness."""
        if "system_message_with_context" in self._template_overrides:
            override = self._template_overrides["system_message_with_context"]
            if callable(override):
                return override(conversation_history)
            return str(override)

        base_message = self.evaluation_system_message()

        if conversation_history and len(conversation_history) > 0:
            context_note = """

IMPORTANT: You are responding to the latest message in an ongoing conversation. Consider the full conversation context when evaluating answers and providing your response."""
            return base_message + context_note

        return base_message

    def format_current_answers_empty(self) -> str:
        """Format current answers section when no answers exist (Case 1)."""
        if "format_current_answers_empty" in self._template_overrides:
            return str(self._template_overrides["format_current_answers_empty"])

        return """<CURRENT ANSWERS from the agents>
(no answers available yet)
<END OF CURRENT ANSWERS>"""

    @staticmethod
    def compute_own_last_order_seed(
        agent_id: str,
        answer_ids: list[str],
        agent_mapping: dict[str, str] | None = None,
    ) -> int:
        """Order seed that rotates ``agent_id``'s own answer into the LAST slot.

        ``format_current_answers_with_summaries`` sorts candidates by anonymous label
        then left-rotates by ``order_seed % n``; passing ``position + 1`` (where
        ``position`` is ``agent_id``'s index in that label-sorted order) places its own
        answer last — counterbalancing both first-position bias and self-preference.

        The seed is derived from the *answering subset* (``answer_ids``), not the global
        roster, so it stays correct when only a non-contiguous subset has answered. When
        ``agent_id`` has no answer in the set, falls back to its anonymous-label index
        for general primacy counterbalancing.
        """
        mapping = agent_mapping or {}
        ordered = sorted(answer_ids, key=lambda a: mapping.get(a, a))
        if agent_id in ordered:
            return ordered.index(agent_id) + 1
        digits = "".join(ch for ch in mapping.get(agent_id, "") if ch.isdigit())
        return int(digits) if digits else 0

    def format_current_answers_with_summaries(
        self,
        agent_summaries: dict[str, str],
        agent_mapping: dict[str, str] | None = None,
        agent_changedocs: dict[str, str] | None = None,
        answer_label_mapping: dict[str, str] | None = None,
        order_seed: int | None = None,
    ) -> str:
        """Format current answers section with agent summaries (Case 2) using anonymous agent IDs.

        Args:
            agent_summaries: Dict of agent_id -> answer summary
            agent_mapping: Optional mapping from real agent ID to anonymous ID (e.g., agent_a -> agent1).
                          If not provided, creates mapping from sorted agent_summaries keys.
                          Pass this from coordination_tracker.get_reverse_agent_mapping() for
                          global consistency with vote tool and injections.
            agent_changedocs: Optional dict of agent_id -> changedoc content. When provided,
                             changedoc content is included within each agent's answer block.
            answer_label_mapping: Optional mapping from real agent ID to versioned label
                                 (e.g., agent_a -> agent1.2). When provided, uses versioned
                                 labels in XML headers for provenance tracking.
            order_seed: Optional integer to counterbalance position bias. When provided, the
                       candidates are presented in a stable label-sorted order left-rotated by
                       ``order_seed % n`` so no candidate permanently occupies the primacy slot
                       across rounds/agents. Anonymous labels stay attached to their own content,
                       so score attribution is unaffected. When ``None``, the legacy
                       insertion-order behavior is preserved.
        """
        if "format_current_answers_with_summaries" in self._template_overrides:
            override = self._template_overrides["format_current_answers_with_summaries"]
            if callable(override):
                return override(agent_summaries)

        lines = ["<CURRENT ANSWERS from the agents>"]

        # Use provided mapping or create from agent_summaries keys (legacy behavior)
        if agent_mapping is None:
            agent_mapping = {}
            for i, agent_id in enumerate(sorted(agent_summaries.keys()), 1):
                agent_mapping[agent_id] = f"agent{i}"

        ordered_items = list(agent_summaries.items())
        if order_seed is not None and len(ordered_items) > 1:
            # Counterbalance position bias: stable base order by anonymous label,
            # then left-rotate by order_seed so the primacy slot cycles across agents.
            ordered_items.sort(key=lambda kv: agent_mapping.get(kv[0], kv[0]))
            rotation = order_seed % len(ordered_items)
            ordered_items = ordered_items[rotation:] + ordered_items[:rotation]

        for agent_id, summary in ordered_items:
            # Use versioned label (agent1.2) if available, otherwise base anonymous ID (agent1)
            anon_id = (answer_label_mapping or {}).get(agent_id) or agent_mapping.get(agent_id, agent_id)
            changedoc = (agent_changedocs or {}).get(agent_id)
            if changedoc:
                lines.append(f"<{anon_id}> {summary}\n<changedoc>\n{changedoc}\n</changedoc> <end of {anon_id}>")
            else:
                lines.append(f"<{anon_id}> {summary} <end of {anon_id}>")

        lines.append("<END OF CURRENT ANSWERS>")
        return "\n".join(lines)

    def enforcement_message(self, buffer_content: str | None = None) -> str:
        """Enforcement message for Case 3 (non-workflow responses).

        Args:
            buffer_content: Optional streaming buffer content from the agent's incomplete response.
                           If provided, this is injected so the agent can see what it was working on.
        """
        if "enforcement_message" in self._template_overrides:
            return str(self._template_overrides["enforcement_message"])

        base_message = "Finish your work above by making a tool call of `vote` or `new_answer`. Make sure you actually call the tool."

        if buffer_content and buffer_content.strip():
            # Include the agent's incomplete work so it can continue from where it left off
            return f"""Your previous response was incomplete. Here is what you were working on:

<incomplete_response>
{buffer_content.strip()}
</incomplete_response>

{base_message}"""

        return base_message

    def evaluation_system_message_vote_only(self) -> str:
        """System message when agent has reached their answer limit and must vote.

        Used when max_new_answers_per_agent is reached. The agent can only use the
        vote tool (new_answer and broadcast tools are removed).
        """
        if "evaluation_system_message_vote_only" in self._template_overrides:
            return str(self._template_overrides["evaluation_system_message_vote_only"])

        return """You are evaluating existing solutions to determine the best answer.

You have provided your maximum number of new answers. Now you MUST vote for the best existing answer.

Use your available tools to analyze the existing answers, then call the `vote` tool to select the best one.

IMPORTANT: The only workflow action available to you is `vote`. You cannot submit new answers."""

    def tool_error_message(self, error_msg: str) -> dict[str, str]:
        """Create a tool role message for tool usage errors."""
        return {"role": "tool", "content": error_msg}

    def enforcement_user_message(self, buffer_content: str | None = None) -> dict[str, str]:
        """Create a user role message for enforcement.

        Args:
            buffer_content: Optional streaming buffer content from the agent's incomplete response.
        """
        return {"role": "user", "content": self.enforcement_message(buffer_content=buffer_content)}

    # =============================================================================
    # TOOL DEFINITIONS
    # =============================================================================

    def get_new_answer_tool(self) -> dict[str, Any]:
        """Get new_answer tool definition.

        TODO: Consider extending with optional context parameters for stateful backends:
        - cwd: Working directory for Claude Code sessions
        - session_id: Backend session identifier for continuity
        - model: Model used to generate the answer
        - tools_used: List of tools actually utilized
        This would enable better context preservation in multi-iteration workflows.
        """
        if "new_answer_tool" in self._template_overrides:
            return self._template_overrides["new_answer_tool"]

        return {
            "type": "function",
            "function": {
                "name": "new_answer",
                "description": "Provide an improved answer to the ORIGINAL MESSAGE",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": (
                                "Your improved answer (HIGH-LEVEL summary): what you created, where to find it, "
                                "how to use it, key features. Do NOT include full code listings - code belongs in "
                                "workspace files. If any builtin tools like search or code execution were used, "
                                "mention how they are used here."
                            ),
                        },
                    },
                    "required": ["content"],
                },
            },
        }

    def get_vote_tool(self, valid_agent_ids: list[str] | None = None) -> dict[str, Any]:
        """Get vote tool definition with anonymous agent IDs."""
        if "vote_tool" in self._template_overrides:
            override = self._template_overrides["vote_tool"]
            if callable(override):
                return override(valid_agent_ids)
            return override

        tool_def = {
            "type": "function",
            "function": {
                "name": "vote",
                "description": "Vote for the best agent to present final answer",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "agent_id": {
                            "type": "string",
                            "description": "Anonymous agent ID to vote for (e.g., 'agent1', 'agent2')",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief reason why this agent has the best answer",
                        },
                    },
                    "required": ["agent_id", "reason"],
                },
            },
        }

        # Create anonymous mapping for enum constraint
        if valid_agent_ids:
            anon_agent_ids = [f"agent{i}" for i in range(1, len(valid_agent_ids) + 1)]
            tool_def["function"]["parameters"]["properties"]["agent_id"]["enum"] = anon_agent_ids

        return tool_def

    def get_stop_tool(self) -> dict[str, Any]:
        """Get stop tool definition for decomposition mode."""
        return {
            "type": "function",
            "function": {
                "name": "stop",
                "description": "Signal that your assigned subtask is complete and well-integrated with other agents' work.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "summary": {
                            "type": "string",
                            "description": "What you accomplished and how it connects to other agents' work",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["complete", "blocked"],
                            "description": "Whether your subtask is complete or blocked on something",
                        },
                    },
                    "required": ["summary", "status"],
                },
            },
        }

    def get_standard_tools(self, valid_agent_ids: list[str] | None = None, decomposition_mode: bool = False) -> list[dict[str, Any]]:
        """Get standard tools for MassGen framework."""
        if decomposition_mode:
            return [self.get_new_answer_tool(), self.get_stop_tool()]
        return [self.get_new_answer_tool(), self.get_vote_tool(valid_agent_ids)]

    def final_presentation_system_message(
        self,
        original_system_message: str | None = None,
        enable_file_generation: bool = False,
        has_irreversible_actions: bool = False,
        enable_command_execution: bool = False,
    ) -> str:
        """System message for final answer presentation by winning agent.

        Args:
            original_system_message: The agent's original system message to preserve
            enable_file_generation: Whether file generation is enabled
            has_irreversible_actions: Whether agent has write access to context paths (requires actual file delivery)
            enable_command_execution: Whether command execution is enabled for this agent
        """
        if "final_presentation_system_message" in self._template_overrides:
            return str(self._template_overrides["final_presentation_system_message"])

        # BACKUP - Original final presentation message (pre-explicit-synthesis update):
        # presentation_instructions = """You have been selected as the winning presenter in a coordination process.
        # Your task is to present a polished, comprehensive final answer that incorporates the best insights from all participants.
        #
        # Consider:
        # 1. Your original response and how it can be refined
        # 2. Valuable insights from other agents' answers that should be incorporated
        # 3. Feedback received through the voting process
        # 4. Ensuring clarity, completeness, and comprehensiveness for the final audience
        #
        # Present your final coordinated answer in the most helpful and complete way possible."""

        presentation_instructions = """You have been selected as the winning presenter in a coordination process.
Present the best possible coordinated answer by combining the strengths from all participants.

This is the **final deliverable** — ensure it is fully polished and complete. Check for any \
unfinished items, Known Gaps, or rough edges from coordination rounds and resolve them now. \
Nothing should be left as a TODO in the final product.

Present your answer using markdown formatting where it aids readability.

When you have composed your final answer, submit it using the `new_answer` tool. Only include the markdown-formatted answer in the tool call. This will be the official final deliverable.\n\n"""

        # Intentionally keep presentation guidance concise.
        # Detailed modality-specific media workflows were removed to reduce prompt bloat.
        # Add file generation instructions only if enabled
        if enable_file_generation:
            presentation_instructions += """For file generation tasks:

  **MANDATORY WORKFLOW - You MUST follow these steps in order:**

  Step 1: **Check for existing files (REQUIRED)**
  - First, list all files in the Shared Reference directory (temp_workspaces) to find ALL files from EVERY agent
  - Look for files of the requested type in each agent's workspace subdirectory

  Step 2: **Understand ALL existing files (REQUIRED if files exist)**
  - For EACH file you found, you MUST call the **understand_file** tool to extract its content, structure, and key elements
  - Do this for files from yourself AND from other agents - analyze ALL files found
  - DO NOT skip this step even if you think you know the content

  Step 3: **Synthesize and generate final file (REQUIRED)**
  - If existing files were found and analyzed:
    * Synthesize ALL file contents into a single, detailed, combined content
    * The combined content should capture the best elements, structure, and information from all analyzed files
    * Call **text_to_file_generation** with this synthesized content to generate the final unified file
  - If NO existing files were found:
    * Generate a new file based directly on the original task requirements
    * Call **text_to_file_generation** with content derived from the original task

  Step 4: **Save and report (REQUIRED)**
  - Save the final generated file in your workspace
  - Report the saved path in your final answer

  **CRITICAL**: You MUST complete Steps 1-4 in order. Do not skip checking for existing files. Do not skip calling
  understand_file on found files. This is a mandatory synthesis workflow.
  """
        #             presentation_instructions += """For file generation tasks:
        # - Extract file paths from the existing answer and resolve them in the shared reference.
        # - Gather ALL files produced by EVERY agent (ignore non-existent files).
        # - IMPORTANT: If you find ANY existing files (from yourself or other agents), you MUST call the **understand_file** tool to extract each file's content.
        # - IMPORTANT: Synthesize contents from all files into a detailed, combined content.
        # - IMPORTANT: You MUST call the **text_to_file_generation** tool with this synthesized content to generate the final file.
        # - IMPORTANT: Save the final output in your workspace and output the saved path.
        # - If no existing files are found, generate based on the original task requirements.
        # """
        # Add irreversible actions reminder if needed
        # TODO: Integrate more general irreversible actions handling in future (i.e., not just for context file delivery)
        if has_irreversible_actions:
            presentation_instructions += (
                "### Write Access to Target Path:\n\n"
                "Reminder: File Delivery Required. You should first place your final answer in your workspace. "
                "However, note your workspace is NOT the final destination. You MUST copy/write files to the Target Path using FULL ABSOLUTE PATHS. "
                "Then, clean up this Target Path by deleting any outdated or unused files. "
                "Then, you must ALWAYS verify that the Target Path contains the correct final files, as no other agents were allowed to write to this path.\n"
            )

        # Add requirements.txt guidance if command execution is enabled
        if enable_command_execution:
            presentation_instructions += (
                "### Package Dependencies:\n\n"
                "Create a `requirements.txt` file listing all Python packages needed to run your code. "
                "This helps users reproduce your work later. Include only the packages you actually used in your solution.\n"
            )

        # Combine with original system message if provided
        if original_system_message:
            return f"""{original_system_message}

{presentation_instructions}"""
        else:
            return presentation_instructions

    def format_restart_context(self, reason: str, instructions: str, previous_answer: str | None = None, workspace_populated: bool = False, branch_info: dict[str, Any] | None = None) -> str:
        """Format restart context for subsequent orchestration attempts.

        This context is added to agent messages (like multi-turn context) on restart attempts.

        Args:
            reason: Why the previous attempt was insufficient
            instructions: Detailed guidance for improvement
            previous_answer: The winning answer from the previous attempt (optional)
            workspace_populated: Whether the workspace still has files from previous attempt
            branch_info: Optional dict with 'own_branch' (str) and 'other_branches' (list[str])
                for communicating branch names from the previous attempt
        """
        if "format_restart_context" in self._template_overrides:
            override = self._template_overrides["format_restart_context"]
            if callable(override):
                return override(reason, instructions, previous_answer)
            return str(override).format(reason=reason, instructions=instructions, previous_answer=previous_answer or "")

        base_context = f"""<PREVIOUS ATTEMPT FEEDBACK>
The previous orchestration attempt was restarted because:
{reason}

**Instructions for this attempt:**
{instructions}"""

        # Include previous answer if available
        if previous_answer:
            base_context += f"""

**Previous attempt's winning answer (for reference):**
{previous_answer}"""

        if workspace_populated:
            base_context += """

**Previous attempt's workspace is still available in your working directory.**
Check your deliverable/ and scratch/ directories for files from the previous attempt."""

        if branch_info:
            own_branch = branch_info.get("own_branch")
            other_branches = branch_info.get("other_branches", {})
            if own_branch:
                base_context += f"\n\n**Your previous work is on branch**: `{own_branch}`"
                base_context += f"\nYou can build on it: `git merge {own_branch}`"
            if other_branches:
                if isinstance(other_branches, dict):
                    branch_list = ", ".join(f"{label}: `{b}`" for label, b in other_branches.items())
                else:
                    # Legacy list format fallback
                    branch_list = ", ".join(f"`{b}`" for b in other_branches)
                base_context += f"\n**Other agents' branches**: {branch_list}"

        base_context += """

Please address these specific issues in your coordination and final answer.
<END OF PREVIOUS ATTEMPT FEEDBACK>"""

        return base_context

    # =============================================================================
    # COMPLETE MESSAGE BUILDERS
    # =============================================================================

    def build_case1_user_message(self, task: str, paraphrase: str | None = None) -> str:
        """Build Case 1 user message (no summaries exist)."""
        return f"""{self.format_original_message(task, paraphrase)}

{self.format_current_answers_empty()}"""

    def build_case2_user_message(
        self,
        task: str,
        agent_summaries: dict[str, str],
        paraphrase: str | None = None,
        agent_mapping: dict[str, str] | None = None,
        agent_changedocs: dict[str, str] | None = None,
        answer_label_mapping: dict[str, str] | None = None,
        order_seed: int | None = None,
    ) -> str:
        """Build Case 2 user message (summaries exist).

        Args:
            task: The task description
            agent_summaries: Dict of agent_id -> answer summary
            paraphrase: Optional paraphrase of the task
            agent_mapping: Mapping from real agent ID to anonymous ID (e.g., agent_a -> agent1).
                          Pass from coordination_tracker.get_reverse_agent_mapping() for
                          global consistency with vote tool and injections.
            agent_changedocs: Optional dict of agent_id -> changedoc content.
            answer_label_mapping: Optional mapping from real agent ID to versioned label
                                 (e.g., agent_a -> agent1.2).
        """
        return f"""{self.format_original_message(task, paraphrase)}

{self.format_current_answers_with_summaries(agent_summaries, agent_mapping, agent_changedocs=agent_changedocs, answer_label_mapping=answer_label_mapping, order_seed=order_seed)}"""

    def build_evaluation_message(
        self,
        task: str,
        agent_answers: dict[str, str] | None = None,
        paraphrase: str | None = None,
        agent_mapping: dict[str, str] | None = None,
        agent_changedocs: dict[str, str] | None = None,
        answer_label_mapping: dict[str, str] | None = None,
        order_seed: int | None = None,
    ) -> str:
        """Build evaluation user message for any case.

        Args:
            task: The task description
            agent_answers: Optional dict of agent_id -> answer
            paraphrase: Optional paraphrase of the task
            agent_mapping: Mapping from real agent ID to anonymous ID (e.g., agent_a -> agent1).
                          Pass from coordination_tracker.get_reverse_agent_mapping() for
                          global consistency with vote tool and injections.
            agent_changedocs: Optional dict of agent_id -> changedoc content.
            answer_label_mapping: Optional mapping from real agent ID to versioned label.
        """
        if agent_answers:
            return self.build_case2_user_message(task, agent_answers, paraphrase, agent_mapping, agent_changedocs=agent_changedocs, answer_label_mapping=answer_label_mapping, order_seed=order_seed)
        else:
            return self.build_case1_user_message(task, paraphrase)

    def build_coordination_context(
        self,
        current_task: str,
        conversation_history: list[dict[str, str]] | None = None,
        agent_answers: dict[str, str] | None = None,
        paraphrase: str | None = None,
        agent_mapping: dict[str, str] | None = None,
        agent_changedocs: dict[str, str] | None = None,
        answer_label_mapping: dict[str, str] | None = None,
        order_seed: int | None = None,
    ) -> str:
        """Build coordination context including conversation history and current state.

        Args:
            current_task: The current task description
            conversation_history: Optional conversation history
            agent_answers: Optional dict of agent_id -> answer
            paraphrase: Optional paraphrase of the task
            agent_mapping: Mapping from real agent ID to anonymous ID (e.g., agent_a -> agent1).
                          Pass from coordination_tracker.get_reverse_agent_mapping() for
                          global consistency with vote tool and injections.
            agent_changedocs: Optional dict of agent_id -> changedoc content.
        """
        if "build_coordination_context" in self._template_overrides:
            override = self._template_overrides["build_coordination_context"]
            if callable(override):
                try:
                    return override(current_task, conversation_history, agent_answers, paraphrase)
                except TypeError:
                    return override(current_task, conversation_history, agent_answers)
            return str(override)

        context_parts = []

        # Add conversation history if present
        if conversation_history and len(conversation_history) > 0:
            history_formatted = self.format_conversation_history(conversation_history)
            if history_formatted:
                context_parts.append(history_formatted)
                context_parts.append("")  # Empty line for spacing

        # Add current task
        context_parts.append(self.format_original_message(current_task, paraphrase))
        context_parts.append("")  # Empty line for spacing

        # Add agent answers
        if agent_answers:
            context_parts.append(
                self.format_current_answers_with_summaries(agent_answers, agent_mapping, agent_changedocs=agent_changedocs, answer_label_mapping=answer_label_mapping, order_seed=order_seed),
            )
        else:
            context_parts.append(self.format_current_answers_empty())

        return "\n".join(context_parts)

    # =============================================================================
    # CONVERSATION BUILDERS
    # =============================================================================

    def build_initial_conversation(
        self,
        task: str,
        agent_summaries: dict[str, str] | None = None,
        valid_agent_ids: list[str] | None = None,
        base_system_message: str | None = None,
        paraphrase: str | None = None,
        agent_mapping: dict[str, str] | None = None,
        decomposition_mode: bool = False,
        agent_changedocs: dict[str, str] | None = None,
        answer_label_mapping: dict[str, str] | None = None,
        order_seed: int | None = None,
    ) -> dict[str, Any]:
        """Build complete initial conversation for MassGen evaluation.

        Args:
            task: The task description
            agent_summaries: Optional dict of agent_id -> answer summary
            valid_agent_ids: List of valid agent IDs for voting
            base_system_message: Optional base system message
            paraphrase: Optional paraphrase of the task
            agent_mapping: Mapping from real agent ID to anonymous ID (e.g., agent_a -> agent1).
                          Pass from coordination_tracker.get_reverse_agent_mapping() for
                          global consistency with vote tool and injections.
            agent_changedocs: Optional dict of agent_id -> changedoc content.
            answer_label_mapping: Optional mapping from real agent ID to versioned label.
        """
        # Use agent's custom system message if provided, otherwise use default evaluation message
        if base_system_message:
            # Check if this is a structured system prompt (contains <system_prompt> tag)
            # Structured prompts already include evaluation message, so don't prepend it
            if "<system_prompt>" in base_system_message:
                system_message = base_system_message
            else:
                # Old-style: prepend evaluation message for backward compatibility
                system_message = f"{self.evaluation_system_message()}\n\n#Special Requirement\n{base_system_message}"
        else:
            system_message = self.evaluation_system_message()

        return {
            "system_message": system_message,
            "user_message": self.build_evaluation_message(
                task,
                agent_summaries,
                paraphrase,
                agent_mapping,
                agent_changedocs=agent_changedocs,
                answer_label_mapping=answer_label_mapping,
                order_seed=order_seed,
            ),
            "tools": self.get_standard_tools(valid_agent_ids, decomposition_mode=decomposition_mode),
        }

    def build_conversation_with_context(
        self,
        current_task: str,
        conversation_history: list[dict[str, str]] | None = None,
        agent_summaries: dict[str, str] | None = None,
        valid_agent_ids: list[str] | None = None,
        base_system_message: str | None = None,
        paraphrase: str | None = None,
        agent_mapping: dict[str, str] | None = None,
        decomposition_mode: bool = False,
        agent_changedocs: dict[str, str] | None = None,
        answer_label_mapping: dict[str, str] | None = None,
        order_seed: int | None = None,
    ) -> dict[str, Any]:
        """Build complete conversation with conversation history context for MassGen evaluation.

        Args:
            current_task: The current task description
            conversation_history: Optional conversation history
            agent_summaries: Optional dict of agent_id -> answer summary
            valid_agent_ids: List of valid agent IDs for voting
            base_system_message: Optional base system message
            paraphrase: Optional paraphrase of the task
            agent_mapping: Mapping from real agent ID to anonymous ID (e.g., agent_a -> agent1).
                          Pass from coordination_tracker.get_reverse_agent_mapping() for
                          global consistency with vote tool and injections.
            decomposition_mode: If True, use stop tool instead of vote in logged tools
            agent_changedocs: Optional dict of agent_id -> changedoc content.
            answer_label_mapping: Optional mapping from real agent ID to versioned label.
        """
        # Use agent's custom system message if provided, otherwise use default context-aware message
        if base_system_message:
            # Check if this is a structured system prompt (contains <system_prompt> tag)
            # Structured prompts already include evaluation message, so don't append it
            if "<system_prompt>" in base_system_message:
                system_message = base_system_message
            else:
                # Old-style: append evaluation message for backward compatibility
                system_message = f"{base_system_message}\n\n{self.system_message_with_context(conversation_history)}"
        else:
            system_message = self.system_message_with_context(conversation_history)

        return {
            "system_message": system_message,
            "user_message": self.build_coordination_context(
                current_task,
                conversation_history,
                agent_summaries,
                paraphrase,
                agent_mapping,
                agent_changedocs=agent_changedocs,
                answer_label_mapping=answer_label_mapping,
                order_seed=order_seed,
            ),
            "tools": self.get_standard_tools(valid_agent_ids, decomposition_mode=decomposition_mode),
        }

    def build_final_presentation_message(
        self,
        original_task: str,
        vote_summary: str,
        all_answers: dict[str, str],
        selected_agent_id: str,
        agent_changedocs: dict[str, str] | None = None,
        final_answer_strategy: str = "winner_present",
        had_voting: bool = False,
    ) -> str:
        """Build final presentation message for winning agent."""
        # Format all answers with clear marking.
        # Hide (YOUR ANSWER) marker when synthesizing without voting —
        # all answers should be treated equally when there is no winner.
        show_own_marker = had_voting or final_answer_strategy != "synthesize"
        answers_section = "All answers provided during coordination:\n"
        for agent_id, answer in all_answers.items():
            marker = " (YOUR ANSWER)" if show_own_marker and agent_id == selected_agent_id else ""
            changedoc = (agent_changedocs or {}).get(agent_id)
            if changedoc:
                answers_section += f'\n{agent_id}{marker}: "{answer}"\n<changedoc>\n{changedoc}\n</changedoc>\n'
            else:
                answers_section += f'\n{agent_id}{marker}: "{answer}"\n'

        if final_answer_strategy == "synthesize":
            if had_voting:
                # Winner-biased: winner's answer is primary, incorporate from others
                strategy_instruction = (
                    "Your answer was selected as the best by your peers. "
                    "Use it as the primary basis for the final response. "
                    "Actively incorporate the strongest elements from the other agents' "
                    "answers where they improve completeness, accuracy, or depth.\n\n"
                    "Preserve concrete details during synthesis: keep specific "
                    "implementation details, exact values, named elements, and "
                    "actionable directives verbatim from whichever answer provided "
                    "them. Be selective — integrate specific strengths rather than "
                    "diluting your answer by merging everything."
                )
            else:
                # Neutral: no winner, combine the best parts equally
                strategy_instruction = (
                    "Synthesize the strongest relevant parts across all completed "
                    "answers into a single final answer.\n\n"
                    "Preserve concrete details during synthesis: keep specific "
                    "implementation details, exact values, named elements, and "
                    "actionable directives verbatim from whichever answer provided "
                    "them. Do not abstract concrete findings into vague "
                    "generalizations — the synthesized output should be at least as "
                    "specific as the most detailed individual answer. "
                    "When answers overlap on a topic, combine them intelligently — "
                    "keep the most specific version and merge in any unique details "
                    "from others rather than dropping either."
                )
        elif final_answer_strategy == "winner_present":
            strategy_instruction = "Use your answer as the primary basis for the final response. " "You may incorporate useful details from other answers when they improve completeness or accuracy."
        else:
            strategy_instruction = "Present the selected answer clearly as the final response."

        return f"""{self.format_original_message(original_task)}

VOTING RESULTS:
{vote_summary}

{answers_section}

{strategy_instruction}"""

    def add_enforcement_message(
        self,
        conversation_messages: list[dict[str, str]],
        buffer_content: str | None = None,
    ) -> list[dict[str, str]]:
        """Add enforcement message to existing conversation (Case 3).

        Args:
            conversation_messages: Existing conversation messages.
            buffer_content: Optional streaming buffer content from the agent's incomplete response.
        """
        messages = conversation_messages.copy()
        messages.append({"role": "user", "content": self.enforcement_message(buffer_content=buffer_content)})
        return messages

    def command_execution_system_message(
        self,
        docker_mode: bool = False,
        enable_sudo: bool = False,
    ) -> str:
        """Generate concise command execution instructions when command line execution is enabled.

        Args:
            docker_mode: Whether commands execute in Docker containers
            enable_sudo: Whether sudo is available in Docker containers
        """
        parts = ["## Command Execution"]
        parts.append("You can run command line commands using the `execute_command` tool.\n")

        if docker_mode:
            parts.append("**IMPORTANT: Docker Execution Environment**")
            parts.append("- You are running in a Linux Docker container (Debian-based)")
            parts.append("- Base image: Python 3.11-slim with Node.js 20.x")
            parts.append("- Pre-installed: git, curl, build-essential, pytest, requests, numpy, pandas")
            parts.append("- Use `apt-get` for system packages (NOT brew, dnf, yum, etc.)")

            if enable_sudo:
                parts.append("- **Sudo is available**: You can install packages with `sudo apt-get install <package>`")
                parts.append("- Example: `sudo apt-get update && sudo apt-get install -y ffmpeg`")
            else:
                parts.append("- Sudo is NOT available - use pip/npm for user-level packages only")
                parts.append("- For system packages, ask the user to rebuild the Docker image with needed packages")

            parts.append("")

        parts.append("If a `.venv` directory exists in your workspace, it will be automatically used.")

        return "\n".join(parts)

    def filesystem_system_message(
        self,
        main_workspace: str | None = None,
        temp_workspace: str | None = None,
        context_paths: list[dict[str, str]] | None = None,
        previous_turns: list[dict[str, Any]] | None = None,
        workspace_prepopulated: bool = False,
        enable_image_generation: bool = False,
        agent_answers: dict[str, str] | None = None,
        enable_command_execution: bool = False,
        docker_mode: bool = False,
        enable_sudo: bool = False,
        agent_mapping: dict[str, str] | None = None,
    ) -> str:
        """Generate filesystem access instructions for agents with filesystem support.

        Args:
            main_workspace: Path to agent's main workspace
            temp_workspace: Path to shared reference workspace
            context_paths: List of context paths with permissions
            previous_turns: List of previous turn metadata
            workspace_prepopulated: Whether workspace is pre-populated
            enable_image_generation: Whether image generation is enabled
            agent_answers: Dict of agent answers (keys are agent IDs) to show workspace structure
            enable_command_execution: Whether command line execution is enabled
            docker_mode: Whether commands execute in Docker containers
            enable_sudo: Whether sudo is available in Docker containers
            agent_mapping: Optional mapping from real agent ID to anonymous ID.
                          Pass from coordination_tracker.get_reverse_agent_mapping() for consistency.
        """
        if "filesystem_system_message" in self._template_overrides:
            return str(self._template_overrides["filesystem_system_message"])

        parts = ["## Filesystem Access"]

        # Explain workspace behavior
        parts.append(
            "Your working directory is set to your workspace, so all relative paths in your file operations "
            "will be resolved from there. This ensures each agent works in isolation while having access to shared references. "
            "Only include in your workspace files that should be used in your answer.\n",
        )

        if main_workspace:
            workspace_note = f"**Your Workspace**: `{main_workspace}` - Write actual files here using file tools. All your file operations will be relative to this directory."
            if workspace_prepopulated:
                # Workspace is pre-populated with writable copy of most recent turn
                workspace_note += (
                    " **Note**: Your workspace already contains a writable copy of the previous turn's results - "
                    "you can modify or build upon these files. The original unmodified version is also available as "
                    "a read-only context path if you need to reference what was originally there."
                )
            parts.append(workspace_note)

        if temp_workspace:
            # Build workspace tree structure
            workspace_tree = f"**Shared Reference**: `{temp_workspace}` - Contains previous answers from all agents (read/execute-only)\n"

            # Add agent subdirectories in tree format
            # This was added bc weaker models would often try many incorrect paths.
            # No point in requiring extra list dir calls if we can just show them the structure.
            if agent_answers:
                # Use provided mapping or create from agent_answers keys (legacy behavior)
                if agent_mapping is None:
                    agent_mapping = {}
                    for i, agent_id in enumerate(sorted(agent_answers.keys()), 1):
                        agent_mapping[agent_id] = f"agent{i}"
                else:
                    # Filter to only agents with answers, maintain global numbering
                    agent_mapping = {aid: agent_mapping[aid] for aid in agent_answers.keys() if aid in agent_mapping}

                workspace_tree += "   Available agent workspaces:\n"
                # Sort by anon ID to ensure consistent display order
                agent_items = sorted(agent_mapping.items(), key=lambda x: x[1])
                for idx, (agent_id, anon_id) in enumerate(agent_items):
                    is_last = idx == len(agent_items) - 1
                    prefix = "   └── " if is_last else "   ├── "
                    workspace_tree += f"{prefix}{temp_workspace}/{anon_id}/\n"

            workspace_tree += (
                "   - To improve upon existing answers: Copy files from Shared Reference to your workspace using `copy_file` or `copy_directory` tools, then modify them\n"
                "   - These correspond directly to the answers shown in the CURRENT ANSWERS section\n"
                "   - However, not all workspaces may have a matching answer (e.g., if an agent was in the middle of working but restarted before submitting an answer). "
                "So, it is wise to check the actual files in the Shared Reference, not rely solely on the CURRENT ANSWERS section.\n"
            )
            parts.append(workspace_tree)

        if context_paths:
            has_target = any(p.get("will_be_writable", False) for p in context_paths)
            has_readonly_context = any(not p.get("will_be_writable", False) and p.get("permission") == "read" for p in context_paths)

            if has_target:
                parts.append(
                    "\n**Important Context**: If the user asks about improving, fixing, debugging, or understanding an existing "
                    "code/project (e.g., 'Why is this code not working?', 'Fix this bug', 'Add feature X'), they are referring "
                    "to the Target Path below. First READ the existing files from that path to understand what's there, then "
                    "make your changes based on that codebase. Final deliverables must end up there.\n",
                )
            elif has_readonly_context:
                parts.append(
                    "\n**Important Context**: If the user asks about debugging or understanding an existing code/project "
                    "(e.g., 'Why is this code not working?', 'Explain this bug'), they are referring to (one of) the Context Path(s) "
                    "below. Read then provide analysis/explanation based on that codebase - you cannot modify it directly.\n",
                )

            for path_config in context_paths:
                path = path_config.get("path", "")
                permission = path_config.get("permission", "read")
                will_be_writable = path_config.get("will_be_writable", False)
                if path:
                    if permission == "read" and will_be_writable:
                        parts.append(
                            f"**Target Path**: `{path}` (read-only now, write access later) - This is where your changes will be delivered. "
                            f"Work in your workspace first, then the final presenter will place or update files DIRECTLY into `{path}` using the FULL ABSOLUTE PATH.",
                        )
                    elif permission == "write":
                        parts.append(
                            f"**Target Path**: `{path}` (write access) - This is where your changes must be delivered. "
                            f"First, ensure you place your answer in your workspace, then copy/write files DIRECTLY into `{path}` using FULL ABSOLUTE PATH (not relative paths). "
                            f"Files must go directly into the target path itself (e.g., `{path}/file.txt`), NOT into a `.massgen/` subdirectory within it.",
                        )
                    else:
                        parts.append(f"**Context Path**: `{path}` (read-only) - Use FULL ABSOLUTE PATH when reading.")

        # Add note connecting conversation history (in user message) to context paths (in system message)
        if previous_turns:
            parts.append(
                "\n**Note**: This is a multi-turn conversation. Each User/Assistant exchange in the conversation "
                "history represents one turn. The workspace from each turn is available as a read-only context path "
                "listed above (e.g., turn 1's workspace is at the path ending in `/turn_1/workspace`).",
            )

        # Add intelligent task handling guidance with clear priority hierarchy
        parts.append(
            "\n**Task Handling Priority**: When responding to user requests, follow this priority order:\n"
            "1. **Use MCP Tools First**: If you have specialized MCP tools available, call them DIRECTLY to complete the task\n"
            "   - Save any outputs/artifacts from MCP tools to your workspace\n"
            "2. **Write Code If Needed**: If MCP tools cannot complete the task, write and execute code\n"
            "3. **Create Other Files**: Create configs, documents, or other deliverables as needed\n"
            "4. **Text Response Otherwise**: If no tools or files are needed, provide a direct text answer\n\n"
            "**Important**: Do NOT ask the user for clarification or additional input. Make reasonable assumptions and proceed with sensible defaults. "
            "You will not receive user feedback, so complete the task autonomously based on the original request.\n",
        )

        # Add requirement for path explanations in answers
        # if enable_image_generation:
        # #     # Enabled for image generation tasks
        #     parts.append(
        #         "\n**Image Generation Tasks**: When working on image generation tasks, if you find images equivalent and cannot choose between them, "
        #         "choose the one with the smallest file size.\n"
        #         "\n**New Answer**: When calling `new_answer` tool:"
        #         "- For non-image generation tasks, if you created files, list your cwd and file paths (but do NOT paste full file contents)\n"
        #         "- For image generation tasks, do not use file write tools. Instead, the images are already generated directly "
        #         "with the image_generation tool. Then, providing new answer with 1) briefly describing the contents of the images "
        #         "and 2) listing your full cwd and the image paths you created.\n",
        #     )
        # else:
        # Not enabled for image generation tasks
        new_answer_guidance = "\n**New Answer**: When calling `new_answer`:\n"
        if enable_command_execution:
            new_answer_guidance += "- If you executed commands (e.g., running tests), explain the results in your answer (what passed, what failed, what the output shows)\n"
        new_answer_guidance += "- If you created files, list your cwd and file paths (but do NOT paste full file contents)\n"
        new_answer_guidance += "- If providing a text response, include your analysis/explanation in the `content` field\n"
        parts.append(new_answer_guidance)

        # Add workspace cleanup guidance
        parts.append(
            "**Workspace Cleanup**: Before submitting your answer with `new_answer`, " "ensure that your workspace contains only the files relevant to your final answer.\n",
            # use `delete_file` or "
            # "`delete_files_batch` to remove any outdated, temporary, or unused files from your workspace. "
            # "Note: You cannot delete read-only files (e.g., files from other agents' workspaces or read-only context paths). "
            # "This ensures only the relevant final files remain for evaluation. For example, if you created "
            # "`old_index.html` then later created `new_website/index.html`, delete the old version.\n",
        )

        # Add diff tools guidance
        parts.append(
            "**Comparison Tools**: Use `compare_directories` to see differences between two directories (e.g., comparing "
            "your workspace to another agent's workspace or a previous version), or `compare_files` to see line-by-line diffs "
            "between two files. These read-only tools help you understand what changed, build upon existing work effectively, "
            "or verify solutions before voting.\n",
        )

        # Add voting guidance
        # if enable_image_generation:
        #     # Enabled for image generation tasks
        #     parts.append(
        #         "**Evaluation**: When evaluating agents' answers, do NOT base your decision solely on the answer text. "
        #         "Instead, read and verify the actual files in their workspaces (via Shared Reference) to ensure the work matches their claims."
        #         "IMPORTANT: For image tasks, you MUST use ONLY the `mcp__workspace__extract_multimodal_files` tool to view and evaluate images. Do NOT use any other tool for this purpose.\n",
        #     )
        # else:
        # Not enabled for image generation tasks
        parts.append(
            "**Evaluation**: When evaluating agents' answers, do NOT base your decision solely on the answer text. "
            "Instead, read and verify the actual files in their workspaces (via Shared Reference) to ensure the work matches their claims.\n",
        )

        # Add command execution instructions if enabled
        if enable_command_execution:
            command_exec_message = self.command_execution_system_message(
                docker_mode=docker_mode,
                enable_sudo=enable_sudo,
            )
            parts.append(f"\n{command_exec_message}")

        return "\n".join(parts)

    def get_broadcast_guidance(
        self,
        broadcast_mode: str,
        wait_by_default: bool = True,
        sensitivity: str = "medium",
    ) -> str:
        """Generate guidance for using broadcast/communication tools.

        Args:
            broadcast_mode: "agents" or "human"
            wait_by_default: Whether ask_others() blocks by default
            sensitivity: How frequently to use ask_others() ("low", "medium", "high")

        Returns:
            Formatted guidance string to append to system messages
        """
        if "get_broadcast_guidance" in self._template_overrides:
            return str(self._template_overrides["get_broadcast_guidance"])

        guidance = """

## Agent Communication

You have access to the `ask_others()` tool for collaborative problem-solving.

**IMPORTANT: Call ask_others() when you need input, coordination, or collaboration from other agents"""
        if broadcast_mode == "human":
            guidance += " and the human user"
        guidance += """. Use it strategically to work effectively as a team.**

"""
        # Add sensitivity-specific guidance
        if sensitivity == "high":
            guidance += """**Collaboration frequency: HIGH - Use ask_others() frequently whenever you're considering options, proposing approaches, or could benefit from input.**

"""
        elif sensitivity == "low":
            guidance += """**Collaboration frequency: LOW - Use ask_others() only when blocked or for critical architectural decisions.**

"""
        else:  # medium
            guidance += """**Collaboration frequency: MEDIUM - Use ask_others() for significant decisions, design choices, or when confirmation would be valuable.**

"""

        guidance += """**When to use ask_others():**
- **When the user explicitly asks you to**: If the prompt says "ask_others for..." then CALL THE TOOL
- **Before making a key decision**: "What server-side rendering requirements does this project have?"
- **When you need clarification**: "What authentication patterns are already implemented?"
- **After providing an answer**: Ask others for feedback on your approach
- **When reviewing existing answers**: Ask questions about others' implementations
- **When stuck on something specific**: "How should I handle [specific issue]?"

**When NOT to use ask_others():**
- **For rhetorical questions**: Don't ask if you don't need actual responses
- **When the answer is obvious**: Use your judgment on what needs coordination
- **Repeatedly on the same topic**: One broadcast per decision is usually enough

**Best practices for timing:**
- **User says "ask_others"**: Call the tool immediately as requested
- **Need input before deciding**: Ask first, then provide your answer based on responses
- **Want feedback on your work**: Provide answer first, then ask for feedback
- **Use your judgment**: You can ask at any point when collaboration would help

**IMPORTANT: Include broadcast responses in your answer:**
When you receive responses from ask_others(), INCLUDE THEM in your new_answer() text file:
- Example: "I asked others about the framework choice. The response was: Vue. Based on this input, I will..."
- This ensures the information persists if your execution is restarted
- Check your answer file before calling ask_others() again - if you already documented the response, use it instead of asking again

**How it works:**"""

        if wait_by_default:
            guidance += """
- Call `ask_others(question)` with your question
- The tool blocks and waits for responses from other agents"""
            if broadcast_mode == "human":
                guidance += " and the human user"
            guidance += """
- Returns all responses immediately when ready
- You can then continue with your task"""
        else:
            guidance += """
- Call `ask_others(question, wait=False)` to send question without waiting
- Continue working on other tasks
- Later, check status with `check_broadcast_status(request_id)`
- Get responses with `get_broadcast_responses(request_id)` when ready"""

        guidance += """

**Best practices:**
- Be specific and actionable in your questions
- Use when you genuinely need coordination or input
- Actually CALL THE TOOL (don't just mention it in your answer text)
- Respond helpfully when others ask you questions

**Examples of good questions (feature-focused, not comparative):**
- "What SSR capabilities does the project require?"
- "What database constraints or dependencies exist for the User model?"
- "Which OAuth library is configured in the project dependencies?"
- "What authentication patterns are already implemented in this codebase?"
- "What are the performance requirements for this feature?"
"""

        if broadcast_mode == "human":
            guidance += """
**Note:** The human user may also respond to your questions alongside other agents.
"""

        return guidance


# ### IMPORTANT Evaluation Note:
# When evaluating other agents' work, focus on the CONTENT and FUNCTIONALITY of their files.
# Each agent works in their own isolated workspace - this is correct behavior.
# The paths shown in their answers are normalized so you can access and verify their work.
# Judge based on code quality, correctness, and completeness, not on which workspace directory was used.


# Global template instance
_templates = MessageTemplates()


def get_templates() -> MessageTemplates:
    """Get global message templates instance."""
    return _templates


def set_templates(templates: MessageTemplates) -> None:
    """Set global message templates instance."""
    global _templates
    _templates = templates


# Convenience functions for common operations
def build_case1_conversation(task: str) -> dict[str, Any]:
    """Build Case 1 conversation (no summaries exist)."""
    return get_templates().build_initial_conversation(task)


def build_case2_conversation(
    task: str,
    agent_summaries: dict[str, str],
    valid_agent_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Build Case 2 conversation (summaries exist)."""
    return get_templates().build_initial_conversation(task, agent_summaries, valid_agent_ids)


def get_standard_tools(
    valid_agent_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Get standard MassGen tools."""
    return get_templates().get_standard_tools(valid_agent_ids)


def get_enforcement_message(buffer_content: str | None = None) -> str:
    """Get enforcement message for Case 3.

    Args:
        buffer_content: Optional streaming buffer content from the agent's incomplete response.
    """
    return get_templates().enforcement_message(buffer_content=buffer_content)
