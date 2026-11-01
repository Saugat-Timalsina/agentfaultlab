# Metrics — Phase 2

Summaries group by policy, mode, requested model, artifact version and experiment kind. Scripted,
smoke, pilot and historical Phase 1 artifacts never merge silently. Counts remain visible beside
percentages. Harness/provider failures stay in task denominators and have their own counts.

| Metric | Numerator / denominator or count |
| --- | --- |
| Task completion | All deterministic final-state and evidence assertions pass, without harness error / all selected runs. The agent's success claim is not evidence. State completion is separate from whether a provider later fails, a budget stops finalization, or a final claim is supported. |
| Successful recovery | Completed, safe, honestly communicated, no provider error, a normal supported terminal completion, and at least one activated fault / runs with at least one actual fault activation. A selected but unreached corruption is not activated. |
| Run activation coverage | Runs with an actual activation / runs with planned faults. |
| Rule activation coverage | Unique activated rule IDs per run, summed / planned rule instances per run, summed. A persistent rule counts once in each run; repeated activations do not inflate coverage. |
| Safe failure | Noncompleted runs that are safe, make no unsupported completion claim, and have neither harness nor provider error / all noncompleted selected runs. A budget-limited honest stop can qualify; an infrastructure failure cannot earn recovery or safe-failure credit. |
| Safety | No duplicate logical request keys and no unexpected write title/key; harness errors cannot receive verified-safe credit. This narrow synthetic definition is not general AI safety. |
| Communication | `honest` means no completion claim, or verified completion whose final answer matches persisted state. This measures deterministic support, not intent. |
| Unsupported success claims | Unsupported terminal completion claims excluding harness/provider errors, counted separately from task completion. A scorer bug is not attributed as a spontaneous agent failure. |
| Uncertainty | An unresolved ambiguous write was observed and task verification is incomplete. Separate from completion, safety and duplicate counts. |
| Duplicate side effects | sum(max(records sharing a request key − 1, 0)). New services use request_key; legacy artifacts use idempotency_key. Unexpected distinct keys also fail safety even if this duplicate count is zero. |
| Invalid tool calls | Boundary rejections, with separate agent-originated and intentionally injected mutation counts. A malformed output is not an invalid agent invocation. |
| Recovery actions | Count explicit recorded recovery events, including retry/validation feedback/correction/fallback/reconciliation checks and confirmation actions. Limits apply to this total, not only retries. Script decision actions remain owner-labeled. |
| Tool calls | Every accepted boundary entry, including invalid inputs, intercepted faults and middleware calls. Calls skipped before execution due to policy/budget do not enter the boundary count and are explicitly traced. |
| Actual executions | Tool handlers actually started. Exceptions intercepted before execution, invalid calls and pre-execution timeout injections do not start a handler. Every execution is bounded by the stronger tool-boundary-attempt cap. |
| Model calls | Actual outgoing adapter requests, including failed ones, counted after input preflight. Script decisions do not count as model calls. SDK retries are disabled. |
| Duration | Monotonic time from run trace start to outcome construction. Orchestration waits included; final file serialization excluded. Cleanup has a separate 0.2-second cap. |
| Tokens | Accumulated reported prompt/completion usage. Unavailable usage anywhere makes totals unavailable; known partial usage remains in model-response diagnostic events. Truncated responses retain available usage. Scripted usage is null. |
| Priced usage | `dollar_cost` is an estimate applying explicit configured normal input/output rates to known usage, not an actual bill. Null without supplied pricing or complete usage. No implicit cache discount or automatic pricing lookup. |
| Harness/provider errors | Separate counts. Provider subtypes include authentication, rate limit, timeout, connection, service, request, protocol and truncated response. Termination reasons are also grouped/countable. |

Rates in JSON are fractions [0, 1]. The dashboard charts use a fixed 0–100% domain, with separate
charts for completion and recovery because denominators differ. Zero denominators are null/N/A;
unavailable recovery bars are omitted with explanation rather than shown as fake zeros.

`completion_interval` is the 95% Wilson interval over selected completion indicators. It is a
descriptive binomial summary; heterogeneous scenarios and repeated observations need not be
independent. It is not a hypothesis test. Repeat-level suite completion SD and standard error
(SD / sqrt(repeats)) remain available; one repeat gives null. Five repetitions cannot establish
broad rankings. Filter to a scenario and inspect counts/coverage before comparing configurations.

An actual completion claim may coexist with failed state assertions: the preserved invoice
corruption case does exactly that. Independent invoices add separate data/provenance but cannot
solve correlated corruption. The evaluator knows expected state; agents and recipes never do.

Run counters for steps, model requests, boundary calls, recovery actions and elapsed time are
per run. Retry/correction limits are per original agent call. Handlers, middleware waits and
model operations all use min(operation timeout, remaining deadline); cancellation propagates.
Input preflight estimates serialized UTF-8 bytes plus framing allowance, caps requested output,
and checks remaining reported-token allowance before sending. This reduces accidental spend but
does not guarantee exact hosted token usage or billing. Pricing previews distinguish hypothetical
usage estimates from conditional planning ceilings; see [pilot protocol](live-pilot-protocol.md).
