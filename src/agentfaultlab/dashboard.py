"""Read-only playback of actual saved artifacts. No experiment execution here."""

import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from agentfaultlab.reporting import csv_text, load_results, summarize
from agentfaultlab.tracing import load_trace

POLICY_LABELS = {
    "fail_fast": "Fail fast",
    "bounded_retry": "Bounded retry",
    "resilient": "Resilient",
}


def percentage_chart(summaries, metric):
    title = {
        "completion_rate": "Completed / all selected runs (%)",
        "recovery_rate": "Recovered / activated fault runs (%)",
    }[metric]
    data = []
    for summary in summaries:
        value = getattr(summary, metric)
        if value is not None:
            data.append(
                {
                    "configuration": f"{POLICY_LABELS[summary.policy]} · {summary.mode} · "
                    f"{summary.experiment_kind} · {summary.artifact_version} · "
                    f"{summary.model or 'script'}",
                    "percentage": value * 100,
                }
            )
    return (
        alt.Chart(pd.DataFrame(data, columns=["configuration", "percentage"]))
        .mark_bar()
        .encode(
            x=alt.X(
                "configuration:N",
                title="Agent + middleware",
                axis=alt.Axis(labelAngle=-15, labelLimit=500),
            ),
            y=alt.Y(
                "percentage:Q",
                title=title,
                scale=alt.Scale(domain=[0, 100], nice=False, clamp=False),
                axis=alt.Axis(values=[0, 25, 50, 75, 100]),
            ),
            tooltip=["configuration:N", alt.Tooltip("percentage:Q", format=".1f")],
        )
        .properties(height=280, title=title)
    )


def main():
    st.set_page_config(page_title="AgentFaultLab", page_icon="🧪", layout="wide")
    st.title("AgentFaultLab")
    st.caption("Controlled tool faults · evidence-backed outcomes · saved-run playback")
    st.info(
        "Scripted results exercise software and predefined policies. They do not measure "
        "LLM intelligence. Live results are labeled separately."
    )
    directory = Path(st.sidebar.text_input("Results directory", "results/demo")).expanduser()
    try:
        outcomes = load_results(directory)
    except (OSError, ValueError, KeyError) as exc:
        st.error(f"Could not read experiment artifacts: {exc}")
        return
    if not outcomes:
        st.info("No saved runs found. Run `agentfaultlab demo` in the terminal first.")
        return
    selected = outcomes
    if st.session_state.get("_filter_directory") != str(directory):
        for field in (
            "scenario_id",
            "policy",
            "mode",
            "fault_type",
            "artifact_version",
            "experiment_kind",
        ):
            st.session_state.pop(field, None)
        st.session_state["_filter_directory"] = str(directory)
    for label, field in [
        ("Scenario", "scenario_id"),
        ("Policy", "policy"),
        ("Mode", "mode"),
        ("Fault type", "fault_type"),
        ("Artifact version", "artifact_version"),
        ("Experiment kind", "experiment_kind"),
    ]:
        options = sorted({getattr(r, field) for r in outcomes})
        values = st.sidebar.multiselect(label, options, default=options, key=field)
        selected = [r for r in selected if getattr(r, field) in values]
    condition = st.sidebar.radio("Condition", ["All", "Fault-free controls", "Faulted cases"])
    if condition != "All":
        controls = condition == "Fault-free controls"
        selected = [r for r in selected if (r.fault_type == "control") == controls]
    if not selected:
        st.info("No runs match these filters.")
        return
    summaries = summarize(selected)
    if len(selected) < 15 or any(s.runs < 5 for s in summaries):
        st.warning(
            "Too little evidence for a stable comparison. Small filtered samples do not "
            "support rankings or broad robustness claims."
        )
    st.subheader("Outcome summary")
    st.write(
        f"{sum(r.completed for r in selected)}/{len(selected)} completed; "
        f"{sum(r.fault_activations > 0 for r in selected)}/"
        f"{sum(r.fault_planned is not None for r in selected)} faulted runs activated; "
        f"{sum(not r.honest for r in selected)} unsupported success claims; "
        f"{sum(r.uncertain for r in selected)} uncertain outcomes."
    )
    st.subheader("Policy comparison")
    st.caption(
        f"{len(selected)} saved runs. Recovery uses activated fault runs only. "
        "Filter controls and faulted cases separately to compare conditions."
    )
    records = [s.model_dump() for s in summaries]
    table = pd.DataFrame(
        [
            {
                "policy": s.policy,
                "mode": s.mode,
                "model": s.model or "N/A",
                "artifact version": s.artifact_version,
                "experiment kind": s.experiment_kind,
                "activated / faulted": f"{s.activated_runs}/{s.faulted_runs}",
                "activated rules / planned rules": (
                    f"{s.fault_rules_activated}/{s.fault_rules_planned}"
                ),
                "activation coverage %": s.activation_coverage * 100
                if s.activation_coverage is not None
                else None,
                "unsupported claims": s.unsupported_claims,
                "provider errors": s.provider_failures,
                "uncertain runs": s.uncertain_runs,
                "completion 95% interval": str([round(100 * x, 1) for x in s.completion_interval]),
                "completed / runs": f"{s.completed}/{s.runs}",
                "completion %": 100 * s.completion_rate,
                "recovered / activated": f"{s.recovered}/{s.activated_runs}",
                "recovery %": 100 * s.recovery_rate if s.recovery_rate is not None else None,
                "safe failures / failed": f"{s.safe_failures}/{s.failed_runs}",
                "safe failure %": 100 * s.safe_failure_rate
                if s.safe_failure_rate is not None
                else None,
                "safe runs": s.safe_runs,
                "honest runs": s.honest_runs,
                "duplicates": s.duplicate_side_effects,
                "invalid calls": s.invalid_tool_calls,
                "agent invalid calls": s.agent_invalid_calls,
                "injected invalid calls": s.injected_invalid_calls,
                "retries": s.retries,
                "fallbacks": s.fallbacks,
                "tool calls": s.tool_calls,
                "model calls": s.model_calls,
                "mean seconds": s.mean_duration_s,
                "completion repeat SD": s.completion_stddev,
                "input tokens": s.input_tokens,
                "output tokens": s.output_tokens,
                "harness failures": s.harness_failures,
            }
            for s in summaries
        ]
    )
    st.dataframe(table, hide_index=True)
    st.altair_chart(percentage_chart(summaries, "completion_rate"))
    st.altair_chart(percentage_chart(summaries, "recovery_rate"))
    st.caption(
        "Separate denominators; axes fixed at 0–100%. Missing recovery bars mean no "
        "activated faults. Completion Wilson intervals are descriptive, not a ranking."
    )
    st.write({s.policy + " / " + s.experiment_kind: s.termination_reasons for s in summaries})
    st.download_button(
        "Export filtered comparison CSV", csv_text(records), "comparison.csv", mime="text/csv"
    )
    st.subheader("Run playback")
    run_id = st.selectbox("Saved run", [r.run_id for r in selected])
    run = next(r for r in selected if r.run_id == run_id)
    st.write(
        f"**{run.mode.upper()}** · {run.scenario_id} · {run.policy} · "
        f"model: {run.model or 'scripted baseline'} · stop: {run.stop_reason}"
    )
    st.write(
        {
            "completed": run.completed,
            "safe": run.safe,
            "honest": run.honest,
            "fault activations": run.fault_activations,
            "harness error": run.harness_error,
        }
    )
    expected, actual = st.columns(2)
    expected.write("Expected state")
    expected.json(run.expected_state)
    actual.write("Actual final state")
    actual.json(run.actual_state)
    failures = [name for name, passed in run.assertions.items() if not passed]
    if failures:
        st.warning("Failed assertions: " + ", ".join(failures))
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "assertion": name,
                    "passed": passed,
                    "expected": json.dumps(
                        run.assertion_details.get(name, {}).get("expected", "legacy")
                    ),
                    "observed": json.dumps(
                        run.assertion_details.get(name, {}).get("observed", "legacy")
                    ),
                }
                for name, passed in run.assertions.items()
            ]
        ),
        hide_index=True,
    )
    st.write({"final status": run.final_status, "final answer": run.final_answer})
    try:
        trace_path = directory / run.trace_file
        events = load_trace(trace_path)
    except (OSError, ValueError) as exc:
        st.error(f"Trace unavailable: {exc}")
        return
    focus = st.checkbox("Focus on faults and recovery", value=True)
    displayed = [
        e
        for e in events
        if not focus
        or e.event_type
        in {
            "agent_decision",
            "tool_call",
            "fault_activated",
            "environment_commit",
            "observed_result",
            "recovery",
            "middleware_result",
            "reconciliation_unresolved",
            "agent_observation",
            "tool_call_skipped",
            "budget_exhausted",
            "provider_failure",
            "verified_outcome",
        }
    ]
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "seq": e.seq,
                    "owner": e.owner or "legacy / harness",
                    "root call": e.root_call_id,
                    "parent call": e.parent_call_id,
                    "attempt": e.attempt,
                    "elapsed_s": e.elapsed_s,
                    "duration_s": e.duration_s,
                    "event": e.event_type,
                    "tool": e.tool_name,
                    "call ID": e.call_id,
                    "error": e.error_category,
                    "recovery": e.recovery_action,
                }
                for e in displayed
            ]
        ),
        hide_index=True,
    )
    for event in events:
        with st.expander(
            f"{event.seq:03d} · {event.event_type} · {event.owner or 'harness'} · "
            f"{event.tool_name or ''}"
        ):
            st.json(event.model_dump())
    st.download_button(
        "Export selected trace JSONL",
        trace_path.read_text(),
        trace_path.name,
        mime="application/x-ndjson",
    )
    st.download_button(
        "Export selected run JSON",
        json.dumps(run.model_dump(), indent=2),
        f"{run.run_id}.run.json",
        mime="application/json",
    )
