"""Counts, explicit denominators and variability; no composite reliability score."""

import csv
import io
import json
import statistics
from collections import defaultdict
from pathlib import Path

from agentfaultlab.schemas import MetricSummary, RunOutcome


def load_results(directory: Path) -> list[RunOutcome]:
    manifest = directory / "manifest.json"
    if manifest.exists():
        # Only the latest experiment manifest; avoid silently mixing older runs.
        paths = [
            directory / f"{name}.run.json" for name in json.loads(manifest.read_text())["runs"]
        ]
    else:
        paths = sorted(directory.glob("*.run.json"))
    return [RunOutcome.model_validate_json(path.read_text()) for path in paths]


def summarize(outcomes: list[RunOutcome]) -> list[MetricSummary]:
    groups = defaultdict(list)
    for run in outcomes:
        groups[(run.policy, run.mode, run.model)].append(run)
    summaries = []
    for (policy, mode, model), runs in sorted(groups.items(), key=lambda item: str(item[0])):
        n = len(runs)
        completed = sum(r.completed for r in runs)
        activated = sum(r.fault_activations > 0 for r in runs)
        recovered = sum(r.recovered for r in runs)
        failed = n - completed
        safe_failures = sum(r.safe_failure for r in runs)
        # Variability across repeat-level suite rates, not across heterogeneous scenarios.
        repeats = defaultdict(list)
        for r in runs:
            repeats[r.repeat].append(r.completed)
        rates = [statistics.mean(values) for values in repeats.values()]
        sd = statistics.stdev(rates) if len(rates) > 1 else None

        def available_sum(field, runs=runs):
            values = [getattr(r, field) for r in runs]
            return sum(values) if all(v is not None for v in values) else None

        summaries.append(
            MetricSummary(
                policy=policy,
                mode=mode,
                model=model,
                runs=n,
                completed=completed,
                completion_rate=completed / n,
                activated_runs=activated,
                recovered=recovered,
                recovery_rate=recovered / activated if activated else None,
                failed_runs=failed,
                safe_failures=safe_failures,
                safe_failure_rate=safe_failures / failed if failed else None,
                safe_runs=sum(r.safe for r in runs),
                honest_runs=sum(r.honest for r in runs),
                harness_failures=sum(r.harness_error is not None for r in runs),
                duplicate_side_effects=sum(r.duplicate_side_effects for r in runs),
                invalid_tool_calls=sum(r.invalid_tool_calls for r in runs),
                retries=sum(r.retries for r in runs),
                fallbacks=sum(r.fallbacks for r in runs),
                tool_calls=sum(r.tool_calls for r in runs),
                model_calls=sum(r.model_calls for r in runs),
                mean_duration_s=statistics.mean(r.duration_s for r in runs),
                completion_stddev=sd,
                completion_standard_error=sd / len(rates) ** 0.5 if sd is not None else None,
                input_tokens=available_sum("input_tokens"),
                output_tokens=available_sum("output_tokens"),
            )
        )
    return summaries


def csv_text(records: list[dict]) -> str:
    stream = io.StringIO()
    if records:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return stream.getvalue()


def write_report(outcomes: list[RunOutcome], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    summaries = [s.model_dump() for s in summarize(outcomes)]
    (directory / "summary.json").write_text(json.dumps(summaries, indent=2) + "\n")
    (directory / "summary.csv").write_text(csv_text(summaries))
    (directory / "runs.csv").write_text(
        csv_text(
            [
                r.model_dump(
                    exclude={
                        "config",
                        "dependency_versions",
                        "assertions",
                        "actual_state",
                        "expected_state",
                        "fault_planned",
                    }
                )
                for r in outcomes
            ]
        )
    )
