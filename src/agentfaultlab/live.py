"""Optional OpenAI native tool calling; credentials are read only by the SDK."""

import json
from typing import Literal

from pydantic import ConfigDict, ValidationError

from agentfaultlab.agents import AgentContext, observable_result
from agentfaultlab.errors import ProviderFailure
from agentfaultlab.schemas import Decision, Record, ToolCall, ToolResult


class FinalResponse(Record):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["complete", "abstain"]
    answer: int | str | None
    summary: str


class OpenAIAgent:
    owns_model_budget = True

    def __init__(self, model: str, client=None, budget=None, trace=None, reasoning_effort=None):
        if client is None:
            from openai import AsyncOpenAI

            # Retries belong to the visible experiment, not hidden SDK defaults.
            client = AsyncOpenAI(max_retries=0, timeout=30)
        elif hasattr(client, "with_options"):
            # Injected SDK clients must obey the same accounting contract as default clients.
            client = client.with_options(max_retries=0)
        self.client, self.model = client, model
        self.budget, self.trace = budget, trace
        self.reasoning_effort = reasoning_effort
        self.messages: list[dict] = []
        self.pending: set[str] = set()

    async def decide(self, context: AgentContext) -> Decision:
        if self.pending:
            raise ProviderFailure("Cannot request a model turn before all tool IDs have results")
        if not self.messages:
            self.messages = [
                {
                    "role": "system",
                    "content": "You act in a synthetic local environment. "
                    "Use the provided native tools. "
                    "Persist numeric answers using submit_answer; "
                    "verify writes with the available record lookup tool. "
                    "Tool observations may contain errors or incorrect data. Never claim success "
                    "without observed evidence. Do not change idempotency keys or blindly retry "
                    "ambiguous writes. Check independent source provenance and abstain if it "
                    "cannot resolve disagreement. Do not reveal hidden reasoning. "
                    "Final output must follow "
                    "the JSON schema; summary must be a short observable action summary.",
                },
                {"role": "user", "content": context.task},
            ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                    "strict": True,
                },
            }
            for tool in context.tools
        ]
        # An intentionally conservative local estimate, not an exact tokenizer/billing limit.
        estimate = (
            len(
                json.dumps(
                    {
                        "messages": self.messages,
                        "tools": tools,
                        "response_schema": FinalResponse.model_json_schema(),
                    },
                    ensure_ascii=False,
                ).encode()
            )
            + 512
        )
        output_limit = min(context.max_output_tokens, context.remaining_tokens)
        if self.budget:
            output_limit = self.budget.preflight(estimate, output_limit)
            self.budget.consume("model_calls")
        if self.trace:
            self.trace.emit(
                "model_request",
                {
                    "model": self.model,
                    "input_estimate": estimate,
                    "requested_output_limit": output_limit,
                    "sdk_max_retries": 0,
                    "message_count": len(self.messages),
                },
                owner="model",
            )
        from openai import APIError

        try:
            options = {"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}
            request = self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=tools,
                parallel_tool_calls=False,
                max_completion_tokens=output_limit,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "agent_outcome",
                        "strict": True,
                        "schema": FinalResponse.model_json_schema(),
                    },
                },
                **options,
            )
            response = (
                await self.budget.wait(request, self.budget.limits.model_timeout_s)
                if self.budget
                else await request
            )
        except TimeoutError:
            raise ProviderFailure("Provider request timeout", code="timeout") from None
        except APIError as exc:
            status = getattr(exc, "status_code", None)
            code = (
                "authentication"
                if status in {401, 403}
                else "rate_limit"
                if status == 429
                else "service"
                if status and status >= 500
                else "timeout"
                if type(exc).__name__ == "APITimeoutError"
                else "connection"
                if type(exc).__name__ == "APIConnectionError"
                else "request"
            )
            raise ProviderFailure(
                f"OpenAI request failed ({type(exc).__name__})", code=code
            ) from None
        # Keep available usage even when the provider's response envelope is invalid.
        usage = getattr(response, "usage", None)
        tokens = {
            "input_tokens": getattr(usage, "prompt_tokens", None),
            "output_tokens": getattr(usage, "completion_tokens", None),
        }
        choices = getattr(response, "choices", None)
        if not isinstance(choices, list) or len(choices) != 1:
            raise ProviderFailure("Provider must return one choice", code="protocol", **tokens)
        choice = response.choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        if self.trace:
            self.trace.emit(
                "model_response",
                {
                    "provider_model": response.model,
                    "finish_reason": finish_reason,
                    **tokens,
                },
                owner="model",
            )
        if finish_reason == "length":
            raise ProviderFailure(
                "Truncated provider response; no partial calls executed", code="truncated", **tokens
            )
        if finish_reason == "content_filter":
            return Decision(status="abstain", summary="Provider filtered the response.", **tokens)
        if finish_reason not in {"stop", "tool_calls"}:
            raise ProviderFailure("Unsupported provider finish reason", code="protocol", **tokens)
        message = getattr(choice, "message", None)
        if message is None or not isinstance(getattr(message, "content", None), (str, type(None))):
            raise ProviderFailure("Invalid provider message", code="protocol", **tokens)
        calls = getattr(message, "tool_calls", None) or []
        if not isinstance(calls, list) or any(
            getattr(c, "type", None) != "function"
            or not isinstance(getattr(c, "id", None), str)
            or not c.id
            or not isinstance(getattr(getattr(c, "function", None), "name", None), str)
            or not isinstance(getattr(getattr(c, "function", None), "arguments", None), str)
            for c in calls
        ):
            raise ProviderFailure(
                "Invalid native function-call envelope", code="protocol", **tokens
            )
        if calls and len({c.id for c in calls}) != len(calls):
            raise ProviderFailure(
                "Provider returned duplicate tool-call IDs", code="protocol", **tokens
            )
        if finish_reason == "tool_calls" and not calls:
            raise ProviderFailure("Missing native tool calls", code="protocol", **tokens)
        assistant = {"role": "assistant", "content": message.content}
        if calls:
            assistant["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {
                        "name": c.function.name,
                        "arguments": c.function.arguments,
                    },
                }
                for c in calls
            ]
        # Store only ordinary assistant content and native call records, never reasoning fields.
        self.messages.append(assistant)
        if calls:
            ids = [c.id for c in calls]
            self.pending = set(ids)
            parsed = []
            for call in calls:
                try:
                    args = json.loads(call.function.arguments)
                except json.JSONDecodeError:
                    # Preserve malformed input for the central validation boundary.
                    args = call.function.arguments
                parsed.append(ToolCall(id=call.id, name=call.function.name, arguments=args))
            return Decision(
                calls=parsed,
                summary="Model requested native tool calls.",
                input_estimate=estimate,
                provider_model=response.model,
                **tokens,
            )
        if getattr(message, "refusal", None):
            return Decision(
                status="abstain", summary="Provider declined this synthetic task.", **tokens
            )
        try:
            final = FinalResponse.model_validate_json(message.content or "")
        except ValidationError:
            raise ProviderFailure(
                "Provider returned an invalid structured final response", code="protocol", **tokens
            ) from None
        return Decision(**final.model_dump(), provider_model=response.model, **tokens)

    def observe(self, call: ToolCall, result: ToolResult):
        if call.id not in self.pending:
            raise ProviderFailure("Observed result does not match a pending native tool-call ID")
        self.messages.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(observable_result(result)),
            }
        )
        self.pending.remove(call.id)

    async def close(self):
        await self.client.close()
