"""The advisor plays real SurgE surgeries without an illegal move or an exception.

The adapter here is test-local: it turns the harness screen state into a
`ScreenState`, keeps one `Memory` per surgery and calls `engine.decide`. The test
reads hidden values (counts that must never go below zero) only to check the
advisor against; the advisor itself never sees them (AGENTS.md hard rule 2).
"""

from collections import Counter
from typing import Any

from advisor import knowledge
from advisor.config import Config
from advisor.engine import decide
from advisor.memory import Memory
from advisor.state import ScreenState, Status, Tool
from harness.runner import Settings, Surgery
from harness.surge import CONDITION_NAMES, MALADY_NAMES

SKILLS = (0, 100)
SEEDS = (0, 1)


class AdvisorAdapter:
    """One advisor per surgery: its memory must never be shared."""

    def __init__(self) -> None:
        self.memory = Memory.new(knowledge.load())
        self.config: Config | None = None

    def __call__(self, state: dict[str, Any], patient: Any) -> dict[str, str]:
        screen = ScreenState.from_dict(state)
        if self.config is None:
            modifier = screen.modifier.value if screen.modifier else None
            self.config = Config.for_patient(screen.skill_level, modifier)
        return decide(screen, self.memory, self.config).to_dict()


def play_one(settings: Settings) -> tuple[str, int]:
    """Play one surgery, asserting the advisor's moves are legal at every turn.

    Returns the outcome and the turn count.
    """
    where = (
        f"{settings.malady}/{settings.condition}/skill {settings.skill}"
        f"/seed {settings.seed}"
    )
    surgery = Surgery(settings, AdvisorAdapter(), "advisor")
    while not surgery.ended:
        record = surgery.step()
        state, tool = record["state"], record["decision"]["tool"]
        label = f"{where} turn {record['turn']} ({tool})"
        assert record["legal"], f"{label}: tool is not in usable_tools"
        assert not (tool == Tool.SCALPEL and state["status"] == Status.AWAKE), label
        assert not (
            tool == Tool.ANESTHETIC and state["status"] == Status.UNCONSCIOUS
        ), label
        # The three traps push a hidden count below zero (docs/game-model.md).
        patient = surgery.patient
        assert patient.BleedingLevel >= 0, f"{label}: bleeding went negative"
        assert patient.BrokenBoneCount >= 0, f"{label}: broken bones went negative"
        assert patient.ShatteredBoneCount >= 0, f"{label}: shattered went negative"
    result = surgery.result()
    assert result.illegal_moves == 0, where
    return result.outcome, result.turns


def play_grid() -> Counter[str]:
    """All maladies x all conditions x skills 0 and 100 x two seeds."""
    outcomes: Counter[str] = Counter()
    for malady in MALADY_NAMES:
        for condition in CONDITION_NAMES:
            for skill in SKILLS:
                for seed in SEEDS:
                    outcome, _ = play_one(
                        Settings(malady, condition, skill, None, seed)
                    )
                    outcomes[outcome] += 1
    return outcomes


def test_advisor_makes_no_illegal_move_on_real_surgeries() -> None:
    outcomes = play_grid()
    assert sum(outcomes.values()) == (
        len(MALADY_NAMES) * len(CONDITION_NAMES) * len(SKILLS) * len(SEEDS)
    )
