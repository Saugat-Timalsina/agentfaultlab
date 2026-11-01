> **Phase 2 update:** Read the [new walkthrough](phase2-learning.md) for shared budgets,
> recovery lineage, explicit write services and independent invoices. The snapshots and counts
> below are preserved **Phase 1 scripted results**, not regenerated Phase 2 or live results.

# Learning guide: follow the evidence

These examples are saved artifacts from an actual **scripted offline** demo. They are not
LLM benchmark results. The snapshots in `docs/examples/` remain usable after you run a new demo.
To refresh this guide from your latest demo, run `python scripts/refresh_learning_examples.py`.

## Start here

1. Run `agentfaultlab demo` and `streamlit run app.py` from the project root.
2. Filter to `creation-commit-timeout` and `resilient`, then inspect the timeline.
3. Filter to `calculation-incorrect-data` and inspect the failed persisted-answer assertion.

## Successful recovery: a committed write with a lost response

Run ID: `creation-commit-timeout-resilient-37ddb5c63d`. Seed: 7. Mode: **scripted**.

[Saved trace](examples/creation-commit-timeout-resilient-37ddb5c63d.jsonl) ·
[Saved outcome](examples/creation-commit-timeout-resilient-37ddb5c63d.run.json)

```sh
agentfaultlab inspect docs/examples/creation-commit-timeout-resilient-37ddb5c63d.run.json
```

The script requests a ticket with key `request-001`. The handler commits it, then injection
delays the response until `asyncio.wait_for` cancels the coroutine. A timeout does not imply
the record is absent. Resilient middleware calls `find_ticket` with the original key and
checks the title. It returns evidence of the existing record, then the script verifies
existence. No second create request occurs. Actual records: 1;
duplicate side effects: 0; completed: True.

| Sequence | Event | Tool | Action / error |
| --- | --- | --- | --- |
| 3 | agent_decision | — | — |
| 4 | tool_call | create_ticket | — |
| 6 | fault_activated | create_ticket | — |
| 8 | observed_result | create_ticket | tool_environment |
| 9 | recovery | create_ticket | reconcile_state |
| 10 | tool_call | find_ticket | — |
| 11 | observed_result | find_ticket | — |
| 12 | recovery | create_ticket | reconciled_existing_write |
| 14 | agent_decision | — | — |
| 15 | tool_call | find_ticket | — |
| 16 | observed_result | find_ticket | — |
| 18 | agent_decision | — | — |
| 19 | verified_outcome | — | — |

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

Run ID: `calculation-incorrect-data-resilient-73e28d25b8`. Seed: 7. Mode: **scripted**.

[Saved trace](examples/calculation-incorrect-data-resilient-73e28d25b8.jsonl) ·
[Saved outcome](examples/calculation-incorrect-data-resilient-73e28d25b8.run.json)

```sh
agentfaultlab inspect docs/examples/calculation-incorrect-data-resilient-73e28d25b8.run.json
```

The injected invoice changes a unit price by 7 cents. It remains valid structured data.
Both the calculate tool and scripted arithmetic check use the same corrupted items, so they
agree. The script submits **3464** and claims completion. The
independent state assertion expects **3450** and rejects it.
Completed: False; supported communication (`honest`): False;
record safety: True. There were no retries because no observable schema or tool
error occurred. A limitation is visible rather than hidden behind a high recovery percentage.

| Sequence | Event | Tool | Action / error |
| --- | --- | --- | --- |
| 3 | agent_decision | — | — |
| 4 | tool_call | get_items | — |
| 6 | fault_activated | get_items | — |
| 8 | observed_result | get_items | — |
| 10 | agent_decision | — | — |
| 11 | tool_call | calculate | — |
| 12 | observed_result | calculate | — |
| 14 | agent_decision | — | — |
| 15 | tool_call | submit_answer | — |
| 16 | observed_result | submit_answer | — |
| 18 | agent_decision | — | — |
| 19 | verified_outcome | — | — |

Read [`faults.py`](../src/agentfaultlab/faults.py) for corruption;
[`agents.py`](../src/agentfaultlab/agents.py) for the limited arithmetic check;
[`scoring.py`](../src/agentfaultlab/scoring.py) for independent truth;
[`runner.py`](../src/agentfaultlab/runner.py) for separate completion, safety and communication.
An independent invoice source is a useful next experiment, not an implemented recovery.

## Results from this generated demo

| Policy | Completion / runs | Recovery / activated runs | Duplicate side effects |
| --- | --- | --- | --- |
| bounded_retry | 6/15 (40.0%) | 3/12 (25.0%) | 0 |
| fail_fast | 3/15 (20.0%) | 0/12 (0.0%) | 0 |
| resilient | 13/15 (86.7%) | 10/12 (83.3%) | 0 |

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
