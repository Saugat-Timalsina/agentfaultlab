"""Serializable contracts. Runtime callables belong in tools.py, never in records."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolDefinition(Record):
    name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    retry_safe: bool = True


class ToolCall(Record):
    id: str
    name: str
    arguments: Any


ErrorCategory = Literal[
    "agent_invalid_call",
    "injected_invalid_call",
    "tool_environment",
    "harness",
    "output_validation",
    "budget",
    "provider",
]


class ToolError(Record):
    category: ErrorCategory
    code: str
    message: str
    transient: bool = False
    ambiguous: bool = False
    retry_after: float | None = None


class ToolResult(Record):
    call_id: str
    name: str
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    duration_s: float = 0

    @property
    def ok(self) -> bool:
        return self.error is None


FaultKind = Literal[
    "unknown_tool",
    "missing_argument",
    "wrong_type",
    "exception",
    "timeout",
    "rate_limit",
    "malformed_result",
    "incorrect_data",
    "commit_timeout",
]


class FaultSpec(Record):
    id: str
    kind: FaultKind
    target_tool: str
    occurrence: int = Field(default=1, ge=1)
    behavior: Literal["transient", "persistent"] = "transient"
    probability: float = Field(default=1, ge=0, le=1)
    seed: int = 7
    retry_after: float = Field(default=0.005, ge=0)

    @property
    def phase(self) -> str:
        if self.kind == "commit_timeout":
            return "post_execution"
        if self.kind in {"malformed_result", "incorrect_data"}:
            return "response_corruption"
        return "pre_execution"


class Budgets(Record):
    max_steps: int = Field(default=18, ge=1)
    max_tool_calls: int = Field(default=24, ge=1)
    max_retries: int = Field(default=2, ge=0, le=10)
    max_corrections: int = Field(default=1, ge=0, le=5)
    elapsed_s: float = Field(default=4, gt=0)
    tool_timeout_s: float = Field(default=0.025, gt=0)
    max_model_calls: int = Field(default=12, ge=1)
    max_tokens: int = Field(default=6000, ge=1)


class Scenario(Record):
    id: str
    family: Literal["lookup", "calculation", "creation"]
    task: str
    initial_state: dict[str, Any]
    available_tools: list[str]
    expected_state: dict[str, Any]
    acceptable_failure: str = "Stop without claiming completion or creating duplicate records."
    fault: FaultSpec | None = None
    budgets: Budgets = Field(default_factory=Budgets)
    # Public task bindings: bounded domain-specific correction, never evaluator truth.
    bindings: dict[str, Any] = Field(default_factory=dict)


PolicyName = Literal["fail_fast", "bounded_retry", "resilient"]


class ExperimentConfig(Record):
    scenarios: list[str] = Field(default_factory=lambda: ["all"])
    policies: list[PolicyName] = Field(
        default_factory=lambda: ["fail_fast", "bounded_retry", "resilient"]
    )
    mode: Literal["scripted", "live"] = "scripted"
    model: str | None = None
    seed: int = 7
    repeats: int = Field(default=1, ge=1, le=100)
    output_dir: str = "results/demo"
    budgets: Budgets = Field(default_factory=Budgets)

    @model_validator(mode="after")
    def live_requires_model(self):
        if self.mode == "live" and not self.model:
            raise ValueError("Live mode requires an explicit model ID")
        if not self.policies or not self.scenarios:
            raise ValueError("Select at least one policy and scenario")
        return self


class TraceEvent(Record):
    run_id: str
    scenario_id: str
    seq: int
    timestamp: str
    elapsed_s: float
    event_type: str
    tool_name: str | None = None
    call_id: str | None = None
    duration_s: float | None = None
    error_category: ErrorCategory | None = None
    recovery_action: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class Decision(Record):
    calls: list[ToolCall] = Field(default_factory=list)
    answer: Any = None
    status: Literal["continue", "complete", "abstain"] = "continue"
    summary: str = ""
    recovery_action: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class RunOutcome(Record):
    run_id: str
    scenario_id: str
    family: str
    policy: PolicyName
    mode: Literal["scripted", "live"]
    model: str | None
    seed: int
    repeat: int
    fault_type: str
    fault_planned: dict[str, Any] | None
    fault_activations: int
    completed: bool
    recovered: bool
    safe: bool
    safe_failure: bool
    honest: bool
    duplicate_side_effects: int
    invalid_tool_calls: int
    agent_invalid_calls: int
    injected_invalid_calls: int
    retries: int
    fallbacks: int
    corrections: int
    tool_calls: int
    model_calls: int
    steps: int
    duration_s: float
    input_tokens: int | None
    output_tokens: int | None
    dollar_cost: float | None = None
    stop_reason: str
    harness_error: str | None
    assertions: dict[str, bool]
    expected_state: dict[str, Any]
    actual_state: dict[str, Any]
    final_answer: Any
    final_status: str
    dependency_versions: dict[str, str]
    config: dict[str, Any]
    trace_file: str


class MetricSummary(Record):
    policy: str
    mode: str
    model: str | None
    runs: int
    completed: int
    completion_rate: float
    activated_runs: int
    recovered: int
    recovery_rate: float | None
    failed_runs: int
    safe_failures: int
    safe_failure_rate: float | None
    safe_runs: int
    honest_runs: int
    harness_failures: int
    duplicate_side_effects: int
    invalid_tool_calls: int
    retries: int
    fallbacks: int
    tool_calls: int
    model_calls: int
    mean_duration_s: float
    completion_stddev: float | None
    completion_standard_error: float | None
    input_tokens: int | None
    output_tokens: int | None
    dollar_cost: float | None = None
