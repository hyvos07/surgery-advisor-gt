"""The death lookback: avoidable at an earlier turn, found by playing branches on."""

from typing import Any

import pytest

import cli
from harness.bench import Grid, _check_comparable, run_cell, run_grid
from harness.runner import (
    AVOIDABLE_DEATH,
    UNLUCKY_DEATH,
    AdvisorPolicy,
    Result,
    Settings,
    Surgery,
    policy_by_name,
    run_surgery,
)

HEART_ATTACK = ("Heart Attack", "none", 0, None)
SMALL = Grid(("Broken Arm", "Heart Attack"), ("none",), (0,), (None,))


def play(name: str, seed: int, lookback: int) -> Result:
    settings = Settings(*HEART_ATTACK[:3], HEART_ATTACK[3], seed)
    return run_surgery(settings, policy_by_name(name), name, lookback=lookback)


def fields(result: Result) -> tuple[str, int | None, str | None]:
    return result.outcome, result.mistake_turns_back, result.alternative


# Baseline, Heart Attack, no condition, skill 0: what lookback 1 (the one-turn
# check) says, and what lookback 3 says. Found by scanning seeds 0 to 39.
BASELINE_LOOKBACK_1 = {
    3: (AVOIDABLE_DEATH, 0, "transfusion"),  # avoidable at the fatal turn
    12: (UNLUCKY_DEATH, None, None),
    19: (UNLUCKY_DEATH, None, None),  # a turn earlier would have saved it
    26: (UNLUCKY_DEATH, None, None),
    35: (UNLUCKY_DEATH, None, None),
}


@pytest.mark.parametrize("seed", BASELINE_LOOKBACK_1)
def test_lookback_1_is_the_one_turn_check(seed: int) -> None:
    assert fields(play("baseline", seed, 1)) == BASELINE_LOOKBACK_1[seed]


def test_lookback_is_one_by_default() -> None:
    settings = Settings(*HEART_ATTACK[:3], HEART_ATTACK[3], 19)
    default = run_surgery(settings, policy_by_name("baseline"), "baseline")
    assert fields(default) == BASELINE_LOOKBACK_1[19]


def test_lookback_3_turns_an_unlucky_death_avoidable() -> None:
    assert fields(play("baseline", 19, 3)) == (AVOIDABLE_DEATH, 1, "stitches")
    assert fields(play("baseline", 35, 3)) == (AVOIDABLE_DEATH, 1, "clamp")
    # The advisor too: two turns before the fatal one a Sponge would have won.
    assert fields(play("advisor", 8, 3)) == (AVOIDABLE_DEATH, 2, "sponge")


def test_lookback_3_keeps_what_lookback_1_already_found() -> None:
    assert fields(play("baseline", 3, 3)) == (AVOIDABLE_DEATH, 0, "transfusion")


def test_lookback_3_leaves_a_hopeless_death_unlucky() -> None:
    assert fields(play("baseline", 12, 3)) == (UNLUCKY_DEATH, None, None)
    assert fields(play("advisor", 10, 3)) == (UNLUCKY_DEATH, None, None)


def test_a_longer_lookback_only_adds_avoidable_deaths() -> None:
    for seed in range(40):
        short, long = play("baseline", seed, 1), play("baseline", seed, 3)
        assert short.turns == long.turns
        if short.outcome == AVOIDABLE_DEATH:
            assert fields(short) == fields(long)


def test_the_new_fields_are_none_when_nothing_died() -> None:
    result = run_surgery(
        Settings("Broken Arm", "none", 100, seed=0),
        policy_by_name("advisor"),
        lookback=3,
    )
    assert result.mistake_turns_back is None and result.alternative is None


def test_an_illegal_move_is_avoidable_with_no_turn_or_tool() -> None:
    # A death after an illegal move: Defibrillator first, then a fatal Scalpel.
    for seed in range(20):
        r = run_surgery(
            Settings("Heart Attack", "none", 100, seed=seed),
            lambda s, p: {
                "tool": "defibrillator"
                if s["last_tool_text"] == "Patient is prepped for surgery."
                else "scalpel",
                "rule": "T0",
                "reason": "t",
            },
            lookback=3,
        )
        if r.outcome == AVOIDABLE_DEATH:
            assert r.illegal_moves == 1 and fields(r) == (AVOIDABLE_DEATH, None, None)
            return
    pytest.fail("no seed died")


def test_same_settings_and_lookback_give_the_same_fields() -> None:
    for name, seed in (("baseline", 19), ("advisor", 8), ("baseline", 12)):
        assert fields(play(name, seed, 3)) == fields(play(name, seed, 3))


def test_the_replay_reaches_the_same_screens_as_the_surgery() -> None:
    settings = Settings(*HEART_ATTACK[:3], HEART_ATTACK[3], 8)
    surgery = Surgery(settings, policy_by_name("advisor"), "advisor", lookback=3)
    states: list[Any] = []
    while not surgery.ended:
        states.append(surgery.state)
        surgery.step()
    for turn in range(len(states)):
        assert surgery._replay_to(turn).state == states[turn]


def test_a_death_on_the_first_turns_looks_back_only_as_far_as_there_are_turns() -> None:
    result = run_surgery(
        Settings("Heart Attack", "none", 100, seed=0),
        lambda s, p: {"tool": "scalpel", "rule": "T0", "reason": "t"},
        lookback=10,
    )
    assert result.outcome == AVOIDABLE_DEATH and result.turns == 1


def test_note_override_makes_memory_confirm_the_replaced_tool() -> None:
    lab_kit = (
        "You performed lab work on the patient, and have antibiotics at the ready."
    )
    surgery = Surgery(Settings("Heart Attack", "none", 100, seed=1), AdvisorPolicy())
    policy = surgery.policy
    assert isinstance(policy, AdvisorPolicy)
    assert policy.memory.last_decision is not None
    picked = policy.memory.last_decision.tool.value
    assert picked != "lab_kit"

    shown = dict(surgery.state, last_tool_text=lab_kit)
    control = AdvisorPolicy()
    control(surgery.state, surgery.patient)
    control(shown, surgery.patient)
    assert not control.memory.lab_kit_done  # the engine's own pick was not Lab Kit

    policy.note_override("lab_kit")
    assert policy.memory.last_decision is not None
    assert policy.memory.last_decision.tool.value == "lab_kit"
    assert policy.memory.last_decision.rule == "X0"
    policy(shown, surgery.patient)
    assert policy.memory.lab_kit_done


def test_step_with_an_override_applies_it_and_tells_the_policy() -> None:
    surgery = Surgery(Settings("Heart Attack", "none", 100, seed=1), AdvisorPolicy())
    record = surgery.step(override="sponge")
    assert record["applied_tool"] == "sponge" and record["decision"]["rule"] == "X0"


def test_lookback_below_one_is_refused() -> None:
    settings = Settings("Heart Attack", seed=0)
    with pytest.raises(ValueError, match="lookback"):
        Surgery(settings, policy_by_name("baseline"), lookback=0)
    with pytest.raises(ValueError, match="lookback"):
        run_grid("baseline", 1, SMALL, workers=1, lookback=0)


def test_bench_cli_refuses_lookback_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["bench", "--runs", "1", "--lookback", "0"]) == 1
    assert "--lookback" in capsys.readouterr().err


def test_play_prints_the_two_fields_for_a_death(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = ["play", "--malady", "Heart Attack", "--condition", "none", "--skill", "0"]
    code = cli.main([*args, "--seed", "19", "--policy", "baseline", "--lookback", "3"])
    assert code == 0
    out = capsys.readouterr().out
    assert "mistake_turns_back 1, alternative stitches" in out


def test_play_rejects_lookback_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["play", "--seed", "1", "--lookback", "0"]) == 1
    assert "lookback" in capsys.readouterr().err


def test_a_bench_cell_records_the_fields_on_each_death() -> None:
    cell = run_cell(("baseline", HEART_ATTACK, 40, 3))
    deaths = {d["seed"]: d for d in cell["deaths"]}
    assert deaths[19]["mistake_turns_back"] == 1
    assert deaths[19]["alternative"] == "stitches"
    assert deaths[12]["mistake_turns_back"] is None
    assert deaths[12]["alternative"] is None
    assert all({"mistake_turns_back", "alternative"} <= set(d) for d in deaths.values())


def test_the_report_records_the_lookback() -> None:
    assert run_grid("baseline", 1, SMALL, workers=1)["meta"]["lookback"] == 1
    assert (
        run_grid("baseline", 1, SMALL, workers=1, lookback=3)["meta"]["lookback"] == 3
    )


def test_reports_with_different_lookbacks_are_not_comparable() -> None:
    one = run_grid("baseline", 1, SMALL, workers=1)
    three = run_grid("baseline", 1, SMALL, workers=1, lookback=3)
    with pytest.raises(ValueError, match="lookback differs"):
        _check_comparable(one, three)
    _check_comparable(three, three)


def test_a_report_without_the_key_counts_as_lookback_one() -> None:
    one = run_grid("baseline", 1, SMALL, workers=1)
    old = {**one, "meta": {k: v for k, v in one["meta"].items() if k != "lookback"}}
    _check_comparable(one, old)
    three = run_grid("baseline", 1, SMALL, workers=1, lookback=3)
    with pytest.raises(ValueError, match="lookback differs"):
        _check_comparable(three, old)
