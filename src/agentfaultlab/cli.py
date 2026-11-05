"""Local commands. Playback reads saved data and never calls a model."""

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from agentfaultlab.planning import preview
from agentfaultlab.reporting import load_results, summarize, write_report
from agentfaultlab.runner import run_experiment
from agentfaultlab.schemas import ExperimentConfig, RunOutcome
from agentfaultlab.tracing import load_trace

app = typer.Typer(no_args_is_help=True, help="AgentFaultLab — controlled local tool faults.")


def execute(config: ExperimentConfig, allow_paid=False):
    if config.mode == "live":
        import os

        if not allow_paid:
            raise typer.BadParameter(
                "Paid execution requires --allow-paid and OPENAI_API_KEY. "
                "Use --dry-run to inspect the prepared configuration."
            )
        if not os.environ.get("OPENAI_API_KEY"):
            raise typer.BadParameter("Live mode requires OPENAI_API_KEY in the environment.")
    if config.mode == "live" and config.experiment_kind == "smoke":
        from agentfaultlab.smoke import launch_smoke, prepare_smoke

        config, report = prepare_smoke(config)
        typer.echo(json.dumps(report, indent=2))
        outcomes = asyncio.run(launch_smoke(config, report))
    else:
        outcomes = asyncio.run(run_experiment(config))
    typer.echo(f"{len(outcomes)} {config.mode} runs saved to {Path(config.output_dir).resolve()}")
    display(outcomes)
    if config.experiment_kind == "smoke" and smoke_failed(outcomes):
        raise typer.Exit(1)


def smoke_failed(outcomes):
    return len(outcomes) != 3 or any(
        o.provider_error or o.harness_error or o.input_tokens is None or o.output_tokens is None
        for o in outcomes
    )


def display(outcomes):
    for summary in summarize(outcomes):
        recovery = (
            (f"{summary.recovered}/{summary.activated_runs} ({summary.recovery_rate:.1%})")
            if summary.recovery_rate is not None
            else "N/A"
        )
        typer.echo(
            f"{summary.policy} [{summary.mode}] completion "
            f"{summary.completed}/{summary.runs} ({summary.completion_rate:.1%}); "
            f"recovery {recovery}; safe failures {summary.safe_failures}/{summary.failed_runs}; "
            f"duplicates {summary.duplicate_side_effects}"
        )


@app.command()
def demo(output: Annotated[Path, typer.Option()] = Path("results/offline-v2")):
    """Run 45 offline scripted experiments (12 fault cases + 3 controls, 3 policies)."""
    execute(ExperimentConfig(output_dir=str(output), experiment_kind="scripted"))


@app.command()
def run(
    config: Annotated[Path, typer.Option(exists=True)],
    dry_run: Annotated[bool, typer.Option()] = False,
    allow_paid: Annotated[bool, typer.Option()] = False,
):
    """Run an explicitly validated YAML experiment configuration."""
    try:
        configuration = ExperimentConfig.model_validate(yaml.safe_load(config.read_text()))
        if dry_run:
            typer.echo(json.dumps(preview(configuration), indent=2))
        else:
            execute(configuration, allow_paid)
    except (ValueError, yaml.YAMLError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def smoke(
    config: Annotated[Path, typer.Option(exists=True)] = Path("configs/phase2/smoke-v1.yaml"),
    dry_run: Annotated[bool, typer.Option()] = False,
    allow_paid: Annotated[bool, typer.Option()] = False,
    spending_allowance: Annotated[float, typer.Option()] = 1.0,
):
    """Launch only the prepared three-run smoke test in a new timestamped directory."""
    from agentfaultlab.smoke import launch_smoke, prepare_smoke

    try:
        configuration = ExperimentConfig.model_validate(yaml.safe_load(config.read_text()))
        configuration, report = prepare_smoke(configuration, spending_allowance)
        typer.echo(json.dumps(report, indent=2))
        if dry_run:
            return
        if not allow_paid:
            raise ValueError("Generation requires explicit --allow-paid; preview with --dry-run")
        outcomes = asyncio.run(launch_smoke(configuration, report))
        typer.echo(f"{len(outcomes)}/3 smoke runs saved to {configuration.output_dir}")
        display(outcomes)
        if smoke_failed(outcomes):
            raise typer.Exit(1)
    except (ValueError, OSError, yaml.YAMLError) as exc:
        raise typer.BadParameter(str(exc)) from exc


@app.command()
def compare(results: Annotated[Path, typer.Option(exists=True, file_okay=False)]):
    """Rebuild JSON/CSV comparisons using the latest experiment manifest."""
    outcomes = load_results(results)
    write_report(outcomes, results)
    display(outcomes)


@app.command()
def inspect(run_file: Annotated[Path, typer.Argument(exists=True)]):
    """Playback a saved .run.json or .jsonl file; no execution or network access."""
    if run_file.name.endswith(".run.json"):
        outcome = RunOutcome.model_validate_json(run_file.read_text())
        typer.echo(f"{outcome.scenario_id} [{outcome.mode}] {outcome.policy}")
        typer.echo(
            json.dumps(
                {
                    "expected": outcome.expected_state,
                    "actual": outcome.actual_state,
                    "assertions": outcome.assertions,
                },
                indent=2,
            )
        )
        path = run_file.parent / outcome.trace_file
    else:
        path = run_file
    for event in load_trace(path):
        typer.echo(
            f"{event.seq:03d} {event.elapsed_s:.4f}s {event.event_type} "
            f"{event.tool_name or ''} {event.recovery_action or ''} "
            f"{json.dumps(event.payload)}"
        )


if __name__ == "__main__":
    app()
