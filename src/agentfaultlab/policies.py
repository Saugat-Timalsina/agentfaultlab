"""Deterministic middleware; no model reasoning is attributed to these actions."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from agentfaultlab.schemas import Budgets, PolicyName, ToolCall, ToolResult
from agentfaultlab.tools import Tool
from agentfaultlab.tracing import Trace


class Recovery:
    def __init__(
        self,
        name: PolicyName,
        budgets: Budgets,
        registry: dict[str, Tool],
        trace: Trace,
        invoke: Callable[[ToolCall], Awaitable[ToolResult]],
        deadline: float,
        bindings: dict,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    ):
        self.name, self.budgets, self.registry = name, budgets, registry
        self.trace, self.invoke, self.deadline, self.bindings = trace, invoke, deadline, bindings
        self.clock, self.sleep = clock, sleep
        self.retries = self.fallbacks = self.corrections = 0

    def action(self, action, call, **payload):
        self.trace.emit(
            "recovery",
            {"owner": "deterministic_middleware", **payload},
            tool_name=call.name,
            call_id=call.id,
            recovery_action=action,
        )

    async def execute(self, call: ToolCall) -> ToolResult:
        current = call
        result = await self.invoke(current)
        attempt = corrections = 0
        while result.error and self.name != "fail_fast":
            error = result.error
            tool = self.registry.get(current.name)
            # Ambiguous writes are never blindly retried, even if a tool claims idempotency.
            if error.ambiguous:
                if self.name == "resilient" and current.name == "create_ticket":
                    self.action("reconcile_state", current)
                    check = ToolCall(
                        id=uuid4().hex,
                        name="find_ticket",
                        arguments={"idempotency_key": self.bindings["idempotency_key"]},
                    )
                    found = await self.invoke(check)
                    if found.ok and len(found.data["records"]) == 1:
                        record = found.data["records"][0]
                        if record["title"] == self.bindings["title"]:
                            self.action(
                                "reconciled_existing_write", current, verification_call_id=check.id
                            )
                            return ToolResult(call_id=call.id, name=call.name, data=record)
                return result
            if error.transient and tool and tool.definition.retry_safe:
                if attempt >= self.budgets.max_retries:
                    break
                delay = min(0.01 * 2**attempt, 0.1)
                # Retry-After is a minimum. Do not cap it downward or retry early.
                delay = max(delay, error.retry_after or 0)
                if self.clock() + delay >= self.deadline:
                    self.action("retry_skipped_deadline", current, retry_after=delay)
                    return result
                self.action("retry", current, delay_s=delay, attempt=attempt + 1)
                self.retries += 1
                attempt += 1
                await self.sleep(delay)
                current = current.model_copy(update={"id": uuid4().hex})
                result = await self.invoke(current)
                continue
            if self.name != "resilient":
                return result
            if error.code in {"unknown_tool", "invalid_arguments"}:
                if corrections >= self.budgets.max_corrections:
                    break
                # Only bounded, task-bound correction is supported; no speculative filling.
                name = current.name
                if name.endswith("_typo") and name[:-5] in self.registry:
                    name = name[:-5]
                args = current.arguments
                if name in {"lookup_primary", "lookup_secondary"}:
                    args = {"key": self.bindings["key"]}
                elif name == "create_ticket":
                    args = dict(self.bindings)
                elif error.code == "invalid_arguments":
                    break
                if name not in self.registry:
                    break
                corrected = ToolCall(id=uuid4().hex, name=name, arguments=args)
                self.action("argument_correction", current, corrected_call=corrected.model_dump())
                corrections += 1
                self.corrections += 1
                current = corrected
                result = await self.invoke(current)
                continue
            if error.code == "invalid_result" and tool and tool.definition.retry_safe:
                if attempt >= self.budgets.max_retries:
                    break
                self.action("validation_feedback", current, message=error.message)
                self.retries += 1
                attempt += 1
                current = current.model_copy(update={"id": uuid4().hex})
                result = await self.invoke(current)
                continue
            break
        if result.error and self.name == "resilient" and call.name == "lookup_primary":
            self.action("fallback", call, fallback_tool="lookup_secondary")
            self.fallbacks += 1
            fallback = ToolCall(
                id=uuid4().hex, name="lookup_secondary", arguments={"key": self.bindings["key"]}
            )
            observed = await self.invoke(fallback)
            return observed.model_copy(update={"call_id": call.id, "name": call.name})
        return result.model_copy(update={"call_id": call.id, "name": call.name})
