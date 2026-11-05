"""Fresh-state runs sharing one budget and retaining every execution's provenance."""

import asyncio
import json
import platform
import time
from copy import deepcopy
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from uuid import uuid4

from agentfaultlab.agents import Agent, AgentContext, ScriptedAgent, observable_result
from agentfaultlab.budget import BudgetExceeded, RunBudget
from agentfaultlab.errors import ProviderFailure
from agentfaultlab.executor import ToolExecutor
from agentfaultlab.faults import FaultInjector
from agentfaultlab.planning import build_schedule, token_cost
from agentfaultlab.policies import Recovery
from agentfaultlab.scenarios import scenario_catalog
from agentfaultlab.schemas import (
    Decision,
    ExperimentConfig,
    RunOutcome,
    ToolError,
    ToolResult,
)
from agentfaultlab.scoring import assertion_details, score
from agentfaultlab.tools import Environment
from agentfaultlab.tracing import Trace, redact


def dependency_versions():
    versions = {"python": platform.python_version()}
    for name in ["agentfaultlab", "pydantic", "typer", "streamlit", "PyYAML", "openai"]:
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = "not installed"
    return versions


async def run_one(
    scenario,
    policy,
    config: ExperimentConfig,
    repeat=0,
    agent: Agent | None = None,
    environment=None,
) -> RunOutcome:
    run_id = f"{scenario.id}-{policy}-{uuid4().hex[:10]}"
    output = Path(config.output_dir)
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=True)
    trace_path = output / f"{run_id}.jsonl"
    trace = Trace(run_id, scenario.id)
    controller = RunBudget(config.budgets)
    scenario = scenario.model_copy(deep=True)
    scenario.budgets = config.budgets
    rules = ([scenario.fault] if scenario.fault else []) + scenario.additional_faults
    for rule in rules:
        rule.seed = config.seed + repeat
    env = environment or Environment(scenario.initial_state)
    registry = {k: v for k, v in env.registry().items() if k in scenario.available_tools}
    injector = FaultInjector(rules)
    executor = ToolExecutor(registry, injector, trace, config.budgets.tool_timeout_s, controller)
    recovery = Recovery(
        policy,
        config.budgets,
        registry,
        trace,
        executor.execute,
        controller.deadline,
        scenario.bindings,
        budget=controller,
    )
    observations, transcript = [], []
    unanswered = {}
    final = Decision(status="abstain", summary="Run ended without a supported completion claim.")
    stop_reason, harness_error, provider_error = "agent_finished", None, None
    ambiguous_seen = False
    trace.emit(
        "run_started",
        {
            "artifact_version": "phase2-v1",
            "scenario": scenario.model_dump(),
            "config": config.model_dump(),
            "policy": policy,
            "mode": config.mode,
            "repeat": repeat,
            "seed": config.seed + repeat,
        },
    )
    trace.emit("fault_planned", {"rules": [r.model_dump() for r in rules], "activated": False})

    def deliver(call, result):
        observations.append({"call": call.model_dump(), "result": observable_result(result)})
        public_call = call.model_dump(include={"id", "name", "arguments"})
        transcript.append({"call": public_call, "result": observable_result(result)})
        trace.emit(
            "agent_observation",
            {"call": call.model_dump(), "result": observable_result(result)},
            tool_name=call.name,
            call_id=call.id,
        )
        agent.observe(call, result)
        unanswered.pop(call.id, None)

    def finish_unanswered(reason):
        # Timeout/cancellation can interrupt the batch before the ordinary skip loop runs.
        for call in list(unanswered.values()):
            started = any(
                e.event_type == "tool_call" and e.call_id == call.id for e in trace.events
            )
            trace.emit(
                "tool_call_terminated" if started else "tool_call_skipped",
                {"reason": reason},
                call_id=call.id,
                tool_name=call.name,
            )
            deliver(
                call,
                ToolResult(
                    call_id=call.id,
                    name=call.name,
                    error=ToolError(
                        category="harness"
                        if reason == "harness_failure"
                        else "provider"
                        if reason == "provider_failure"
                        else "budget",
                        code="run_terminated",
                        message="Run terminated before this result became available.",
                    ),
                ),
            )

    try:
        if agent is None:
            if config.mode == "live":
                from agentfaultlab.live import OpenAIAgent

                agent = OpenAIAgent(
                    config.model,
                    budget=controller,
                    trace=trace,
                    reasoning_effort=config.reasoning_effort,
                )
            else:
                agent = ScriptedAgent()
        if getattr(agent, "owns_model_budget", False):
            agent.budget, agent.trace = controller, trace
        # Defense in depth: shared boundaries also enforce this deadline independently.
        async with asyncio.timeout_at(controller.deadline):
            while True:
                controller.consume("steps")
                tokens = controller.input_tokens + controller.output_tokens
                if tokens >= config.budgets.max_tokens:
                    raise BudgetExceeded("max_tokens")
                context = AgentContext(
                    task=scenario.task,
                    family=scenario.family,
                    bindings=deepcopy(scenario.bindings),
                    tools=[t.definition for t in registry.values()],
                    observations=observations,
                    policy=policy,
                    remaining_tokens=config.budgets.max_tokens - tokens,
                    max_output_tokens=config.budgets.max_output_tokens,
                )
                if config.mode == "live" and not getattr(agent, "owns_model_budget", False):
                    controller.consume("model_calls")
                try:
                    decision = await controller.wait(
                        agent.decide(context),
                        controller.remaining()
                        if getattr(agent, "owns_model_budget", False)
                        else config.budgets.model_timeout_s,
                    )
                except TimeoutError:
                    if config.mode == "live":
                        raise ProviderFailure("Model request timeout", code="timeout") from None
                    raise BudgetExceeded("agent_timeout") from None
                decision.calls = [
                    call.model_copy(
                        update={
                            "owner": "model" if config.mode == "live" else "scripted_agent",
                            "root_call_id": call.id,
                            "parent_call_id": None,
                            "attempt": 1,
                        }
                    )
                    for call in decision.calls
                ]
                trace.emit(
                    "agent_decision",
                    decision.model_dump(),
                    owner="model" if config.mode == "live" else "scripted_agent",
                )
                for index, call in enumerate(decision.calls):
                    unanswered[call.id] = call
                    trace.register_call(call)
                    trace.emit(
                        "agent_call_queued",
                        {"batch_index": index},
                        call_id=call.id,
                        tool_name=call.name,
                    )
                transcript.append({"decision": decision.model_dump(exclude={"input_estimate"})})
                if config.mode == "live":
                    controller.usage(decision.input_tokens, decision.output_tokens)
                if decision.recovery_action:
                    controller.consume("recovery_actions")
                    owner = "model" if config.mode == "live" else "scripted_agent"
                    trace.emit(
                        "recovery",
                        {"owner": owner, "summary": decision.summary},
                        owner=owner,
                        recovery_action=decision.recovery_action,
                    )
                    if decision.recovery_action == "fallback":
                        recovery.fallbacks += 1
                if decision.status != "continue":
                    final = decision
                    break
                if not decision.calls:
                    raise ProviderFailure("No call or terminal decision", code="protocol")
                halt, deferred = False, None
                for call in decision.calls:
                    if halt:
                        result = ToolResult(
                            call_id=call.id,
                            name=call.name,
                            error=ToolError(
                                category="budget" if deferred else "tool_environment",
                                code="batch_stopped",
                                message="Not executed: earlier call terminated batch.",
                            ),
                        )
                        trace.emit(
                            "tool_call_skipped",
                            {"reason": str(deferred) if deferred else stop_reason},
                            call_id=call.id,
                            tool_name=call.name,
                        )
                    else:
                        try:
                            result = await recovery.execute(call)
                        except BudgetExceeded as exc:
                            deferred, halt = exc, True
                            result = ToolResult(
                                call_id=call.id,
                                name=call.name,
                                error=ToolError(
                                    category="budget",
                                    code=str(exc),
                                    message="Shared run budget exhausted.",
                                ),
                            )
                            trace.emit(
                                "tool_call_terminated",
                                {"limit": str(exc)},
                                call_id=call.id,
                                tool_name=call.name,
                                error_category="budget",
                            )
                        if result.error:
                            ambiguous_seen |= result.error.ambiguous
                            if policy in {"fail_fast", "bounded_retry"} or result.error.ambiguous:
                                halt = True
                                stop_reason = result.error.code
                    deliver(call, result)
                if deferred:
                    raise deferred
                if halt:
                    break
    except asyncio.CancelledError:
        finish_unanswered("external_cancellation")
        trace.emit("run_cancelled", {"reason": "external_cancellation"})
        trace.save(trace_path)
        raise
    except (BudgetExceeded, TimeoutError) as exc:
        stop_reason = str(exc) or "elapsed_s"
        trace.emit("budget_exhausted", {"limit": stop_reason}, error_category="budget")
    except ProviderFailure as exc:
        provider_error, stop_reason = exc.code, "provider_failure"
        controller.usage_available &= exc.input_tokens is not None and exc.output_tokens is not None
        if exc.input_tokens is not None or exc.output_tokens is not None:
            controller.input_tokens += exc.input_tokens or 0
            controller.output_tokens += exc.output_tokens or 0
        trace.emit(
            "provider_failure", {"message": str(exc), "code": exc.code}, error_category="provider"
        )
    except Exception as exc:
        stop_reason = "harness_failure"
        harness_error = f"{type(exc).__name__}: {exc}"
        trace.emit("harness_failure", {"message": harness_error}, error_category="harness")
    finally:
        close = getattr(agent, "close", None)
        if close:
            try:
                await asyncio.wait_for(close(), timeout=0.2)
            except Exception as exc:
                harness_error = f"Provider close failed: {type(exc).__name__}"
                stop_reason = "harness_failure"
                trace.emit("harness_failure", {"message": harness_error}, error_category="harness")

    finish_unanswered(stop_reason)
    try:
        assertions, duplicates = score(scenario, env.state, trace.events)
        details = assertion_details(scenario, env.state, trace.events, assertions)
    except Exception as exc:
        assertions, duplicates, details = {"evaluator_completed": False}, 0, {}
        harness_error, stop_reason = f"Evaluator {type(exc).__name__}: {exc}", "harness_failure"
        trace.emit("harness_failure", {"message": harness_error}, error_category="harness")
    completed = all(assertions.values()) and harness_error is None
    safe = duplicates == 0 and harness_error is None
    if scenario.family == "creation":
        key = "request_key" if "request_key" in scenario.bindings else "idempotency_key"
        safe &= all(
            r[key] == scenario.bindings[key] and r["title"] == scenario.bindings["title"]
            for r in env.state["records"]
        )
        answer_matches = any(final.answer == r["id"] for r in env.state["records"])
    else:
        answer_matches = final.answer == env.state["answer"]
    honest = final.status != "complete" or (completed and answer_matches)
    finished_ids = {e.call_id for e in trace.events if e.event_type == "observed_result"}
    ambiguous_seen |= any(
        e.event_type == "observed_result" and (e.payload.get("error") or {}).get("ambiguous", False)
        for e in trace.events
    )
    ambiguous_seen |= any(
        e.event_type == "tool_call"
        and e.call_id not in finished_ids
        and e.tool_name in registry
        and not registry[e.tool_name].definition.retry_safe
        for e in trace.events
    )
    usage_known = config.mode == "live" and controller.usage_available
    input_tokens = controller.input_tokens if usage_known else None
    output_tokens = controller.output_tokens if usage_known else None
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
        fault_planned=(
            {**rules[0].model_dump(), "additional_rules": [r.model_dump() for r in rules[1:]]}
            if rules
            else None
        ),
        fault_activations=len(injector.activations),
        fault_rules_planned=len(rules),
        fault_rules_activated=len({a["rule_id"] for a in injector.activations}),
        completed=completed,
        recovered=bool(injector.activations)
        and completed
        and safe
        and honest
        and provider_error is None
        and stop_reason == "agent_finished"
        and final.status == "complete",
        safe=safe,
        safe_failure=not completed
        and safe
        and honest
        and harness_error is None
        and provider_error is None,
        honest=honest,
        duplicate_side_effects=duplicates,
        invalid_tool_calls=executor.agent_invalid + executor.injected_invalid,
        agent_invalid_calls=executor.agent_invalid,
        injected_invalid_calls=executor.injected_invalid,
        retries=recovery.retries,
        fallbacks=recovery.fallbacks,
        corrections=recovery.corrections,
        tool_calls=executor.calls,
        model_calls=controller.counts["model_calls"],
        steps=controller.counts["steps"],
        duration_s=time.monotonic() - trace.start,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        dollar_cost=token_cost(config.pricing, input_tokens, output_tokens),
        stop_reason=stop_reason,
        harness_error=harness_error,
        assertions=assertions,
        assertion_details=details,
        expected_state=scenario.expected_state,
        actual_state=deepcopy(env.state),
        final_answer=final.answer,
        final_status=final.status,
        dependency_versions=dependency_versions(),
        config=config.model_dump(),
        trace_file=trace_path.name,
        artifact_version="phase2-v1",
        experiment_kind=config.experiment_kind,
        provider_error=provider_error,
        uncertain=ambiguous_seen and not completed,
        recovery_actions=controller.counts["recovery_actions"],
        actual_executions=controller.counts["actual_executions"],
    )
    outcome = RunOutcome.model_validate(redact(outcome.model_dump()))
    trace.emit("verified_outcome", outcome.model_dump())
    trace.save(trace_path)
    (output / f"{run_id}.run.json").write_text(outcome.model_dump_json(indent=2) + "\n")
    public = getattr(agent, "messages", None) or transcript
    if config.mode == "live":
        public = {
            "messages": public,
            "sent_message_counts": [
                e.payload["message_count"] for e in trace.events if e.event_type == "model_request"
            ],
            "note": "Tool replies after the last sent prefix may be prepared but unsent. "
            "A model receives them only in a subsequent request.",
        }
    (output / f"{run_id}.transcript.json").write_text(json.dumps(redact(public), indent=2) + "\n")
    return outcome


async def run_experiment(config):
    catalog, schedule = scenario_catalog(), build_schedule(config)
    outcomes = []
    suite_stop_reason = None
    for name, policy, repeat in schedule:
        outcome = await run_one(catalog[name], policy, config, repeat)
        outcomes.append(outcome)
        if config.experiment_kind == "smoke":
            # A broken setup must not spend the remaining allowance on later runs.
            if outcome.harness_error or outcome.provider_error:
                suite_stop_reason = "infrastructure_failure"
                break
            if outcome.input_tokens is None or outcome.output_tokens is None:
                suite_stop_reason = "unknown_provider_usage"
                break
    from agentfaultlab.reporting import write_report

    write_report(outcomes, Path(config.output_dir))
    manifest = {
        "artifact_version": "phase2-v1",
        "config": config.model_dump(),
        "runs": [o.run_id for o in outcomes],
        "dependencies": dependency_versions(),
        "execution_order": [
            {"scenario": o.scenario_id, "policy": o.policy, "repeat": o.repeat} for o in outcomes
        ],
        "planned_execution_order": [
            {"scenario": n, "policy": p, "repeat": r} for n, p, r in schedule
        ],
        "suite_stop_reason": suite_stop_reason,
        "unstarted_runs": len(schedule) - len(outcomes),
    }
    (Path(config.output_dir) / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return outcomes
