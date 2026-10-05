"""`surg next STATE.json` prints one decision for a hand-written screen state."""

import json
from pathlib import Path

import pytest

import cli

# The first screen of a Heart Attack surgery, written by hand.
STATE = {
    "skill_level": 100,
    "modifier": None,
    "special_condition_text": None,
    "scan_text": None,
    "pulse": "strong",
    "status": "awake",
    "temperature": 98.6,
    "site": "not_sanitized",
    "visibility": "clear",
    "incisions": 0,
    "bones": None,
    "bleeding": None,
    "fever": None,
    "last_tool_text": "Patient is prepped for surgery.",
    "usable_tools": ["sponge", "anesthetic", "scalpel", "ultrasound", "antiseptic"],
}


def write(tmp_path: Path, content: object) -> str:
    path = tmp_path / "state.json"
    path.write_text(
        content if isinstance(content, str) else json.dumps(content), encoding="utf-8"
    )
    return str(path)


def test_next_prints_the_decision_as_indented_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["next", write(tmp_path, STATE)]) == 0
    out = capsys.readouterr().out
    decision = json.loads(out)
    assert set(decision) == {"tool", "rule", "reason"}
    assert decision["tool"] in STATE["usable_tools"]
    assert decision["rule"] and decision["reason"]
    assert out.startswith('{\n  "tool": ')  # indent 2


def test_next_starts_with_empty_memory_every_time(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(tmp_path, STATE)
    cli.main(["next", path])
    first = capsys.readouterr().out
    cli.main(["next", path])
    assert capsys.readouterr().out == first


def test_next_never_picks_a_tool_that_is_not_usable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    only_sponge = {**STATE, "usable_tools": ["sponge"]}
    assert cli.main(["next", write(tmp_path, only_sponge)]) == 0
    assert json.loads(capsys.readouterr().out)["tool"] == "sponge"


def test_next_reports_a_schema_error_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = {k: v for k, v in STATE.items() if k != "pulse"}
    assert cli.main(["next", write(tmp_path, broken)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "invalid screen state" in captured.err and "pulse" in captured.err
    assert cli.main(["next", write(tmp_path, {**STATE, "pulse": "loud"})]) == 1
    assert "pulse" in capsys.readouterr().err
    assert cli.main(["next", write(tmp_path, {**STATE, "skill_level": 101})]) == 1
    assert "skill_level" in capsys.readouterr().err


def test_next_reports_invalid_json_and_a_missing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["next", write(tmp_path, "{not json")]) == 1
    assert "not valid JSON" in capsys.readouterr().err
    assert cli.main(["next", str(tmp_path / "missing.json")]) == 1
    assert "cannot read" in capsys.readouterr().err


def test_next_reports_a_json_value_that_is_not_an_object(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["next", write(tmp_path, "[1, 2]")]) == 1
    assert "invalid screen state" in capsys.readouterr().err
