# Design

AgentFaultLab is a local experiment lab for injecting controlled tool faults, comparing
recovery policies, and inspecting evidence-backed agent outcomes.

## Boundaries

`schemas.py` defines validated serializable records for definitions, calls, results, errors,
faults, budgets, scenarios, configuration, trace events, decisions, outcomes, and summaries.
Configuration forbids unknown fields. Tool inputs/outputs also use strict validation:
`"42"` cannot silently become an integer. The executor never repairs calls.

`tools.py` creates a fresh `Environment` with a deep copy of each scenario's initial state.
Tools are async callables with Pydantic input/output models and a retry-safety contract.
The registry exposes only the scenario's allowed tools. All attempts, including middleware
retries, fallback reads, and reconciliation, pass through `ToolExecutor.execute`.

The executor records a call, validates its original name and arguments, selects a fault,
revalidates injected mutations, executes or intercepts the call, validates its output, and
records the observed result. Agent-invalid calls, injected-invalid calls, expected environment
failures, output-validation errors, provider failures, and unexpected harness bugs have
separate categories. Unexpected Python exceptions propagate to the runner's harness boundary;
they are never mislabeled as bad model decisions. Scorer exceptions also become harness failures.

## Fault scheduling

One occurrence is **one entry into the executor for the original tool name**. Invalid agent
attempts count, but cannot activate a fault because original validation failed. Retry attempts
count. Fallback and reconciliation reads count under their own original names. Mutated names
do not move the counter. Counter state is fresh for each run.

`occurrence: 2` with transient behavior selects only attempt 2; persistent behavior selects
attempt 2 and all subsequent attempts. Eligibility draws from a per-rule seeded RNG. A
probability miss consumes that eligible occurrence; a transient fault is not postponed.
The first matching activated rule wins; at most one fault applies to a call. The MVP scenario
has one rule; `FaultInjector` can accept multiple rules with unique IDs. Experiment seed plus
repeat index overrides each scenario rule's seed; the same repeat seed is shared across policies.

| Phase | Faults | Activation point |
| --- | --- | --- |
| Pre-execution | Unknown tool, missing/wrong argument, exception, timeout, rate limit | Before tool execution or intercept |
| Post-execution | Commit followed by lost response | After handler returns and before cancellation during response delay |
| Response corruption | Malformed result, plausible incorrect data | After handler returns, when output is actually changed |

The trace distinguishes planned, selected, and activated faults. A selected corruption whose
handler never returns has not activated. Activation records contain planned/actual tool and
occurrence, phase, original/effective calls; corruption events show before/after results.
Unreached or probability-skipped faults do not enter recovery denominators.

Injection metadata and expected state are evaluator-only. `AgentContext` exposes task text,
public bindings, schemas, and public observations, not scenario IDs, initial truth, fault
rules, activations, or evaluator assertions. `observable_result` strips internal attribution
categories. Ordinary observable error codes, Retry-After, and write ambiguity remain visible.
Trace viewers can see injector metadata; the agent cannot.

## Policy and model ownership

The deterministic `Recovery` middleware owns explicitly transient read retries, capped
backoff, respecting Retry-After as a minimum, domain-bound argument correction, schema-feedback
retries, primary lookup fallback after exhausted errors, and ambiguous-write reconciliation.
It has no access to expected answers or the fault schedule. Corrections use public task
bindings, not evaluator truth. It can strip a documented `_typo` suffix, restore lookup keys,
or restore create-ticket task fields; it does not guess arbitrary arguments.

The scripted agent executes a predefined sequence. Its resilient disagreement rule chooses
the task's vetted secondary snapshot. This is a script decision, explicitly recorded with
`owner: scripted_agent`; middleware actions have `owner: deterministic_middleware`.
Arithmetic verification checks consistency against observed items, not the hidden ground truth.
The live model owns its native next-call selection and final structured answer. Both modes
use the same middleware and evaluator. A live model may select a fallback itself after
successful but questionable observations; fallback metrics count explicit recorded actions,
so implicit live strategies are not inferred from model prose.

The curated fake write service accepts a client idempotency key but does not enforce
deduplication (`deduplicate_writes: false` in initial state). An unguarded repeated request
really can create duplicate records. Other fake environments can opt into key enforcement.
The tool is marked `retry_safe=False`. A lost response
does not prove a failed write. Resilient recovery queries the same idempotency key, verifies
exactly one matching title, and returns the verified record. It makes no second write.
If reconciliation fails, the run stops with an ambiguous result. Neither policy blindly
retries a write. This does not model distributed transaction isolation or real-service guarantees.

## Budgets and cancellation

Tool calls and model calls have global run limits. Agent steps include each decision (script
steps are not model requests). `max_retries` and `max_corrections` are per logical requested
call; the global tool budget bounds their combined effects. All middleware attempts consume
the tool budget. Retry-After greater than the remaining deadline produces no retry.
Backoff is `min(0.01 * 2**attempt, 0.1)` seconds, then raised to any Retry-After minimum.

An asyncio run deadline encloses orchestration. `wait_for` enforces per-tool timeouts and
awaits cooperative cancellation. Real delayed coroutines exercise both timeouts and lost
write responses. Setup, scoring and file export add small overhead outside the orchestration
deadline. Blocking or cancellation-resistant production handlers are outside this MVP.

Model completion tokens are requested within the remaining token allowance; reported input
and output usage is checked before tools execute. Input usage cannot be known exactly in
advance for arbitrary hosted models; one request can overshoot. No provider retry is hidden:
the SDK is configured with `max_retries=0`. The runner closes provider clients on completion
and cancellation. Each repeat starts a fresh client conversation and environment.

## Outcomes and persistence

`scoring.py` checks persisted answers or exact record state and requires evidence of relevant
successful tool calls. A create commit alone does not satisfy the verification requirement.
Claimed success has no power to change task completion. Communication additionally checks
that a terminal completion claim is supported and the final answer matches persisted state.
Safety checks no duplicate records and no unexpected record titles or keys.

Events have stable run/scenario IDs, sequence numbers, UTC timestamps, monotonic elapsed time,
call IDs, result durations, error categories and explicit recovery actions. The final event
contains deterministic assertion results and outcome. No hidden chain-of-thought is requested
or stored. The provider retains ordinary conversation content only, not reasoning fields.

`tracing.redact` recursively masks common credential field names and recognizable `sk-…` or
Bearer strings. Token *counts* and synthetic idempotency keys remain visible. The same redaction
applies to summaries. Arbitrary secrets, PII, and encoded credentials can evade it; use synthetic
inputs and review artifacts before sharing. Raw provider exception text is omitted entirely.

Reports follow the experiment manifest rather than mixing leftover runs. Playback reads and
validates event sequences without performing any tool/model execution. Streamlit is only a
consumer. The event schema leaves room for a later OpenTelemetry exporter using run IDs,
call IDs, durations, and event types; there is no exporter or telemetry service in the MVP.

## Extension points

Add a typed tool and handler to `Environment.registry`; mark retry safety conservatively.
Add a fault kind/phase and mutation or interception branch through the existing injector.
Add a scenario with initial state, public task, tool allowlist, assertions, budgets, and rule.
For a new task family, add explicit scripted behavior and independent state assertions.
A new provider implements `Agent.decide`, `observe`, and optional `close`; it receives no
injection/evaluation internals. Add tests for the new boundary rather than relying on a demo alone.
