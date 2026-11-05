# AgentFaultLab

**A local experiment lab for injecting controlled tool faults, comparing recovery policies,
and inspecting evidence-backed agent outcomes.**

AgentFaultLab runs resettable synthetic lookup, calculation, and write tasks through three
middleware policies: fail fast, bounded retry, and resilient recovery. It records what happened,
who performed each action, and whether final state supports the claimed outcome.

**Verified offline:** 119 tests passed, one opt-in live test deselected. Scripted experiments,
dashboard playback, and the optional provider adapter's mocked HTTP tests are verified.
**No real-provider LLM tests were run.** Live execution is optional and is not required to use,
test, or publish this project. Scripted completion rates describe this fixture suite only;
they are not measurements of model intelligence or general reliability.

## Quick start

Requires Python 3.11+. No API key or provider account is needed.

```sh
git clone https://github.com/Saugat-Timalsina/agentfaultlab.git
cd agentfaultlab
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
agentfaultlab run --config configs/phase2/offline-v1.yaml
agentfaultlab compare --results results/phase2-offline-v1
streamlit run app.py
```

Open <http://127.0.0.1:8501> and enter `results/phase2-offline-v1` in **Results directory**.
The expanded suite runs 25 scenarios × 3 policies = 75 scripted runs. Filter to one scenario
to inspect completion, fault activation, uncertainty, duplicate side effects, and recovery.
Charts use fixed 0–100% scales and separate denominators for completion and recovery.

To explore the sanitized teaching artifacts immediately, select `docs/examples-phase2` in
the dashboard. Saved playback needs no experiment execution:

```sh
agentfaultlab inspect docs/examples-phase2/correlation-write-lost-response-resilient-61e87db69f.run.json
```

The original 15-scenario suite and the separately labeled hardening recheck remain available:

```sh
agentfaultlab demo
agentfaultlab compare --results results/offline-v2
agentfaultlab run --config configs/phase2/offline-hardening-v1.yaml
```

Generated results are ignored by Git. Each run retains a unique ID; the directory's manifest
selects its latest experiment. Use a new output directory for a new study. Historical examples
are preserved in `docs/examples` and `docs/examples-phase2`.

## What the lab demonstrates

- Nine fault types, including transient errors, timeouts, invalid calls/results, plausible
  data corruption, and a write that commits before its response is lost.
- Shared run budgets for decisions, model requests, tool boundary attempts, recovery actions,
  elapsed time, and available token usage. Retry/correction limits are per original call.
- Explicit correlation-key and server-idempotent services. Reused keys with conflicting
  content fail; ambiguous writes are reconciled rather than blindly repeated.
- Independent invoice stores with source/authority provenance, including supported abstention
  when evidence cannot resolve disagreement. The original single-source corruption failure remains.
- Call lineage, individual attempts, execution-owner labels, synthesized recovery results,
  diagnostic JSONL traces, separate model-visible transcripts, and JSON/CSV comparisons.
- A read-only Streamlit dashboard with assertions, expected/observed values, and raw-event details.

Some fixtures deliberately produce duplicate or conflicting records. Those side effects remain
visible even if middleware correctly abstains. Independent-source agreement cannot detect
correlated corruption in both stores. Deterministic recovery recipes are middleware actions,
not model reasoning.

## Design and walkthroughs

```text
CLI/YAML → runner + RunBudget → scripted agent or optional provider adapter
                ↓
          Recovery + Recipe registry → ToolExecutor → synthetic tools + injected faults
                ↓                            ↓
          model-visible result         diagnostic lineage / verified state changes
                ↓                            ↓
          independent evaluator → JSON/CSV + JSONL → read-only dashboard
```

Start with the [Phase 2 walkthrough](docs/phase2-learning.md), then read the
[design](docs/design.md), [metric definitions](docs/metrics.md), [audit](docs/phase2-audit.md),
and [related work](docs/related-work.md). The [Phase 1 guide](docs/learning-guide.md) preserves
historical scripted results. [Release verification](docs/public-release.md) records publication
checks and links to the earlier verification records.

## Offline development and CI

```sh
python -m pip install -e '.[dev,live]'
ruff check .
ruff format --check .
pytest -q -m 'not live'
python -m pip check
```

The `live` extra installs the optional OpenAI SDK so controlled HTTP tests can exercise the
adapter offline. Installing it makes no model requests. Default pytest settings exclude the
real-provider test; GitHub Actions explicitly selects `not live` on Python 3.11 and 3.12.
Package installation requires network access, but tests and scripted runs require no provider
credentials or inference calls. The latest verified local result is **119 passed, 1 deselected**.
`requirements-lock.txt` is a recorded Mac/Python 3.12 environment snapshot, not a portable lockfile.

## Optional live adapter — mocked tests only

The OpenAI adapter supports native tool calls, sequential batches, usage accounting, structured
final output, and distinct provider error categories. SDK retries are disabled. Its serialization,
call IDs, ordering, malformed responses, and failure paths have controlled offline tests.
**Actual provider compatibility, account access, hosted model behavior, and billing are unverified.**

Optional examples remain in `configs/live.example.yaml` and `configs/phase2/smoke-v1.yaml` /
`pilot-v1.yaml`. The [live protocol](docs/live-pilot-protocol.md) and dated cost previews are
unexecuted experiment designs, not release requirements or current pricing promises. Inspect
the optional plan without credentials or provider requests:

```sh
agentfaultlab smoke --dry-run --spending-allowance 1
```

Live execution requires an explicit `--allow-paid` flag and an environment-supplied API key;
`.env` files are not loaded automatically. This release intentionally contains no live results.
Client budgets and token estimates cannot guarantee an exact provider billing cap.

## Limits and license

This is a portfolio and learning implementation, not production infrastructure or a general
robustness benchmark. Cancellation requires cooperative handlers; scoring/export adds overhead
outside the orchestration deadline. Source authority is a synthetic contract. Redaction is
heuristic; review traces before sharing and keep credentials and personal data out of artifacts.
See the [roadmap](docs/roadmap.md) for optional future directions.

Licensed under the [MIT License](LICENSE).
