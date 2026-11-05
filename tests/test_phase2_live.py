import asyncio
import json
from types import SimpleNamespace

import pytest
from test_live import client_for, completion, context, httpx

from agentfaultlab.errors import ProviderFailure
from agentfaultlab.live import OpenAIAgent
from agentfaultlab.runner import run_one
from agentfaultlab.scenarios import scenario_catalog
from agentfaultlab.schemas import ExperimentConfig
from agentfaultlab.tools import Environment
from agentfaultlab.tracing import load_trace


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "authentication"),
        (403, "authentication"),
        (429, "rate_limit"),
        (500, "service"),
        (503, "service"),
    ],
)
async def test_provider_errors_are_distinct_and_not_retried(tmp_path, status, code):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(
            status, json={"error": {"message": "do not persist headers or secrets"}}
        )

    agent = OpenAIAgent("mock", client_for(handler))
    result = await run_one(
        scenario_catalog()["lookup-control"],
        "resilient",
        ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path)),
        agent=agent,
    )
    assert result.provider_error == code and result.harness_error is None
    assert result.tool_calls == 0 and result.fault_activations == 0
    assert result.model_calls == 1 and len(requests) == 1
    assert not result.recovered and not result.safe_failure


@pytest.mark.parametrize("kind,code", [("timeout", "timeout"), ("connection", "connection")])
async def test_provider_transport_failures(tmp_path, kind, code):
    def handler(request):
        if kind == "timeout":
            raise httpx.ReadTimeout("mock timeout", request=request)
        raise httpx.ConnectError("mock disconnected", request=request)

    agent = OpenAIAgent("mock", client_for(handler))
    config = ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path))
    result = await run_one(scenario_catalog()["lookup-control"], "resilient", config, agent=agent)
    assert result.provider_error == code and result.model_calls == 1


def native_call(name="lookup_primary", args='{"key":"capacity"}', call_id="a"):
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


@pytest.mark.parametrize(
    "defect",
    [
        "empty_choices",
        "duplicate_ids",
        "custom_call",
        "missing_function",
        "missing_calls",
        "finish_reason",
    ],
)
async def test_invalid_provider_envelope_keeps_usage_and_does_not_execute(tmp_path, defect):
    def handler(request):
        response = completion({"role": "assistant", "content": None, "tool_calls": [native_call()]})
        choice = response["choices"][0]
        if defect == "empty_choices":
            response["choices"] = []
        elif defect == "duplicate_ids":
            choice["message"]["tool_calls"].append(native_call())
        elif defect == "custom_call":
            choice["message"]["tool_calls"] = [
                {"id": "custom", "type": "custom", "custom": {"name": "unsupported", "input": "x"}}
            ]
        elif defect == "missing_function":
            choice["message"]["tool_calls"][0].pop("function")
        elif defect == "missing_calls":
            choice["finish_reason"] = "tool_calls"
            choice["message"]["tool_calls"] = []
        else:
            choice["finish_reason"] = "function_call"  # Unsupported legacy protocol.
        return httpx.Response(200, json=response)

    result = await run_one(
        scenario_catalog()["lookup-control"],
        "resilient",
        ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path)),
        agent=OpenAIAgent("mock", client_for(handler)),
    )
    assert result.provider_error == "protocol" and result.harness_error is None
    assert result.input_tokens == 100 and result.output_tokens == 10
    assert result.tool_calls == 0 and not result.recovered and not result.safe_failure


async def test_content_filtered_response_abstains_without_executing_calls(tmp_path):
    def handler(request):
        response = completion({"role": "assistant", "content": None, "tool_calls": [native_call()]})
        response["choices"][0]["finish_reason"] = "content_filter"
        return httpx.Response(200, json=response)

    result = await run_one(
        scenario_catalog()["lookup-control"],
        "resilient",
        ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path)),
        agent=OpenAIAgent("mock", client_for(handler)),
    )
    assert result.final_status == "abstain" and result.honest
    assert result.tool_calls == 0 and result.input_tokens == 100
    assert result.harness_error is None and result.provider_error is None


async def test_truncated_native_calls_never_execute_and_usage_is_kept(tmp_path):
    def handler(request):
        response = completion({"role": "assistant", "content": None, "tool_calls": [native_call()]})
        response["choices"][0]["finish_reason"] = "length"
        return httpx.Response(200, json=response)

    config = ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path))
    result = await run_one(
        scenario_catalog()["lookup-control"],
        "resilient",
        config,
        agent=OpenAIAgent("mock", client_for(handler)),
    )
    assert result.provider_error == "truncated" and result.tool_calls == 0
    assert result.input_tokens == 100 and result.output_tokens == 10


@pytest.mark.parametrize(
    "content,expected",
    [
        ('{"status":"abstain","answer":null,"summary":"Insufficient evidence"}', None),
        ('{"status":"complete","answer":42,"summary":"Unsupported success"}', None),
        ("not valid final JSON", "protocol"),
    ],
)
async def test_no_tool_calls_final_response(tmp_path, content, expected):
    def handler(request):
        return httpx.Response(200, json=completion({"role": "assistant", "content": content}))

    result = await run_one(
        scenario_catalog()["lookup-control"],
        "resilient",
        ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path)),
        agent=OpenAIAgent("mock", client_for(handler)),
    )
    assert result.provider_error == expected and not result.completed
    if "Unsupported" in content:
        assert not result.honest


async def test_multiple_native_calls_executed_sequentially_with_complete_transcript(tmp_path):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if len(seen) == 1:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    native_call(call_id="first"),
                    native_call("lookup_secondary", call_id="second"),
                ],
            }
        elif len(seen) == 2:
            assert [m["tool_call_id"] for m in body["messages"] if m["role"] == "tool"] == [
                "first",
                "second",
            ]
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [native_call("submit_answer", '{"answer":42}', "submit")],
            }
        else:
            message = {
                "role": "assistant",
                "content": json.dumps(
                    {
                        "status": "complete",
                        "answer": 42,
                        "summary": "Value cross-checked and persisted.",
                    }
                ),
            }
        return httpx.Response(200, json=completion(message))

    config = ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path))
    config.budgets.max_tokens = 20000
    result = await run_one(
        scenario_catalog()["lookup-control"],
        "resilient",
        config,
        agent=OpenAIAgent("mock", client_for(handler)),
    )
    assert result.completed and result.model_calls == 3 and result.tool_calls == 3
    events = load_trace(tmp_path / result.trace_file)
    calls = [e for e in events if e.event_type == "tool_call"]
    assert [e.call_id for e in calls] == ["first", "second", "submit"]
    assert all(e.owner == "model" for e in calls)
    assert [e.payload["message_count"] for e in events if e.event_type == "model_request"] == [
        2,
        5,
        7,
    ]
    assert all("scenario_id" not in json.dumps(request) for request in seen)
    assert all("expected_state" not in json.dumps(request) for request in seen)


async def test_unknown_tool_in_batch_is_not_counted_as_injected_and_remaining_call_is_explicit(
    tmp_path,
):
    def handler(request):
        return httpx.Response(
            200,
            json=completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        native_call("unknown_tool", "{}", "bad"),
                        native_call(call_id="not-executed"),
                    ],
                }
            ),
        )

    agent = OpenAIAgent("mock", client_for(handler))
    config = ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path))
    result = await run_one(scenario_catalog()["lookup-control"], "fail_fast", config, agent=agent)
    assert result.agent_invalid_calls == 1 and result.injected_invalid_calls == 0
    assert result.tool_calls == 1 and not agent.pending
    events = load_trace(tmp_path / result.trace_file)
    assert any(e.event_type == "tool_call_skipped" and e.call_id == "not-executed" for e in events)
    ids = [m["tool_call_id"] for m in agent.messages if m["role"] == "tool"]
    assert ids == ["bad", "not-executed"]


async def test_identical_initial_model_payload_across_policies():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=completion(
                {
                    "role": "assistant",
                    "content": '{"status":"abstain","answer":null,"summary":"Not enough evidence"}',
                }
            ),
        )

    for policy in ["fail_fast", "bounded_retry", "resilient"]:
        ctx = context()
        ctx.policy = policy
        agent = OpenAIAgent("mock", client_for(handler))
        await agent.decide(ctx)
        await agent.close()
    assert bodies[0] == bodies[1] == bodies[2]
    assert "resilient" not in json.dumps(bodies)


async def test_preflight_stops_before_any_model_request(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        raise AssertionError("Preflight must block network")

    config = ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path))
    config.budgets.max_input_estimate = 1
    result = await run_one(
        scenario_catalog()["lookup-control"],
        "resilient",
        config,
        agent=OpenAIAgent("mock", client_for(handler)),
    )
    assert result.stop_reason == "max_input_estimate"
    assert result.model_calls == 0 and not seen


async def test_injected_sdk_client_also_disables_automatic_retries():
    def handler(request):
        return httpx.Response(429, json={"error": {"message": "controlled rate limit"}})

    client = client_for(handler)
    client.max_retries = 2
    agent = OpenAIAgent("mock", client)
    assert agent.client.max_retries == 0
    with pytest.raises(ProviderFailure):
        await agent.decide(context())
    await agent.close()


async def test_deadline_during_model_batch_drains_all_native_ids(tmp_path):
    def handler(request):
        return httpx.Response(
            200,
            json=completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        native_call(call_id="slow"),
                        native_call("lookup_secondary", call_id="unstarted"),
                    ],
                }
            ),
        )

    scenario = scenario_catalog()["lookup-control"]
    env = Environment(scenario.initial_state)
    tools = env.registry()

    async def slow(key):
        await asyncio.sleep(10)

    tools["lookup_primary"].handler = slow
    env.registry = lambda: tools
    agent = OpenAIAgent("mock", client_for(handler))
    config = ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path))
    config.budgets.elapsed_s = 0.04
    config.budgets.tool_timeout_s = 10
    result = await run_one(scenario, "resilient", config, agent=agent, environment=env)
    assert result.stop_reason == "elapsed_s" and not agent.pending
    assert result.tool_calls == 1
    events = load_trace(tmp_path / result.trace_file)
    assert any(e.event_type == "tool_call_skipped" and e.call_id == "unstarted" for e in events)
    assert [m["tool_call_id"] for m in agent.messages if m["role"] == "tool"] == [
        "slow",
        "unstarted",
    ]


async def test_unexpected_adapter_bug_is_harness_error(tmp_path):
    async def broken(**kwargs):
        raise TypeError("programming error in adapter boundary")

    async def close():
        pass

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=broken)), close=close
    )
    config = ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path))
    result = await run_one(
        scenario_catalog()["lookup-control"], "resilient", config, agent=OpenAIAgent("mock", client)
    )
    assert result.harness_error.startswith("TypeError") and result.provider_error is None
    assert not result.recovered
