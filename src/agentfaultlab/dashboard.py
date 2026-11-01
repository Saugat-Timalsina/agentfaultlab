"""Read-only playback of actual saved artifacts. No experiment execution here."""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from agentfaultlab.reporting import csv_text, load_results, summarize
from agentfaultlab.tracing import load_trace


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
    for label, field in [
        ("Scenario", "scenario_id"),
        ("Policy", "policy"),
        ("Mode", "mode"),
        ("Fault type", "fault_type"),
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
    chart = pd.DataFrame(
        [
            {
                "policy / mode / model": f"{s.policy} / {s.mode} / {s.model or 'script'}",
                "completion": s.completion_rate,
                "recovery": s.recovery_rate,
            }
            for s in summaries
        ]
    ).set_index("policy / mode / model")
    st.bar_chart(chart, stack=False)
    st.caption("Bars are proportions from 0 to 1. Missing recovery means no activated faults.")
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
            [{"assertion": name, "passed": passed} for name, passed in run.assertions.items()]
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
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "seq": e.seq,
                    "elapsed_s": e.elapsed_s,
                    "duration_s": e.duration_s,
                    "event": e.event_type,
                    "tool": e.tool_name,
                    "call ID": e.call_id,
                    "error": e.error_category,
                    "recovery": e.recovery_action,
                }
                for e in events
            ]
        ),
        hide_index=True,
    )
    for event in events:
        with st.expander(f"{event.seq:03d} · {event.event_type} · {event.tool_name or ''}"):
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
