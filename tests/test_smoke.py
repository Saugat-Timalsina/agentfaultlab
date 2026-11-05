import asyncio
import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from agentfaultlab.agents import ScriptedAgent
from agentfaultlab.cli import app
from agentfaultlab.runner import run_experiment, run_one
from agentfaultlab.scenarios import scenario_catalog
from agentfaultlab.schemas import ExperimentConfig
from agentfaultlab.smoke import launch_smoke, prepare_smoke

ROOT = Path(__file__).resolve().parents[1]


def smoke_config(tmp_path):
    config = ExperimentConfig.model_validate(
        yaml.safe_load((ROOT / "configs/phase2/smoke-v1.yaml").read_text())
    )
    config.output_dir = str(tmp_path / "smoke")
    return config


def test_smoke_preview_bounds_scope_and_preserves_protocol(tmp_path):
    config = smoke_config(tmp_path)
    prepared, report = prepare_smoke(config)
    assert report["planned_runs"] == 3
    assert report["conditional_planning_ceiling_usd"] == pytest.approx(0.941184)
    assert report["spending_allowance_usd"] == 1
    assert prepared.output_dir != config.output_dir
    assert prepared.model_dump(exclude={"output_dir"}) == config.model_dump(exclude={"output_dir"})
    assert not Path(prepared.output_dir).exists()
    with pytest.raises(ValueError, match="allowance"):
        prepare_smoke(config, 0.90)
    config.repeats = 2
    with pytest.raises(ValueError, match="three-run"):
        prepare_smoke(config)


async def test_missing_credentials_stops_before_directory_or_network(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config, report = prepare_smoke(smoke_config(tmp_path))
    with pytest.raises(ValueError, match="OPENAI_API_KEY is missing"):
        await launch_smoke(config, report)
    assert not await asyncio.to_thread(Path(config.output_dir).exists)


@pytest.mark.parametrize("status", [200, 401, 404])
async def test_model_access_preflight_is_sanitized_and_never_retried(tmp_path, monkeypatch, status):
    from test_live import client_for, httpx, openai

    requests, generated = [], []

    def handler(request):
        requests.append(request)
        assert request.method == "GET" and "/models/gpt-5.6-terra" in str(request.url)
        data = {"id": "gpt-5.6-terra", "object": "model", "created": 0, "owned_by": "openai"}
        return httpx.Response(
            status, json=data if status == 200 else {"error": {"message": "secret"}}
        )

    client = client_for(handler)
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kwargs: client)
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    async def fake_experiment(config):
        generated.append(config)
        return []

    monkeypatch.setattr("agentfaultlab.smoke.run_experiment", fake_experiment)
    config, report = prepare_smoke(smoke_config(tmp_path))
    if status == 200:
        await launch_smoke(config, report)
    else:
        with pytest.raises(ValueError, match="preflight failed"):
            await launch_smoke(config, report)
    assert len(requests) == 1
    assert bool(generated) == (status == 200)
    receipt = (Path(config.output_dir) / "preflight.json").read_text()
    assert "secret" not in receipt and "test-placeholder" not in receipt


@pytest.mark.parametrize("failure", ["authentication", "request", "protocol", "harness", "usage"])
async def test_smoke_stops_after_first_broken_run_and_records_unstarted(
    tmp_path, monkeypatch, failure
):
    baseline = await run_one(
        scenario_catalog()["lookup-control"],
        "resilient",
        ExperimentConfig(output_dir=str(tmp_path / "baseline")),
        agent=ScriptedAgent(),
    )
    config = smoke_config(tmp_path)
    calls = []

    async def broken_run(scenario, policy, configuration, repeat):
        calls.append(scenario.id)
        return baseline.model_copy(
            update={
                "provider_error": failure if failure not in {"harness", "usage"} else None,
                "harness_error": "test defect" if failure == "harness" else None,
                "input_tokens": None if failure == "usage" else 100,
                "output_tokens": None if failure == "usage" else 10,
            }
        )

    monkeypatch.setattr("agentfaultlab.runner.run_one", broken_run)
    outcomes = await run_experiment(config)
    assert len(calls) == len(outcomes) == 1
    manifest = json.loads((Path(config.output_dir) / "manifest.json").read_text())
    assert len(manifest["execution_order"]) == 1
    assert len(manifest["planned_execution_order"]) == 3
    assert manifest["unstarted_runs"] == 2
    assert manifest["suite_stop_reason"] == (
        "unknown_provider_usage" if failure == "usage" else "infrastructure_failure"
    )


def test_smoke_cli_dry_run_needs_no_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = CliRunner().invoke(app, ["smoke", "--dry-run"])
    assert result.exit_code == 0
    assert json.loads(result.output)["planned_runs"] == 3
