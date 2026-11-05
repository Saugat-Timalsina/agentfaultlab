# Phase 2 hardening verification — 2026-11-04

The follow-up began from `1b7e26a`. Existing source and historical examples were preserved.
These are offline verification results, not live model measurements.

| Check actually executed | Observed result |
| --- | --- |
| `.venv/bin/pytest -q` | 108 passed, 1 live test deselected after the hardening changes. Includes Streamlit AppTest and controlled SDK HTTP responses. |
| `.venv/bin/ruff check .` | Passed. |
| `.venv/bin/ruff format --check .` | Passed; 39 Python files. |
| `.venv/bin/python -m pip check` | No broken requirements. Existing home-cache permission warning only. |
| `.venv/bin/agentfaultlab run --config configs/phase2/offline-hardening-v1.yaml` | 75 scripted runs in a new directory; no harness/provider errors. Completion: fail fast 5/25, bounded retry 8/25, resilient 17/25. |
| `.venv/bin/agentfaultlab demo --output results/phase2-hardening-legacy-v1` | 45 scripted runs; original completion counts 3/15, 6/15, 13/15 preserved. No harness/provider errors or duplicates. |
| Smoke and pilot `run --dry-run` | Prepared 3 and 60 runs; estimates $0.072864/$1.45728 and conditional ceilings $0.941184/$18.82368. No provider requests. |
| `git diff --quiet HEAD -- docs/examples docs/examples-phase2` | Passed; both sets of committed examples unchanged. |

New tests cover actual commits followed by service errors, timeout or cancellation; preventing
an empty read before a write from verifying its later commit; malformed provider envelopes,
duplicate IDs, unsupported call types/finish reasons and content-filter abstention. Usage is
retained on protocol errors. Unexpected Python failures still reach the harness boundary.

The initial standalone dashboard start was blocked by sandbox socket permissions. A subsequent
approved start used `.venv/bin/streamlit run app.py --server.address 127.0.0.1 --server.port 8517
--server.headless true`. `curl --fail` returned health `ok` and homepage HTTP 200. The server
was then stopped. No unrelated server process was changed.

No paid requests or live results were produced. The schema stays phase2-v1; the separately
labeled offline recheck protocol is phase2-hardening-v1. Conditional cost estimates cannot
guarantee an exact provider billing cap. Cooperative cancellation, synthetic source authority
and correlated corruption remain limitations documented in the audit and design.
