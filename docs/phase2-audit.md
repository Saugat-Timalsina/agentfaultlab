# Phase 2 audit — phase2-v1

Audited the executor, policies, runner, scoring, live adapter and dashboard from local commit
`367d653` before implementing these changes. No applicable AGENTS.md exists in this repository
or its ancestor directories. Existing source, tests and saved Phase 1 artifacts were preserved.

| Concern | Finding in Phase 1 | Phase 2 response |
| --- | --- | --- |
| Run deadline misses recovery | **Already covered in runner:** its outer asyncio deadline surrounded retries, correction, fallback and reconciliation. It was inaccurate to claim every runner recovery path could overrun simply because it lacked a local check. **Gap:** direct executor/policy use did not share that protection. | `RunBudget` is shared by runner, executor and recovery. All awaited operations use remaining allowance; outer run timeout remains defense in depth. |
| Tool timeout can exceed remaining time | **Confirmed local-boundary gap.** Executor passed the full configured tool timeout to wait_for. The outer runner normally cancelled it sooner. | Every tool wait uses min(tool timeout, remaining run time). Deadline exhaustion raises a named budget termination; cancellation is not converted into a transient tool error. |
| Recovery budgets | **Partly already handled:** every runner middleware tool call used the counted invoke wrapper, and retries/corrections were locally capped. **Limitation:** recovery actions had no shared count and direct use bypassed global limits. | Shared run counters cover steps, actual model requests, boundary attempts, handler executions and recovery actions. Per-original-call retry/correction caps remain. |
| Recovery loses provenance | **Confirmed defect.** Retry/fallback results were rewritten to original IDs/names; reconciliation synthesized success without an explicit returned-result event. Actual child calls appeared individually but lacked lineage. | Root/parent IDs, attempt number and execution owner; `middleware_result` records synthesis, reason and supporting call IDs. Native IDs remain unchanged in the model transcript. |
| Commit inferred from handler return | **Confirmed defect.** `environment_commit` was emitted after return regardless of actual store mutation. | Fake write tools expose a diagnostic-only state probe. Before/after state is compared, `write_state_checked` records evidence, and `environment_commit` requires an actual change. A no-op handler produces no commit event. |
| Hard-coded domain recovery | **Confirmed extensibility limitation.** Policies branched on lookup/create tool names and public bindings. They did not use evaluator truth. | Small explicit `Recipe` registry holds correction fields, fallback targets, reconciliation contracts and independent-source checks. Policy scheduling/budgets are generic; registry tests exercise a renamed tool. |
| Misnamed idempotency key | **Confirmed terminology problem.** A field called idempotency_key could be used against a service that did not enforce it. | Explicit `correlation` and `idempotent` service tools use neutral `request_key`. The first permits duplicates; the second deduplicates equivalent requests and rejects conflicting content. Legacy names remain for compatibility and are labeled historical. |
| Chart truncation | **Confirmed missing guarantee**, not a reproduced pixel-level defect: st.bar_chart supplied no fixed percentage domain. No original screenshot was available to establish exactly which bars appeared clipped. | Two separate Altair charts, each with an explicit 0–100% domain, readable configuration labels and no stacking. Tests inspect the serialized chart scale. No bar is fabricated for an unavailable recovery denominator. |
| Pilot fairness | **Confirmed confound.** Live system prompt named the current policy and singled out resilient behavior. | Identical live system/task/tool payloads across policies; controlled HTTP test compares initial requests exactly. Only middleware changes. Historical scripted lookup behavior remains a declared fixture strategy. |
| Multiple native calls | **Adapter already parsed multiple calls. Runner gap:** early termination could leave later calls silently unprocessed. | Execute sequentially in returned array order. If policy/budget stops the batch, each remaining call gets an explicit skipped result and trace event; no next model request is made with unanswered IDs. |
| Truncation | **Confirmed defect.** Calls were handled before the finish-reason length check. | Reject all truncated responses before executing partial tool calls; retain available usage and classify provider truncation separately. |
| Provider vs harness attribution | **Confirmed weakness.** Broad adapter exception handling could turn programming bugs into provider failures. | Catch expected SDK API errors and assign authentication/rate-limit/timeout/connection/service subtypes. Unexpected Python errors reach the harness boundary. |
| Independent evidence | **Known limitation**, not a schema validator bug: old invoice data corruption passed arithmetic checks against the same bad data. | Preserve that failure case; add separately stored, separately targeted invoice sources with provenance, declared authority and supported abstention on unresolved disagreement. |

## Explicit boundaries

No recipe receives scenario IDs, hidden faults, expected state or environment state. Public
bindings are task inputs only. Store snapshots and injector metadata exist only in diagnostic
traces. A separate `.transcript.json` records model-visible messages (or scripted observable
history). The final diagnostic event includes state assertions, as intended for local evaluation.

No ambiguous write is automatically repeated, including the idempotent variant. The declared
policy is conservative: one matching verified record resolves success; zero, multiple,
conflicting or unavailable records leave the outcome uncertain. This is a choice rather than
an unimplemented implicit retry promise.

The deadline covers agent/tool/recovery work, not final scoring/serialization. Client close is
separately capped at 0.2 seconds. Python cancellation is cooperative; hostile blocking handlers
still need process isolation. Source authority is a synthetic declared contract, not cryptographic
provenance. Correlated source corruption remains undetectable by agreement alone.

## API/documentation review

Checked official [Chat Completions request/finish semantics](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
and [GPT-5.6 Terra capabilities and pricing](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
on 2026-11-01. The prepared model supports Chat Completions, function calls, structured outputs
and reasoning effort `none`. Configured pricing is an explicit dated assumption, not an
unsourced promise of future rates or account availability. SDK automatic retries are disabled.

Observed checks and actual commands are recorded in [Phase 2 verification](phase2-verification.md).
No paid requests or live results were produced.

## Follow-up audit — 2026-11-04

The repository already contained Phase 2 at `1b7e26a` when this request was received.
Inspected executor, budgets, policies/recipes, runner, live adapter, scoring/reporting and
dashboard before changing behavior. The baseline passed 96 offline tests (one live test
deselected). Existing Phase 1 and Phase 2 artifacts were retained.

Confirmed additional defects and fixes:

- **Handler interruption lost commit evidence.** The state probe ran only after normal handler
  return. It now runs in a handler `finally` block, including service exceptions, timeout and
  cancellation. Snapshots are copied to avoid mutable aliases. Unexpected Python exceptions
  still propagate as harness defects; diagnostic state is never returned to the model.
- **Write service errors could hide ambiguity.** A transient unavailable response on an unsafe
  write now explicitly carries ambiguity. A permanent service error after a verified mutation
  is also ambiguous. This invokes the declared reconciliation recipe without repeating the write.
  An idempotency conflict with no mutation remains a permanent nonambiguous error.
- **Verification scoring accepted any successful lookup.** Even an empty lookup before a later
  create could satisfy the evidence assertion. Completion now requires one matching record
  observed after the last write attempt, identical to a stored record. Failed assertion details
  include write/result sequence numbers and returned records.
- **Invalid response envelopes lost usage or looked like harness defects.** Empty choices and
  duplicate IDs now retain reported usage. Unsupported custom calls, missing function envelopes,
  missing calls and unsupported finish reasons terminate as provider protocol failures before
  any tool execution. Content-filtered responses abstain without executing partial calls.
  Arbitrary adapter programming errors remain harness failures.
- **Dashboard summaries could disagree or overwrite groups.** The headline now uses the same
  unsupported-claim exclusion rules as the report. Termination summaries retain every complete
  configuration identity instead of overwriting configurations sharing a policy/kind label.

Rechecked the official [request API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
and [configured model page](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
on 2026-11-04. The published $2 input / $12 output per million and 1.25× cache-write
assumptions still match the dated configurations; their original retrieval dates remain intact.
No live requests or account-access verification were performed.

The original deadline concerns remain qualified as above: the runner already had an outer
deadline, and final evaluator/export work still lies outside orchestration. Shared attempts bound
actual executions without a separate handler cap. Cooperative cancellation, synthetic authority,
correlated corruption and approximate billing remain limitations, not newly fixed defects.
The new recheck configuration uses protocol `phase2-hardening-v1` and a fresh output directory;
the serialized artifact schema remains backward-compatible `phase2-v1`.

## Smoke execution preparation — 2026-11-04

**Confirmed defect:** `run_experiment` retained a provider/harness failure but proceeded to the
next scheduled run. For the authorized smoke test this could repeatedly spend on a broken
configuration. Smoke suites now stop on the first provider/harness failure or unknown usage;
partial manifests separate actual order from planned order and count unstarted runs. The
three-run launcher reuses the original config, guards a conditional estimate within the $1
allowance, checks model access with retries disabled, and requires a new timestamped directory.
The existing smoke `run` path also uses these guards. This does not authorize repeated attempts.

The missing-key path, model metadata auth/access failures, scope/cost guards and suite stopping
were tested offline. Final checks: 119 tests passed, one live test deselected; lint, format and
dependency checks passed. See the [readiness report](live-smoke-readiness-20261104.md). Credentials
were absent, so no account model-access check, paid request, live trace review or live smoke
result is claimed. Pilot execution remains unauthorized.
