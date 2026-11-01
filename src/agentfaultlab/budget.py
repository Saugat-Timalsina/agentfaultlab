"""One run controller shared by agents, tools, and all recovery paths."""

import asyncio
import time
from collections import Counter

from agentfaultlab.schemas import Budgets


class BudgetExceeded(Exception):
    """A named resource termination; never a retryable tool error."""


class RunBudget:
    def __init__(self, limits: Budgets, deadline=None, clock=time.monotonic):
        self.limits, self.clock = limits, clock
        self.deadline = deadline if deadline is not None else clock() + limits.elapsed_s
        self.counts: Counter[str] = Counter()
        self.input_tokens = self.output_tokens = 0
        self.usage_available = True

    def remaining(self):
        return max(0, self.deadline - self.clock())

    def check(self):
        if self.remaining() <= 0:
            raise BudgetExceeded("elapsed_s")

    def consume(self, resource):
        self.check()
        limit = getattr(self.limits, "max_" + resource)
        if self.counts[resource] >= limit:
            raise BudgetExceeded("max_" + resource)
        self.counts[resource] += 1

    def timeout(self, operation_timeout):
        self.check()
        return min(operation_timeout, self.remaining())

    async def wait(self, awaitable, operation_timeout):
        try:
            allowance = self.timeout(operation_timeout)
        except BaseException:
            # Avoid unawaited coroutine warnings when a deadline already expired.
            close = getattr(awaitable, "close", None)
            if close:
                close()
            raise
        try:
            return await asyncio.wait_for(awaitable, allowance)
        except TimeoutError:
            self.check()  # A run deadline is a budget termination, not a tool timeout.
            raise

    def preflight(self, estimate, requested_output):
        self.check()
        if estimate > self.limits.max_input_estimate:
            raise BudgetExceeded("max_input_estimate")
        remaining = self.limits.max_tokens - self.input_tokens - self.output_tokens
        if remaining <= estimate:
            raise BudgetExceeded("max_tokens_preflight")
        return min(requested_output, remaining - estimate)

    def usage(self, input_tokens, output_tokens):
        self.usage_available &= input_tokens is not None and output_tokens is not None
        self.input_tokens += input_tokens or 0
        self.output_tokens += output_tokens or 0
        if self.input_tokens + self.output_tokens > self.limits.max_tokens:
            raise BudgetExceeded("max_tokens")
