"""Provider-independent observable decision interface and a labeled scripted baseline."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

from agentfaultlab.schemas import Decision, PolicyName, ToolCall, ToolDefinition, ToolResult


def observable_result(result: ToolResult) -> dict[str, Any]:
    error = result.error.model_dump(exclude={"category"}) if result.error else None
    return {"call_id": result.call_id, "name": result.name, "data": result.data, "error": error}


@dataclass
class AgentContext:
    task: str
    family: str
    bindings: dict[str, Any]
    tools: list[ToolDefinition]
    observations: list[dict[str, Any]]
    policy: PolicyName
    remaining_tokens: int


class Agent(Protocol):
    async def decide(self, context: AgentContext) -> Decision: ...

    def observe(self, call: ToolCall, result: ToolResult) -> None: ...


class ScriptedAgent:
    """A small domain script, not an LLM and not evidence of model intelligence."""

    def observe(self, call, result):
        pass

    async def decide(self, context: AgentContext) -> Decision:
        observations = context.observations

        def successes(name):
            return [
                o["result"]["data"]
                for o in observations
                if o["call"]["name"] == name and not o["result"]["error"]
            ]

        def call(name, **args):
            return Decision(
                calls=[ToolCall(id=uuid4().hex, name=name, arguments=args)],
                summary=f"Scripted next action: {name}",
            )

        def abstain(reason):
            return Decision(status="abstain", summary=reason)

        if observations and observations[-1]["result"]["error"]:
            return abstain("Available recovery actions exhausted; task remains unverified.")
        if context.family == "lookup":
            primary, secondary = successes("lookup_primary"), successes("lookup_secondary")
            if not primary:
                return call("lookup_primary", **context.bindings)
            if not secondary:
                return call("lookup_secondary", **context.bindings)
            value = primary[-1]["value"]
            if value != secondary[-1]["value"]:
                if context.policy != "resilient":
                    return abstain("Cross-check disagrees; cannot verify primary value.")
                value = secondary[-1]["value"]
            if not successes("submit_answer"):
                decision = call("submit_answer", answer=value)
                if primary[-1]["value"] != secondary[-1]["value"]:
                    decision.recovery_action = "fallback"
                    decision.summary = "Scripted disagreement rule selects the vetted secondary."
                return decision
            return Decision(status="complete", answer=value, summary="Scripted sources checked.")
        if context.family == "calculation":
            items = successes("get_items")
            if not items:
                return call("get_items")
            totals = successes("calculate")
            if not totals:
                return call("calculate", **items[-1])
            verified = sum(i["unit_price"] * i["quantity"] for i in items[-1]["items"])
            if totals[-1]["total"] != verified:
                return abstain("Arithmetic cross-check failed; cannot verify result.")
            if not successes("submit_answer"):
                return call("submit_answer", answer=verified)
            return Decision(
                status="complete",
                answer=verified,
                summary="Scripted arithmetic checked against observed items.",
            )
        created = successes("create_ticket")
        if not created:
            return call("create_ticket", **context.bindings)
        found = successes("find_ticket")
        if not found:
            return call("find_ticket", idempotency_key=context.bindings["idempotency_key"])
        records = found[-1]["records"]
        if len(records) != 1 or records[0]["title"] != context.bindings["title"]:
            return abstain("Record verification did not find exactly one matching ticket.")
        return Decision(
            status="complete",
            answer=records[0]["id"],
            summary="Scripted ticket existence verified.",
        )
