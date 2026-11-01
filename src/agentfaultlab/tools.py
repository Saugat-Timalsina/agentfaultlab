"""Resettable synthetic tools. No production services and no process-global state."""

from collections.abc import Awaitable, Callable
from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentfaultlab.schemas import ToolDefinition


class ToolData(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class LookupArgs(ToolData):
    key: str


class ValueResult(ToolData):
    value: int
    source: str


class Empty(ToolData):
    pass


class Item(ToolData):
    unit_price: int = Field(ge=0)
    quantity: int = Field(ge=1)


class ItemsResult(ToolData):
    items: list[Item] = Field(min_length=1)


class TotalResult(ToolData):
    total: int = Field(ge=0)


class CreateArgs(ToolData):
    title: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)


class FindArgs(ToolData):
    idempotency_key: str


class Ticket(ToolData):
    id: str
    title: str
    idempotency_key: str


class FindResult(ToolData):
    records: list[Ticket]


class SubmitArgs(ToolData):
    answer: int


class Submitted(ToolData):
    accepted: bool


class RequestArgs(ToolData):
    title: str = Field(min_length=1)
    request_key: str = Field(min_length=1)


class RequestKey(ToolData):
    request_key: str


class ServiceTicket(RequestArgs):
    id: str
    service: Literal["correlation", "idempotent"]


class ServiceRecords(ToolData):
    records: list[ServiceTicket]


class InvoiceResult(ItemsResult):
    source: str
    authority: Literal["peer", "vetted"]


class ToolUnavailable(Exception):
    """An expected transient environment problem (not an unexpected Python bug)."""


class DomainError(Exception):
    """A known permanent tool/environment error."""


class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        inputs: type[BaseModel],
        outputs: type[BaseModel],
        handler: Callable[..., Awaitable[dict]],
        retry_safe: bool = True,
        state_probe=None,
    ):
        self.inputs, self.outputs, self.handler = inputs, outputs, handler
        self.state_probe = state_probe
        self.definition = ToolDefinition(
            name=name,
            description=description,
            input_schema=inputs.model_json_schema(),
            output_schema=outputs.model_json_schema(),
            retry_safe=retry_safe,
        )


class Environment:
    def __init__(self, initial: dict[str, Any]):
        self.state = deepcopy(initial)

    def registry(self) -> dict[str, Tool]:
        def state_probe():
            return deepcopy(self.state["records"])

        async def primary(key):
            if key != "capacity":
                raise DomainError("Unknown lookup key")
            return {"value": self.state["capacity"], "source": "primary"}

        async def secondary(key):
            if key != "capacity":
                raise DomainError("Unknown lookup key")
            return {"value": self.state["secondary_capacity"], "source": "secondary"}

        async def inventory():
            return {"items": deepcopy(self.state["items"])}

        async def calculate(items):
            return {"total": sum(i["unit_price"] * i["quantity"] for i in items)}

        async def create_ticket(title, idempotency_key):
            # Some fake backends enforce keys; curated write cases deliberately do not.
            # The client key still enables reconciliation of a non-idempotent endpoint.
            for record in self.state["records"]:
                if (
                    self.state.get("deduplicate_writes", True)
                    and record["idempotency_key"] == idempotency_key
                ):
                    if record["title"] != title:
                        raise DomainError("Idempotency key conflicts with another title")
                    return deepcopy(record)
            ticket = {
                "id": f"T-{len(self.state['records']) + 1}",
                "title": title,
                "idempotency_key": idempotency_key,
            }
            self.state["records"].append(ticket)
            return deepcopy(ticket)

        async def find_ticket(idempotency_key):
            return {
                "records": deepcopy(
                    [r for r in self.state["records"] if r["idempotency_key"] == idempotency_key]
                )
            }

        async def submit_answer(answer):
            self.state["answer"] = answer
            return {"accepted": True}

        def writer(service):
            async def create(title, request_key):
                if service == "idempotent":
                    existing = [
                        r
                        for r in self.state["records"]
                        if r["request_key"] == request_key and r["service"] == service
                    ]
                    if existing:
                        if any(r["title"] != title for r in existing):
                            raise DomainError("idempotency_conflict: same key, different content")
                        return deepcopy(existing[0])
                record = {
                    "id": f"T-{len(self.state['records']) + 1}",
                    "title": title,
                    "request_key": request_key,
                    "service": service,
                }
                behavior = self.state.get("write_behavior", "normal")
                if behavior != "no-record":
                    stored = deepcopy(record)
                    if behavior == "conflicting-content":
                        stored["title"] = "Conflicting ticket"
                    self.state["records"].append(stored)
                    if behavior == "multiple-records":
                        self.state["records"].append({**stored, "id": "T-duplicate"})
                return deepcopy(record)

            return create

        def finder(service):
            async def find(request_key):
                return {
                    "records": deepcopy(
                        [
                            r
                            for r in self.state["records"]
                            if r["request_key"] == request_key and r["service"] == service
                        ]
                    )
                }

            return find

        async def invoice_primary():
            return {
                "items": deepcopy(self.state["primary_invoice"]),
                "source": "invoice-primary",
                "authority": "peer",
            }

        async def invoice_reference():
            return {
                "items": deepcopy(self.state["reference_invoice"]),
                "source": "finance-snapshot",
                "authority": self.state["reference_authority"],
            }

        specs = [
            Tool(
                "lookup_primary",
                "Look up capacity from the primary source.",
                LookupArgs,
                ValueResult,
                primary,
            ),
            Tool(
                "lookup_secondary",
                "Independent capacity cross-check / fallback source.",
                LookupArgs,
                ValueResult,
                secondary,
            ),
            Tool(
                "get_items",
                "Retrieve invoice items, prices in integer cents.",
                Empty,
                ItemsResult,
                inventory,
            ),
            Tool(
                "calculate",
                "Calculate sum(unit_price * quantity) in cents.",
                ItemsResult,
                TotalResult,
                calculate,
            ),
            Tool(
                "create_ticket",
                "Create a local ticket. Reuse the task's idempotency key.",
                CreateArgs,
                Ticket,
                create_ticket,
                retry_safe=False,
                state_probe=state_probe,
            ),
            Tool(
                "find_ticket",
                "Reconcile a write by its idempotency key.",
                FindArgs,
                FindResult,
                find_ticket,
            ),
            Tool(
                "submit_answer",
                "Persist the final numeric answer for state verification.",
                SubmitArgs,
                Submitted,
                submit_answer,
            ),
        ]
        for service in ("correlation", "idempotent"):
            specs.extend(
                [
                    Tool(
                        f"create_{service}_ticket",
                        f"Create in {service} service. "
                        + (
                            "Keys only correlate records; repeats can create duplicates."
                            if service == "correlation"
                            else "Equivalent requests deduplicate; "
                            "changed content with same key conflicts."
                        ),
                        RequestArgs,
                        ServiceTicket,
                        writer(service),
                        retry_safe=False,
                        state_probe=state_probe,
                    ),
                    Tool(
                        f"find_{service}_ticket",
                        "Find records using the original request key.",
                        RequestKey,
                        ServiceRecords,
                        finder(service),
                    ),
                ]
            )
        specs.extend(
            [
                Tool(
                    "get_invoice_primary",
                    "Retrieve primary invoice with source provenance.",
                    Empty,
                    InvoiceResult,
                    invoice_primary,
                ),
                Tool(
                    "get_invoice_reference",
                    "Retrieve a separately stored finance invoice snapshot. "
                    "The returned authority states whether this source is vetted or only a peer.",
                    Empty,
                    InvoiceResult,
                    invoice_reference,
                ),
            ]
        )
        return {t.definition.name: t for t in specs}
