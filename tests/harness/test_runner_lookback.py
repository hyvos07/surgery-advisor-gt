"""The death lookback: avoidable at an earlier turn, found by playing branches on."""

import copy
import random
from typing import Any

import pytest

import cli
from harness import runner
from harness.bench import Grid, _check_comparable, run_cell, run_grid
from harness.runner import (
    AVOIDABLE_DEATH,
    BRANCH_WINS_NEEDED,
    SUCCESS,
    UNLUCKY_DEATH,
    AdvisorPolicy,
    Result,
    Settings,
    Surgery,
    _rollouts,
    policy_by_name,
    rollout_rng,
    run_surgery,
)

HEART_ATTACK = ("Heart Attack", "none", 0, None)
SMALL = Grid(("Broken Arm", "Heart Attack"), ("none",), (0,), (None,))


def play(name: str, seed: int, lookback: int) -> Result:
    settings = Settings(*HEART_ATTACK[:3], HEART_ATTACK[3], seed)
    return run_surgery(settings, policy_by_name(name), name, lookback=lookback)


def fields(result: Result) -> tuple[str, int | None, str | None]:
    return result.outcome, result.mistake_turns_back, result.alternative


# Baseline, Heart Attack, no condition, skill 0: what lookback 1 (the shared-roll test
# at the fatal turn only) says. Found by scanning seeds 0 to 39. Seed 3 was avoidable
# (Transfusion) under the pre-D23 rule, where another tool only had to survive the
# fatal turn; with the shared rolls and the original-tool control it is luck.
BASELINE_LOOKBACK_1 = {
    3: (UNLUCKY_DEATH, None, None),  # was (AVOIDABLE_DEATH, 0, "transfusion")
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


# Pinned by scanning seeds: the advisor at Heart Attack, no condition, skill 50, and
# at Fatty Liver. Both deaths were unlucky at lookback 1.
# (Re-pinned after D25: Heart Attack at skill 50 seed 44 and Fatty Liver seed 71 are
# now won; seeds 0-799 of Heart Attack at skill 50 hold no such death any more.)
ADVISOR_HEART_25 = Settings("Heart Attack", "none", 25, None, 70)
ADVISOR_LIVER_50 = Settings("Fatty Liver", "none", 50, None, 358)

# Pinned by scanning seeds (the advisor, skill 50 or 25, no modifier). In the first two
# the advisor's Antibiotics failed its skill roll on the fatal turn (E6), which adds
# fever; almost every other tool "survives" that turn, but the patient dies the next
# turn whatever is done, and the shared-roll test says so. Under the pre-D23 rule all
# were avoidable (Sponge, Anesthetic, Stitches and others survived the turn).
# (Seeds re-scanned after the D24 margins: Brainworms seed 1 no longer ends that way.)
BRAINWORMS_1 = Settings("Brainworms", "none", 50, None, 1)
FATTY_LIVER_4 = Settings("Fatty Liver", "none", 50, None, 4)
FATTY_LIVER_7 = Settings("Fatty Liver", "none", 50, None, 7)
# Avoidable at the fatal turn by the shared-roll test: Stitches wins 2 of 3 rollouts
# and the policy's own tool does not. In both Brainworms seeds (253 and 286, after
# D25; they were 71 and 5 after D24) a skill-failed Transfusion ends it and no
# tool survived the fatal turn on the real draw, so they were unlucky before D23.
BRAINWORMS_253 = Settings("Brainworms", "none", 50, None, 253)
BRAINWORMS_286 = Settings("Brainworms", "none", 50, None, 286)
FATTY_LIVER_25_24 = Settings("Fatty Liver", "none", 25, None, 24)


def play_settings(settings: Settings, lookback: int = 3) -> Result:
    return run_surgery(
        settings, policy_by_name("advisor"), "advisor", lookback=lookback
    )


def branch_at(
    settings: Settings, back: int, name: str = "advisor"
) -> tuple[Surgery, int, str]:
    """The branch point `back` turns before the fatal turn, and the tool used there."""
    surgery = Surgery(settings, policy_by_name(name), name, lookback=3)
    while not surgery.ended:
        surgery.step()
    turn = len(surgery.applied) - 1 - back
    return surgery._replay_to(turn), turn, surgery.applied[turn]


def test_lookback_3_an_unlucky_death_stays_avoidable_when_the_original_fails() -> None:
    result = play_settings(ADVISOR_HEART_25)
    assert (result.outcome, result.mistake_turns_back) == (AVOIDABLE_DEATH, 1)
    assert result.alternative == "stitches"
    assert result.alternatives == (
        "stitches",
        "sponge",
        "antiseptic",
        "fix_it",
        "antibiotics",
    )
    assert play_settings(ADVISOR_HEART_25, 1).outcome == UNLUCKY_DEATH


def test_the_credited_alternative_has_the_most_wins_not_the_first_in_the_tray() -> None:
    result = play_settings(ADVISOR_LIVER_50)
    assert (result.outcome, result.mistake_turns_back) == (AVOIDABLE_DEATH, 2)
    assert result.alternative == "transfusion"
    assert result.alternatives == ("transfusion", "clamp")
    branch, turn, original = branch_at(ADVISOR_LIVER_50, 2)
    tray = branch.state["usable_tools"]
    assert tray.index("sponge") < tray.index("transfusion")  # tray order says Sponge
    wins = {
        tool: _rollouts(branch, turn, tool, run_all_when_working=True)[0]
        for tool in tray
        if tool != original
    }
    assert wins["sponge"] < BRANCH_WINS_NEEDED  # the old rule credited it, wrongly
    assert wins["transfusion"] == max(wins.values())
    assert {t for t, w in wins.items() if w >= BRANCH_WINS_NEEDED} == set(
        result.alternatives
    )
    assert _rollouts(branch, turn, original, run_all_when_working=True)[0] < 2


def test_lookback_3_a_death_the_original_tool_wins_with_fresh_draws_is_luck() -> None:
    # Under the old rule these were avoidable (baseline seed 29: Sponge one turn back;
    # advisor seed 10: Stitches two turns back) because some other tool won 2 of 3
    # rollouts. The tool really used wins 2 of 3 with the same draws, so the death
    # at that depth is luck, and nothing deeper is found.
    for name, settings, back in (
        ("baseline", Settings(*HEART_ATTACK[:3], HEART_ATTACK[3], 29), 1),
        ("advisor", Settings(*HEART_ATTACK[:3], HEART_ATTACK[3], 10), 2),
    ):
        result = run_surgery(settings, policy_by_name(name), name, lookback=3)
        assert fields(result) == (UNLUCKY_DEATH, None, None)
        assert result.alternatives == ()
        branch, turn, original = branch_at(settings, back, name)
        working = [
            tool
            for tool in branch.state["usable_tools"]
            if tool != original
            and _rollouts(branch, turn, tool, run_all_when_working=True)[0] >= 2
        ]
        assert working  # the old rule's reason to call it avoidable
        assert _rollouts(branch, turn, original, run_all_when_working=False)[0] >= 2


def test_rollout_rng_does_not_depend_on_the_tool() -> None:
    a, b = rollout_rng(7, 3, 1), rollout_rng(7, 3, 1)
    assert [a.random() for _ in range(5)] == [b.random() for _ in range(5)]
    first = rollout_rng(7, 3, 0).random()
    assert rollout_rng(7, 3, 1).random() != first
    assert rollout_rng(7, 4, 0).random() != first
    assert rollout_rng(8, 3, 0).random() != first


def test_every_tool_at_a_turn_gets_the_same_draws(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    branch, turn, original = branch_at(ADVISOR_LIVER_50, 2)
    asked: dict[str, list[tuple[int, int, int]]] = {}
    current = ""

    def spy(seed: int, turn: int, rollout: int) -> random.Random:
        asked.setdefault(current, []).append((seed, turn, rollout))
        return rollout_rng(seed, turn, rollout)

    monkeypatch.setattr(runner, "rollout_rng", spy)
    for current in ("sponge", "transfusion", original):
        _rollouts(branch, turn, current, run_all_when_working=True)
    seed = ADVISOR_LIVER_50.seed
    every = [(seed, turn, 0), (seed, turn, 1), (seed, turn, 2)]
    for tool, calls in asked.items():  # a tool that cannot win stops early
        assert calls == every[: len(calls)], tool
    assert asked["transfusion"] == every


@pytest.mark.parametrize(
    ("settings", "back"),
    [(ADVISOR_LIVER_50, 2), (BRAINWORMS_253, 0), (BRAINWORMS_1, 0)],
)
def test_stopping_early_gives_the_same_verdict_as_running_every_rollout(
    settings: Settings, back: int
) -> None:
    branch, turn, _ = branch_at(settings, back)
    for tool in branch.state["usable_tools"]:
        full, _ = _rollouts(branch, turn, tool, run_all_when_working=True)
        early, _ = _rollouts(branch, turn, tool, run_all_when_working=False)
        assert (full >= BRANCH_WINS_NEEDED) == (early >= BRANCH_WINS_NEEDED)


def test_lookback_3_keeps_what_lookback_1_already_found() -> None:
    for settings in (BRAINWORMS_253, BRAINWORMS_286, FATTY_LIVER_25_24):
        one, three = play_settings(settings, 1), play_settings(settings, 3)
        assert one.outcome == AVOIDABLE_DEATH and one.mistake_turns_back == 0
        assert one == three
    # At the fatal turn the working tools are listed best first, without repeats.
    result = play_settings(FATTY_LIVER_25_24, 1)
    assert result.alternative == "sponge"
    assert result.alternatives == (
        "sponge",
        "antiseptic",
        "ultrasound",
        "transfusion",
        "stitches",
    )


def survivors_of_the_fatal_turn(settings: Settings) -> list[str]:
    """The pre-D23 test: tools that merely get through the fatal turn (one draw)."""
    surgery = Surgery(settings, policy_by_name("advisor"), "advisor")
    while not surgery.ended:
        surgery.step()
    branch = surgery._replay_to(len(surgery.applied) - 1)
    survivors = []
    for tool in branch.state["usable_tools"]:
        if tool == surgery.applied[-1]:
            continue
        trial = copy.deepcopy(branch)
        trial.step(override=tool)
        if not trial.ended or trial.outcome == SUCCESS:
            survivors.append(tool)
    return survivors


def last_turn_of(settings: Settings) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    run_surgery(
        settings,
        policy_by_name("advisor"),
        "advisor",
        on_record=records.append,
    )
    return records[-1]


@pytest.mark.parametrize("settings", [FATTY_LIVER_7, FATTY_LIVER_4])
def test_a_skill_failed_antibiotics_on_the_fatal_turn_is_luck(
    settings: Settings,
) -> None:
    last = last_turn_of(settings)
    assert (last["applied_tool"], last["decision"]["rule"]) == ("antibiotics", "E6")
    assert last["skill_fail"]
    old = survivors_of_the_fatal_turn(settings)
    assert {"sponge", "anesthetic", "stitches"} <= set(old)  # avoidable before D23
    result = play_settings(settings, 1)
    assert fields(result) == (UNLUCKY_DEATH, None, None)
    assert result.alternatives == ()


def test_the_fatal_turn_is_avoidable_if_another_tool_wins_and_the_original_not() -> (
    None
):
    for settings in (BRAINWORMS_253, BRAINWORMS_286):
        result = play_settings(settings, 1)
        assert fields(result) == (AVOIDABLE_DEATH, 0, "stitches")
        assert result.alternatives == ("stitches",)
        branch, turn, original = branch_at(settings, 0)
        assert turn == result.turns - 1
        wins = {
            tool: _rollouts(branch, turn, tool, run_all_when_working=True)[0]
            for tool in branch.state["usable_tools"]
        }
        assert wins["stitches"] >= BRANCH_WINS_NEEDED
        assert wins[original] < BRANCH_WINS_NEEDED
        working = {
            t for t, w in wins.items() if w >= BRANCH_WINS_NEEDED and t != original
        }
        assert working == set(result.alternatives)
    # The Brainworms deaths were unlucky before D23: no tool survived the fatal turn
    # (a skill-failed Transfusion). The Fatty Liver death was avoidable then as well.
    assert survivors_of_the_fatal_turn(BRAINWORMS_286) == []
    assert survivors_of_the_fatal_turn(BRAINWORMS_253) == []
    assert "stitches" in survivors_of_the_fatal_turn(FATTY_LIVER_25_24)


def test_lookback_3_leaves_a_hopeless_death_unlucky() -> None:
    assert fields(play("baseline", 12, 3)) == (UNLUCKY_DEATH, None, None)
    assert fields(play("advisor", 166, 3)) == (UNLUCKY_DEATH, None, None)


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
    assert result.alternatives == ()


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
            assert r.alternatives == ()
            return
    pytest.fail("no seed died")


def test_same_settings_and_lookback_give_the_same_fields() -> None:
    for name, seed in (("baseline", 19), ("advisor", 8), ("baseline", 12)):
        assert fields(play(name, seed, 3)) == fields(play(name, seed, 3))
    assert play_settings(ADVISOR_LIVER_50) == play_settings(ADVISOR_LIVER_50)
    assert play_settings(ADVISOR_HEART_25) == play_settings(ADVISOR_HEART_25)
    for settings in (BRAINWORMS_253, BRAINWORMS_1):  # decided at the fatal turn
        assert play_settings(settings, 1) == play_settings(settings, 1)


def test_the_replay_reaches_the_same_screens_as_the_surgery() -> None:
    settings = Settings(*HEART_ATTACK[:3], HEART_ATTACK[3], 8)
    surgery = Surgery(settings, policy_by_name("advisor"), "advisor", lookback=3)
    states: list[Any] = []
    while not surgery.ended:
        states.append(surgery.state)
        surgery.step()
    for turn in range(len(states)):
        assert surgery._replay_to(turn).state == states[turn]


class ScalpelFirst:
    """The advisor, except that its first move is a Scalpel on the awake patient."""

    def __init__(self) -> None:
        self.advisor = AdvisorPolicy()
        self.first = True

    def __call__(self, state: dict[str, Any], patient: Any) -> dict[str, str]:
        pick = self.advisor(state, patient)
        if self.first:
            self.first = False
            return {"tool": "scalpel", "rule": "T0", "reason": "t"}
        return pick

    def note_override(self, tool: str) -> None:
        self.advisor.note_override(tool)


def test_a_death_on_the_first_turns_looks_back_only_as_far_as_there_are_turns() -> None:
    result = run_surgery(
        Settings("Heart Attack", "none", 100, seed=0), ScalpelFirst(), lookback=10
    )
    assert result.outcome == AVOIDABLE_DEATH and result.turns == 1
    assert result.mistake_turns_back == 0


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
    args = ["play", "--malady", "Heart Attack", "--condition", "none", "--skill", "25"]
    code = cli.main([*args, "--seed", "70", "--policy", "advisor", "--lookback", "3"])
    assert code == 0
    out = capsys.readouterr().out
    assert "mistake_turns_back 1, alternative stitches" in out


def test_play_rejects_lookback_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["play", "--seed", "1", "--lookback", "0"]) == 1
    assert "lookback" in capsys.readouterr().err


def test_a_bench_cell_records_the_fields_on_each_death() -> None:
    cell = run_cell(("baseline", HEART_ATTACK, 40, 3))
    deaths = {d["seed"]: d for d in cell["deaths"]}
    assert deaths[3]["mistake_turns_back"] is None  # luck since D23 (was Transfusion)
    assert deaths[29]["mistake_turns_back"] is None  # luck: the original wins too
    assert deaths[12]["mistake_turns_back"] is None
    assert deaths[12]["alternative"] is None and deaths[12]["alternatives"] == []
    keys = {"mistake_turns_back", "alternative", "alternatives"}
    assert all(keys <= set(d) for d in deaths.values())
    heart = run_cell(("advisor", ("Heart Attack", "none", 25, None), 80, 3))
    (death,) = [d for d in heart["deaths"] if d["seed"] == 70]
    assert death["mistake_turns_back"] == 1 and death["alternative"] == "stitches"
    assert death["alternatives"] == [
        "stitches",
        "sponge",
        "antiseptic",
        "fix_it",
        "antibiotics",
    ]
    worms = run_cell(("advisor", ("Brainworms", "none", 50, None), 300, 1))
    (fatal,) = [d for d in worms["deaths"] if d["seed"] == 253]
    assert fatal["mistake_turns_back"] == 0 and fatal["alternative"] == "stitches"
    assert fatal["alternatives"] == ["stitches"]


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
