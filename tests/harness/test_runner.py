"""The runner plays one surgery per seed, deterministically, and classifies the end."""

import json
import random
from typing import Any

import pytest

from harness.runner import (
    AVOIDABLE_DEATH,
    MAX_TURNS,
    SUCCESS,
    TIMEOUT,
    UNLUCKY_DEATH,
    Settings,
    Surgery,
    run_surgery,
)

State = dict[str, Any]


def decision(tool: str) -> dict[str, str]:
    return {"tool": tool, "rule": "T0", "reason": "test policy"}


def always(tool: str) -> Any:
    return lambda state, patient: decision(tool)


def careful_sponger(state: State, patient: Any) -> dict[str, str]:
    """Never makes a mistake, never makes progress: re-sleeps, revives, then sponges."""
    if state["status"] == "heart_stopped":
        return decision("defibrillator")
    if state["status"] == "awake":
        return decision("anesthetic")
    return decision("sponge")


def records_of(settings: Settings, policy: Any, **kwargs: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    run_surgery(settings, policy, on_record=records.append, **kwargs)
    return records


def test_same_seed_plays_the_same_surgery() -> None:
    settings = Settings("Heart Attack", "none", 0, None, seed=11)
    assert records_of(settings, careful_sponger) == records_of(
        settings, careful_sponger
    )


def test_different_seeds_play_differently() -> None:
    logs = {
        json.dumps(
            records_of(
                Settings("Heart Attack", "none", 0, None, seed=s), careful_sponger
            )
        )
        for s in range(5)
    }
    assert len(logs) > 1


def test_global_random_state_is_left_alone() -> None:
    random.seed(1234)
    expected = random.getstate()
    surgery = Surgery(Settings("Heart Attack", "none", 0, seed=3), careful_sponger)
    for _ in range(10):
        if not surgery.ended:
            surgery.step()
    assert random.getstate() == expected


def test_interleaved_surgeries_do_not_change_each_others_rolls() -> None:
    a = Settings("Heart Attack", "none", 0, seed=1)
    b = Settings("Broken Arm", "none", 0, seed=2)
    alone_a, alone_b = records_of(a, careful_sponger), records_of(b, careful_sponger)

    sa, sb = Surgery(a, careful_sponger), Surgery(b, careful_sponger)
    got_a: list[dict[str, Any]] = []
    got_b: list[dict[str, Any]] = []
    while not (sa.ended and sb.ended):
        if not sa.ended:
            got_a.append(sa.step())
        if not sb.ended:
            got_b.append(sb.step())
    assert got_a == alone_a
    assert got_b == alone_b


def test_record_has_the_agreed_fields() -> None:
    (first, *_) = records_of(
        Settings("Heart Attack", seed=5), always("sponge"), max_turns=1
    )
    assert list(first) == [
        "seed",
        "malady",
        "condition",
        "skill",
        "modifier",
        "policy",
        "turn",
        "state",
        "decision",
        "legal",
        "applied_tool",
        "tool_text",
        "skill_fail",
        "ended",
        "outcome",
    ]
    assert first["turn"] == 0 and first["state"]["status"] == "awake"
    json.dumps(first)  # JSON lines must serialise


def test_timeout_at_the_turn_cap() -> None:
    result = run_surgery(
        Settings("Heart Attack", "none", 100, seed=0), always("sponge"), max_turns=5
    )
    assert result.outcome == TIMEOUT and result.turns == 5 and result.tools_used == 5


def test_default_cap_is_eighty_turns() -> None:
    assert MAX_TURNS == 80


def test_illegal_decision_is_rejected_and_recorded() -> None:
    records = records_of(
        Settings("Heart Attack", seed=0), always("defibrillator"), max_turns=3
    )
    assert all(not r["legal"] and r["applied_tool"] == "sponge" for r in records)
    result = run_surgery(
        Settings("Heart Attack", seed=0), always("defibrillator"), max_turns=3
    )
    assert result.illegal_moves == 3


def test_scalpel_on_an_awake_patient_is_an_avoidable_death() -> None:
    outcomes = [
        run_surgery(
            Settings("Heart Attack", "none", 100, seed=s), always("scalpel")
        ).outcome
        for s in range(20)
    ]
    assert AVOIDABLE_DEATH in outcomes
    assert UNLUCKY_DEATH not in outcomes


def test_two_failed_defibrillations_are_an_unlucky_death() -> None:
    outcomes = [
        run_surgery(
            Settings("Heart Attack", "none", 0, seed=s), careful_sponger
        ).outcome
        for s in range(300)
    ]
    assert UNLUCKY_DEATH in outcomes
    assert AVOIDABLE_DEATH not in outcomes


def test_a_death_after_an_illegal_move_is_avoidable() -> None:
    def illegal_then_scalpel(state: State, patient: Any) -> dict[str, str]:
        # Defibrillator is unusable on a beating heart; then a fatal Scalpel.
        first = state["last_tool_text"] == "Patient is prepped for surgery."
        return decision("defibrillator" if first else "scalpel")

    results = [
        run_surgery(Settings("Heart Attack", "none", 100, seed=s), illegal_then_scalpel)
        for s in range(20)
    ]
    deaths = [r for r in results if r.outcome not in (SUCCESS, TIMEOUT)]
    assert deaths
    assert all(r.outcome == AVOIDABLE_DEATH and r.illegal_moves == 1 for r in deaths)


def test_step_after_the_end_is_an_error() -> None:
    surgery = Surgery(Settings("Heart Attack", seed=0), always("sponge"), max_turns=1)
    surgery.step()
    assert surgery.ended and surgery.decision is None
    with pytest.raises(RuntimeError):
        surgery.step()
