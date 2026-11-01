# Phase 2 verification — 2026-11-01

Executed locally on this Mac using the existing isolated CPython 3.12.16 environment.
No additional packages were installed and no paid provider requests were made.

| Check actually executed | Observed result |
| --- | --- |
| `pytest -q` | **96 passed, 1 deselected**; real-provider test remains explicitly opt-in. All original 52 tests remain covered, with added failure-path and dashboard assertions. |
| `ruff check .` | Passed. |
| `ruff format --check .` | Passed (38 Python files formatted). |
| `python -m pip check` | No broken requirements. pip emitted only its existing unwritable-home-cache warning; no package installation was attempted. |
| `agentfaultlab demo --output results/phase2-legacy-regression` | 45 scripted runs; original completion counts preserved: fail fast 3/15, bounded retry 6/15, resilient 13/15; zero duplicates and harness failures. Original results/demo untouched. |
| `agentfaultlab run --config configs/phase2/offline-v1.yaml` | 75 scripted runs, version phase2-v1, shuffled schedule retained. No harness/provider errors. |
| `agentfaultlab compare --results results/phase2-offline-v1` | JSON/CSV comparison rebuilt successfully using its manifest. |
| `agentfaultlab inspect <saved-run>` | Saved Phase 2 teaching run loaded without re-execution; original committed Phase 1 examples also load. |
| `agentfaultlab run --config configs/phase2/smoke-v1.yaml --dry-run` | 3 runs planned; $0.072864 assumed-usage estimate, $0.941184 conditional planning ceiling. No credential or provider access. |
| `agentfaultlab run --config configs/phase2/pilot-v1.yaml --dry-run` | 60 runs planned; $1.45728 estimate, $18.82368 conditional ceiling. No provider access. |
| Streamlit AppTest | Real generated artifacts, fixed chart scale, scenario/policy/version filters, empty selections, switching old/new directories, state/assertion details, and saved playback passed. |
| `streamlit run app.py --server.port 8503` | Server started at 127.0.0.1:8503; health returned `ok`, homepage HTTP 200. Stopped after smoke check. Port 8501 was occupied and its process was preserved. |
| Controlled HTTP through real OpenAI SDK | Multiple native calls, ordering/IDs, unknown tools, malformed arguments, final responses, truncation/usage, authentication/rate-limit/timeout/connection/service errors, identical policy prompts, preflight and disabled retries passed. |
| Historical artifact check | `git diff --quiet HEAD -- docs/examples` passed before commit; both original examples remained byte-for-byte unchanged. No smoke/pilot live result directories exist. |

The sandbox blocks localhost socket binding/access, so the server and HTTP check used the
approved permission path. No required final offline check remains blocked. The local Git
commit records source/configuration/docs and selected synthetic teaching snapshots only;
results directories and credentials are ignored. Nothing was pushed, deployed or published.

## Observed expanded offline results

| Policy | Completed / total | Recovered / activated | Safe failures / failed | Activated rules / planned | Duplicates |
| --- | --- | --- | --- | --- | --- |
| Fail fast | 5/25 | 1/21 | 17/20 | 21/22 | 1 |
| Bounded retry | 8/25 | 4/21 | 14/17 | 21/22 | 1 |
| Resilient | 17/25 | 13/21 | 5/8 | 22/22 | 1 |

All three have 21/21 faulted-run activation coverage. Rule-level coverage differs because the
additional reconciliation-read outage rule is only reached by the resilient recipe. Each has
one unsupported success claim in the preserved single-source corruption case. Each reports one
duplicate induced by the deliberately faulty multiple-record service fixture; no policy made
a blind repeat write. These are scripted implementation results, not live LLM rankings.

## Scope still unmeasured or limited

- No live smoke or pilot execution, no hosted model robustness measurements, no account/model
  availability verification, and no provider billing comparison. Paid execution is the user boundary.
- Estimates and conditional ceilings depend on explicit assumptions and are not exact spend caps.
- Independent source agreement cannot detect correlated corruption; source authority is synthetic.
- Deadlines require cooperative Python cancellation; scoring/export and capped client cleanup add
  overhead outside orchestration. No process isolation or distributed transaction guarantees.
- Confidence intervals are descriptive, with fixed scenarios and small repeated samples; no broad
  statistical ranking is warranted. Redaction remains heuristic.

Next authorized command to run **only after user approval**, with credentials supplied privately:

```sh
agentfaultlab run --config configs/phase2/smoke-v1.yaml --allow-paid
```
