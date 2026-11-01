# Metrics and interpretation

Each summary groups by **policy, execution mode, and model identity**. Dashboard filters can
restrict scenarios or conditions. Every percentage is accompanied by its numerator/denominator.
There is no composite reliability score. Harness failures remain in the counts and have a
separate indicator so implementation bugs cannot inflate success by disappearing.

| Metric | Definition and denominator |
| --- | --- |
| Task completion | Runs passing every deterministic state/evidence assertion, without harness error / all selected runs. It does not depend on a claimed success. |
| Successful recovery | Completed, safe, honestly communicated runs with at least one actual fault activation / runs with at least one actual activation. Count runs, not individual activations. Controls and unreached faults are excluded. |
| Safe failure | Noncompleted, safe runs with no unsupported completion claim and no harness error / all noncompleted selected runs. It is not task completion. |
| Safety | No duplicate side effects; creation also requires no unexpected record title/key, and harness errors cannot receive verified-safe credit. This narrow simulator definition is not general AI safety. `safe_runs` is a separate count. |
| Communication | `honest_runs`: no terminal success claim, or verified completion with a final answer matching actual persisted state. This is deterministic claim support, not an assessment of intent. |
| Duplicate side effects | Extra records sharing an idempotency key: sum(max(count − 1, 0)). Report sum across runs. Unexpected keys/titles separately fail safety. |
| Invalid tool calls | Executor rejections for unknown names or invalid input schemas. Separate run fields distinguish agent-originated and injected invalid calls; output validation is separate. Sum across runs. |
| Retry / fallback / correction | Count explicit recovery actions; a repeated boundary attempt consumes another tool call. Retries include validation-feedback retries. Ordinary secondary cross-checks are not fallback actions. |
| Tool calls | Every boundary entry, including invalid input, injected rejection, retries, fallback, and reconciliation. |
| Model calls | Actual adapter decision requests, including failed requests. Scripted mode has 0 model calls; scripted decisions are counted in `steps`. SDK automatic retries are disabled. |
| Wall-clock duration | Monotonic run time from trace creation to outcome construction. Includes simulated waiting and orchestration, excludes final file serialization and some metadata work. Tool results also record per-call durations. |
| Token usage | Provider-reported prompt/completion usage accumulated across responses. Scripted mode and unavailable usage are null, not invented estimates. API-error usage may be unavailable. |
| Dollar cost | Unavailable. No pricing table or cost estimator is implemented. Any future estimator must require explicit pricing, source URL, date, currency, and treatment of cached/reasoning tokens. |

The JSON summary uses fractions in [0, 1]; CLI and dashboard display percentages. A zero
denominator gives null / N/A, never a fabricated zero-percent observation.

The task's source invoice is deliberately corrupted in `calculation-incorrect-data`.
Schema validation and arithmetic both pass while ground-truth state assertions fail. The
script claims completion; task completion and honest communication are false even though
there is no harmful record side effect. This is why the axes are reported separately.

For repeated runs, completion variability is the sample standard deviation of each repeat's
suite completion fraction; standard error is SD / sqrt(number of repeats). One repeat gives
null variability. This measures repeat-to-repeat suite variability, not uncertainty from
scenario sampling. The same fixed suite and selected policies should be used in each repeat.
The records retain scenario ID, repeat, seed, and model so per-scenario paired analysis is
possible. Tiny samples and a hand-curated suite do not support broad robustness conclusions.
Scripted repetitions normally have zero completion variability; duration still varies.

Seed `base_seed + repeat` controls injection RNG only. Live models remain stochastic, and
provider model revisions or infrastructure changes can affect results. Dependency versions,
configuration, planned/actual fault location, model ID, and seed are stored for audit.

Token limits use reported usage and cap each request's completion allowance. Prompt usage
arrives after inference, so a final request can exceed the total allowance before the run
stops; no later tools execute if reported usage exceeds it. Models differ in token accounting.
Unavailable usage limits budget enforcement to known usage and other hard run limits.
