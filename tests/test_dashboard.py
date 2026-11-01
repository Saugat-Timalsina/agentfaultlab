import asyncio
from pathlib import Path

from streamlit.testing.v1 import AppTest

from agentfaultlab.runner import run_experiment
from agentfaultlab.schemas import ExperimentConfig


def test_dashboard_load_filters_playback_and_empty_state(tmp_path):
    asyncio.run(run_experiment(ExperimentConfig(output_dir=str(tmp_path))))
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    # First import of dataframe/chart wheels can exceed Streamlit's three-second default.
    app = AppTest.from_file(str(app_path), default_timeout=20).run()
    app.sidebar.text_input[0].set_value(str(tmp_path)).run()
    assert not app.exception
    assert len(app.dataframe) >= 3
    app.sidebar.multiselect(key="scenario_id").set_value(["creation-commit-timeout"]).run()
    app.sidebar.multiselect(key="policy").set_value(["resilient"]).run()
    assert not app.exception
    comparison = app.dataframe[0].value
    assert comparison.iloc[0]["completed / runs"] == "1/1"
    assert len(app.selectbox[0].options) == 1
    app.sidebar.text_input[0].set_value(str(tmp_path / "empty")).run()
    assert not app.exception
    assert any("No saved runs" in info.value for info in app.info)
