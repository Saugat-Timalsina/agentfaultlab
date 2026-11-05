# Local verification

Historical Phase 1 record. The latest verified local result is **119 passed, 1 live test
deselected**; see [release verification](public-release.md). Live testing is optional and was
intentionally not performed for publication. Counts and scope limits below describe Phase 1.

Executed on this Mac with Python 3.12.16 on 2026-11-01:

- `pytest -q`: **52 passed, 1 deselected**. The deselected test is the explicit live-provider test.
- `ruff check .`: passed.
- `ruff format --check .`: passed.
- `python -m pip check`: no broken requirements.
- `agentfaultlab demo`: 45 scripted runs; no harness failures, no duplicate side effects.
- CLI config execution, comparison, and saved-run playback: passed, including automated coverage.
- Streamlit AppTest: generated-data loading, filters, playback, assertions and empty directory passed.
- Local Streamlit server: `/_stcore/health` returned `ok`; homepage returned HTTP 200.
  The server was stopped after the smoke test. Start it with `streamlit run app.py`.
- Real OpenAI SDK + mocked HTTP: native tool serialization, call IDs, ordering, malformed
  arguments, usage and provider errors passed without external model calls.

The default test run emitted four upstream Streamlit/Pandas deprecation warnings concerning
`DataFrame.reset_index(inplace=True)`. They do not fail rendering or tests; no third-party
package files were modified. pip also reported its default home cache was not writable;
installation completed without using that cache.

Initial package download and localhost binding/access were blocked by sandbox restrictions.
Authorized retries completed dependency installation and server checks. No final offline
checks remain blocked. No API key was present, and no live-model experiment was performed.
GitHub Actions was authored locally; it has not been executed by GitHub because nothing was pushed.

Generated suite results (scripted only):

| Policy | Completion | Recovery among activated runs | Duplicate side effects |
| --- | --- | --- | --- |
| Fail fast | 3/15 (20.0%) | 0/12 (0.0%) | 0 |
| Bounded retry | 6/15 (40.0%) | 3/12 (25.0%) | 0 |
| Resilient | 13/15 (86.7%) | 10/12 (83.3%) | 0 |

The unsafe boundary test separately proves that bypassing recovery and blindly repeating a
committed write creates a duplicate. The supported policies never do that in this suite.
These counts describe the curated script and simulator, not general LLM robustness.

Remaining scope limits: no live benchmark, dollar-cost estimator, independent invoice source,
production integrations, distributed safety guarantees, or telemetry exporter. See
[design](design.md), [metrics](metrics.md), and [roadmap](roadmap.md).
