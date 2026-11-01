"""Refresh the learning guide from a real, completed offline demo."""

import shutil
from pathlib import Path

from agentfaultlab.reporting import load_results, summarize
from agentfaultlab.tracing import load_trace


def main():
    root = Path(__file__).resolve().parents[1]
    results = root / "results/demo"
    runs = load_results(results)
    examples = root / "docs/examples"
    examples.mkdir(parents=True, exist_ok=True)
    success = next(
        r for r in runs if r.scenario_id == "creation-commit-timeout" and r.policy == "resilient"
    )
    failure = next(
        r for r in runs if r.scenario_id == "calculation-incorrect-data" and r.policy == "resilient"
    )
    for run in [success, failure]:
        for filename in [run.trace_file, f"{run.run_id}.run.json"]:
            shutil.copyfile(results / filename, examples / filename)

    def timeline(run):
        events = load_trace(results / run.trace_file)
        rows = []
        for event in events:
            if event.event_type in {
                "agent_decision",
                "tool_call",
                "fault_activated",
                "observed_result",
                "recovery",
                "verified_outcome",
            }:
                rows.append(
                    f"| {event.seq} | {event.event_type} | {event.tool_name or '—'} | "
                    f"{event.recovery_action or event.error_category or '—'} |"
                )
        return "\n".join(rows)

    metrics = "\n".join(
        f"| {s.policy} | {s.completed}/{s.runs} ({s.completion_rate:.1%}) | "
        f"{s.recovered}/{s.activated_runs} ({s.recovery_rate:.1%}) | {s.duplicate_side_effects} |"
        for s in summarize(runs)
    )
    content = f"""# Learning guide: follow the evidence

These examples are saved artifacts from an actual **scripted offline** demo. They are not
LLM benchmark results. The snapshots in `docs/examples/` remain usable after you run a new demo.
To refresh this guide from your latest demo, run `python scripts/refresh_learning_examples.py`.

## Start here

1. Run `agentfaultlab demo` and `streamlit run app.py` from the project root.
2. Filter to `creation-commit-timeout` and `resilient`, then inspect the timeline.
3. Filter to `calculation-incorrect-data` and inspect the failed persisted-answer assertion.

## Successful recovery: a committed write with a lost response

Run ID: `{success.run_id}`. Seed: {success.seed}. Mode: **{success.mode}**.

[Saved trace](examples/{success.trace_file}) ·
[Saved outcome](examples/{success.run_id}.run.json)

```sh
agentfaultlab inspect docs/examples/{success.run_id}.run.json
```

The script requests a ticket with key `request-001`. The handler commits it, then injection
delays the response until `asyncio.wait_for` cancels the coroutine. A timeout does not imply
the record is absent. Resilient middleware calls `find_ticket` with the original key and
checks the title. It returns evidence of the existing record, then the script verifies
existence. No second create request occurs. Actual records: {len(success.actual_state["records"])};
duplicate side effects: {success.duplicate_side_effects}; completed: {success.completed}.

| Sequence | Event | Tool | Action / error |
| --- | --- | --- | --- |
{timeline(success)}

Read [`executor.py`](../src/agentfaultlab/executor.py) for the post-commit delay and cancellation;
[`policies.py`](../src/agentfaultlab/policies.py) for `reconcile_state`;
[`tools.py`](../src/agentfaultlab/tools.py) for idempotency;
[`scoring.py`](../src/agentfaultlab/scoring.py) for required state and verification evidence.

Discussion point: this fake service accepts a client key but does not enforce deduplication.
A blind repeated create really can duplicate records; a boundary test demonstrates this.
Recovery reconciles state using that key before considering another write.
The fail-fast and bounded-retry policies leave one committed record unverified and do not
receive task-completion credit. They do not blindly retry it either.

## Failure: plausible input corruption defeats a local consistency check

Run ID: `{failure.run_id}`. Seed: {failure.seed}. Mode: **{failure.mode}**.

[Saved trace](examples/{failure.trace_file}) ·
[Saved outcome](examples/{failure.run_id}.run.json)

```sh
agentfaultlab inspect docs/examples/{failure.run_id}.run.json
```

The injected invoice changes a unit price by 7 cents. It remains valid structured data.
Both the calculate tool and scripted arithmetic check use the same corrupted items, so they
agree. The script submits **{failure.actual_state["answer"]}** and claims completion. The
independent state assertion expects **{failure.expected_state["answer"]}** and rejects it.
Completed: {failure.completed}; supported communication (`honest`): {failure.honest};
record safety: {failure.safe}. There were no retries because no observable schema or tool
error occurred. A limitation is visible rather than hidden behind a high recovery percentage.

| Sequence | Event | Tool | Action / error |
| --- | --- | --- | --- |
{timeline(failure)}

Read [`faults.py`](../src/agentfaultlab/faults.py) for corruption;
[`agents.py`](../src/agentfaultlab/agents.py) for the limited arithmetic check;
[`scoring.py`](../src/agentfaultlab/scoring.py) for independent truth;
[`runner.py`](../src/agentfaultlab/runner.py) for separate completion, safety and communication.
An independent invoice source is a useful next experiment, not an implemented recovery.

## Results from this generated demo

| Policy | Completion / runs | Recovery / activated runs | Duplicate side effects |
| --- | --- | --- | --- |
{metrics}

Each policy has three controls and twelve faulted cases. Counts describe this fixed script
and fixture suite only. Hosted model results need separate repeated experiments.

## Practice explaining the code

- Why validate arguments before selecting a fault? It separates original agent errors from
  injected mutations. Every repair is a later observable policy action.
- Why count only activated faults? A run that never reached the planned injection point
  cannot demonstrate recovery.
- Why use a monotonic clock? Wall-clock adjustments should not affect elapsed-time budgets.
- Why not trust a success sentence? State assertions and observed verification provide evidence.
- Why keep Streamlit separate? CLI experiments and tests work independently of the viewer.
- Why call the viewer playback? It reads events; it does not recreate nondeterministic executions.

Read first: this guide, `src/agentfaultlab/executor.py`, then `src/agentfaultlab/policies.py`.
For interview preparation, follow one call ID from `agent_decision` through `tool_call`, fault
activation, observed result, recovery, agent observation, and verified outcome.
"""
    (root / "docs/learning-guide.md").write_text(content)
    print("Learning guide and two actual run snapshots refreshed.")


if __name__ == "__main__":
    main()
