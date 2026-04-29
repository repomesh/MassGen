"""
Textual widgets for the MassGen TUI.

This module provides reusable Textual widgets for the production TUI interface.
"""

from .agent_status_ribbon import (
    AgentStatusRibbon,
    AnswerNowClicked,
    AnswerNowLabel,
    BackgroundTasksClicked,
    BackgroundTasksLabel,
    ContextPathsClicked,
    DropdownItem,
    RoundSelected,
    RoundSelector,
    TasksClicked,
    ViewDropdown,
    ViewSelected,
)
from .background_tasks_modal import BackgroundTasksModal
from .content_sections import (
    CompletionFooter,
    FinalPresentationCard,
    ReasoningSection,
    ResponseSection,
    RestartBanner,
    StatusBadge,
    ThinkingSection,
    TimelineSection,
    ToolSection,
)
from .copy_mode_banner import CopyModeBanner
from .execution_status_line import ExecutionStatusLine
from .final_answer_view import FinalAnswerView
from .injection_card import InjectionSubCard
from .mode_bar import (
    ModeBar,
    ModeChanged,
    ModeHelpClicked,
    ModeToggle,
    OverrideRequested,
    PlanConfigChanged,
    PlanSettingsClicked,
    SkillsClicked,
    SubtasksClicked,
)
from .multi_line_input import MultiLineInput
from .path_suggestion import PathSuggestion, PathSuggestionDropdown
from .phase_indicator_bar import PhaseIndicatorBar
from .plan_approval_modal import PlanApprovalModal, PlanApprovalResult
from .plan_options import (
    AnalysisProfileChanged,
    AnalysisSkillLifecycleChanged,
    AnalysisTargetChanged,
    AnalysisTargetTypeChanged,
    BroadcastModeChanged,
    ExecuteAutoContinueChanged,
    ExecutePrefillRequested,
    ExecuteRefinementModeChanged,
    PlanChunkTargetChanged,
    PlanDepthChanged,
    PlanOptionsPopover,
    PlanSelected,
    PlanStepTargetChanged,
    ViewAnalysisRequested,
    ViewPlanRequested,
)
from .queued_input_banner import QueuedInputBanner
from .quickstart_wizard import QuickstartWizard
from .session_info_panel import SessionInfoPanel
from .setup_wizard import SetupWizard
from .subagent_card import SubagentCard
from .subagent_modal import SubagentModal
from .subagent_screen import SubagentPanel, SubagentScreen, SubagentView
from .subagent_tui_modal import SubagentTuiModal
from .tab_bar import AgentTab, AgentTabBar, AgentTabChanged, SessionInfoClicked
from .task_plan_card import TaskPlanCard
from .task_plan_host import TaskPlanHost
from .task_plan_modal import TaskPlanModal
from .tool_batch_card import ToolBatchCard, ToolBatchItem
from .tool_card import ToolCallCard, format_tool_display_name, get_tool_category
from .tool_detail_modal import ToolDetailModal
from .wizard_base import (
    StepComponent,
    WizardCancelled,
    WizardCompleted,
    WizardModal,
    WizardState,
    WizardStep,
)

__all__ = [
    # Mode bar
    "ModeBar",
    "ModeToggle",
    "ModeChanged",
    "ModeHelpClicked",
    "OverrideRequested",
    "PlanConfigChanged",
    "PlanSettingsClicked",
    "SkillsClicked",
    "SubtasksClicked",
    # Plan options popover
    "PlanOptionsPopover",
    "PlanSelected",
    "PlanDepthChanged",
    "PlanStepTargetChanged",
    "PlanChunkTargetChanged",
    "BroadcastModeChanged",
    "ViewPlanRequested",
    "ExecuteAutoContinueChanged",
    "ExecuteRefinementModeChanged",
    "ExecutePrefillRequested",
    "AnalysisProfileChanged",
    "AnalysisSkillLifecycleChanged",
    "AnalysisTargetChanged",
    "AnalysisTargetTypeChanged",
    "ViewAnalysisRequested",
    # Tab bar
    "AgentTab",
    "AgentTabBar",
    "AgentTabChanged",
    "SessionInfoClicked",
    # Agent status ribbon
    "AgentStatusRibbon",
    "AnswerNowClicked",
    "AnswerNowLabel",
    "BackgroundTasksClicked",
    "BackgroundTasksLabel",
    "ContextPathsClicked",
    "DropdownItem",
    "RoundSelected",
    "RoundSelector",
    "TasksClicked",
    "ViewDropdown",
    "ViewSelected",
    # Execution status line
    "ExecutionStatusLine",
    # Phase indicator bar
    "PhaseIndicatorBar",
    # Session info panel
    "SessionInfoPanel",
    # Tool cards and modal
    "ToolCallCard",
    "ToolBatchCard",
    "ToolBatchItem",
    "ToolDetailModal",
    "get_tool_category",
    "format_tool_display_name",
    # Task plan card and modal
    "TaskPlanCard",
    "TaskPlanHost",
    "TaskPlanModal",
    # Plan approval modal
    "PlanApprovalModal",
    "PlanApprovalResult",
    # Subagent card, modal, and screen
    "SubagentCard",
    "SubagentModal",
    "SubagentPanel",
    "SubagentScreen",
    "SubagentView",
    "SubagentTuiModal",
    # Background tasks modal
    "BackgroundTasksModal",
    # Injection sub-card
    "InjectionSubCard",
    # Content sections
    "ToolSection",
    "TimelineSection",
    "ThinkingSection",
    "ReasoningSection",
    "ResponseSection",
    "StatusBadge",
    "CompletionFooter",
    "RestartBanner",
    "FinalPresentationCard",
    # Final Answer View
    "FinalAnswerView",
    # Input widgets
    "MultiLineInput",
    "CopyModeBanner",
    "QueuedInputBanner",
    # Path autocomplete
    "PathSuggestion",
    "PathSuggestionDropdown",
    # Wizard framework
    "WizardModal",
    "WizardState",
    "WizardStep",
    "WizardCancelled",
    "WizardCompleted",
    "StepComponent",
    "SetupWizard",
    "QuickstartWizard",
]
