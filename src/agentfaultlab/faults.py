"""Occurrence-based schedules. The agent never receives these records."""

import random
from collections import Counter
from copy import deepcopy
from typing import Any

from agentfaultlab.schemas import FaultSpec, ToolCall


class FaultInjector:
    def __init__(self, rules: list[FaultSpec]):
        self.rules = rules
        self.counts: Counter[str] = Counter()
        self.activations: list[dict[str, Any]] = []
        self.random = {r.id: random.Random(r.seed) for r in rules}
        if len(self.random) != len(rules):
            raise ValueError("Fault rule IDs must be unique")

    def observe(self, original_name: str) -> int:
        self.counts[original_name] += 1
        return self.counts[original_name]

    def select(self, original_name: str, occurrence: int) -> FaultSpec | None:
        # First matching activated rule wins; at most one fault per boundary call.
        for rule in self.rules:
            eligible = occurrence == rule.occurrence or (
                rule.behavior == "persistent" and occurrence >= rule.occurrence
            )
            if rule.target_tool == original_name and eligible:
                if self.random[rule.id].random() < rule.probability:
                    return rule
        return None

    @staticmethod
    def mutate_call(call: ToolCall, rule: FaultSpec) -> ToolCall:
        mutated = call.model_copy(deep=True)
        if rule.kind == "unknown_tool":
            mutated.name = call.name + "_typo"
        elif rule.kind in {"missing_argument", "wrong_type"}:
            args = deepcopy(call.arguments)
            if not args:
                raise ValueError("Argument mutation needs a non-empty argument object")
            field = next(iter(args))
            if rule.kind == "missing_argument":
                del args[field]
            else:
                args[field] = {"invalid": "type"}
            mutated.arguments = args
        return mutated

    @staticmethod
    def corrupt(data: dict[str, Any], rule: FaultSpec) -> dict[str, Any]:
        if rule.kind == "malformed_result":
            return {"unexpected": "missing required fields"}
        result = deepcopy(data)
        if "value" in result:
            result["value"] += 7
        elif "total" in result:
            result["total"] += 7
        elif "items" in result:
            result["items"][0]["unit_price"] += 7
        else:
            raise ValueError("No numeric corruption supported for this output")
        return result
