# Related work

Bounded official-documentation review: **2026-11-01**. These projects were read for positioning;
they are not dependencies and were not benchmarked against AgentFaultLab.

| Project | Overlap supported by its official documentation | AgentFaultLab focus and limits |
| --- | --- | --- |
| [Strands Agents chaos testing](https://strandsagents.com/docs/user-guide/evals-sdk/chaos_testing/) | `ChaosPlugin`, `ChaosCase`, and `ChaosExperiment` inject failures such as timeouts, errors and corrupted tool responses. This directly overlaps controlled agent fault testing. | A small provider-independent boundary, resettable synthetic state, explicit occurrence schedules, and a write-commit/lost-response teaching case. This is not a claim that Strands lacks those capabilities or that this project invented chaos testing. |
| [OpenAI Agents SDK testing](https://openai.github.io/openai-agents-python/testing/) | Scripted models exercise real SDK loops and tool workflows without model requests; the docs distinguish normalized workflow tests from provider-wire tests. | An independent Python loop with fault selection, explicit policy comparison, and local state assertions. The optional adapter uses the OpenAI API directly; it does not test or replace the full Agents SDK. |
| [Inspect AI](https://inspect.aisi.org.uk/) | General evaluation framework with datasets, agents, tools, scorers, and log-viewing tooling. | A deliberately narrow local fault/recovery experiment suite with a small dashboard. It does not offer Inspect's breadth of evals, providers, sandboxing, or ecosystem. |
| [Microsoft AgentRx](https://www.microsoft.com/en-us/research/blog/systematic-debugging-for-ai-agents-introducing-the-agentrx-framework/) | Diagnoses failed trajectories using normalized traces, generated constraints, guarded evaluation, and an LLM judge to identify a critical failure step. | Injects known controlled faults prospectively and scores synthetic final state deterministically. It does not synthesize constraints, implement an LLM failure judge, or claim automated root-cause diagnosis. |

AgentFaultLab is **a local experiment lab for injecting controlled tool faults, comparing
recovery policies, and inspecting evidence-backed agent outcomes**. It is a portfolio and
learning implementation, not the first fault-testing framework or a validated replacement
for the systems above. Scripted results measure this harness and curated policies, not model intelligence.

Implementation references checked before implementation:

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling):
  native tool schemas, assistant calls, tool result IDs and message ordering.
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs):
  validated terminal JSON. An account-accessible compatible model must be configured explicitly.
- [Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/):
  input/output type validation without silent coercion.
- [Typer tutorial](https://typer.tiangolo.com/tutorial/): typed CLI arguments and options.
- [pytest invocation](https://docs.pytest.org/en/stable/how-to/usage.html): local test execution.
- [Streamlit download button](https://docs.streamlit.io/develop/api-reference/widgets/st.download_button):
  exporting saved comparisons and traces.

APIs and dependency versions can change. Installed versions are captured in run records and
`requirements-lock.txt`. Provider serialization was tested with a mocked HTTP transport;
no actual live-model behavior was evaluated in this implementation session.
