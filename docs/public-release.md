# Public release verification

AgentFaultLab is published as an **offline-verified synthetic experiment lab**. The owner chose
not to run live LLM tests. No provider requests were made for release preparation. The optional
adapter and live configurations remain available, with mocked HTTP tests and no real-provider
verification. Live tests are not required to use, test, or publish this project.

## Verified scope

The latest completed local suite check was **119 passed, 1 live test deselected**, with Ruff
lint/format checks and dependency checks passing. Dashboard AppTest, controlled OpenAI SDK HTTP
responses, budgets, cancellation, write reconciliation, independent-source disagreement and
evaluator isolation are covered. Package installation and CI setup may use the network to fetch
dependencies; verification makes no model inference requests.

The prior scripted recheck produced 75 runs, with completion counts of 5/25 (fail fast),
8/25 (bounded retry), and 17/25 (resilient). These are deterministic fixture-suite results,
not a reliability ranking or evidence about model intelligence. The 45-run legacy regression
preserved 3/15, 6/15, and 13/15 respectively. Both had no harness/provider errors. Deliberately
induced duplicate records in the expanded suite remain counted; they are not hidden as recovery.

Detailed historical records:

- [Initial Phase 1 verification](verification.md).
- [Initial Phase 2 verification](phase2-verification.md).
- [Hardening verification and dashboard HTTP check](phase2-verification-20261104.md).
- [119-test launch-guard verification and archived live preparation](live-smoke-readiness-20261104.md).
- [Audit findings and fixes](phase2-audit.md).

## Publication review

- README now starts with portable offline installation and exploration commands. The optional
  SDK extra is needed for mocked adapter tests, not for ordinary scripted use.
- An MIT license is included and declared in package metadata alongside the README.
- GitHub Actions uses Python 3.11 and 3.12, read-only repository permissions, and explicit
  `pytest -q -m 'not live'`. No provider secrets, paid commands, or deployment steps are configured.
- Reviewed all 105 reachable historical file blobs before release edits and all 67 then-tracked
  paths. No private-key blocks, GitHub/OpenAI/Slack token patterns, AWS access-key patterns,
  credential-bearing URLs, tracked credential files, generated result directories, or binary
  artifacts were found. Explicit placeholder credentials in tests and `.env.example` are synthetic.
- Existing standard Git author identity metadata and commit history are retained. Historical
  local verification paths and timestamps describe development, not secret account information.
- Sanitized examples in `docs/examples` and `docs/examples-phase2` are preserved unchanged.
  `.gitignore` excludes environment files, environments/caches, and generated results.

Pattern scanning is a bounded review, not a guarantee that every possible secret format can
be recognized. No credentials were printed or added to Git. Authentication for publication uses
the configured macOS Git credential helper privately.

## Release-specific checks actually executed

| Check | Result |
| --- | --- |
| Ruff lint and format checks | Passed. No runtime feature changes were made for release preparation. |
| `pytest --collect-only -q -m 'not live'` | 119/120 tests collected, 1 deselected. This checks the updated CI selector; the prior completed execution remains 119 passed, 1 deselected. |
| CLI `--help` for run/compare/inspect/demo; `smoke --dry-run` | README options and the default demo output directory match the CLI; optional preview made no provider requests. |
| Saved Phase 2 `inspect` command | Passed using the committed correlation-write teaching run, without re-execution. |
| Local Markdown link/fragment check | 59 links checked; no missing targets or heading anchors. |
| Workflow/configuration review | Correct 3.11/3.12 matrix, read-only permissions, explicit offline selection, no secret references or paid/deployment steps. Optional live YAML values unchanged; only labels/comments added. |
| `python -m pip wheel . --no-deps --wheel-dir /tmp/agentfaultlab-release-wheel` | Built agentfaultlab-0.1.0 wheel. Verified README metadata and bundled MIT license; no credentials, Git metadata, or result directories bundled. Initial sandbox DNS failure was resolved through the approved network path. |
| Historical example diff | No changes to either sanitized example directory. |
| Tracked-file/history review | No credential-pattern findings or unintended generated/sensitive file paths in the reviewed history. |

No scripted experiments were regenerated for documentation-only changes. No live smoke, pilot,
provider model-access check, dashboard deployment, or new runtime feature was added. Package
building fetched only its isolated backend dependencies from PyPI.

The authenticated account already had an empty public `AgentFaultLab` repository (no branches).
Publication reuses it under the requested lowercase name, without force-pushing or replacing
unrelated work. [GitHub Actions](https://github.com/Saugat-Timalsina/agentfaultlab/actions) is the
source of CI status for the published commit; earlier local records do not claim GitHub execution.
