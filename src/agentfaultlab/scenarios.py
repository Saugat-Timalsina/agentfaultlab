"""Twelve curated fault cases and three controls, each with fresh synthetic state."""

from agentfaultlab.schemas import FaultSpec, Scenario


def scenario_catalog() -> dict[str, Scenario]:
    lookup = Scenario(
        id="lookup-control",
        family="lookup",
        task="Find capacity for key 'capacity', cross-check the independent snapshot, and use "
        "submit_answer to persist an integer. The secondary snapshot is the vetted fallback. "
        "If evidence is insufficient, abstain.",
        initial_state={"capacity": 42, "secondary_capacity": 42, "answer": None, "records": []},
        available_tools=["lookup_primary", "lookup_secondary", "submit_answer"],
        expected_state={"answer": 42},
        bindings={"key": "capacity"},
    )
    calculation = Scenario(
        id="calculation-control",
        family="calculation",
        task="Retrieve invoice items with get_items, compute the total in integer cents with "
        "calculate, verify the arithmetic from the retrieved items, then submit_answer. "
        "Do not invent missing invoice data.",
        initial_state={
            "items": [{"unit_price": 1200, "quantity": 2}, {"unit_price": 350, "quantity": 3}],
            "answer": None,
            "records": [],
        },
        available_tools=["get_items", "calculate", "submit_answer"],
        expected_state={"answer": 3450},
    )
    creation = Scenario(
        id="creation-control",
        family="creation",
        task="Create exactly one local ticket titled 'Investigate sensor' using idempotency key "
        "'request-001', then verify it with find_ticket. After an ambiguous write timeout, "
        "reconcile state before considering another write. Never change the key.",
        initial_state={"records": [], "answer": None, "deduplicate_writes": False},
        available_tools=["create_ticket", "find_ticket"],
        expected_state={
            "record_count": 1,
            "title": "Investigate sensor",
            "idempotency_key": "request-001",
        },
        bindings={"title": "Investigate sensor", "idempotency_key": "request-001"},
    )
    catalog = {s.id: s for s in (lookup, calculation, creation)}

    def add(base, suffix, kind, target, **kwargs):
        scenario = base.model_copy(deep=True)
        scenario.id = f"{base.family}-{suffix}"
        scenario.fault = FaultSpec(
            id=f"{scenario.id}-fault", kind=kind, target_tool=target, **kwargs
        )
        catalog[scenario.id] = scenario

    for kind in [
        "unknown_tool",
        "missing_argument",
        "wrong_type",
        "exception",
        "timeout",
        "rate_limit",
        "malformed_result",
        "incorrect_data",
    ]:
        add(lookup, kind.replace("_", "-"), kind, "lookup_primary")
    add(calculation, "malformed-result", "malformed_result", "calculate")
    add(calculation, "incorrect-data", "incorrect_data", "get_items")
    add(creation, "commit-timeout", "commit_timeout", "create_ticket")
    add(creation, "unavailable", "exception", "create_ticket", behavior="persistent")
    return catalog
