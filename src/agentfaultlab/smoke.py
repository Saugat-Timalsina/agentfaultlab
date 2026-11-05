"""Guarded launch of the existing three-run smoke protocol; no automatic reruns."""

import asyncio
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path

from agentfaultlab.planning import build_schedule, preview
from agentfaultlab.runner import run_experiment

SMOKE_SCENARIOS = {
    "lookup-control",
    "lookup-exception",
    "correlation-write-lost-response",
}


def prepare_smoke(config, spending_allowance=1.0):
    schedule = build_schedule(config)
    if (
        config.mode != "live"
        or config.experiment_kind != "smoke"
        or len(schedule) != 3
        or {name for name, _, _ in schedule} != SMOKE_SCENARIOS
        or config.policies != ["resilient"]
    ):
        raise ValueError("This launcher permits only the prepared three-run resilient smoke test")
    report = preview(config)
    ceiling = report["conditional_planning_ceiling_usd"]
    if (
        not math.isfinite(spending_allowance)
        or not 0 < spending_allowance <= 1.0
        or ceiling is None
        or not math.isfinite(ceiling)
        or ceiling > spending_allowance
    ):
        raise ValueError("Sourced conservative cost estimate must fit the allowance (at most $1)")
    if config.pricing.source_url != (
        f"https://developers.openai.com/api/docs/models/{config.model}"
    ):
        raise ValueError("Smoke pricing must cite the configured model's official source")
    # Preserve the prepared configuration and its seeded schedule. Only the output path changes.
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    config = config.model_copy(update={"output_dir": f"{config.output_dir}-{stamp}"}, deep=True)
    report = preview(config)
    report["spending_allowance_usd"] = spending_allowance
    report["model_access"] = "unverified; checked before generation when credentials are present"
    return config, report


async def launch_smoke(config, report):
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise ValueError("OPENAI_API_KEY is missing; no model access or generation request made")
    if os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/") != (
        "https://api.openai.com/v1"
    ):
        raise ValueError("Smoke pricing/access checks require the official OpenAI API endpoint")
    from openai import APIError, AsyncOpenAI

    output = Path(config.output_dir)
    # Never overwrite a previous attempt.
    await asyncio.to_thread(output.mkdir, parents=True, exist_ok=False)
    preflight = {**report, "model_access": "not_checked", "run_execution_started": False}
    receipt = output / "preflight.json"
    receipt.write_text(json.dumps(preflight, indent=2) + "\n")
    client = AsyncOpenAI(max_retries=0, timeout=config.budgets.model_timeout_s)
    try:
        model = await asyncio.wait_for(
            client.models.retrieve(config.model), timeout=config.budgets.model_timeout_s
        )
        if model.id != config.model:
            raise ValueError("Model-access response did not match the configured model")
        preflight["model_access"] = "available"
    except (APIError, TimeoutError) as exc:
        # Never persist provider messages, headers, credentials or account details.
        preflight["model_access"] = "failed"
        preflight["error_type"] = type(exc).__name__
        raise ValueError(f"Model access preflight failed ({type(exc).__name__}); stopped") from None
    finally:
        receipt.write_text(json.dumps(preflight, indent=2) + "\n")
        await client.close()
    # Access metadata does not establish support for every request setting. A rejected setting
    # in the first generation request is a provider error and stops the experiment immediately.
    preflight["run_execution_started"] = True
    receipt.write_text(json.dumps(preflight, indent=2) + "\n")
    return await run_experiment(config)
