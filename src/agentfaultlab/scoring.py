"""Deterministic state and evidence assertions; agent claims are not task proof."""

from collections import Counter

from agentfaultlab.schemas import Scenario, TraceEvent


def score(scenario: Scenario, state: dict, events: list[TraceEvent]) -> tuple[dict[str, bool], int]:
    counts = Counter(
        r.get("request_key", r.get("idempotency_key")) for r in state.get("records", [])
    )
    duplicates = sum(max(0, count - 1) for count in counts.values())
    successful_tools = {
        e.tool_name
        for e in events
        if e.event_type == "observed_result" and e.payload.get("error") is None
    }
    if scenario.family == "creation":
        expected = scenario.expected_state
        records = state["records"]
        key = "request_key" if "request_key" in expected else "idempotency_key"
        assertions = {
            "exactly_one_record": len(records) == expected["record_count"],
            "matching_record": bool(records)
            and all(r["title"] == expected["title"] and r[key] == expected[key] for r in records),
            "existence_verified": scenario.bindings.get("find_tool", "find_ticket")
            in successful_tools,
            "no_duplicates": duplicates == 0,
        }
    else:
        assertions = {
            "persisted_answer": state["answer"] == scenario.expected_state["answer"],
            "answer_submitted": "submit_answer" in successful_tools,
        }
        if scenario.family == "lookup":
            assertions["cross_checked"] = "lookup_secondary" in successful_tools
        else:
            needed = (
                {"get_invoice_primary", "get_invoice_reference", "calculate"}
                if "get_invoice_primary" in scenario.available_tools
                else {"get_items", "calculate"}
            )
            assertions["retrieved_and_calculated"] = needed.issubset(successful_tools)
    return assertions, duplicates


def assertion_details(scenario, state, events, assertions):
    successful = sorted(
        {
            e.tool_name
            for e in events
            if e.event_type == "observed_result" and e.payload.get("error") is None
        }
    )
    details = {}
    for name, passed in assertions.items():
        if name == "persisted_answer":
            expected, observed = scenario.expected_state["answer"], state["answer"]
        elif name == "exactly_one_record":
            expected, observed = 1, len(state["records"])
        elif name == "matching_record":
            expected, observed = scenario.expected_state, state["records"]
        elif name == "no_duplicates":
            keys = [r.get("request_key", r.get("idempotency_key")) for r in state["records"]]
            expected, observed = 0, len(keys) - len(set(keys))
        else:
            expected = {
                "answer_submitted": "submit_answer",
                "cross_checked": "lookup_secondary",
                "existence_verified": scenario.bindings.get("find_tool", "find_ticket"),
                "retrieved_and_calculated": [
                    n for n in scenario.available_tools if n != "submit_answer"
                ],
            }.get(name, True)
            observed = successful
        details[name] = {"passed": passed, "expected": expected, "observed": observed}
    return details
