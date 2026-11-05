# Architecture — Phase 2

The public release is verified offline: 119 tests passed, one live test deselected. The optional
provider adapter has controlled HTTP tests but no real-provider verification. No live execution
is required for the scripted lab, dashboard, tests, or publication.

The core is independent of Streamlit and any specific provider. Existing Phase 1 examples remain
readable with defaulted new record fields; all newly generated artifacts are labeled phase2-v1.
The original 15 scenarios remain the default suite. `configs/phase2/offline-v1.yaml` explicitly
selects the expanded 25-scenario suite (75 policy runs).

```text
runner / shared RunBudget
  → model or scripted decision → root agent calls
  → Recovery scheduler → explicit Recipe registry
  → ToolExecutor (every attempt) → validation → fault selection → handler → result validation
  → middleware_result (if synthesized, links supporting child IDs)
  → model-visible observation / transcript
  → deterministic state and evidence assertions → JSONL / JSON / CSV
  → read-only Streamlit playback
```

## Budget ownership

`budget.py` owns the per-run deadline and counters for decisions, actual model requests, tool
boundary attempts, started handlers, recovery actions and reported usage. Executor and recovery
share the same instance, including standalone tests. Retry and correction counts are local to
the original call; all their attempts/actions also consume shared run allowance. Check before
operations and clamp waits to remaining time. Tool timeouts are ordinary observable environment
errors only when the run deadline has not expired. A run deadline raises BudgetExceeded;
CancelledError propagates without being converted to a retryable result. The runner's outer
timeout is additional protection. Scoring/serialization is outside this orchestration deadline;
provider cleanup is separately capped at 0.2 seconds. Cancellation remains cooperative.

The OpenAI adapter preflights an estimate of serialized UTF-8 request bytes + 512 framing tokens,
then records an actual model request and sends max_completion_tokens bounded by configured
output/remaining allowance. No additional request counts merely because a preflight failed.
Reported usage is accounted before requested tools execute. Unavailable usage stays unavailable.
This is a client safeguard, not exact tokenizer knowledge or an account billing cap.

## Calls, results and evidence

Every call has its own ID, root_call_id, parent_call_id, attempt number and owner (`model`,
`scripted_agent`, `middleware`). A retry/correction/fallback/verification read is a distinct child
call, retaining the original root. Attempt numbers indicate lineage depth; call ID and trace
sequence are the unique identifiers, not a global chronological attempt index.

ToolExecutor validates original inputs, counts the occurrence under the original name, selects
eligible faults, revalidates mutations, executes/intercepts, validates outputs and traces them.
Malformed agent calls are never silently repaired at the executor. Corrections are later explicit
middleware calls using legitimate task bindings. Unexpected tool Python exceptions reach the
harness boundary rather than masquerading as model mistakes or transient service errors.

A returned recovery result uses the original native call ID so the model transcript remains
valid. This is not allowed to erase provenance: a `middleware_result` diagnostic event records
its supporting child IDs, observed source data and synthesis reason. The agent receives only
the ordinary result/error, not hidden attribution categories, injector records or evaluator truth.
The `.transcript.json` stores native conversation messages plus sent-prefix lengths;
tool replies prepared after the last sent prefix have not been seen by the provider model.
No observation is attributed as received until a subsequent request includes it. `.jsonl` stores diagnostic metadata,
state probes and final assertions for the local viewer. No hidden chain-of-thought is requested.

Multiple native calls run sequentially in returned array order. After a policy/budget stop,
remaining calls receive explicit skipped error replies and trace records; none are silently
lost or executed outside the budget. The adapter refuses another request while call IDs lack
replies. Truncated provider output is rejected before partial calls execute. SDK retries are
zero. Expected SDK failures receive provider subtypes; unexpected adapter Python defects are
harness errors. Live system/task/tool requests are identical across policies before observations.

## Small recovery registry

`recipes.py` contains explicit Recipe entries: public correction fields, fallback tool,
verification tool/key/content fields and independent-source target. `policies.py` owns generic
bounded retry/backoff/validation feedback, dispatch and accounting. Recipes receive calls,
observed results and public task inputs only. They cannot inspect scenario IDs, expected answers,
fault rules or environment state. Registering a renamed tool requires a recipe entry, not editing
the scheduler. This is intentionally a small domain library rather than a plugin ecosystem.

Retry-After is a minimum, never capped downward. Exponential backoff is capped at 0.1 seconds
before applying Retry-After. If a wait would exhaust the run deadline, record a skipped retry.
Schema-invalid read results may be retried under the resilient policy. Unknown arbitrary
arguments are not guessed: correction only fills the explicit recipe's permitted task fields.

## Write services

The new tools explicitly distinguish:

- `create_correlation_ticket` / `find_correlation_ticket`: request_key correlates records and
  does not enforce deduplication. Repeating a create can produce duplicate state.
- `create_idempotent_ticket` / `find_idempotent_ticket`: equivalent title+key requests return
  the existing record. Reusing a key with a different title raises a permanent idempotency conflict
  without mutation. Enforcement is atomic only within this cooperative single-process simulator.

Legacy create_ticket/find_ticket and their historical idempotency_key field remain for the old
suite. New experiments use the clear names. Every write is conservatively non-retry-safe.
After ambiguity the policy queries the same key and checks exactly one matching record.
Zero, multiple, conflicting or unavailable records leave the result uncertain. Neither service
variant is automatically re-written after ambiguity; server idempotency does not by itself
satisfy the task's existence-verification requirement.

Diagnostic-only state probes snapshot records before/after handlers. A handler returning is
not proof of a commit: write_state_checked records the snapshot comparison; environment_commit
requires a real state change. A write can be committed even when its response subsequently times
out. Final scoring independently checks state, matching content, duplicates and verification
call evidence. Fault fixtures can produce no state, duplicate state or conflicting content to
exercise unresolved reconciliation; such induced duplicates are distinguished from agent retries.

State probing runs in the handler's `finally` block so handler errors and cooperative cancellation
retain commit evidence. Unavailable unsafe writes are ambiguous; permanent errors with observed
mutation are ambiguous too. This diagnostic state never selects a recovery recipe or proves
success to an agent. Reconciliation must use the public lookup. The evaluator requires exactly
one matching stored record returned after the last write attempt; an earlier empty lookup cannot
verify a later create. Assertion details preserve sequence numbers and returned evidence.

Provider-envelope validation happens before tool execution. Invalid native-call structures,
duplicate IDs, missing choices/calls and unsupported finish reasons are provider protocol errors,
with available usage retained. A content-filter stop yields abstention. Malformed argument JSON
inside a valid call still goes to the executor as an agent-originated invalid call.

## Independent invoice evidence

Primary and finance-reference invoices live in different state fields/deep-copied arrays and
have separate tools/fault targets. Responses include source and authority. They do not merely
recalculate the same input. Agreement permits calculation; a vetted reference can resolve a
corrupted primary; peer disagreement or reference unavailability requires abstention. Resilient
middleware can perform the independent check and return the selected source with supporting
call IDs; the script/live model can also follow the public task instructions itself. The original
single-source failure is retained unchanged. Correlated corruption in both stores remains a
limitation, with an explicit test showing false completion rejected by the evaluator.

## Fault schedules and artifacts

One occurrence = one executor entry under the original tool name, including original invalid
attempts and middleware attempts. Invalid original calls count but cannot activate injection.
Transient rules target exactly the selected occurrence; persistent rules target it and later
occurrences. Probability draws use seeded per-rule RNGs; misses consume the eligible occurrence.
First activated matching rule wins per call. A scenario can have additional explicit rules.
Fault selection is not activation: post-execution and corruption faults activate only when those
points are actually reached. Diagnostics record planned/actual tool, occurrence, phase and change.
Run- and rule-level coverage remain separate from recovery denominators.

Experiment planning uses a recorded seeded shuffle of scenario/policy/repeat tuples. Fresh state
and conversation for every tuple; identical injection seed per paired repetition. Manifests retain
actual execution order. Previews are network-free and include budgets, pricing assumptions,
conditional ceilings and schedule. CLI live execution requires an explicit --allow-paid flag
as well as credentials. No paid requests have been made during Phase 2 development.

`smoke.py` wraps the existing three-run protocol with a sourced conditional cost check, model
metadata access preflight, zero SDK retries, and exclusive timestamped output creation. It does
not alter tasks or the fault schedule. Smoke suites stop at the first provider/harness failure
or unknown usage and record unstarted runs in the manifest. A conditional estimate is not a
provider billing cap; it reserves all permitted generation requests including a failed one.

Summaries keep artifact version and experiment kind separate. The dashboard loads the latest
manifest, supports filtering old/new data, shows fixed-scale separate metrics, highlights
fault/recovery lineage and expands raw events. Playback only reads saved data; it is not
re-execution. Credential redaction remains heuristic; use synthetic inputs and review before
sharing. No database, distributed coordinator, production integration or telemetry exporter.
