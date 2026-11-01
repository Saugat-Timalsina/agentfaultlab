"""Real SDK with mocked HTTP transport; default tests never contact a provider."""

import importlib
import json
import os

import pytest

openai = pytest.importorskip("openai")
try:
    httpx = importlib.import_module("httpx2")  # OpenAI Python v3
except ImportError:
    httpx = importlib.import_module("httpx")  # OpenAI Python v2

from agentfaultlab.agents import AgentContext  # noqa: E402
from agentfaultlab.live import OpenAIAgent  # noqa: E402
from agentfaultlab.runner import ProviderFailure, run_one  # noqa: E402
from agentfaultlab.scenarios import scenario_catalog  # noqa: E402
from agentfaultlab.schemas import ExperimentConfig, ToolCall, ToolResult  # noqa: E402
from agentfaultlab.tools import Environment  # noqa: E402


def completion(message, usage=True):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "mock",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
        if usage
        else None,
    }


def context():
    scenario = scenario_catalog()["lookup-control"]
    tools = Environment(scenario.initial_state).registry()
    return AgentContext(
        task=scenario.task,
        family=scenario.family,
        bindings=scenario.bindings,
        tools=[tools[n].definition for n in scenario.available_tools],
        observations=[],
        policy="resilient",
        remaining_tokens=1000,
    )


def client_for(handler):
    return openai.AsyncOpenAI(
        api_key="test-placeholder",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_sdk_native_calls_ids_ordering_and_usage():
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json=completion(
                    {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "provider-call-123",
                                "type": "function",
                                "function": {
                                    "name": "lookup_primary",
                                    "arguments": '{"key":"capacity"}',
                                },
                            }
                        ],
                    }
                ),
            )
        assert [m["role"] for m in body["messages"]] == ["system", "user", "assistant", "tool"]
        assert body["messages"][-1]["tool_call_id"] == "provider-call-123"
        assert "fault" not in body["messages"][-1]["content"]
        return httpx.Response(
            200,
            json=completion(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {"status": "abstain", "answer": None, "summary": "Not enough evidence yet."}
                    ),
                }
            ),
        )

    agent = OpenAIAgent("mock-model", client_for(handler))
    first = await agent.decide(context())
    assert first.calls[0].id == "provider-call-123"
    assert first.input_tokens == 100 and first.output_tokens == 10
    with pytest.raises(ProviderFailure, match="all tool IDs"):
        await agent.decide(context())
    agent.observe(
        first.calls[0],
        ToolResult(
            call_id=first.calls[0].id,
            name="lookup_primary",
            data={"value": 42, "source": "primary"},
        ),
    )
    final = await agent.decide(context())
    assert final.status == "abstain"
    assert requests[0]["tools"][0]["function"]["strict"] is True
    assert requests[0]["parallel_tool_calls"] is False
    assert requests[0]["max_completion_tokens"] == 1000
    await agent.close()


async def test_multiple_calls_all_get_replies_before_next_request():
    def handler(request):
        return httpx.Response(
            200,
            json=completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": f"call-{i}",
                            "type": "function",
                            "function": {"name": "lookup_primary", "arguments": "{}"},
                        }
                        for i in range(2)
                    ],
                }
            ),
        )

    agent = OpenAIAgent("mock", client_for(handler))
    decision = await agent.decide(context())
    agent.observe(decision.calls[0], ToolResult(call_id="call-0", name="lookup_primary", data={}))
    with pytest.raises(ProviderFailure):
        await agent.decide(context())
    agent.observe(decision.calls[1], ToolResult(call_id="call-1", name="lookup_primary", data={}))
    assert not agent.pending
    assert [m["tool_call_id"] for m in agent.messages[-2:]] == ["call-0", "call-1"]
    await agent.close()


async def test_malformed_native_arguments_preserved_for_executor():
    def handler(request):
        return httpx.Response(
            200,
            json=completion(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "bad",
                            "type": "function",
                            "function": {"name": "lookup_primary", "arguments": "{broken"},
                        }
                    ],
                }
            ),
        )

    agent = OpenAIAgent("mock", client_for(handler))
    assert (await agent.decide(context())).calls[0].arguments == "{broken"
    await agent.close()


async def test_provider_exception_does_not_echo_credentials(tmp_path):
    def handler(request):
        return httpx.Response(
            401,
            json={"error": {"message": "sensitive-provider-text", "type": "authentication_error"}},
        )

    agent = OpenAIAgent("mock", client_for(handler))
    config = ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path))
    outcome = await run_one(scenario_catalog()["lookup-control"], "resilient", config, agent=agent)
    assert outcome.stop_reason == "provider_failure" and outcome.harness_error is None
    assert outcome.model_calls == 1
    assert "sensitive-provider-text" not in (tmp_path / outcome.trace_file).read_text()


async def test_live_model_call_and_token_budgets(tmp_path):
    class Repeating:
        async def decide(self, ctx):
            from agentfaultlab.schemas import Decision

            return Decision(
                calls=[ToolCall(id="x", name="lookup_primary", arguments={"key": "capacity"})],
                input_tokens=10,
                output_tokens=5,
            )

        def observe(self, call, result):
            pass

    config = ExperimentConfig(mode="live", model="mock", output_dir=str(tmp_path))
    config.budgets.max_model_calls = 1
    result = await run_one(
        scenario_catalog()["lookup-control"], "resilient", config, agent=Repeating()
    )
    assert result.stop_reason == "max_model_calls" and result.model_calls == 1
    config.budgets.max_model_calls = 10
    config.budgets.max_tokens = 12
    result = await run_one(
        scenario_catalog()["lookup-control"], "resilient", config, agent=Repeating()
    )
    assert result.stop_reason == "max_tokens" and result.tool_calls == 0


@pytest.mark.live
async def test_opt_in_real_provider(tmp_path):
    if os.environ.get("AGENTFAULTLAB_LIVE_TEST") != "1":
        pytest.skip("Set AGENTFAULTLAB_LIVE_TEST=1 explicitly")
    model = os.environ.get("AGENTFAULTLAB_MODEL")
    if not model or not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("Requires explicit model and API key")
    config = ExperimentConfig(mode="live", model=model, output_dir=str(tmp_path))
    config.budgets.elapsed_s = 120
    config.budgets.max_tokens = 30000
    outcome = await run_one(scenario_catalog()["lookup-control"], "resilient", config)
    assert outcome.harness_error is None and outcome.stop_reason != "provider_failure"
