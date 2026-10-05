"""`surg play` and the blank-field rules it shares with the web viewer."""

import json
from pathlib import Path

import pytest

import cli
from harness.runner import resolve_settings
from harness.surge import CONDITION_NAMES, MALADY_NAMES


def test_play_runs_a_surgery_to_its_end(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        [
            "play",
            "--malady",
            "Broken Arm",
            "--condition",
            "none",
            "--skill",
            "100",
            "--seed",
            "3",
        ]
    )
    out = capsys.readouterr().out
    assert code == 0
    assert out.startswith("Broken Arm | none | skill 100 | modifier - | seed 3")
    assert "Turn 0" in out and "-> " in out and "Result: " in out


def test_play_is_repeatable(capsys: pytest.CaptureFixture[str]) -> None:
    args = ["play", "--malady", "Heart Attack", "--skill", "40", "--seed", "7"]
    cli.main(args)
    first = capsys.readouterr().out
    cli.main(args)
    assert capsys.readouterr().out == first


def test_play_writes_one_json_line_per_turn(tmp_path: Path) -> None:
    log = tmp_path / "turns.jsonl"
    cli.main(["play", "--malady", "Nose Job", "--seed", "1", "--log", str(log)])
    records = [
        json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()
    ]
    assert [r["turn"] for r in records] == list(range(len(records)))
    assert records[-1]["ended"] and records[-1]["outcome"]


def test_play_rejects_unknown_names(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["play", "--malady", "Hiccups"]) == 1
    assert "unknown malady" in capsys.readouterr().err
    assert cli.main(["play", "--condition", "grumpy"]) == 1
    assert cli.main(["play", "--policy", "advisor"]) == 1
    assert "M2" in capsys.readouterr().err


def test_blank_fields_are_filled_the_same_way_for_the_same_seed() -> None:
    a, b = resolve_settings(seed=42), resolve_settings(seed=42)
    assert a == b
    assert a.malady in MALADY_NAMES and a.condition in CONDITION_NAMES
    assert 0 <= a.skill <= 100 and a.modifier is None


def test_given_fields_are_kept_and_blank_seed_is_chosen() -> None:
    settings = resolve_settings("Heart Attack", "filthy", 0, "tea")
    assert (settings.malady, settings.condition, settings.skill) == (
        "Heart Attack",
        "filthy",
        0,
    )
    assert settings.modifier == "tea" and settings.seed >= 0
