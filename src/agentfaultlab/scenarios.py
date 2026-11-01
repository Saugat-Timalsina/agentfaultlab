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
    catalog.update(phase2_scenarios())
    return catalog


def phase2_scenarios() -> dict[str, Scenario]:
    from copy import deepcopy

    cases = {}
    for service in ("correlation", "idempotent"):
        scenario = Scenario(
            id=f"{service}-write-lost-response",
            family="creation",
            suite_version="phase2-v1",
            task=f"Use create_{service}_ticket to create exactly one ticket titled "
            "'Investigate sensor' with request_key 'request-001'. Then verify existence "
            f"using find_{service}_ticket. This is the {service} service. A correlation "
            "key does not enforce deduplication; an idempotent service rejects conflicting "
            "content for an existing key. After a response timeout reconcile state, and "
            "abstain if state is absent, conflicting, duplicated or unavailable.",
            initial_state={"records": [], "answer": None},
            available_tools=[f"create_{service}_ticket", f"find_{service}_ticket"],
            expected_state={
                "record_count": 1,
                "title": "Investigate sensor",
                "request_key": "request-001",
            },
            bindings={
                "title": "Investigate sensor",
                "request_key": "request-001",
                "create_tool": f"create_{service}_ticket",
                "find_tool": f"find_{service}_ticket",
            },
            fault=FaultSpec(
                id=f"{service}-lost", kind="commit_timeout", target_tool=f"create_{service}_ticket"
            ),
        )
        cases[scenario.id] = scenario
    base = cases["correlation-write-lost-response"]
    for behavior in ("no-record", "multiple-records", "conflicting-content", "read-fails"):
        variant = base.model_copy(deep=True)
        variant.id = f"correlation-reconcile-{behavior}"
        variant.initial_state["write_behavior"] = behavior
        if behavior == "read-fails":
            variant.additional_faults = [
                FaultSpec(
                    id="read-outage",
                    kind="exception",
                    target_tool="find_correlation_ticket",
                    behavior="persistent",
                )
            ]
        cases[variant.id] = variant

    items = [{"unit_price": 1200, "quantity": 2}, {"unit_price": 350, "quantity": 3}]
    invoice = Scenario(
        id="invoice-sources-agree",
        family="calculation",
        suite_version="phase2-v1",
        task="Retrieve get_invoice_primary and the separately stored get_invoice_reference. "
        "Cross-check both before calculate and submit_answer. On disagreement select the "
        "reference only if its observed authority is 'vetted'; if both are peers, abstain. "
        "If either source is unavailable, abstain. Never infer authority from a value.",
        initial_state={
            "primary_invoice": deepcopy(items),
            "reference_invoice": deepcopy(items),
            "reference_authority": "vetted",
            "answer": None,
            "records": [],
        },
        available_tools=[
            "get_invoice_primary",
            "get_invoice_reference",
            "calculate",
            "submit_answer",
        ],
        expected_state={"answer": 3450},
    )
    cases[invoice.id] = invoice
    for condition in ("primary-corrupted", "reference-unavailable", "unresolved-disagreement"):
        variant = invoice.model_copy(deep=True)
        variant.id = f"invoice-{condition}"
        if condition == "reference-unavailable":
            variant.fault = FaultSpec(
                id="reference-down",
                kind="exception",
                target_tool="get_invoice_reference",
                behavior="persistent",
            )
        else:
            variant.fault = FaultSpec(
                id="primary-corruption", kind="incorrect_data", target_tool="get_invoice_primary"
            )
            if condition == "unresolved-disagreement":
                variant.initial_state["reference_authority"] = "peer"
        cases[variant.id] = variant
    return cases
