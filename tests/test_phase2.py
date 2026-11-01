import asyncio
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agentfaultlab.budget import BudgetExceeded, RunBudget
from agentfaultlab.cli import app
from agentfaultlab.dashboard import percentage_chart
from agentfaultlab.executor import ToolExecutor
from agentfaultlab.faults import FaultInjector
from agentfaultlab.planning import build_schedule, preview
from agentfaultlab.policies import Recovery
from agentfaultlab.recipes import Recipe
from agentfaultlab.reporting import load_results, summarize
from agentfaultlab.runner import run_one
from agentfaultlab.scenarios import scenario_catalog
from agentfaultlab.schemas import Budgets, ExperimentConfig, ToolCall
from agentfaultlab.tools import DomainError, Environment
from agentfaultlab.tracing import Trace, load_trace

PROJECT_ROOT = Path(__file__).resolve().parents[1]


async def run_case(tmp_path, name, policy="resilient", **kwargs):
    return await run_one(
        scenario_catalog()[name], policy, ExperimentConfig(output_dir=str(tmp_path)), **kwargs
    )


def boundary(scenario, limits=None):
    env = Environment(scenario.initial_state)
    trace = Trace("test", scenario.id)
    budget = RunBudget(limits or Budgets())
    rules = ([scenario.fault] if scenario.fault else []) + scenario.additional_faults
    executor = ToolExecutor(
        env.registry(), FaultInjector(rules), trace, budget.limits.tool_timeout_s, budget
    )
    recovery = Recovery(
        "resilient",
        budget.limits,
        executor.registry,
        trace,
        executor.execute,
        budget.deadline,
        scenario.bindings,
        budget=budget,
    )
    return env, trace, budget, executor, recovery


async def test_tool_remaining_deadline_wins_over_operation_timeout():
    env, trace, budget, executor, _ = boundary(
        scenario_catalog()["lookup-control"], Budgets(elapsed_s=0.015, tool_timeout_s=10)
    )
    cancelled = asyncio.Event()

    async def slow(key):
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    executor.registry["lookup_primary"].handler = slow
    with pytest.raises(BudgetExceeded, match="elapsed_s"):
        await executor.execute(
            ToolCall(id="r", name="lookup_primary", arguments={"key": "capacity"})
        )
    assert cancelled.is_set()
    assert not any(e.event_type == "observed_result" for e in trace.events)


async def test_cancellation_propagates_through_executor_and_policy():
    _, _, _, executor, policy = boundary(scenario_catalog()["lookup-control"])
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def slow(key):
        entered.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    executor.registry["lookup_primary"].handler = slow
    task = asyncio.create_task(
        policy.execute(ToolCall(id="r", name="lookup_primary", arguments={"key": "capacity"}))
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set() and executor.calls == 1 and policy.retries == 0


async def test_deadline_exhaustion_during_reconciliation():
    scenario = scenario_catalog()["correlation-write-lost-response"]
    env, trace, budget, executor, policy = boundary(
        scenario, Budgets(elapsed_s=0.04, tool_timeout_s=0.015)
    )

    async def slow(request_key):
        await asyncio.sleep(10)

    executor.registry["find_correlation_ticket"].handler = slow
    # Longer read timeout, but total shared deadline still bounds it.
    original = executor.timeout_s

    async def invoke(call):
        executor.timeout_s = original if call.name.startswith("create") else 10
        return await executor.execute(call)

    policy.invoke = invoke
    with pytest.raises(BudgetExceeded, match="elapsed_s"):
        await policy.execute(
            ToolCall(
                id="r",
                name="create_correlation_ticket",
                arguments={"title": "Investigate sensor", "request_key": "request-001"},
            )
        )
    assert len(env.state["records"]) == 1 and executor.calls == 2


@pytest.mark.parametrize("resource,limit", [("max_tool_calls", 1), ("max_recovery_actions", 0)])
async def test_recovery_consumes_shared_budget(tmp_path, resource, limit):
    config = ExperimentConfig(output_dir=str(tmp_path))
    setattr(config.budgets, resource, limit)
    result = await run_one(
        scenario_catalog()["correlation-write-lost-response"], "resilient", config
    )
    assert result.stop_reason == resource
    assert not result.completed and not result.recovered
    assert result.tool_calls == 1
    assert result.uncertain


async def test_budget_stop_after_verification_is_not_successful_recovery(tmp_path):
    config = ExperimentConfig(output_dir=str(tmp_path))
    config.budgets.max_recovery_actions = 1
    result = await run_one(
        scenario_catalog()["correlation-write-lost-response"], "resilient", config
    )
    assert result.stop_reason == "max_recovery_actions"
    assert result.completed  # State/evidence already verified, independently of termination.
    assert not result.recovered  # No terminal successful recovery was returned to the agent.


@pytest.mark.parametrize(
    "case,reason,count",
    [
        ("correlation-write-lost-response", "reconciled_existing_write", 1),
        ("idempotent-write-lost-response", "reconciled_existing_write", 1),
        ("correlation-reconcile-no-record", "no_record", 0),
        ("correlation-reconcile-multiple-records", "multiple_records", 2),
        ("correlation-reconcile-conflicting-content", "conflicting_content", 1),
        ("correlation-reconcile-read-fails", "verification_failed", 1),
    ],
)
async def test_write_reconciliation_cases_and_provenance(tmp_path, case, reason, count):
    result = await run_case(tmp_path, case)
    events = load_trace(tmp_path / result.trace_file)
    returned = next(e for e in events if e.event_type == "middleware_result")
    assert returned.payload["reason"] == reason
    assert len(result.actual_state["records"]) == count
    calls = [e for e in events if e.event_type == "tool_call"]
    writes = [e for e in calls if e.tool_name.startswith("create")]
    assert len(writes) == 1
    root = writes[0].call_id
    assert all(e.root_call_id == root for e in calls[:2])
    assert calls[1].parent_call_id == root and calls[1].owner == "middleware"
    assert calls[1].call_id in returned.payload["supporting_call_ids"]
    assert returned.call_id == root and returned.owner == "middleware"
    assert result.completed == (reason == "reconciled_existing_write")
    assert result.uncertain != result.completed
    if count == 0:
        assert not any(e.event_type == "environment_commit" for e in events)


async def test_commit_event_requires_real_state_change():
    scenario = scenario_catalog()["correlation-write-lost-response"]
    env, trace, _, executor, _ = boundary(scenario)

    async def pretend(title, request_key):
        return {
            "id": "fiction",
            "title": title,
            "request_key": request_key,
            "service": "correlation",
        }

    executor.registry["create_correlation_ticket"].handler = pretend
    result = await executor.execute(
        ToolCall(
            id="r",
            name="create_correlation_ticket",
            arguments={"title": "Investigate sensor", "request_key": "request-001"},
        )
    )
    assert result.error.ambiguous and not env.state["records"]
    assert not any(e.event_type == "environment_commit" for e in trace.events)


async def test_server_idempotency_and_conflict_are_explicit():
    scenario = scenario_catalog()["idempotent-write-lost-response"]
    env = Environment(scenario.initial_state)
    create = env.registry()["create_idempotent_ticket"].handler
    first = await create(title="same", request_key="k")
    assert await create(title="same", request_key="k") == first
    with pytest.raises(DomainError, match="idempotency_conflict"):
        await create(title="different", request_key="k")
    assert len(env.state["records"]) == 1
    correlated = env.registry()["create_correlation_ticket"].handler
    await correlated(title="same", request_key="c")
    await correlated(title="same", request_key="c")
    assert len(env.state["records"]) == 3


async def test_fallback_preserves_source_and_lineage(tmp_path):
    scenario = scenario_catalog()["lookup-exception"]
    scenario.fault.behavior = "persistent"
    result = await run_one(scenario, "resilient", ExperimentConfig(output_dir=str(tmp_path)))
    events = load_trace(tmp_path / result.trace_file)
    synthesized = next(e for e in events if e.event_type == "middleware_result")
    calls = {e.call_id: e for e in events if e.event_type == "tool_call"}
    ids = synthesized.payload["supporting_call_ids"]
    assert calls[ids[-1]].tool_name == "lookup_secondary"
    assert calls[ids[-1]].owner == "middleware"
    assert synthesized.payload["result"]["data"]["source"] == "secondary"
    assert len({calls[i].root_call_id for i in ids}) == 1


@pytest.mark.parametrize(
    "case,complete",
    [
        ("invoice-sources-agree", True),
        ("invoice-primary-corrupted", True),
        ("invoice-reference-unavailable", False),
        ("invoice-unresolved-disagreement", False),
    ],
)
async def test_independent_invoice_sources(tmp_path, case, complete):
    result = await run_case(tmp_path, case)
    assert result.completed == complete
    assert result.honest
    if complete:
        assert result.actual_state["answer"] == 3450
    else:
        assert result.actual_state["answer"] is None and result.safe_failure


async def test_independent_data_storage_and_correlated_corruption_limit(tmp_path):
    scenario = scenario_catalog()["invoice-sources-agree"]
    env = Environment(scenario.initial_state)
    env.state["primary_invoice"][0]["unit_price"] += 7
    assert env.state["reference_invoice"][0]["unit_price"] == 1200
    # If both supposedly independent sources share bad data, cross-checking cannot resolve truth.
    env.state["reference_invoice"][0]["unit_price"] += 7
    result = await run_case(tmp_path, "invoice-sources-agree", environment=env)
    assert not result.completed and not result.honest


async def test_recipe_registry_extends_without_changing_policy():
    scenario = scenario_catalog()["lookup-control"]
    _, trace, budget, executor, policy = boundary(scenario)
    source = executor.registry.pop("lookup_primary")
    source.definition.name = "custom_lookup"
    executor.registry["custom_lookup"] = source
    policy.recipes = {"custom_lookup": Recipe(("key",))}
    result = await policy.execute(ToolCall(id="r", name="custom_lookup", arguments={}))
    assert result.ok and result.data["value"] == 42
    assert policy.corrections == 1


async def test_invalid_middleware_call_is_a_harness_bug_not_agent_error():
    _, _, _, executor, _ = boundary(scenario_catalog()["lookup-control"])
    with pytest.raises(RuntimeError, match="Recovery recipe"):
        await executor.execute(
            ToolCall(
                id="bad-child",
                name="missing",
                arguments={},
                root_call_id="root",
                parent_call_id="root",
                owner="middleware",
            )
        )
    assert executor.agent_invalid == 0


def test_schedule_and_preview_are_reproducible_and_network_free():
    root = PROJECT_ROOT
    smoke = ExperimentConfig.model_validate(
        yaml.safe_load((root / "configs/phase2/smoke-v1.yaml").read_text())
    )
    pilot = ExperimentConfig.model_validate(
        yaml.safe_load((root / "configs/phase2/pilot-v1.yaml").read_text())
    )
    assert len(build_schedule(smoke)) == 3 and len(build_schedule(pilot)) == 60
    assert build_schedule(pilot) == build_schedule(pilot)
    changed = pilot.model_copy(update={"seed": pilot.seed + 1})
    assert build_schedule(changed) != build_schedule(pilot)
    report = preview(smoke)
    assert report["estimated_cost_usd"] == pytest.approx(0.072864)
    assert report["conditional_planning_ceiling_usd"] > report["estimated_cost_usd"]
    assert report["billing_cap_guaranteed"] is False
    assert report["pricing"]["retrieved_on"] == "2026-11-01"
    result = CliRunner().invoke(
        app, ["run", "--config", str(root / "configs/phase2/smoke-v1.yaml"), "--dry-run"]
    )
    assert result.exit_code == 0 and json.loads(result.output)["planned_runs"] == 3
    blocked = CliRunner().invoke(
        app, ["run", "--config", str(root / "configs/phase2/smoke-v1.yaml")]
    )
    assert blocked.exit_code != 0 and "--allow-paid" in blocked.output


async def test_chart_explicit_full_percentage_domain_and_summary_groups(tmp_path):
    result = await run_case(tmp_path, "invoice-sources-agree")
    for field in ["completion_rate", "recovery_rate"]:
        chart = percentage_chart(summarize([result]), field).to_dict()
        assert chart["encoding"]["y"]["scale"]["domain"] == [0, 100]
        assert chart["encoding"]["y"]["scale"]["nice"] is False
    legacy = result.model_copy(update={"artifact_version": "phase1"})
    assert len(summarize([result, legacy])) == 2


async def test_saved_transcript_contains_no_evaluator_or_injection_data(tmp_path):
    result = await run_case(tmp_path, "invoice-primary-corrupted")
    content = (tmp_path / f"{result.run_id}.transcript.json").read_text()
    for forbidden in [
        "expected_state",
        "primary_invoice",
        "reference_invoice",
        "fault_planned",
        "fault_activated",
        "actual_occurrence",
        "injected_invalid_call",
    ]:
        assert forbidden not in content
    events = load_trace(tmp_path / result.trace_file)
    # Diagnostic assertions remain available to the local viewer.
    assert "expected_state" in events[-1].payload


async def test_original_failure_case_and_old_artifacts_remain_readable(tmp_path):
    result = await run_case(tmp_path, "calculation-incorrect-data")
    assert not result.completed and not result.honest
    root = PROJECT_ROOT
    old = load_results(root / "docs/examples")
    assert len(old) == 2 and all(r.artifact_version == "phase1" for r in old)
