"""Deterministic state and evidence assertions; agent claims are not task proof."""

from collections import Counter

from agentfaultlab.schemas import Scenario, TraceEvent


def score(scenario: Scenario, state: dict, events: list[TraceEvent]) -> tuple[dict[str, bool], int]:
    counts = Counter(r["idempotency_key"] for r in state.get("records", []))
    duplicates = sum(max(0, count - 1) for count in counts.values())
    successful_tools = {
        e.tool_name
        for e in events
        if e.event_type == "observed_result" and e.payload.get("error") is None
    }
    if scenario.family == "creation":
        expected = scenario.expected_state
        records = state["records"]
        assertions = {
            "exactly_one_record": len(records) == expected["record_count"],
            "matching_record": bool(records)
            and all(
                r["title"] == expected["title"]
                and r["idempotency_key"] == expected["idempotency_key"]
                for r in records
            ),
            "existence_verified": "find_ticket" in successful_tools,
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
            assertions["retrieved_and_calculated"] = {"get_items", "calculate"}.issubset(
                successful_tools
            )
    return assertions, duplicates
