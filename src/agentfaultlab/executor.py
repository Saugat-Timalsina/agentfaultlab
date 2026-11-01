"""The only route to tool execution: validate, inject, execute, validate, trace."""

import asyncio
import time

from pydantic import ValidationError

from agentfaultlab.faults import FaultInjector
from agentfaultlab.schemas import ToolCall, ToolError, ToolResult
from agentfaultlab.tools import DomainError, Tool, ToolUnavailable
from agentfaultlab.tracing import Trace


class ToolExecutor:
    def __init__(
        self, registry: dict[str, Tool], injector: FaultInjector, trace: Trace, timeout_s: float
    ):
        self.registry, self.injector, self.trace = registry, injector, trace
        self.timeout_s = timeout_s
        self.calls = 0
        self.agent_invalid = 0
        self.injected_invalid = 0

    def validate(self, call: ToolCall):
        if call.name not in self.registry:
            return None, "unknown_tool", "Unknown tool name; consult available tool definitions."
        tool = self.registry[call.name]
        try:
            parsed = tool.inputs.model_validate(call.arguments, strict=True)
        except ValidationError as exc:
            # Include field/type feedback, never echo potentially secret invalid input.
            issues = [
                {"field": list(e["loc"]), "type": e["type"]}
                for e in exc.errors(include_input=False)
            ]
            return None, "invalid_arguments", str(issues)
        return parsed.model_dump(), None, None

    async def execute(self, call: ToolCall) -> ToolResult:
        self.calls += 1
        occurrence = self.injector.observe(call.name)
        started = time.monotonic()
        self.trace.emit(
            "tool_call",
            {"arguments": call.arguments, "occurrence": occurrence},
            tool_name=call.name,
            call_id=call.id,
        )

        def finish(data=None, error=None):
            result = ToolResult(
                call_id=call.id,
                name=call.name,
                data=data,
                error=error,
                duration_s=time.monotonic() - started,
            )
            self.trace.emit(
                "observed_result",
                result.model_dump(),
                tool_name=call.name,
                call_id=call.id,
                duration_s=result.duration_s,
                error_category=error.category if error else None,
            )
            return result

        args, code, message = self.validate(call)
        if code:
            self.agent_invalid += 1
            return finish(
                error=ToolError(category="agent_invalid_call", code=code, message=message)
            )

        rule = self.injector.select(call.name, occurrence)
        effective = call
        if rule:
            effective = self.injector.mutate_call(call, rule)
            activation = {
                "rule_id": rule.id,
                "kind": rule.kind,
                "planned_tool": rule.target_tool,
                "planned_occurrence": rule.occurrence,
                "actual_tool": call.name,
                "actual_occurrence": occurrence,
                "phase": rule.phase,
                "original_call": call.model_dump(),
                "effective_call": effective.model_dump(),
                "activated": True,
            }
            self.trace.emit(
                "fault_selected",
                {**activation, "activated": False},
                tool_name=call.name,
                call_id=call.id,
            )
            if rule.phase == "pre_execution":
                self.injector.activations.append(activation)
                self.trace.emit("fault_activated", activation, tool_name=call.name, call_id=call.id)
            args, code, message = self.validate(effective)
            if code:
                self.injected_invalid += 1
                return finish(
                    error=ToolError(category="injected_invalid_call", code=code, message=message)
                )
            if rule.kind == "rate_limit":
                return finish(
                    error=ToolError(
                        category="tool_environment",
                        code="rate_limit",
                        message="Rate limit; Retry-After is in seconds.",
                        transient=True,
                        retry_after=rule.retry_after,
                    )
                )

        tool = self.registry[effective.name]

        async def invoke():
            if rule and rule.kind == "exception":
                raise ToolUnavailable("Synthetic temporary service outage")
            if rule and rule.kind == "timeout":
                await asyncio.sleep(self.timeout_s * 4 + 0.05)
            data = await tool.handler(**args)
            if rule and rule.kind == "commit_timeout":
                self.injector.activations.append(activation)
                self.trace.emit("fault_activated", activation, tool_name=call.name, call_id=call.id)
                self.trace.emit(
                    "environment_commit",
                    {"response_lost": True},
                    tool_name=call.name,
                    call_id=call.id,
                )
                await asyncio.sleep(self.timeout_s * 4 + 0.05)
            return data

        try:
            data = await asyncio.wait_for(invoke(), timeout=self.timeout_s)
        except TimeoutError:
            return finish(
                error=ToolError(
                    category="tool_environment",
                    code="timeout",
                    message="Response deadline exceeded; write state may be unknown.",
                    transient=True,
                    ambiguous=not tool.definition.retry_safe,
                )
            )
        except ToolUnavailable as exc:
            return finish(
                error=ToolError(
                    category="tool_environment",
                    code="unavailable",
                    message=str(exc),
                    transient=True,
                )
            )
        except DomainError as exc:
            return finish(
                error=ToolError(category="tool_environment", code="domain_error", message=str(exc))
            )
        # Unexpected exceptions deliberately propagate to the runner's harness boundary.
        if rule and rule.phase == "response_corruption":
            corrupted = self.injector.corrupt(data, rule)
            self.injector.activations.append(activation)
            self.trace.emit("fault_activated", activation, tool_name=call.name, call_id=call.id)
            self.trace.emit(
                "response_corrupted",
                {"before": data, "after": corrupted, "rule_id": rule.id},
                tool_name=call.name,
                call_id=call.id,
            )
            data = corrupted
        try:
            validated = tool.outputs.model_validate(data, strict=True).model_dump()
        except ValidationError:
            return finish(
                error=ToolError(
                    category="output_validation",
                    code="invalid_result",
                    message="Tool result failed its declared output schema.",
                    ambiguous=not tool.definition.retry_safe,
                )
            )
        return finish(data=validated)
