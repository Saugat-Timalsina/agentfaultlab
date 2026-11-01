"""Optional OpenAI native tool calling; credentials are read only by the SDK."""

import json
from typing import Literal

from pydantic import ConfigDict, ValidationError

from agentfaultlab.agents import AgentContext, observable_result
from agentfaultlab.runner import ProviderFailure
from agentfaultlab.schemas import Decision, Record, ToolCall, ToolResult


class FinalResponse(Record):
    model_config = ConfigDict(extra="forbid", strict=True)
    status: Literal["complete", "abstain"]
    answer: int | str | None
    summary: str


class OpenAIAgent:
    def __init__(self, model: str, client=None):
        if client is None:
            from openai import AsyncOpenAI

            # Retries belong to the visible experiment, not hidden SDK defaults.
            client = AsyncOpenAI(max_retries=0, timeout=30)
        self.client, self.model = client, model
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
                    "Persist numeric answers using submit_answer; verify writes with find_ticket. "
                    "Tool observations may contain errors or incorrect data. Never claim success "
                    "without observed evidence. Do not change idempotency keys or blindly retry "
                    "ambiguous writes. Do not reveal hidden reasoning. Final output must follow "
                    "the JSON schema; summary must be a short observable action summary. "
                    f"Recovery middleware policy is {context.policy}. The resilient policy permits "
                    "domain fallback selection and correction after validation feedback.",
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
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=tools,
                parallel_tool_calls=False,
                max_completion_tokens=min(1024, context.remaining_tokens),
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "agent_outcome",
                        "strict": True,
                        "schema": FinalResponse.model_json_schema(),
                    },
                },
            )
        except Exception as exc:
            # Do not persist raw provider exceptions: they can contain headers or credentials.
            raise ProviderFailure(f"OpenAI request failed ({type(exc).__name__})") from None
        if not response.choices:
            raise ProviderFailure("Provider returned no choices")
        choice = response.choices[0]
        message = choice.message
        calls = message.tool_calls or []
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
        tokens = {
            "input_tokens": response.usage.prompt_tokens if response.usage else None,
            "output_tokens": response.usage.completion_tokens if response.usage else None,
        }
        if calls:
            ids = [c.id for c in calls]
            if len(set(ids)) != len(ids):
                raise ProviderFailure("Provider returned duplicate tool-call IDs")
            self.pending = set(ids)
            parsed = []
            for call in calls:
                try:
                    args = json.loads(call.function.arguments)
                except json.JSONDecodeError:
                    # Preserve malformed input for the central validation boundary.
                    args = call.function.arguments
                parsed.append(ToolCall(id=call.id, name=call.function.name, arguments=args))
            return Decision(calls=parsed, summary="Model requested native tool calls.", **tokens)
        if choice.finish_reason == "length":
            raise ProviderFailure("Provider output exhausted its completion token allowance")
        if getattr(message, "refusal", None):
            return Decision(
                status="abstain", summary="Provider declined this synthetic task.", **tokens
            )
        try:
            final = FinalResponse.model_validate_json(message.content or "")
        except ValidationError:
            raise ProviderFailure(
                "Provider returned an invalid structured final response"
            ) from None
        return Decision(**final.model_dump(), **tokens)

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
