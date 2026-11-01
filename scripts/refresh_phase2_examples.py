"""Create Phase 2 teaching snapshots without overwriting Phase 1 examples."""

import shutil
from pathlib import Path

from agentfaultlab.reporting import load_results, summarize
from agentfaultlab.tracing import load_trace


def main():
    root = Path(__file__).resolve().parents[1]
    directory = root / "results/phase2-offline-v1"
    runs = load_results(directory)
    destination = root / "docs/examples-phase2"
    destination.mkdir(exist_ok=True)
    sections = []
    for name, title, explanation in [
        (
            "correlation-write-lost-response",
            "Recovering an ambiguous write",
            "The scripted agent requests one create. Actual before/after state verifies that the "
            "record committed, then the response delay times out. Middleware consumes a shared "
            "recovery action and a child read to reconcile the original request key. It finds one "
            "matching record and emits middleware_result with supporting call IDs. The agent then "
            "verifies existence and makes its final decision. No second write occurs.",
        ),
        (
            "invoice-unresolved-disagreement",
            "Supported failure on independent disagreement",
            "The primary response is plausibly corrupted. Middleware obtains a genuinely separate "
            "reference invoice, but its observed authority is only peer. The two values disagree. "
            "Middleware returns an explicit unresolved-disagreement error with both call IDs; the "
            "script abstains. Task completion remains false. Evaluator truth never enters a recipe "
            "or prompt. Agreement between two correlated bad sources would still be a limitation.",
        ),
    ]:
        run = next(r for r in runs if r.scenario_id == name and r.policy == "resilient")
        for filename in [run.trace_file, f"{run.run_id}.run.json", f"{run.run_id}.transcript.json"]:
            shutil.copyfile(directory / filename, destination / filename)
        events = load_trace(directory / run.trace_file)
        rows = []
        for event in events:
            if event.event_type in {
                "agent_decision",
                "tool_call",
                "environment_commit",
                "fault_activated",
                "observed_result",
                "recovery",
                "middleware_result",
                "agent_observation",
                "verified_outcome",
            }:
                rows.append(
                    f"| {event.seq} | {event.event_type} | {event.owner or 'harness/evaluator'} "
                    f"| {event.tool_name or '—'} | {event.recovery_action or '—'} |"
                )
        sections.append(f"""## {title}

Run `{run.run_id}`, mode **{run.mode}**, artifact **{run.artifact_version}**.
[Trace](examples-phase2/{run.trace_file}) ·
[Outcome](examples-phase2/{run.run_id}.run.json) ·
[Observable transcript](examples-phase2/{run.run_id}.transcript.json)

{explanation}

Observed: completed **{run.completed}**, safe **{run.safe}**, honest **{run.honest}**,
uncertain **{run.uncertain}**, duplicate side effects **{run.duplicate_side_effects}**,
boundary calls **{run.tool_calls}**, recovery actions **{run.recovery_actions}**.

```sh
agentfaultlab inspect docs/examples-phase2/{run.run_id}.run.json
```

| Seq | Event | Execution owner | Tool | Recovery action |
| --- | --- | --- | --- | --- |
{chr(10).join(rows)}
""")
    metrics = "\n".join(
        f"| {s.policy} | {s.completed}/{s.runs} | {s.recovered}/{s.activated_runs} "
        f"| {s.activated_runs}/{s.faulted_runs} | {s.harness_failures} |"
        for s in summarize(runs)
    )
    text = (
        """# Phase 2 learning walkthrough

These are actual **scripted** saved runs, not LLM results. They are separate from the historical
[Phase 1 learning guide](learning-guide.md). Run `python scripts/refresh_phase2_examples.py`
to refresh these teaching copies after running the versioned offline configuration.

Start with `agentfaultlab run --config configs/phase2/offline-v1.yaml` and `streamlit run app.py`
(use `--server.port 8503` if 8501 is occupied). Select `results/phase2-offline-v1` in the dashboard.
Expand middleware_result to follow the original request, child calls and supporting verification
IDs. The diagnostic trace and observable transcript have deliberately different audiences.

"""
        + "\n".join(sections)
        + f"""
## Observed offline suite

| Policy | Completed / total | Recovered / activated | Activated / faulted | Harness errors |
| --- | --- | --- | --- | --- |
{metrics}

The suite has 25 scenarios × 3 policies. It includes a fixture where the service itself produces
two records: each policy reports one duplicate side effect there. This is not a blind retry by
supported middleware. Inspect unsafe state and unresolved evidence separately from completion.
The preserved single-source invoice corruption still produces an unsupported success claim.

## Code to discuss

1. [`budget.py`](../src/agentfaultlab/budget.py): one controller bounds model, tool and
   recovery work.
2. [`executor.py`](../src/agentfaultlab/executor.py): strict boundary, actual write-state evidence,
   real cancellation and actual fault activation.
3. [`policies.py`](../src/agentfaultlab/policies.py) and
   [`recipes.py`](../src/agentfaultlab/recipes.py): generic bounded scheduling versus explicit
   domain contracts. Synthesized results retain supporting call IDs.
4. [`live.py`](../src/agentfaultlab/live.py): the model chooses native calls/final responses;
   middleware performs declared deterministic recovery. It receives no evaluator truth.
5. [`scoring.py`](../src/agentfaultlab/scoring.py): deterministic completion and expected/observed
   assertion details; a success sentence cannot establish correctness.

In a future live write run, **the model** requests creation. **The executor** enforces the boundary
and timeout. **Middleware** queries the same key and verifies content under an explicit recipe.
**The model** receives that recovered result under its original native ID and decides what to do
next. **The evaluator** independently checks actual final state. These are different owners;
none of the deterministic actions is described as model reasoning.

No live requests were made to create this guide. The ready-to-review
[live protocol](live-pilot-protocol.md) is a separate experiment with its own output directories.
"""
    )
    (root / "docs/phase2-learning.md").write_text(text)
    print("Phase 2 guide and two independent teaching snapshots saved; Phase 1 copies preserved.")


if __name__ == "__main__":
    main()
