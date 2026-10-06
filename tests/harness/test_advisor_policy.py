"""`AdvisorPolicy` and `policy_by_name`: fresh memory per surgery, repeatable play."""

import pytest

import harness.bench as bench
from harness.bench import run_cell
from harness.runner import (
    POLICY_NAMES,
    AdvisorPolicy,
    Record,
    Result,
    Settings,
    Surgery,
    policy_by_name,
    run_surgery,
)

NAMES = ["advisor", "advisor-draft-antiseptic", "baseline", "train-e-plus"]
# Seeds 0 to 2 of a cell where stale memory (a diagnosis, a finished fix) would
# change the play: Heart Attack with Tough Skin needs counted incisions and a fix.
CELL = ("Heart Attack", "tough_skin", 100, None)


def play(settings: Settings, name: str = "advisor") -> tuple[list[Record], Result]:
    records: list[Record] = []
    result = run_surgery(settings, policy_by_name(name), name, on_record=records.append)
    return records, result


def test_policy_names_are_the_four_documented_ones() -> None:
    assert list(POLICY_NAMES) == NAMES


def test_unknown_policy_lists_the_valid_names() -> None:
    with pytest.raises(ValueError) as error:
        policy_by_name("magic")
    for name in NAMES:
        assert name in str(error.value)


def test_every_call_returns_a_fresh_advisor_with_its_own_memory() -> None:
    a, b = policy_by_name("advisor"), policy_by_name("advisor")
    assert isinstance(a, AdvisorPolicy) and isinstance(b, AdvisorPolicy)
    assert a is not b and a.memory is not b.memory


def test_advisor_defaults_to_minimal_and_draft_antiseptic_policy_uses_draft() -> None:
    minimal, draft = (
        policy_by_name("advisor"),
        policy_by_name("advisor-draft-antiseptic"),
    )
    assert isinstance(minimal, AdvisorPolicy) and isinstance(draft, AdvisorPolicy)
    assert (minimal.antiseptic_mode, draft.antiseptic_mode) == ("minimal", "draft")
    assert AdvisorPolicy().antiseptic_mode == "minimal"


def test_the_config_is_built_from_the_first_state() -> None:
    policy = AdvisorPolicy("minimal")
    surgery = Surgery(
        Settings("Heart Attack", "none", 100, "exquisite_bone_saw", 1),
        policy,
        "advisor",
    )
    assert surgery.state["modifier"] == "exquisite_bone_saw"
    assert policy.config is not None
    assert policy.config.fail_rate == 2  # skill 100 with the Exquisite Bone Saw
    assert policy.config.antiseptic_mode == "minimal"


def test_the_same_seed_plays_the_same_surgery() -> None:
    settings = Settings("Heart Attack", "tough_skin", 50, None, 7)
    first, result_a = play(settings)
    second, result_b = play(settings)
    assert first == second
    assert result_a == result_b


def test_the_decision_is_for_the_state_the_policy_was_given() -> None:
    records, _ = play(Settings("Broken Arm", "none", 100, None, 3))
    for record in records:
        assert record["decision"]["tool"] in record["state"]["usable_tools"]
        assert set(record["decision"]) == {"tool", "rule", "reason"}


def test_memory_does_not_leak_between_surgeries_of_a_cell() -> None:
    """Three seeds in one cell equal the same three surgeries each played alone."""
    runs = 3
    cell = run_cell(("advisor", CELL, runs))
    malady, condition, skill, modifier = CELL
    outcomes: dict[str, int] = dict.fromkeys(cell["outcomes"], 0)
    turns = fails = 0
    for seed in range(runs):
        _, alone = play(Settings(malady, condition, skill, modifier, seed))
        outcomes[alone.outcome] += 1
        turns += alone.turns
        fails += alone.skill_fails
    assert cell["outcomes"] == outcomes
    assert cell["turns"] == turns and cell["skill_fails"] == fails


def test_a_shared_policy_would_change_the_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The leak test above can fail: if one policy served every seed, play differs."""
    shared = AdvisorPolicy()
    monkeypatch.setattr(bench, "policy_by_name", lambda name: shared)
    leaky = run_cell(("advisor", CELL, 3))
    monkeypatch.undo()
    fresh = run_cell(("advisor", CELL, 3))
    assert leaky["turns"] != fresh["turns"] or leaky["outcomes"] != fresh["outcomes"]
