# AgentFaultLab

**A local experiment lab for injecting controlled tool faults, comparing recovery policies,
and inspecting evidence-backed agent outcomes.**

Phase 2 adds shared resource budgets, traceable recovery, explicit correlation/idempotency
services, independent invoice evidence and a prepared live-agent pilot. All tools remain local
and synthetic. Scripted results test this implementation and its recipes, not LLM intelligence.

## Open and explore on this Mac

Project: `~/Desktop/AgentFaultLab`. In VS Code choose **File → Open Folder → Desktop →
AgentFaultLab**, then **Terminal → New Terminal**. Select `.venv/bin/python` as the interpreter.
If the `code` shell command is installed, `code ~/Desktop/AgentFaultLab` also opens it.

```sh
cd ~/Desktop/AgentFaultLab
source .venv/bin/activate
agentfaultlab run --config configs/phase2/offline-v1.yaml
agentfaultlab compare --results results/phase2-offline-v1
streamlit run app.py
```

Open <http://127.0.0.1:8501> and enter `results/phase2-offline-v1` in **Results directory**.
The expanded suite makes 75 scripted runs: 25 scenarios × 3 policies. Filter to one scenario
before comparing configurations; unsupported claims, uncertainty and induced unsafe state are
shown separately. The chart axes are fixed at 0–100%, with separate completion/recovery panels.

The original 15-case suite still works:

```sh
agentfaultlab demo
agentfaultlab compare --results results/offline-v2
```

New demo output defaults to `results/offline-v2`; the original `results/demo` artifacts and
committed `docs/examples` snapshots are preserved. Every new run is labeled `phase2-v1`.
Use a new output directory for a new study; the manifest selects the most recent experiment
while retaining older uniquely named run files.

Saved-run playback requires neither a key nor execution:

```sh
agentfaultlab inspect "$(find results/phase2-offline-v1 -name '*.run.json' -print -quit)"
```

## What works offline

- Nine fault kinds: unknown tool, missing/mistyped argument, temporary exception, genuine
  timeout, rate limit with Retry-After, malformed output, plausible wrong data, committed write
  with lost response. Rules have tool/occurrence selectors, transient/persistent behavior and seeds.
- Fail fast, bounded safe retry, and resilient deterministic recipes. Global run budgets cover
  decisions, model requests, boundary calls, started handlers, recovery actions, elapsed time
  and available usage. Retry/correction limits are per original call.
- Resettable lookup, calculation and creation tasks with independent final-state assertions.
- Explicit correlation-key service permits duplicates; idempotent service deduplicates equivalent
  requests and rejects key/content conflicts. Ambiguous writes are reconciled, never blindly retried.
- Independent invoice sources include separate stored data and source/authority provenance.
  The original corruption failure remains; peer disagreement and missing reference evidence abstain.
- Original/child call lineage, supporting verification IDs, explicit synthesized-result events,
  JSONL diagnostic traces and separate model-visible transcripts; JSON/CSV reports and downloads.
- Native provider adapter exercised entirely through controlled HTTP responses, plus dashboard tests.

The write fixtures deliberately include multiple records/conflicting content. Their unsafe state
is counted even when middleware correctly refuses to claim completion; it is not hidden behind
a recovery metric. Independent-source agreement cannot detect correlated corruption in both stores.

## Architecture and learning

```text
CLI/YAML → runner + RunBudget → scripted agent or native provider adapter
                ↓
          Recovery + Recipe registry → ToolExecutor → validated synthetic tools + faults
                ↓                            ↓
          model-visible result         diagnostic lineage / verified state changes
                ↓                            ↓
          independent evaluator → JSON/CSV + JSONL → read-only Streamlit playback
```

Read first: [Phase 2 learning walkthrough](docs/phase2-learning.md),
[tool executor](src/agentfaultlab/executor.py), and [recovery policies](src/agentfaultlab/policies.py).
[Design](docs/design.md), [metrics](docs/metrics.md), [audit](docs/phase2-audit.md), and
[related work](docs/related-work.md) explain contracts and positioning. This project does not
claim to be the first agent fault-testing framework or production-ready infrastructure.

## Live execution is prepared, not performed

The versioned [protocol](docs/live-pilot-protocol.md) specifies a three-run smoke test followed
by a separately authorized 60-run pilot. It compares **agent-plus-middleware configurations**.
The same model, task instructions, tools and fault schedule are used across policies; prompts
do not identify the policy. Each run resets state and conversation, and a recorded seed shuffles
execution order. Native calls execute sequentially in response-array order. If execution stops,
remaining calls are explicitly marked skipped rather than silently discarded.

Review configuration and cost without credentials or network:

```sh
agentfaultlab run --config configs/phase2/smoke-v1.yaml --dry-run
agentfaultlab run --config configs/phase2/pilot-v1.yaml --dry-run
```

Prepared model: `gpt-5.6-terra`, reasoning effort `none`. Pricing is explicit with official source
URL and retrieval date in each config. Under the stated usage assumptions the smoke estimate is
$0.072864; its conditional planning ceiling is $0.941184. These are **not guaranteed billing caps**.
See the committed [smoke preview](docs/smoke-cost-preview-v1.json) and
[pilot preview](docs/pilot-cost-preview-v1.json). Provider access, rates and hosted model revisions
can change; review the source and your account before authorizing execution.

After reviewing the concrete protocol, provide the key privately using macOS zsh:

```sh
read -s "OPENAI_API_KEY?OpenAI API key: "
export OPENAI_API_KEY
# Explicit authorization for three paid smoke runs:
agentfaultlab run --config configs/phase2/smoke-v1.yaml --allow-paid
```

The command is provided for the user; it has **not** been executed during development.
Do not start the pilot until you have reviewed the smoke artifacts and authorized it separately.
The CLI refuses live execution without `--allow-paid`. Credentials come from the environment;
.env files are not automatically loaded. Never put a key in YAML, source, traces or commits.

Provider authentication, rate-limit, connection, timeout, service and truncated/protocol responses
are tracked separately from injected tool errors and harness bugs. SDK automatic retries are off.
Client input estimates and output caps help bound spend; they cannot guarantee exact billing.
No live robustness results are claimed.

## Installation and checks

The existing isolated environment is ready on this Mac. On a fresh machine with Python 3.11+:

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,live]'
ruff check .
ruff format --check .
pytest -q
python -m pip check
```

The local environment uses CPython 3.12.16 from the existing
`~/Desktop/evidenceguard/.runtime/` installation; that project was not modified. Recreate `.venv`
with another Python 3.11+ installation if the base interpreter moves. `requirements-lock.txt`
captures the installed Mac/Python 3.12 package snapshot; it is not a universal cross-platform lock.

Default tests make no provider requests. Tests marked live require all of `AGENTFAULTLAB_LIVE_TEST=1`,
`AGENTFAULTLAB_MODEL` and `OPENAI_API_KEY`, with `pytest -m live`; do not use that during an offline check.
GitHub Actions defines offline checks only. Nothing has been pushed, published or deployed.
Actual executed checks and limitations: [Phase 2 verification](docs/phase2-verification.md).

## Limits

A small synthetic suite does not establish general robustness. Recipes and source authority are
domain contracts, not autonomous model reasoning or authenticated provenance. Token estimates
can differ from provider accounting. Python cancellation requires cooperative handlers; cleanup
and final export add small overhead outside orchestration. Redaction is heuristic, not a guarantee
against arbitrary credentials/PII. Keep traces local and review before sharing. No database,
production integration, distributed safety proof or telemetry backend is included. See the
[roadmap](docs/roadmap.md).
