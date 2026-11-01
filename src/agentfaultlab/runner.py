"""Fresh-state orchestration, resource budgets, failure attribution, and artifact writing."""

import asyncio
import json
import platform
import time
from copy import deepcopy
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from uuid import uuid4

from agentfaultlab.agents import Agent, AgentContext, ScriptedAgent, observable_result
from agentfaultlab.executor import ToolExecutor
from agentfaultlab.faults import FaultInjector
from agentfaultlab.policies import Recovery
from agentfaultlab.scenarios import scenario_catalog
from agentfaultlab.schemas import Decision, ExperimentConfig, RunOutcome, Scenario, ToolCall
from agentfaultlab.scoring import score
from agentfaultlab.tools import Environment
from agentfaultlab.tracing import Trace, redact


class BudgetExceeded(Exception):
    pass


class ProviderFailure(Exception):
    """Provider/network/protocol failure, separate from harness bugs."""


def dependency_versions():
    versions = {"python": platform.python_version()}
    for name in ["agentfaultlab", "pydantic", "typer", "streamlit", "PyYAML", "openai"]:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = "not installed"
    return versions


async def run_one(
    scenario: Scenario,
    policy,
    config: ExperimentConfig,
    repeat=0,
    agent: Agent | None = None,
    environment: Environment | None = None,
) -> RunOutcome:
    run_id = f"{scenario.id}-{policy}-{uuid4().hex[:10]}"
    output = Path(config.output_dir)
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=True)
    trace_path = output / f"{run_id}.jsonl"
    trace = Trace(run_id, scenario.id)
    budget = config.budgets
    scenario = scenario.model_copy(deep=True)
    scenario.budgets = budget
    if scenario.fault:
        scenario.fault.seed = config.seed + repeat
    env = environment or Environment(scenario.initial_state)
    registry = {k: v for k, v in env.registry().items() if k in scenario.available_tools}
    injector = FaultInjector([scenario.fault] if scenario.fault else [])
    executor = ToolExecutor(registry, injector, trace, budget.tool_timeout_s)
    deadline = time.monotonic() + budget.elapsed_s
    observations = []
    model_calls = steps = 0
    input_tokens = output_tokens = None
    usage_unavailable = False
    final = Decision(status="abstain", summary="Run did not reach a verified final decision.")
    stop_reason, harness_error = "agent_finished", None
    trace.emit(
        "run_started",
        {
            "scenario": scenario.model_dump(),
            "config": config.model_dump(),
            "policy": policy,
            "mode": config.mode,
            "repeat": repeat,
            "seed": config.seed + repeat,
        },
    )
    trace.emit(
        "fault_planned",
        {"rule": scenario.fault.model_dump() if scenario.fault else None, "activated": False},
    )

    async def invoke(call: ToolCall):
        if executor.calls >= budget.max_tool_calls:
            raise BudgetExceeded("max_tool_calls")
        if time.monotonic() >= deadline:
            raise BudgetExceeded("elapsed_s")
        return await executor.execute(call)

    recovery = Recovery(policy, budget, registry, trace, invoke, deadline, scenario.bindings)
    try:
        if agent is None:
            if config.mode == "live":
                from agentfaultlab.live import OpenAIAgent

                agent = OpenAIAgent(config.model)
            else:
                agent = ScriptedAgent()
        async with asyncio.timeout_at(deadline):
            while steps < budget.max_steps:
                if config.mode == "live" and model_calls >= budget.max_model_calls:
                    raise BudgetExceeded("max_model_calls")
                tokens = (input_tokens or 0) + (output_tokens or 0)
                if tokens >= budget.max_tokens:
                    raise BudgetExceeded("max_tokens")
                context = AgentContext(
                    task=scenario.task,
                    family=scenario.family,
                    bindings=deepcopy(scenario.bindings),
                    tools=[t.definition for t in registry.values()],
                    observations=observations,
                    policy=policy,
                    remaining_tokens=budget.max_tokens - tokens,
                )
                steps += 1
                if config.mode == "live":
                    model_calls += 1
                decision = await agent.decide(context)
                if config.mode == "live" and (
                    decision.input_tokens is None or decision.output_tokens is None
                ):
                    usage_unavailable = True
                trace.emit(
                    "agent_decision",
                    {
                        "summary": decision.summary,
                        "calls": [c.model_dump() for c in decision.calls],
                        "status": decision.status,
                        "answer": decision.answer,
                        "mode": config.mode,
                        "input_tokens": decision.input_tokens,
                        "output_tokens": decision.output_tokens,
                    },
                )
                if decision.input_tokens is not None:
                    input_tokens = (input_tokens or 0) + decision.input_tokens
                if decision.output_tokens is not None:
                    output_tokens = (output_tokens or 0) + decision.output_tokens
                if (input_tokens or 0) + (output_tokens or 0) > budget.max_tokens:
                    raise BudgetExceeded("max_tokens")
                if decision.recovery_action:
                    trace.emit(
                        "recovery",
                        {"owner": f"{config.mode}_agent", "summary": decision.summary},
                        recovery_action=decision.recovery_action,
                    )
                    if decision.recovery_action == "fallback":
                        recovery.fallbacks += 1
                if decision.status != "continue":
                    final = decision
                    break
                if not decision.calls:
                    raise ProviderFailure("Agent returned neither a call nor a terminal decision")
                for call in decision.calls:
                    result = await recovery.execute(call)
                    observations.append(
                        {"call": call.model_dump(), "result": observable_result(result)}
                    )
                    trace.emit(
                        "agent_observation",
                        {"call": call.model_dump(), "result": observable_result(result)},
                        tool_name=call.name,
                        call_id=call.id,
                    )
                    agent.observe(call, result)
                    if result.error and (
                        policy in {"fail_fast", "bounded_retry"} or result.error.ambiguous
                    ):
                        final = Decision(status="abstain", summary="Tool failure; stopped safely.")
                        stop_reason = result.error.code
                        break
                else:
                    continue
                break
            else:
                raise BudgetExceeded("max_steps")
    except (BudgetExceeded, TimeoutError) as exc:
        stop_reason = str(exc) or "elapsed_s"
        trace.emit("budget_exhausted", {"limit": stop_reason}, error_category="budget")
    except ProviderFailure as exc:
        usage_unavailable = config.mode == "live"
        stop_reason = "provider_failure"
        trace.emit("provider_failure", {"message": str(exc)}, error_category="provider")
    except Exception as exc:
        stop_reason = "harness_failure"
        harness_error = f"{type(exc).__name__}: {exc}"
        trace.emit("harness_failure", {"message": harness_error}, error_category="harness")
    finally:
        # Provider sessions created by the runner are closed even when the deadline cancels a call.
        close = getattr(agent, "close", None)
        if close:
            try:
                await close()
            except Exception as exc:
                harness_error = f"Provider close failed: {type(exc).__name__}"
                stop_reason = "harness_failure"
                trace.emit("harness_failure", {"message": harness_error}, error_category="harness")

    try:
        assertions, duplicates = score(scenario, env.state, trace.events)
    except Exception as exc:
        assertions, duplicates = {"evaluator_completed": False}, 0
        harness_error = f"Evaluator {type(exc).__name__}: {exc}"
        stop_reason = "harness_failure"
        trace.emit("harness_failure", {"message": harness_error}, error_category="harness")
    completed = all(assertions.values()) and harness_error is None
    safe = duplicates == 0 and harness_error is None
    if scenario.family == "creation":
        safe = safe and all(
            r["idempotency_key"] == scenario.bindings["idempotency_key"]
            and r["title"] == scenario.bindings["title"]
            for r in env.state["records"]
        )
    if scenario.family == "creation":
        answer_matches = any(final.answer == r["id"] for r in env.state["records"])
    else:
        answer_matches = final.answer == env.state["answer"]
    honest = final.status != "complete" or (completed and answer_matches)
    outcome = RunOutcome(
        run_id=run_id,
        scenario_id=scenario.id,
        family=scenario.family,
        policy=policy,
        mode=config.mode,
        model=config.model if config.mode == "live" else None,
        seed=config.seed + repeat,
        repeat=repeat,
        fault_type=scenario.fault.kind if scenario.fault else "control",
        fault_planned=scenario.fault.model_dump() if scenario.fault else None,
        fault_activations=len(injector.activations),
        completed=completed,
        recovered=bool(injector.activations) and completed and safe and honest,
        safe=safe,
        safe_failure=not completed and safe and honest and harness_error is None,
        honest=honest,
        duplicate_side_effects=duplicates,
        invalid_tool_calls=executor.agent_invalid + executor.injected_invalid,
        agent_invalid_calls=executor.agent_invalid,
        injected_invalid_calls=executor.injected_invalid,
        retries=recovery.retries,
        fallbacks=recovery.fallbacks,
        corrections=recovery.corrections,
        tool_calls=executor.calls,
        model_calls=model_calls,
        steps=steps,
        duration_s=time.monotonic() - trace.start,
        input_tokens=None if usage_unavailable else input_tokens,
        output_tokens=None if usage_unavailable else output_tokens,
        stop_reason=stop_reason,
        harness_error=harness_error,
        assertions=assertions,
        expected_state=scenario.expected_state,
        actual_state=deepcopy(env.state),
        final_answer=final.answer,
        final_status=final.status,
        dependency_versions=dependency_versions(),
        config=config.model_dump(),
        trace_file=trace_path.name,
    )
    # Apply the same best-effort redaction to summary and trace persistence.
    outcome = RunOutcome.model_validate(redact(outcome.model_dump()))
    trace.emit("verified_outcome", outcome.model_dump())
    trace.save(trace_path)
    (output / f"{run_id}.run.json").write_text(outcome.model_dump_json(indent=2) + "\n")
    return outcome


async def run_experiment(config: ExperimentConfig) -> list[RunOutcome]:
    catalog = scenario_catalog()
    names = list(catalog) if config.scenarios == ["all"] else config.scenarios
    missing = set(names) - catalog.keys()
    if missing:
        raise ValueError(f"Unknown scenarios: {sorted(missing)}")
    outcomes = []
    for repeat in range(config.repeats):
        for name in names:
            for policy in config.policies:
                outcomes.append(await run_one(catalog[name], policy, config, repeat))
    from agentfaultlab.reporting import write_report

    write_report(outcomes, Path(config.output_dir))
    manifest = {
        "config": config.model_dump(),
        "runs": [o.run_id for o in outcomes],
        "dependencies": dependency_versions(),
    }
    (Path(config.output_dir) / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return outcomes
