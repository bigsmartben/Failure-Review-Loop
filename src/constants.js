export const STATUSES = Object.freeze([
  "PENDING",
  "COLLECTING",
  "FAILED_COLLECTION",
  "VALIDATING_EVIDENCE",
  "FAILED_EVIDENCE_VALIDATION",
  "ANALYZING",
  "FAILED_ANALYSIS",
  "VALIDATING_FINDINGS",
  "FAILED_FINDINGS_VALIDATION",
  "COMPUTING_METRICS",
  "FAILED_METRICS",
  "COMPUTING_TREND",
  "FAILED_TREND",
  "CHECKING_THRESHOLD",
  "COMPLETED_NO_TASKS",
  "COMPLETED_WITH_METRICS",
  "COMPLETED_WITH_FINDINGS",
  "OPTIMIZING",
  "FAILED_OPTIMIZATION",
  "VALIDATING_PROPOSAL",
  "FAILED_PROPOSAL_VALIDATION",
  "COMPLETED_WITH_PROPOSAL"
]);

export const TERMINAL_STATUSES = new Set(STATUSES.filter((s) =>
  s.startsWith("FAILED_") || s.startsWith("COMPLETED_")));

export const CATEGORIES = Object.freeze([
  "trigger_failure",
  "workflow_gap",
  "ambiguous_rule",
  "script_bug",
  "reference_gap",
  "template_issue",
  "environment_issue",
  "unclear_expectation"
]);

export const SOURCE_TYPES = Object.freeze([
  "message",
  "tool_call",
  "tool_result",
  "execution_error",
  "artifact_reference"
]);

export const THRESHOLD = 3;

export const MIN_TREND_TASKS = 3;

export const PATTERNS = Object.freeze([
  "repeated_clarification",
  "repeated_execution",
  "unmet_expectation"
]);
