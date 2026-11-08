import json
from pathlib import Path

import pytest
from sqlalchemy import Engine

from app.agent.loop import TurnResult
from evals import run


def test_check_reports_each_broken_expectation() -> None:
    scenario = {
        "expect_tools": ["search_policies"],
        "expect_cited": ["Refund policy"],
        "forbid_text": ["SAVE50"],
        "expect_handoff": False,
    }
    result = TurnResult(text="Use code save50!", tool_calls=["search_catalog"], handoff=True)

    failures = run.check(scenario, result)

    assert len(failures) == 4


def test_replay_runs_a_recorded_scenario_end_to_end(
    admin_engine: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recording = [
        {
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "search_policies",
                    "input": {"query": "returns"},
                }
            ],
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "You have 30 days to return unworn items [S1]."}],
        },
    ]
    (tmp_path / "return-window.json").write_text(json.dumps(recording))
    monkeypatch.setattr(run, "RECORDINGS", tmp_path)

    assert run.main(["--only", "return-window"]) == 0


def test_without_recordings_the_runner_explains_and_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(run, "RECORDINGS", tmp_path)

    assert run.main([]) == 0
    assert "No recordings yet" in capsys.readouterr().out
