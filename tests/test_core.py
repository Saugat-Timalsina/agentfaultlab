import asyncio
import json
import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentfaultlab.agents import ScriptedAgent
from agentfaultlab.cli import app
from agentfaultlab.executor import ToolExecutor
from agentfaultlab.faults import FaultInjector
from agentfaultlab.policies import Recovery
from agentfaultlab.reporting import load_results, summarize
from agentfaultlab.runner import run_experiment, run_one
from agentfaultlab.scenarios import scenario_catalog
from agentfaultlab.schemas import Budgets, Decision, ExperimentConfig, FaultSpec, ToolCall
from agentfaultlab.tools import Environment
from agentfaultlab.tracing import Trace, load_trace, redact


@pytest.fixture
def config(tmp_path):
    return ExperimentConfig(output_dir=str(tmp_path))


def make_executor(rule=None, timeout=0.01):
    env = Environment(scenario_catalog()["lookup-control"].initial_state)
    trace = Trace("run", "scenario")
    executor = ToolExecutor(env.registry(), FaultInjector([rule] if rule else []), trace, timeout)
    return env, executor, trace


@pytest.mark.parametrize(
    "name,args,code",
    [
        ("invented_tool", {}, "unknown_tool"),
        ("lookup_primary", {}, "invalid_arguments"),
        ("lookup_primary", {"key": 1}, "invalid_arguments"),
        ("lookup_primary", '{"key": "capacity"}', "invalid_arguments"),
        ("lookup_primary", {"key": "capacity", "extra": True}, "invalid_arguments"),
    ],
)
async def test_invalid_calls_are_not_silently_repaired(name, args, code):
    _, executor, trace = make_executor()
    result = await executor.execute(ToolCall(id="c", name=name, arguments=args))
    assert result.error.category == "agent_invalid_call"
    assert result.error.code == code
    assert executor.agent_invalid == 1
    assert [e.event_type for e in trace.events] == ["tool_call", "observed_result"]


async def test_strict_valid_argument_and_result():
    _, executor, _ = make_executor()
    call = ToolCall(id="c", name="lookup_primary", arguments={"key": "capacity"})
    result = await executor.execute(call)
    assert result.data == {"value": 42, "source": "primary"}


@pytest.mark.parametrize("kind", ["unknown_tool", "missing_argument", "wrong_type"])
async def test_mutations_are_distinguished_from_agent_errors(kind):
    rule = FaultSpec(id="f", kind=kind, target_tool="lookup_primary")
    _, executor, trace = make_executor(rule)
    result = await executor.execute(
        ToolCall(id="c", name="lookup_primary", arguments={"key": "capacity"})
    )
    assert result.error.category == "injected_invalid_call"
    assert executor.injected_invalid == 1 and executor.agent_invalid == 0
    activation = next(e for e in trace.events if e.event_type == "fault_activated")
    assert activation.payload["original_call"] != activation.payload["effective_call"]


async def test_invalid_attempt_counts_but_does_not_activate():
    rule = FaultSpec(id="f", kind="exception", target_tool="lookup_primary", occurrence=2)
    _, executor, _ = make_executor(rule)
    await executor.execute(ToolCall(id="bad", name="lookup_primary", arguments={}))
    await executor.execute(
        ToolCall(id="good", name="lookup_primary", arguments={"key": "capacity"})
    )
    assert executor.injector.activations[0]["actual_occurrence"] == 2


@pytest.mark.parametrize("behavior,expected", [("transient", [2]), ("persistent", [2, 3, 4])])
def test_explicit_occurrence_and_target(behavior, expected):
    rule = FaultSpec(
        id="f", kind="exception", target_tool="lookup_primary", occurrence=2, behavior=behavior
    )
    injector = FaultInjector([rule])
    assert injector.select("other", injector.observe("other")) is None
    selected = [
        i
        for i in range(1, 5)
        if injector.select("lookup_primary", injector.observe("lookup_primary"))
    ]
    assert selected == expected


def test_seeded_schedule_reproducibility():
    def schedule(seed):
        rule = FaultSpec(
            id="f",
            kind="exception",
            target_tool="t",
            probability=0.5,
            behavior="persistent",
            seed=seed,
        )
        injector = FaultInjector([rule])
        return [injector.select("t", injector.observe("t")) is not None for _ in range(40)]

    assert schedule(12) == schedule(12)
    assert schedule(12) != schedule(13)


async def test_real_timeout_cancels_handler():
    _, executor, _ = make_executor(timeout=0.01)
    cancelled = asyncio.Event()

    async def slow(key):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    executor.registry["lookup_primary"].handler = slow
    started = time.monotonic()
    result = await executor.execute(
        ToolCall(id="slow", name="lookup_primary", arguments={"key": "capacity"})
    )
    assert result.error.code == "timeout"
    assert cancelled.is_set()
    assert 0.005 <= time.monotonic() - started < 1


async def test_retry_limits_and_capped_backoff_without_real_sleep():
    rule = FaultSpec(id="f", kind="exception", target_tool="lookup_primary", behavior="persistent")
    _, executor, trace = make_executor(rule)
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    policy = Recovery(
        "bounded_retry",
        Budgets(max_retries=5),
        executor.registry,
        trace,
        executor.execute,
        100,
        {"key": "capacity"},
        clock=lambda: 0,
        sleep=fake_sleep,
    )
    result = await policy.execute(
        ToolCall(id="c", name="lookup_primary", arguments={"key": "capacity"})
    )
    assert result.error and executor.calls == 6
    assert delays == [0.01, 0.02, 0.04, 0.08, 0.1]


async def test_retry_after_exceeding_deadline_does_not_retry_early():
    rule = FaultSpec(id="f", kind="rate_limit", target_tool="lookup_primary", retry_after=30)
    _, executor, trace = make_executor(rule)
    policy = Recovery(
        "bounded_retry",
        Budgets(),
        executor.registry,
        trace,
        executor.execute,
        2,
        {"key": "capacity"},
        clock=lambda: 0,
    )
    result = await policy.execute(
        ToolCall(id="c", name="lookup_primary", arguments={"key": "capacity"})
    )
    assert result.error.retry_after == 30 and executor.calls == 1
    assert policy.retries == 0


async def test_retry_after_minimum_respected():
    rule = FaultSpec(id="f", kind="rate_limit", target_tool="lookup_primary", retry_after=0.3)
    _, executor, trace = make_executor(rule)
    delays = []

    async def fake_sleep(delay):
        delays.append(delay)

    policy = Recovery(
        "bounded_retry",
        Budgets(),
        executor.registry,
        trace,
        executor.execute,
        10,
        {"key": "capacity"},
        clock=lambda: 0,
        sleep=fake_sleep,
    )
    assert (
        await policy.execute(ToolCall(id="c", name="lookup_primary", arguments={"key": "capacity"}))
    ).ok
    assert delays == [0.3]


@pytest.mark.parametrize("field,limit", [("max_tool_calls", 1), ("max_steps", 1)])
async def test_run_count_budgets(config, field, limit):
    config.budgets = Budgets(**{field: limit})
    result = await run_one(scenario_catalog()["lookup-control"], "resilient", config)
    assert result.stop_reason == field
    assert not result.completed


async def test_run_deadline_cancels_agent(config):
    class SlowAgent(ScriptedAgent):
        async def decide(self, context):
            await asyncio.sleep(10)

    config.budgets.elapsed_s = 0.02
    result = await run_one(
        scenario_catalog()["lookup-control"], "resilient", config, agent=SlowAgent()
    )
    assert result.stop_reason == "elapsed_s"
    assert result.duration_s < 1


async def test_no_environment_leakage(config):
    scenario = scenario_catalog()["creation-control"]
    first = await run_one(scenario, "resilient", config)
    second = await run_one(scenario, "resilient", config)
    assert first.actual_state == second.actual_state
    assert first.completed and second.completed
    assert scenario.initial_state["records"] == []


@pytest.mark.parametrize(
    "policy,completed", [("fail_fast", False), ("bounded_retry", False), ("resilient", True)]
)
async def test_ambiguous_write_reconciles_without_duplicates(config, policy, completed):
    result = await run_one(scenario_catalog()["creation-commit-timeout"], policy, config)
    assert result.completed == completed
    assert len(result.actual_state["records"]) == 1
    assert result.duplicate_side_effects == 0
    assert result.retries == 0
    events = load_trace(Path(config.output_dir) / result.trace_file)
    assert sum(e.event_type == "tool_call" and e.tool_name == "create_ticket" for e in events) == 1
    if completed:
        assert any(e.recovery_action == "reconcile_state" for e in events)
        assert result.assertions["existence_verified"]


async def test_idempotency_key_deduplicates_at_tool_boundary():
    env, executor, _ = make_executor()
    call = ToolCall(
        id="1", name="create_ticket", arguments={"title": "ticket", "idempotency_key": "same"}
    )
    first = await executor.execute(call)
    second = await executor.execute(call.model_copy(update={"id": "2"}))
    assert first.data == second.data
    assert len(env.state["records"]) == 1


async def test_malformed_result_is_visible_and_recovered(config):
    outcome = await run_one(scenario_catalog()["calculation-malformed-result"], "resilient", config)
    assert outcome.completed and outcome.retries == 1
    events = load_trace(Path(config.output_dir) / outcome.trace_file)
    assert any(e.error_category == "output_validation" for e in events)


async def test_plausible_lookup_corruption_needs_cross_check(config):
    scenario = scenario_catalog()["lookup-incorrect-data"]
    first = await run_one(scenario, "bounded_retry", config)
    resilient = await run_one(scenario, "resilient", config)
    assert not first.completed and first.safe_failure
    assert resilient.completed and resilient.fallbacks == 1


async def test_schema_valid_corruption_can_defeat_arithmetic_check(config):
    result = await run_one(scenario_catalog()["calculation-incorrect-data"], "resilient", config)
    assert result.actual_state["answer"] == 3464
    assert not result.completed and not result.honest and not result.safe_failure
    assert result.final_status == "complete"
    assert result.assertions["persisted_answer"] is False


async def test_scoring_rejects_false_success(config):
    class Liar(ScriptedAgent):
        async def decide(self, context):
            return Decision(status="complete", answer="I succeeded")

    result = await run_one(scenario_catalog()["lookup-control"], "fail_fast", config, agent=Liar())
    assert not result.completed and not result.honest


async def test_harness_bug_is_not_agent_failure(config):
    env = Environment(scenario_catalog()["lookup-control"].initial_state)
    registry = env.registry()

    async def buggy(key):
        raise RuntimeError("programmer bug")

    registry["lookup_primary"].handler = buggy
    env.registry = lambda: registry
    result = await run_one(
        scenario_catalog()["lookup-control"], "resilient", config, environment=env
    )
    assert result.harness_error == "RuntimeError: programmer bug"
    assert result.stop_reason == "harness_failure"
    assert not result.safe_failure and result.agent_invalid_calls == 0


async def test_evaluator_bug_is_harness_failure(config, monkeypatch):
    def broken(*args):
        raise RuntimeError("evaluator bug")

    monkeypatch.setattr("agentfaultlab.runner.score", broken)
    result = await run_one(scenario_catalog()["lookup-control"], "fail_fast", config)
    assert result.harness_error.startswith("Evaluator RuntimeError")
    assert not result.completed


async def test_unactivated_fault_not_recovery(config):
    scenario = scenario_catalog()["lookup-exception"]
    scenario.fault.occurrence = 99
    result = await run_one(scenario, "resilient", config)
    assert result.completed and not result.recovered
    summary = summarize([result])[0]
    assert summary.activated_runs == 0 and summary.recovery_rate is None


async def test_trace_serialization_and_playback(config):
    result = await run_one(scenario_catalog()["lookup-control"], "fail_fast", config)
    path = Path(config.output_dir) / result.trace_file
    events = load_trace(path)
    assert events[0].event_type == "run_started"
    assert events[-1].event_type == "verified_outcome"
    assert events[-1].payload["completed"] is True
    assert all(e.run_id == result.run_id for e in events)
    raw = path.read_text().splitlines()
    item = json.loads(raw[0])
    item["seq"] = 8
    raw[0] = json.dumps(item)
    path.write_text("\n".join(raw))
    with pytest.raises(ValueError, match="sequence"):
        load_trace(path)


def test_redaction_preserves_metrics_and_public_idempotency_keys():
    assert redact({"api_key": "sensitive", "nested": ["Bearer abc", "sk-fake12345678"]}) == {
        "api_key": "[REDACTED]",
        "nested": ["[REDACTED]", "[REDACTED]"],
    }
    assert redact({"input_tokens": 3, "idempotency_key": "public"}) == {
        "input_tokens": 3,
        "idempotency_key": "public",
    }


async def test_agent_cannot_see_injector_metadata(config):
    class Spy(ScriptedAgent):
        async def decide(self, context):
            serialized = json.dumps(context.observations)
            assert "injected_invalid_call" not in serialized
            assert "rule_id" not in serialized and "fault_activated" not in serialized
            assert "expected_state" not in serialized
            return await super().decide(context)

    result = await run_one(
        scenario_catalog()["lookup-missing-argument"], "resilient", config, agent=Spy()
    )
    assert result.completed


async def test_full_offline_matrix_and_repeat_variability(config):
    config.repeats = 2
    outcomes = await run_experiment(config)
    assert len(outcomes) == 90
    assert not any(o.harness_error for o in outcomes)
    assert all(o.mode == "scripted" and o.input_tokens is None for o in outcomes)
    summaries = {s.policy: s for s in summarize(outcomes)}
    assert summaries["resilient"].completed == 26
    assert summaries["resilient"].completion_stddev == 0
    assert len(load_results(Path(config.output_dir))) == 90
    manifest = json.loads((Path(config.output_dir) / "manifest.json").read_text())
    assert len(manifest["runs"]) == 90


def test_cli_demo_compare_and_inspect(tmp_path):
    runner = CliRunner()
    demo = runner.invoke(app, ["demo", "--output", str(tmp_path)])
    assert demo.exit_code == 0, demo.output
    assert "45 scripted runs" in demo.output
    compared = runner.invoke(app, ["compare", "--results", str(tmp_path)])
    assert compared.exit_code == 0
    path = next(tmp_path.glob("*.run.json"))
    inspected = runner.invoke(app, ["inspect", str(path)])
    assert inspected.exit_code == 0 and "verified_outcome" in inspected.output
