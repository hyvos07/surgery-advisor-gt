"""Advisor memory, fed real SurgE screens, agrees with SurgE's hidden truth.

This is the one place the advisor's memory meets the simulator. The test reads
hidden values (`SleepLevel`, `IncisionsNeeded`, ...) to check memory against; the
advisor itself never does (AGENTS.md hard rule 2).
"""

from dataclasses import dataclass

import pytest

from advisor import knowledge
from advisor.config import Config
from advisor.knowledge import HYPERACTIVE, TOUGH_SKIN
from advisor.memory import Memory, is_confirmed
from advisor.state import Decision, ScreenState, Status, Tool
from harness.baseline import baseline_policy, train_e_plus_policy
from harness.runner import Policy, Settings, Surgery

# (malady, condition, skill): skill 50 gives plenty of skill fails and heart stops.
CASES = [
    ("Heart Attack", "hyperactive", 50),
    ("Heart Attack", "tough_skin", 50),
    ("Heart Attack", "filthy", 25),
    ("Brain Tumor", "tough_skin", 75),
    ("Brain Tumor", "hyperactive", 50),
    ("Broken Leg", "none", 50),
    ("Broken Everything", "hemophiliac", 50),
    ("Nose Job", "antibiotic_resistant", 50),
    ("Nose Job", "tough_skin", 50),
    ("Bird Flu", "antibiotic_resistant", 50),
    ("Turtle Flu", "none", 50),
    ("Lung Tumor", "none", 0),
]
SEEDS = range(6)
POLICIES: dict[str, Policy] = {
    "baseline": baseline_policy,
    "train-e-plus": train_e_plus_policy,
}


@dataclass
class Seen:
    """What the surgeries exercised, to prove the comparison was not vacuous."""

    turns: int = 0
    heart_stopped: int = 0
    anesthetic_confirmed: int = 0
    hyperactive_doses: int = 0
    skill_fails: int = 0
    lab_kit_done: int = 0
    fixed: int = 0
    fever_negative: int = 0
    tough_skin_diagnoses: int = 0
    diagnosed: int = 0


def check(memory: Memory, surgery: Surgery, where: str) -> None:
    """Compare memory with SurgE's hidden values where the two are comparable."""
    patient = surgery.patient
    assert (memory.diagnosis is not None) == bool(patient.IsUltrasoundUsed), where
    if memory.diagnosis is not None:
        assert memory.diagnosis.name == patient.diagnostic, where
        assert memory.incisions_needed == patient.IncisionsNeeded, where
        # A malady that needs no Fix It counts as fixed from the start.
        fixed = memory.fixed or not memory.needs_fix
        assert fixed == bool(patient.IsPatientFixed), where
    assert memory.sleep_left == patient.SleepLevel, where
    assert memory.lab_kit_done == bool(patient.IsLabKitUsed), where


def play(
    policy: Policy, malady: str, condition: str, skill: int, seed: int, seen: Seen
) -> None:
    know = knowledge.load()
    where = f"{malady}/{condition}/skill {skill}/seed {seed}"
    surgery = Surgery(Settings(malady, condition, skill, None, seed), policy)
    config = Config.for_patient(skill, None)
    memory = Memory.new(know)
    memory.update(ScreenState.from_dict(surgery.state), config)
    check(memory, surgery, f"{where} start")

    while not surgery.ended:
        record = surgery.step()
        if surgery.ended:
            break  # the screen after the last tool is never shown
        label = f"{where} turn {record['turn']} ({record['applied_tool']})"
        fever_negative_before = memory.fever_negative
        memory.last_decision = Decision(Tool(record["applied_tool"]), "T0", "test")
        state = ScreenState.from_dict(surgery.state)
        memory.update(state, config)
        check(memory, surgery, label)

        # The first turn memory calls the fever negative, the hidden fever is below 0.
        if memory.fever_negative and not fever_negative_before:
            assert surgery.patient.Fever < 0, label
            seen.fever_negative += 1

        seen.turns += 1
        seen.heart_stopped += state.status is Status.HEART_STOPPED
        seen.skill_fails += bool(record["skill_fail"])
        dosed = record["applied_tool"] == "anesthetic" and is_confirmed(
            Tool.ANESTHETIC, state.last_tool_text
        )
        seen.anesthetic_confirmed += dosed
        seen.hyperactive_doses += dosed and memory.has_condition(HYPERACTIVE)

    seen.lab_kit_done += memory.lab_kit_done
    seen.fixed += memory.fixed
    seen.diagnosed += memory.diagnosis is not None
    seen.tough_skin_diagnoses += memory.diagnosis is not None and memory.has_condition(
        TOUGH_SKIN
    )


@pytest.mark.parametrize("policy_name", POLICIES)
def test_memory_matches_surge_on_real_surgeries(policy_name: str) -> None:
    seen = Seen()
    for malady, condition, skill in CASES:
        for seed in SEEDS:
            play(POLICIES[policy_name], malady, condition, skill, seed, seen)

    # The comparison must have met the situations it claims to cover.
    assert seen.turns > 100
    assert seen.diagnosed > 0
    assert seen.anesthetic_confirmed > 0
    assert seen.hyperactive_doses > 0
    assert seen.skill_fails > 0
    assert seen.tough_skin_diagnoses > 0
    assert seen.heart_stopped > 0
    if policy_name == "train-e-plus":
        assert seen.lab_kit_done > 0
        assert seen.fixed > 0
