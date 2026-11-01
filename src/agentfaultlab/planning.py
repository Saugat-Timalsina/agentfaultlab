"""No-network experiment schedules and explicitly sourced cost assumptions."""

import random

from agentfaultlab.scenarios import scenario_catalog


def build_schedule(config):
    catalog = scenario_catalog()
    names = (
        [
            n
            for n, s in catalog.items()
            if config.suite_version == "phase2-v1" or s.suite_version == "phase1"
        ]
        if config.scenarios == ["all"]
        else config.scenarios
    )
    missing = set(names) - catalog.keys()
    if missing:
        raise ValueError(f"Unknown scenarios: {sorted(missing)}")
    schedule = [
        (name, policy, repeat)
        for repeat in range(config.repeats)
        for name in names
        for policy in config.policies
    ]
    if config.experiment_kind == "pilot" and len(schedule) > 60:
        raise ValueError("Pilot protocol permits at most 60 runs")
    if config.shuffle:
        random.Random(config.seed).shuffle(schedule)
    return schedule


def token_cost(pricing, input_tokens, output_tokens):
    if pricing is None or input_tokens is None or output_tokens is None:
        return None
    return (
        input_tokens * pricing.input_per_million + output_tokens * pricing.output_per_million
    ) / 1_000_000


def preview(config):
    schedule = build_schedule(config)
    n, limits = len(schedule), config.budgets
    estimate_in = n * config.estimated_requests_per_run * config.estimated_input_per_request
    estimate_out = n * config.estimated_requests_per_run * config.estimated_output_per_request
    ceiling_in = n * limits.max_model_calls * limits.max_input_estimate
    ceiling_out = n * limits.max_model_calls * limits.max_output_tokens
    return {
        "provider": "openai" if config.mode == "live" else "none",
        "model": config.model,
        "mode": config.mode,
        "experiment_kind": config.experiment_kind,
        "protocol_version": config.protocol_version,
        "planned_runs": n,
        "shuffle_seed": config.seed if config.shuffle else None,
        "per_run_limits": limits.model_dump(),
        "output_directory": config.output_dir,
        "usage_assumptions": {
            "requests_per_run": config.estimated_requests_per_run,
            "input_tokens_per_request": config.estimated_input_per_request,
            "output_tokens_per_request": config.estimated_output_per_request,
        },
        "estimated_input_tokens": estimate_in if config.mode == "live" else None,
        "estimated_output_tokens": estimate_out if config.mode == "live" else None,
        "estimated_cost_usd": token_cost(config.pricing, estimate_in, estimate_out)
        if config.mode == "live"
        else None,
        "conditional_planning_ceiling_usd": token_cost(
            config.pricing,
            ceiling_in * (config.pricing.cache_write_multiplier if config.pricing else 1),
            ceiling_out,
        )
        if config.mode == "live"
        else None,
        "pricing": config.pricing.model_dump() if config.pricing else None,
        "billing_cap_guaranteed": False,
        "ceiling_conditions": "Assumes actual prompt tokens do not exceed enforced UTF-8 byte "
        "estimate + framing allowance; no cache discount, no SDK retries, configured output "
        "caps honored. Provider tokenization/accounting can differ. Not a billing guarantee.",
        "schedule": [{"scenario": n, "policy": p, "repeat": r} for n, p, r in schedule],
    }
