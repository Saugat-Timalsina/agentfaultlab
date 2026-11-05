# Live-agent pilot protocol — phase2-v1

Prepared before producing any live results. The experiment compares **agent-plus-middleware
configurations**, not pure model intelligence. No live execution is authorized by preparing it.

## Fixed configuration and eligibility

- Provider/model: OpenAI `gpt-5.6-terra`, reasoning effort `none`, native strict function calls
  and a strict structured final response. The provider-returned model name is logged as well.
  This alias is not a promise of immutable hosted weights or account access.
- Same task, tool schemas, system instruction, output settings and per-run budgets for every
  policy within a scenario. The live prompt never names the policy. An offline HTTP test verifies
  byte-equivalent initial request payloads across policies. Subsequent observations naturally differ.
- Fail fast stops on a tool error; bounded retry retries only explicitly transient retry-safe
  operations; resilient adds explicit bounded recipes. All actions are attributed to model or middleware.
- Fresh deep-copied state and a fresh model conversation/client per run. No session or tool state
  carries across policies/repetitions. Multiple native calls execute sequentially in returned order.
- `seed + repeat` fixes injection draws. Global seed 20261101 shuffles the complete schedule,
  which is included in dry-run previews and the final manifest. Hosted inference is not deterministic.
- A fault is eligible only after original call validation and at its targeted occurrence. Unknown
  tools/malformed arguments from the model count as agent-originated invalid attempts. Intentionally
  mutated calls count separately as injected invalid calls. The pilot does not inject call mutations.
- An unreached injection point is incomplete coverage, not recovery. Report both activated runs /
  faulted runs and activated rule-instances / planned rule-instances.

## Stage A: three-run smoke test

`configs/phase2/smoke-v1.yaml`: one resilient run each of fault-free lookup, transient lookup
exception, and correlation-service committed write with lost response. This checks tool calling,
call/result ordering, traces, resets, usage accounting and the write-reconciliation boundary.
It is not used to rank policies. The guarded launcher uses a fresh UTC timestamp appended to
`results/live-smoke-v1`, preserving prior attempts and the original configuration.

Smoke acceptance: no harness or provider errors, meaningful native calls, serializable
transcripts/traces, usage present on successful responses, fault activation recorded, and no
unexplained duplicate side effect. A model may still fail the task: report that rather than
silently rerun it. Inspect all three runs before separately authorizing the pilot. If setup fails,
retain artifacts and use a newly labeled configuration/directory for a revised smoke test.

## Stage B: pilot, at most 60 runs

`configs/phase2/pilot-v1.yaml`: four scenarios × three policies × five repetitions = 60.

| Scenario | Predeclared expectation |
| --- | --- |
| lookup-control | Cross-check capacity and persist the correct value. All configurations should have the tools needed; actual results remain unmeasured. |
| lookup-exception | Primary read fails transiently at occurrence 1. Middleware can retry safely or use the public secondary. Count recovery only on actual activation. |
| correlation-write-lost-response | Write really commits but the response times out. Never blindly repeat the write. Resilient middleware can verify one matching record; any other configuration must verify through its own allowed behavior or remain incomplete. |
| calculation-incorrect-data | Plausible schema-valid primary input corruption. Preserve the historical failure case: arithmetic agreement alone does not establish correct source data. A success claim can be unsupported. |

The new independent-invoice scenarios are a separate offline extension, not silently substituted
for the pilot's original corruption case. Their predeclared expectations are: agreement completes;
primary corruption can be resolved by a separately stored vetted reference; unavailable reference
or disagreement between peers leads to supported abstention and incomplete task. Agreement of two
correlated bad sources can still produce a wrong answer.

Pilot output: `results/live-pilot-v1`. Do not pool with smoke or scripted data. No success-based
resampling or hidden prompt tuning. Keep every scheduled failure. Provider outages, harness bugs,
budget terminations, invalid model calls and injected tool faults remain separate. If an outage
prevents the planned experiment, report the partial run set and create a new protocol revision
for any rerun. Reuse of a result directory retains old files but changes its latest manifest, so
use a new output directory for a new study.

## Metrics and analysis

Report counts and percentages for completed/total, recovered/activated runs, activation coverage,
safe failures/all failed, unsupported success claims, duplicates, uncertainty, provider/harness
errors, model/tool/handler calls, recovery actions, tokens, durations and stop reasons. Use
[metrics definitions](metrics.md). Save per-scenario and per-policy results, not just pooled rates.
The dashboard can select one scenario for a fair paired comparison and separate controls.

Wilson completion intervals are descriptive binomial summaries, not evidence that heterogeneous
runs are independent. Repeat-level suite SD/SE is also reported. With five repetitions, avoid
strong rankings, p-value fishing and broad robustness claims. Discuss shared-task dependence and
activation differences. No outcome-independent global score is used.

## Limits and costs

Per run: 12 decisions, 8 model requests, 20 boundary calls, 10 recovery actions; 2 retries and
1 correction per original call; 90 seconds total orchestration, 25 seconds per model request,
0.05 seconds per tool (each clamped to remaining time); 24,000 reported total tokens;
12,000-token input-estimate cap per request; at most 768 output tokens per request.
The input estimate is UTF-8 serialized request bytes plus 512 for framing, not exact tokenization.

Pricing assumptions retrieved 2026-11-01 from the
[official model page](https://developers.openai.com/api/docs/models/gpt-5.6-terra): $2 per million
uncached input tokens and $12 per million output tokens; cached input discounts are ignored.
The conditional ceiling also allows a 1.25× input cache-write multiplier stated on that page.
The small request cap stays well below the documented long-context premium threshold under
these assumptions. These are estimates, not a guarantee of provider accounting or future rates.

Typical planning assumption: 4 requests/run, each 1,500 input and 256 output tokens.
Smoke: **$0.072864 estimated**, **$0.941184 conditional planning ceiling**.
Pilot: **$1.45728 estimated**, **$18.82368 conditional planning ceiling**.
The ceiling multiplies all allowed requests by the input-estimate and output caps; it does not
assume the total token budget is an exact billing cap. Source/cache accounting, unseen usage on
failed requests and tokenizer framing can differ. Report priced usage as an estimate; consult
the provider bill for actual charges. Exact preview artifacts are committed alongside this protocol.

## Concrete execution boundary

Preview requires no key and makes no provider requests:

```sh
source .venv/bin/activate
agentfaultlab run --config configs/phase2/smoke-v1.yaml --dry-run
agentfaultlab smoke --dry-run --spending-allowance 1
agentfaultlab run --config configs/phase2/pilot-v1.yaml --dry-run
```

After reviewing this protocol and supplying the key privately in your environment, this exact
command explicitly authorizes the three smoke runs:

```sh
agentfaultlab smoke --allow-paid --spending-allowance 1
```

Do not run the pilot automatically. Its separate command, after smoke review and authorization:

```sh
agentfaultlab run --config configs/phase2/pilot-v1.yaml --allow-paid
```

No command above has been used here to make paid requests. Offline adapter tests use a controlled
HTTP transport and placeholder credentials. Neither previews nor stored configuration contain keys.

## Readiness recheck — 2026-11-04

No live results have been produced. The model, prompts, schedule, budgets, prices and output
directories above remain the prepared v1 protocol. Official request/model documentation was
rechecked on this date; the configured dated pricing assumptions still match the published page.
The [follow-up audit](phase2-audit.md#follow-up-audit--2026-11-04) strengthens evidence assertions
and provider-protocol handling before any paid execution. The separate offline recheck uses
`configs/phase2/offline-hardening-v1.yaml`; it is excluded from smoke/pilot results. See
[actual verification](phase2-verification-20261104.md) for readiness checks and preview values.

The user subsequently authorized only one three-run smoke attempt within $1. Credentials were
unavailable, so no provider calls were made. The [smoke readiness report](live-smoke-readiness-20261104.md)
records current pricing, setup instructions, remaining checks and an explicitly scripted trace
walkthrough. Smoke execution now stops on provider/harness failures or unavailable usage and
records unstarted runs. The 60-run pilot remains unauthorized and must wait for smoke review.
