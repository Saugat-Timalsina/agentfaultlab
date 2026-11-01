# AgentFaultLab

**A local experiment lab for injecting controlled tool faults, comparing recovery policies,
and inspecting evidence-backed agent outcomes.**

A complete local learning MVP: Python tools, strict validation, real async timeouts,
controlled injection, three recovery policies, deterministic state assertions, JSONL traces,
JSON/CSV reports, a read-only Streamlit dashboard, and an optional OpenAI tool-calling adapter.
All tools use synthetic data in memory. Nothing sends emails, spends money, or modifies calendars.

## Open and run on this Mac

Project: `/Users/saugat/Desktop/AgentFaultLab`.
In VS Code choose **File → Open Folder → Desktop → AgentFaultLab**, then **Terminal → New Terminal**.
Or run `code ~/Desktop/AgentFaultLab` if the VS Code shell command is installed.
Select `.venv/bin/python` with **Python: Select Interpreter**.

```sh
cd ~/Desktop/AgentFaultLab
source .venv/bin/activate
agentfaultlab demo
agentfaultlab compare --results results/demo
streamlit run app.py
```

Open <http://127.0.0.1:8501> for the dashboard. Stop it with Ctrl-C.
The demo takes a few seconds and makes 45 **scripted** runs: 12 fault cases plus 3 controls,
each under 3 policies. Installation needs package downloads; subsequent offline runs need
neither credentials nor network access.

To inspect one run without executing it:

```sh
agentfaultlab run --config configs/demo.yaml
agentfaultlab inspect "$(find results/demo -name '*.run.json' -print -quit)"
```

`results/demo/manifest.json` identifies the latest experiment. Old uniquely named run files
are retained; comparison and dashboard loading follow the manifest to avoid mixing experiments.
Each run has a `.run.json` summary and `.jsonl` event trace, plus experiment-level
`summary.json`, `summary.csv`, and `runs.csv`. Dashboard filters and downloads use these files.
Playback means loading saved events, not deterministic re-execution.

## Install on another machine

Use Python 3.11 or later. Do not use macOS's system Python 3.9.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,live]'
```

The environment already created on this Mac uses locally available CPython 3.12.16.
Its base interpreter lives in the existing `~/Desktop/evidenceguard/.runtime/` tree; no files
there were changed. If that tree is moved, recreate `.venv` using another Python 3.11+ installation.
`requirements-lock.txt` captures the exact installed runtime and test packages for Python 3.12
on this Mac. To reproduce those versions in a fresh compatible environment:

```sh
python -m pip install -r requirements-lock.txt
python -m pip install --no-deps -e .
```

The lock snapshot is not a universal cross-platform lock. `pyproject.toml` provides compatible
dependency ranges for other supported environments.

## What is being compared?

| Policy | Deterministic middleware | Scripted / live agent decisions |
| --- | --- | --- |
| Fail fast | Stop on the first unrecovered tool error | Normal task steps and checks |
| Bounded retry | Retry explicitly transient, retry-safe calls with limits and backoff | Normal task steps and checks |
| Resilient | Add task-bound argument correction, malformed-output feedback, fallback after exhausted lookup errors, and write-state reconciliation | The script chooses the vetted secondary on disagreement; live models choose their next native call from observed feedback |

Middleware is ordinary Python policy logic. Scripted behavior is a small domain program.
Neither is evidence of autonomous model reasoning. The same three policies can wrap live
models, but hosted results are stochastic and require repeated runs.

The curated fake create service does not enforce idempotency keys: an unguarded repeat really
can create duplicates. Keys enable state reconciliation, and an optional fake-backend setting
can enforce deduplication. The create tool is marked unsafe to retry after ambiguity.
The project makes no claim to be the first agent fault-testing framework; see
[related work](docs/related-work.md).

## Architecture

```text
CLI / YAML config → runner → scripted agent or OpenAI adapter
                            ↓ observable decision
                         recovery policy
                            ↓ every attempt
                         tool executor → strict schemas → fault injector → fake environment
                            ↓ observed result
                         agent observation
runner → deterministic state/evidence assertions → JSONL + JSON/CSV → Streamlit playback
```

`src/agentfaultlab/` has separate schemas, tools, faults, executor, agents, policies, scenarios,
runner, scoring, reporting, CLI, live adapter, tracing, and dashboard modules. The core imports
neither Streamlit nor OpenAI. [Design](docs/design.md) explains occurrence counting,
ownership, deadlines, evidence isolation, and extension points.

The 12 fault cases cover unknown tools, missing and mistyped arguments, temporary exceptions,
timeouts, rate limits, malformed outputs, plausible incorrect data, committed writes with
lost responses, and an unavailable write service. Three fault-free controls isolate baseline behavior.

## Optional live LLM mode

The adapter uses OpenAI Chat Completions with native strict function tools and a structured
terminal response. Use an account-accessible model supporting those features. There is no
hard-coded model default. No API key was present during development; real model behavior
has **not** been evaluated. Mocked HTTP tests exercise the installed OpenAI SDK.

```sh
source .venv/bin/activate
python -m pip install -e '.[live]'  # Already installed on this Mac
read -s "OPENAI_API_KEY?OpenAI API key: "
export OPENAI_API_KEY
cp configs/live.example.yaml configs/live.local.yaml
# Edit model in configs/live.local.yaml to a model ID available to your account.
agentfaultlab run --config configs/live.local.yaml
```

The `read` command above uses macOS zsh and avoids putting the key in shell history.
`.env.example` is documentation only; `.env` files are not automatically loaded.
Never paste credentials into YAML, source files, traces, or commits. Live model requests incur
provider charges; all called tools remain local synthetic functions.
Three repeats are only a smoke experiment. Seeded injection does not make hosted inference
deterministic. Dollar cost remains unavailable; no undocumented pricing is assumed.

To opt into a real-provider test explicitly, set `AGENTFAULTLAB_MODEL`, `OPENAI_API_KEY`, and
`AGENTFAULTLAB_LIVE_TEST=1`, then run `pytest -m live`. Default tests and CI do not use the network.

## Checks

```sh
ruff check .
ruff format --check .
pytest -q
python -m pip check
```

Tests cover the entire offline matrix, boundary validation, occurrence and seed behavior,
actual timeout cancellation, budgets and Retry-After, fresh state, corruption, reconciliation,
false claims, harness/evaluator errors, trace loading/redaction, CLI commands, the dashboard,
and mocked native provider messages. GitHub Actions contains offline checks for Python
3.11 and 3.12; this local project has not been pushed or published.

## Limits and next steps

- This is a small synthetic lab, not production infrastructure or a general model benchmark.
- Trusted fallback selection and argument correction are domain-specific and deliberately bounded.
- Schema-valid invoice corruption can pass arithmetic validation. The deterministic evaluator
  catches the wrong state and unsupported success claim; the agent has no independent invoice source.
- No deliberately unsafe retry policy is included. A boundary test demonstrates that a blind
  retry duplicates records; supported policies preserve zero duplicates in the curated suite.
- Python cancellation is cooperative. External blocking tools or cancellation-resistant handlers
  need stronger process isolation. This simulator uses cooperative async handlers.
- Token budgets stop on reported usage and cap requested completion tokens. Prompt usage is
  known after each response, so the last request can overshoot; see [metrics](docs/metrics.md).
- Redaction is heuristic, not a PII or credential detection guarantee. Traces are local sensitive
  artifacts and contain synthetic task data plus live model outputs when used.
- There is no persistent database, telemetry backend, distributed execution, or live-provider
  benchmark. See the [roadmap](docs/roadmap.md).

Read first: [learning guide](docs/learning-guide.md),
[tool executor](src/agentfaultlab/executor.py), and [recovery policies](src/agentfaultlab/policies.py).
