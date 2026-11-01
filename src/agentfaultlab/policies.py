"""Bounded deterministic middleware, with domain behavior in explicit recipes."""

import asyncio
import time
from uuid import uuid4

from agentfaultlab.budget import RunBudget
from agentfaultlab.recipes import correction_target, recipe_registry
from agentfaultlab.schemas import ToolCall, ToolError, ToolResult


class Recovery:
    def __init__(
        self,
        name,
        budgets,
        registry,
        trace,
        invoke,
        deadline,
        bindings,
        clock=time.monotonic,
        sleep=asyncio.sleep,
        budget=None,
        recipes=None,
    ):
        self.name, self.budgets, self.registry = name, budgets, registry
        self.trace, self.invoke, self.deadline, self.bindings = trace, invoke, deadline, bindings
        self.clock, self.sleep = clock, sleep
        self.budget = budget or RunBudget(budgets, deadline, clock)
        self.recipes = recipe_registry() if recipes is None else recipes
        self.retries = self.fallbacks = self.corrections = 0

    def action(self, action, call, **payload):
        self.budget.consume("recovery_actions")
        self.trace.emit(
            "recovery",
            {"owner": "deterministic_middleware", **payload},
            tool_name=call.name,
            call_id=call.id,
            root_call_id=call.root_call_id or call.id,
            owner="middleware",
            recovery_action=action,
        )

    def child(self, parent, name=None, arguments=None):
        return ToolCall(
            id=uuid4().hex,
            name=name or parent.name,
            arguments=parent.arguments if arguments is None else arguments,
            root_call_id=parent.root_call_id or parent.id,
            parent_call_id=parent.id,
            attempt=parent.attempt + 1,
            owner="middleware",
        )

    async def attempt(self, call):
        self.budget.check()
        # This bounds even injected/custom invokers, not just runner-owned executors.
        return await self.budget.wait(self.invoke(call), self.budget.remaining())

    def returned(self, root, result, supporting, reason):
        returned = result.model_copy(
            update={
                "call_id": root.id,
                "name": root.name,
                "supporting_call_ids": list(dict.fromkeys(supporting)),
                "recovery_result": reason,
            }
        )
        self.trace.emit(
            "middleware_result",
            {
                "result": returned.model_dump(),
                "supporting_call_ids": returned.supporting_call_ids,
                "reason": reason,
            },
            tool_name=root.name,
            call_id=root.id,
            root_call_id=root.root_call_id or root.id,
            owner="middleware",
        )
        return returned

    async def verify_write(self, root, current, result, recipe, supporting):
        args = recipe.verification_args(current)
        if args is None or recipe.verification_tool not in self.registry:
            return result
        self.action("reconcile_state", current)
        check = self.child(current, recipe.verification_tool, args)
        found = await self.attempt(check)
        supporting.append(check.id)
        records = found.data["records"] if found.ok else []
        if found.ok and len(records) == 1 and recipe.matches(records[0], current):
            self.action("reconciled_existing_write", current, verification_call_id=check.id)
            verified = ToolResult(call_id=check.id, name=check.name, data=records[0])
            return self.returned(root, verified, supporting, "reconciled_existing_write")
        reason = (
            "verification_failed"
            if not found.ok
            else "no_record"
            if not records
            else "multiple_records"
            if len(records) > 1
            else "conflicting_content"
        )
        self.trace.emit(
            "reconciliation_unresolved",
            {"reason": reason, "verification_call_id": check.id},
            call_id=root.id,
            owner="middleware",
        )
        return self.returned(root, result, supporting, reason)

    async def verify_invoice(self, root, result, recipe, supporting):
        self.action("independent_source_check", root)
        check = self.child(root, recipe.independent_source, {})
        reference = await self.attempt(check)
        supporting.append(check.id)
        if not reference.ok:
            error = ToolError(
                category="tool_environment",
                code="independent_source_unavailable",
                message="Separate invoice source unavailable; evidence incomplete.",
            )
            return self.returned(
                root,
                ToolResult(call_id=root.id, name=root.name, error=error),
                supporting,
                "independent_source_unavailable",
            )
        if result.data["items"] == reference.data["items"]:
            return self.returned(root, result, supporting, "independent_sources_agree")
        if reference.data["authority"] == "vetted":
            self.action("fallback", root, verification_call_id=check.id)
            self.fallbacks += 1
            return self.returned(root, reference, supporting, "vetted_source_selected")
        error = ToolError(
            category="output_validation",
            code="unresolved_disagreement",
            message="Independent peer sources disagree; abstain without authority.",
        )
        return self.returned(
            root,
            ToolResult(call_id=root.id, name=root.name, error=error),
            supporting,
            "unresolved_disagreement",
        )

    async def execute(self, call):
        current = call
        result = await self.attempt(current)
        supporting = [current.id]
        attempt = corrections = 0
        while result.error and self.name != "fail_fast":
            error = result.error
            tool = self.registry.get(current.name)
            recipe = self.recipes.get(correction_target(current, self.registry))
            if error.ambiguous:
                if self.name == "resilient" and recipe and recipe.verification_tool:
                    return await self.verify_write(call, current, result, recipe, supporting)
                return result
            if error.transient and tool and tool.definition.retry_safe:
                if attempt >= self.budgets.max_retries:
                    break
                delay = max(min(0.01 * 2**attempt, 0.1), error.retry_after or 0)
                if self.budget.remaining() <= delay:
                    self.action("retry_skipped_deadline", current, retry_after=delay)
                    return result
                self.action("retry", current, delay_s=delay, attempt=attempt + 1)
                self.retries += 1
                attempt += 1
                await self.budget.wait(self.sleep(delay), self.budget.remaining())
                current = self.child(current)
            elif self.name == "resilient" and error.code in {"unknown_tool", "invalid_arguments"}:
                if corrections >= self.budgets.max_corrections or not recipe:
                    break
                args = recipe.correct(current, self.bindings)
                if args is None:
                    break
                corrected = self.child(current, correction_target(current, self.registry), args)
                self.action("argument_correction", current, corrected_call=corrected.model_dump())
                corrections += 1
                self.corrections += 1
                current = corrected
            elif (
                self.name == "resilient"
                and error.code == "invalid_result"
                and tool
                and tool.definition.retry_safe
            ):
                if attempt >= self.budgets.max_retries:
                    break
                self.action("validation_feedback", current, message=error.message)
                attempt += 1
                self.retries += 1
                current = self.child(current)
            else:
                break
            result = await self.attempt(current)
            supporting.append(current.id)
        recipe = self.recipes.get(call.name)
        if result.error and self.name == "resilient" and recipe and recipe.fallback_tool:
            self.action("fallback", call, fallback_tool=recipe.fallback_tool)
            self.fallbacks += 1
            fallback = self.child(
                current, recipe.fallback_tool, recipe.correct(call, self.bindings)
            )
            result = await self.attempt(fallback)
            supporting.append(fallback.id)
        if result.ok and self.name == "resilient" and recipe and recipe.independent_source:
            return await self.verify_invoice(call, result, recipe, supporting)
        if len(supporting) > 1:
            return self.returned(
                call, result, supporting, "recovered" if result.ok else "exhausted"
            )
        return result
