import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from agentfaultlab.agents import ScriptedAgent
from agentfaultlab.cli import app
from agentfaultlab.executor import ToolExecutor
from agentfaultlab.faults import FaultInjector
from agentfaultlab.runner import run_one
from agentfaultlab.scenarios import scenario_catalog
from agentfaultlab.schemas import ExperimentConfig, FaultSpec, ToolCall
from agentfaultlab.scoring import score
from agentfaultlab.tools import Environment, ToolUnavailable
from agentfaultlab.tracing import Trace, load_trace


@pytest.mark.parametrize("kind", ["malformed_result", "commit_timeout"])
async def test_post_execution_fault_not_activated_if_handler_fails(kind):
    scenario = scenario_catalog()["creation-control"]
    env = Environment(scenario.initial_state)
    registry = env.registry()

    async def unavailable(**kwargs):
        raise ToolUnavailable("not executed")

    registry["create_ticket"].handler = unavailable
    injector = FaultInjector([FaultSpec(id="f", kind=kind, target_tool="create_ticket")])
    trace = Trace("run", "scenario")
    executor = ToolExecutor(registry, injector, trace, 0.01)
    result = await executor.execute(
        ToolCall(id="c", name="create_ticket", arguments=scenario.bindings)
    )
    assert result.error.code == "unavailable"
    assert not injector.activations
    assert any(e.event_type == "fault_selected" for e in trace.events)
    assert not any(e.event_type == "fault_activated" for e in trace.events)


async def test_persistent_lookup_outage_uses_fallback(tmp_path):
    scenario = scenario_catalog()["lookup-exception"]
    scenario.fault.behavior = "persistent"
    result = await run_one(scenario, "resilient", ExperimentConfig(output_dir=str(tmp_path)))
    assert result.completed and result.fallbacks == 1 and result.retries == 2


async def test_state_completion_and_communication_scored_separately(tmp_path):
    class WrongFinalAnswer(ScriptedAgent):
        async def decide(self, context):
            decision = await super().decide(context)
            if decision.status == "complete":
                decision.answer = "incorrect final communication"
            return decision

    result = await run_one(
        scenario_catalog()["lookup-control"],
        "resilient",
        ExperimentConfig(output_dir=str(tmp_path)),
        agent=WrongFinalAnswer(),
    )
    assert result.completed and not result.honest


def test_config_cli_and_invalid_config(tmp_path):
    config_path = tmp_path / "run.yaml"
    config_path.write_text(
        json.dumps({"scenarios": ["lookup-control"], "output_dir": str(tmp_path / "results")})
    )
    result = CliRunner().invoke(app, ["run", "--config", str(config_path)])
    assert result.exit_code == 0 and "3 scripted runs" in result.output
    config_path.write_text("scenarios: [nonexistent]\n")
    invalid = CliRunner().invoke(app, ["run", "--config", str(config_path)])
    assert invalid.exit_code != 0 and "Unknown scenarios" in invalid.output


def test_live_missing_key_is_actionable(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config_path = tmp_path / "live.yaml"
    config_path.write_text("mode: live\nmodel: mock\n")
    result = CliRunner().invoke(app, ["run", "--config", str(config_path)])
    assert result.exit_code != 0 and "OPENAI_API_KEY" in result.output


async def test_trace_duration_and_required_events(tmp_path):
    result = await run_one(
        scenario_catalog()["creation-commit-timeout"],
        "resilient",
        ExperimentConfig(output_dir=str(tmp_path)),
    )
    events = load_trace(Path(tmp_path) / result.trace_file)
    types = [e.event_type for e in events]
    for name in [
        "agent_decision",
        "tool_call",
        "fault_activated",
        "observed_result",
        "recovery",
        "agent_observation",
        "verified_outcome",
    ]:
        assert name in types
    assert types.index("fault_activated") < types.index("recovery")
    assert all(e.duration_s is not None for e in events if e.event_type == "observed_result")


async def test_blind_retry_would_duplicate_a_committed_write():
    scenario = scenario_catalog()["creation-commit-timeout"]
    env = Environment(scenario.initial_state)
    trace = Trace("run", scenario.id)
    executor = ToolExecutor(env.registry(), FaultInjector([scenario.fault]), trace, 0.005)
    original = ToolCall(id="first", name="create_ticket", arguments=scenario.bindings)
    lost = await executor.execute(original)
    assert lost.error.ambiguous and len(env.state["records"]) == 1
    # Deliberately bypass the recovery policy to prove that an unsafe retry causes harm.
    repeated = await executor.execute(original.model_copy(update={"id": "unsafe-retry"}))
    assert repeated.ok and len(env.state["records"]) == 2
    assertions, duplicates = score(scenario, env.state, trace.events)
    assert duplicates == 1 and not assertions["no_duplicates"]
    assert not assertions["exactly_one_record"]


async def test_partial_provider_usage_is_unavailable_not_a_partial_total(tmp_path):
    class PartialUsage(ScriptedAgent):
        async def decide(self, context):
            decision = await super().decide(context)
            if context.observations:
                decision.input_tokens, decision.output_tokens = 10, 5
            return decision

    config = ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path))
    result = await run_one(
        scenario_catalog()["lookup-control"], "resilient", config, agent=PartialUsage()
    )
    assert result.completed and result.model_calls == 4
    assert result.input_tokens is None and result.output_tokens is None
