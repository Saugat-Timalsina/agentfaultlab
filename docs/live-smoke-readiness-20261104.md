# Three-run live smoke readiness — 2026-11-04

**Not executed: credentials unavailable.** `OPENAI_API_KEY` was absent from the process
environment; no project `.env` exists. Values were never printed. No model access/metadata or
generation requests were made. There are no actual live traces to assess. The live path remains
unverified against the provider; the pilot must wait for smoke execution and trace review.

## Hardening and local preparation

Finished the missing [hardening verification record](phase2-verification-20261104.md) and saved
local commit `2f056d1`. Existing examples and results were preserved. The standalone dashboard
started at localhost:8517; health returned `ok`, homepage HTTP 200; the server was then stopped.

Found one further preparation defect: the suite runner continued after a provider/harness
failure. Smoke suites now stop after the first infrastructure failure or missing usage, save
partial reports, and record planned versus actual order and unstarted runs. No automatic reruns.
The new `agentfaultlab smoke` launcher reuses `configs/phase2/smoke-v1.yaml`, changes only the
output directory to a fresh UTC timestamp, and refuses a conditional ceiling above the allowance.
Existing `run --config ...smoke... --allow-paid` also uses these launch guards.

Before generation the launcher checks model access with `models.retrieve`, using a timeout and
zero SDK retries. Authentication/access failure stops before generation, saving a sanitized
preflight receipt. Model metadata access does not prove every request setting is supported;
a rejected setting in generation stops the suite. Endpoint overrides are refused because they
would invalidate the configured provider/pricing assumptions. Existing run/request/token/tool/
recovery/deadline limits remain enforced at their shared boundaries. No model substitution,
prompt change, paid repair run or pilot was introduced.

## Prepared scope and pricing

Provider/model: OpenAI `gpt-5.6-terra`, reasoning effort `none`, resilient middleware only.
The existing shuffle seed 20261101 gives this order:

| Run | Scenario | Live completion | Live fault activation | Provider tokens |
| --- | --- | --- | --- | --- |
| 1 | lookup-exception | Not run | Not observed | Unavailable; no request |
| 2 | lookup-control | Not run | Not applicable; control | Unavailable; no request |
| 3 | correlation-write-lost-response | Not run | Not observed | Unavailable; no request |

All runs reset environment and conversation. Per run: 12 decisions, 8 model requests, 20 tool
boundary calls, 10 recovery actions, 24,000 reported tokens, 90 seconds orchestration. Per
request: input estimate at most 12,000, output at most 768, timeout 25 seconds. Per tool:
0.05 seconds clamped to remaining run time. Per original call: at most 2 retries and 1 correction.

Official [model capabilities/pricing](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
and [model retrieval API](https://developers.openai.com/api/reference/resources/models/methods/retrieve)
were checked on 2026-11-04. The published model supports Chat Completions, function calling,
structured outputs and reasoning effort `none`. Published normal input/output prices remain
**$2/$12 per million tokens**, with **1.25× input rate for cache writes**. The original dated
pricing configuration is preserved; this document records the recheck. Account availability
cannot be established without credentials; the official page lists no free-tier support.

The typical assumption of 4 requests/run × (1,500 input + 256 output) gives **$0.072864**.
The conservative conditional estimate reserves all 24 requests at 12,000 input and 768 output:

`24 × (12,000 × $2 × 1.25 + 768 × $12) / 1,000,000 = $0.941184`.

This fits the authorized $1 allowance with $0.058816 headroom. It is a reasonable planning
bound under the recorded prices and input/output assumptions, **not an enforced provider
billing cap**. Input estimation uses serialized UTF-8 bytes plus 512 for framing; it is not
exact provider tokenization. Unknown usage on failed requests may still be billable; the
request reservation covers the attempted request and the suite then stops. SDK retries are
disabled. Reported usage and priced usage must be compared with actual billing. Metadata
preflight makes no generation request. No requests were made here, no provider usage was
reported, and there are no failed-request costs to reconcile from this session.

## Local setup and the single authorized launch

In the same local zsh terminal, enter the API key privately; do not paste it into chat or files:

```sh
cd ~/Desktop/AgentFaultLab
source .venv/bin/activate
read -s "OPENAI_API_KEY?OpenAI API key: "
export OPENAI_API_KEY
printf '\n'
agentfaultlab smoke --dry-run --spending-allowance 1
agentfaultlab smoke --allow-paid --spending-allowance 1
```

Execute the paid command **once**. It prints and saves the new timestamped directory; do not
repeat it after an infrastructure failure. This uses the existing smoke YAML and performs no
pilot runs. If an unexpected endpoint override is configured, review and remove it locally
before launch. The key is read by the SDK and is excluded from configuration/artifacts/Git.
The user's three-run authorization does not authorize a second smoke attempt or the pilot.

After execution, use the printed directory in the dashboard (`streamlit run app.py`). Review
each native call/result ID and response-array ordering; use transcript `sent_message_counts`
to distinguish tool replies actually sent to the provider from replies merely prepared after
the last request. Confirm middleware lineage/supporting IDs, no hidden evaluator/fault data in
messages, actual usage, final assertions, and planned versus activated faults. No such live
inspection is claimed yet. Three runs validate integration only, never reliability rankings.

## Actual offline verification for the launch guard

- `.venv/bin/pytest -q`: 119 passed, 1 live test deselected on the final guard check.
- `.venv/bin/ruff check .`: passed; `.venv/bin/ruff format --check .`: passed (43 Python files).
- `.venv/bin/python -m pip check`: no broken requirements; existing home-cache warning only.
- `.venv/bin/agentfaultlab smoke --dry-run`: three prepared runs, $0.072864 estimate,
  $0.941184 conditional ceiling, fresh timestamped path, no network.
- New controlled tests verify scope/allowance rejection, missing credentials before requests,
  model metadata success/authentication/access failure with no retries or secret persistence,
  and suite stopping on authentication/request/protocol/harness/unknown-usage failures.

## Available dashboard walkthrough (scripted evidence only)

Run `streamlit run app.py`; set Results directory to `docs/examples-phase2`, select the
correlation-write-lost-response scenario and saved run ending `61e87db69f`.
Sequence 5 is the **scripted agent's** create request; 8 verifies state change; 9 activates
the lost-response injection; 10 observes timeout. Sequences 11–14 are deterministic
**middleware** reconciliation and its public lookup. Sequence 15 returns a synthesized result
linked to those calls. Sequence 19 is the script's own verification; 23 contains final
assertions. In the pending live smoke, native requests should carry owner `model`; middleware
actions must retain owner `middleware`. No action in this saved scripted trace came from an LLM.
