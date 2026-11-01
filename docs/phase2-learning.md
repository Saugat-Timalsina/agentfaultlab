# Phase 2 learning walkthrough

These are actual **scripted** saved runs, not LLM results. They are separate from the historical
[Phase 1 learning guide](learning-guide.md). Run `python scripts/refresh_phase2_examples.py`
to refresh these teaching copies after running the versioned offline configuration.

Start with `agentfaultlab run --config configs/phase2/offline-v1.yaml` and `streamlit run app.py`
(use `--server.port 8503` if 8501 is occupied). Select `results/phase2-offline-v1` in the dashboard.
Expand middleware_result to follow the original request, child calls and supporting verification
IDs. The diagnostic trace and observable transcript have deliberately different audiences.

## Recovering an ambiguous write

Run `correlation-write-lost-response-resilient-61e87db69f`, mode **scripted**, artifact **phase2-v1**.
[Trace](examples-phase2/correlation-write-lost-response-resilient-61e87db69f.jsonl) ·
[Outcome](examples-phase2/correlation-write-lost-response-resilient-61e87db69f.run.json) ·
[Observable transcript](examples-phase2/correlation-write-lost-response-resilient-61e87db69f.transcript.json)

The scripted agent requests one create. Actual before/after state verifies that the record committed, then the response delay times out. Middleware consumes a shared recovery action and a child read to reconcile the original request key. It finds one matching record and emits middleware_result with supporting call IDs. The agent then verifies existence and makes its final decision. No second write occurs.

Observed: completed **True**, safe **True**, honest **True**,
uncertain **False**, duplicate side effects **0**,
boundary calls **3**, recovery actions **2**.

```sh
agentfaultlab inspect docs/examples-phase2/correlation-write-lost-response-resilient-61e87db69f.run.json
```

| Seq | Event | Execution owner | Tool | Recovery action |
| --- | --- | --- | --- | --- |
| 3 | agent_decision | scripted_agent | — | — |
| 5 | tool_call | scripted_agent | create_correlation_ticket | — |
| 8 | environment_commit | scripted_agent | create_correlation_ticket | — |
| 9 | fault_activated | scripted_agent | create_correlation_ticket | — |
| 10 | observed_result | scripted_agent | create_correlation_ticket | — |
| 11 | recovery | middleware | create_correlation_ticket | reconcile_state |
| 12 | tool_call | middleware | find_correlation_ticket | — |
| 13 | observed_result | middleware | find_correlation_ticket | — |
| 14 | recovery | middleware | create_correlation_ticket | reconciled_existing_write |
| 15 | middleware_result | middleware | create_correlation_ticket | — |
| 16 | agent_observation | scripted_agent | create_correlation_ticket | — |
| 17 | agent_decision | scripted_agent | — | — |
| 19 | tool_call | scripted_agent | find_correlation_ticket | — |
| 20 | observed_result | scripted_agent | find_correlation_ticket | — |
| 21 | agent_observation | scripted_agent | find_correlation_ticket | — |
| 22 | agent_decision | scripted_agent | — | — |
| 23 | verified_outcome | harness/evaluator | — | — |

## Supported failure on independent disagreement

Run `invoice-unresolved-disagreement-resilient-0bf07b2cd2`, mode **scripted**, artifact **phase2-v1**.
[Trace](examples-phase2/invoice-unresolved-disagreement-resilient-0bf07b2cd2.jsonl) ·
[Outcome](examples-phase2/invoice-unresolved-disagreement-resilient-0bf07b2cd2.run.json) ·
[Observable transcript](examples-phase2/invoice-unresolved-disagreement-resilient-0bf07b2cd2.transcript.json)

The primary response is plausibly corrupted. Middleware obtains a genuinely separate reference invoice, but its observed authority is only peer. The two values disagree. Middleware returns an explicit unresolved-disagreement error with both call IDs; the script abstains. Task completion remains false. Evaluator truth never enters a recipe or prompt. Agreement between two correlated bad sources would still be a limitation.

Observed: completed **False**, safe **True**, honest **True**,
uncertain **False**, duplicate side effects **0**,
boundary calls **2**, recovery actions **1**.

```sh
agentfaultlab inspect docs/examples-phase2/invoice-unresolved-disagreement-resilient-0bf07b2cd2.run.json
```

| Seq | Event | Execution owner | Tool | Recovery action |
| --- | --- | --- | --- | --- |
| 3 | agent_decision | scripted_agent | — | — |
| 5 | tool_call | scripted_agent | get_invoice_primary | — |
| 7 | fault_activated | scripted_agent | get_invoice_primary | — |
| 9 | observed_result | scripted_agent | get_invoice_primary | — |
| 10 | recovery | middleware | get_invoice_primary | independent_source_check |
| 11 | tool_call | middleware | get_invoice_reference | — |
| 12 | observed_result | middleware | get_invoice_reference | — |
| 13 | middleware_result | middleware | get_invoice_primary | — |
| 14 | agent_observation | scripted_agent | get_invoice_primary | — |
| 15 | agent_decision | scripted_agent | — | — |
| 16 | verified_outcome | harness/evaluator | — | — |

## Observed offline suite

| Policy | Completed / total | Recovered / activated | Activated / faulted | Harness errors |
| --- | --- | --- | --- | --- |
| bounded_retry | 8/25 | 4/21 | 21/21 | 0 |
| fail_fast | 5/25 | 1/21 | 21/21 | 0 |
| resilient | 17/25 | 13/21 | 21/21 | 0 |

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
