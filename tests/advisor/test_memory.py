"""Memory: what it keeps between turns, and that it only trusts confirmed successes."""

import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from advisor.config import Config
from advisor.knowledge import (
    ANTIBIOTIC_RESISTANT,
    HEMOPHILIAC,
    HYPERACTIVE,
    TOUGH_SKIN,
    Knowledge,
)
from advisor.memory import CONFIRMATIONS, SKILL_FAIL_MARKER, Memory, is_confirmed
from advisor.state import Decision, ScreenState, Tool

MakeState = Callable[..., ScreenState]

HEART_ATTACK = "Patient had a heart attack."
HEART_ATTACK_FIX = "The heart is now exposed for operating."
HEART_ATTACK_POST_FIX = "You grafted in some nice new arteries!"
BROKEN_LEG = "Patient broke his leg."
TOUGH_SKIN_TEXT = "The patient exhibits very tough skin. Possibly a superhero."
HYPERACTIVE_TEXT = "The patient is hyperactive."
HEMOPHILIAC_TEXT = "The patient is a hemophiliac."
FILTHY_TEXT = "The patient is absolutely filthy."

ASLEEP = CONFIRMATIONS[Tool.ANESTHETIC]
FIXED = CONFIRMATIONS[Tool.FIX_IT]
LAB_DONE = CONFIRMATIONS[Tool.LAB_KIT]
DOSED = CONFIRMATIONS[Tool.ANTIBIOTICS]

CONFIG = Config.for_patient(50, None)


def decided(memory: Memory, tool: Tool) -> None:
    """Record the decision the engine would have made last turn."""
    memory.last_decision = Decision(tool, "T0", "test")


def status_for(sleep: int) -> str:
    """The status SurgE shows for a sleep level."""
    return "awake" if sleep == 0 else "coming_to" if sleep < 3 else "unconscious"


def snapshot(memory: Memory) -> dict[str, Any]:
    """Every field except the bookkeeping that changes on any update."""
    skip = {"prev_temperature", "temperature_delta", "prev_state", "turn"}
    return {
        f.name: getattr(memory, f.name)
        for f in dataclasses.fields(memory)
        if f.name not in skip
    }


def memory_for(know: Knowledge) -> Memory:
    return Memory.new(know)


# --- Confirmation texts -------------------------------------------------------


def test_confirmation_table_covers_the_tools_memory_tracks() -> None:
    assert set(CONFIRMATIONS) == {
        Tool.ANESTHETIC,
        Tool.FIX_IT,
        Tool.LAB_KIT,
        Tool.ANTIBIOTICS,
        Tool.ULTRASOUND,
    }


@pytest.mark.parametrize("tool", list(CONFIRMATIONS))
def test_is_confirmed_accepts_the_success_text_only(tool: Tool) -> None:
    assert is_confirmed(tool, CONFIRMATIONS[tool])
    assert not is_confirmed(tool, "")
    assert not is_confirmed(tool, "You've made a neat incision.")
    assert not is_confirmed(tool, f"[Skill Fail 5%]: {CONFIRMATIONS[tool]}")


def test_is_confirmed_is_false_for_tools_without_a_confirmation() -> None:
    assert not is_confirmed(Tool.SCALPEL, "You've made a neat incision.")


def test_ultrasound_confirmation_matches_the_full_text() -> None:
    text = (
        "You scanned the patient with ultrasound, discovering they are suffering "
        f"from {HEART_ATTACK}"
    )
    assert is_confirmed(Tool.ULTRASOUND, text)


# --- Skill fails change nothing ----------------------------------------------


@pytest.mark.parametrize("tool", list(CONFIRMATIONS))
def test_skill_fail_text_leaves_memory_unchanged(
    know: Knowledge, make_state: MakeState, tool: Tool
) -> None:
    # Even a fail text that still contains the success text must be ignored.
    fail_texts = [
        f"{SKILL_FAIL_MARKER} 5%]: You contaminated the sample.",
        f"{SKILL_FAIL_MARKER} 18%]: {CONFIRMATIONS[tool]}",
    ]
    for fail_text in fail_texts:
        memory = memory_for(know)
        memory.update(make_state(), CONFIG)
        decided(memory, tool)
        before = snapshot(memory)
        memory.update(make_state(last_tool_text=fail_text), CONFIG)
        assert snapshot(memory) == before, (tool, fail_text)


def test_skill_fail_leaves_anesthetic_sleep_alone_even_when_unconscious(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(), CONFIG)
    decided(memory, Tool.ANESTHETIC)
    memory.update(
        make_state(last_tool_text=f"{SKILL_FAIL_MARKER} 18%]: You end up inhaling"),
        CONFIG,
    )
    assert memory.sleep_left == 0


def test_confirmation_is_tied_to_the_last_decisions_tool(
    know: Knowledge, make_state: MakeState
) -> None:
    # SurgE leaves old text on screen when a tool does nothing, so a stale
    # confirmation of another tool must not count.
    memory = memory_for(know)
    memory.update(make_state(), CONFIG)
    decided(memory, Tool.SPONGE)
    memory.update(make_state(last_tool_text=LAB_DONE), CONFIG)
    decided(memory, Tool.ANTIBIOTICS)
    memory.update(make_state(last_tool_text=LAB_DONE), CONFIG)
    decided(memory, Tool.SCALPEL)
    memory.update(make_state(last_tool_text=FIXED), CONFIG)
    assert not memory.lab_kit_done
    assert not memory.fixed
    assert not memory.antibiotics_dosed


def test_no_last_decision_means_no_tool_effect(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(last_tool_text=LAB_DONE), CONFIG)
    assert not memory.lab_kit_done


# --- Lab kit, fixed, antibiotics ---------------------------------------------


def test_lab_kit_is_remembered_on_confirmation(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(), CONFIG)
    decided(memory, Tool.LAB_KIT)
    memory.update(make_state(last_tool_text=LAB_DONE), CONFIG)
    assert memory.lab_kit_done
    # It stays done on later turns.
    decided(memory, Tool.SPONGE)
    memory.update(
        make_state(last_tool_text="You mopped up the operation site."), CONFIG
    )
    assert memory.lab_kit_done


def test_fixed_from_the_fix_it_confirmation(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK_FIX), CONFIG)
    assert not memory.fixed
    decided(memory, Tool.FIX_IT)
    memory.update(make_state(scan_text=HEART_ATTACK_FIX, last_tool_text=FIXED), CONFIG)
    assert memory.fixed


def test_fixed_from_the_post_fix_scan_text(
    know: Knowledge, make_state: MakeState
) -> None:
    # The Fix It turn's confirmation was missed (say, advice taken from a saved
    # mid-surgery screen); the scan text shows the fix anyway.
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK_FIX), CONFIG)
    assert not memory.fixed
    memory.update(make_state(scan_text=HEART_ATTACK_POST_FIX), CONFIG)
    assert memory.fixed


# --- Fix It unlocked (D15) ---------------------------------------------------


def test_fix_unlocked_when_fix_it_is_in_the_tray(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK), CONFIG)
    assert not memory.fix_unlocked
    memory.update(
        make_state(scan_text=HEART_ATTACK, usable_tools=["sponge", "fix_it"]), CONFIG
    )
    assert memory.fix_unlocked


def test_fix_unlocked_from_the_fix_text_scan_alone(
    know: Knowledge, make_state: MakeState
) -> None:
    # The tray is hidden or Fix It is not listed, but the scan shows the fix text.
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK), CONFIG)
    assert not memory.fix_unlocked
    memory.update(make_state(scan_text=HEART_ATTACK_FIX, usable_tools=[]), CONFIG)
    assert memory.fix_unlocked


def test_fix_unlocked_stays_true_until_fixed(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(
        make_state(scan_text=HEART_ATTACK, usable_tools=["sponge", "fix_it"]), CONFIG
    )
    assert memory.fix_unlocked
    # Neither the tray nor the scan text shows it any more, and it is not fixed.
    memory.update(make_state(scan_text=HEART_ATTACK, usable_tools=["sponge"]), CONFIG)
    assert memory.fix_unlocked
    memory.update(make_state(scan_text=None, usable_tools=[]), CONFIG)
    assert memory.fix_unlocked


def test_fix_unlocked_clears_when_fix_it_is_confirmed(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(
        make_state(scan_text=HEART_ATTACK_FIX, usable_tools=["sponge", "fix_it"]),
        CONFIG,
    )
    assert memory.fix_unlocked
    decided(memory, Tool.FIX_IT)
    # Fix It stays in the tray after it worked; fixed wins.
    memory.update(
        make_state(
            scan_text=HEART_ATTACK_FIX,
            last_tool_text=FIXED,
            usable_tools=["sponge", "fix_it"],
        ),
        CONFIG,
    )
    assert memory.fixed
    assert not memory.fix_unlocked


def test_fix_unlocked_clears_when_the_post_fix_scan_appears(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK_FIX), CONFIG)
    assert memory.fix_unlocked
    memory.update(make_state(scan_text=HEART_ATTACK_POST_FIX), CONFIG)
    assert memory.fixed
    assert not memory.fix_unlocked


def test_fix_unlocked_stays_false_before_diagnosis(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(), CONFIG)
    assert not memory.fix_unlocked
    # A fix-text-like scan cannot unlock without a diagnosis, and an unknown scan
    # text names nothing.
    memory.update(make_state(scan_text="The patient has not been diagnosed."), CONFIG)
    assert memory.diagnosis is None
    assert not memory.fix_unlocked


def test_fix_unlocked_is_false_for_a_malady_without_fix_text(
    know: Knowledge, make_state: MakeState
) -> None:
    # Broken Leg has no fix_text; its scan text must not count as one.
    memory = memory_for(know)
    memory.update(make_state(scan_text=BROKEN_LEG), CONFIG)
    assert memory.diagnosis is not None
    assert memory.diagnosis.fix_text is None
    assert not memory.fix_unlocked


def test_antibiotics_dose_is_remembered_only_when_confirmed(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(temperature=101.0), CONFIG)
    decided(memory, Tool.ANTIBIOTICS)
    memory.update(make_state(temperature=101.5, last_tool_text=LAB_DONE), CONFIG)
    assert not memory.antibiotics_dosed
    memory.update(make_state(temperature=101.5, last_tool_text=DOSED), CONFIG)
    assert memory.antibiotics_dosed


# --- Diagnosis ---------------------------------------------------------------


def test_diagnosis_from_the_scan_text(know: Knowledge, make_state: MakeState) -> None:
    memory = memory_for(know)
    memory.update(make_state(), CONFIG)
    assert memory.diagnosis is None
    assert memory.incisions_needed is None
    assert memory.needs_fix is None
    memory.update(make_state(scan_text=HEART_ATTACK), CONFIG)
    assert memory.diagnosis is not None
    assert memory.diagnosis.name == "Heart Attack"
    assert memory.incisions_needed == 2
    assert memory.needs_fix is True


def test_diagnosis_from_the_fix_text_alone(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK_FIX), CONFIG)
    assert memory.diagnosis is not None
    assert memory.diagnosis.name == "Heart Attack"


def test_malady_without_fix_it_needs_no_fix(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text=BROKEN_LEG), CONFIG)
    assert memory.needs_fix is False
    assert memory.incisions_needed == 1


def test_diagnosis_is_locked_through_scan_fix_and_post_fix_text(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK), CONFIG)
    first = memory.diagnosis
    assert first is not None
    for text in (HEART_ATTACK_FIX, HEART_ATTACK_POST_FIX, None):
        memory.update(make_state(scan_text=text), CONFIG)
        assert memory.diagnosis is first
    assert memory.fixed


def test_diagnosis_does_not_change_when_a_different_scan_text_appears(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK), CONFIG)
    memory.update(make_state(scan_text=BROKEN_LEG), CONFIG)
    assert memory.diagnosis is not None
    assert memory.diagnosis.name == "Heart Attack"
    assert memory.incisions_needed == 2


def test_post_fix_text_alone_identifies_nothing(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK_POST_FIX), CONFIG)
    assert memory.diagnosis is None
    assert memory.incisions_needed is None
    assert not memory.fixed


def test_unknown_scan_text_identifies_nothing(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text="The patient has not been diagnosed."), CONFIG)
    assert memory.diagnosis is None


def test_post_fix_text_shared_by_two_maladies_cannot_misdiagnose(
    know: Knowledge, make_state: MakeState
) -> None:
    # SurgE reuses post-fix texts ("You excised the tumor!"). Give Broken Leg the
    # Heart Attack's post-fix text and check the diagnosis stays Heart Attack.
    leg = next(m for m in know.maladies if m.name == "Broken Leg")
    shared = dataclasses.replace(leg, post_fix_text=HEART_ATTACK_POST_FIX)
    ambiguous = Knowledge(
        maladies=tuple(shared if m is leg else m for m in know.maladies),
        conditions=know.conditions,
    )
    memory = Memory.new(ambiguous)
    memory.update(make_state(scan_text=HEART_ATTACK_FIX), CONFIG)
    memory.update(make_state(scan_text=HEART_ATTACK_POST_FIX), CONFIG)
    assert memory.diagnosis is not None
    assert memory.diagnosis.name == "Heart Attack"
    fresh = Memory.new(ambiguous)
    fresh.update(make_state(scan_text=HEART_ATTACK_POST_FIX), CONFIG)
    assert fresh.diagnosis is None


# --- Special conditions ------------------------------------------------------


def test_tough_skin_known_before_the_diagnosis(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(special_condition_text=TOUGH_SKIN_TEXT), CONFIG)
    assert memory.has_condition(TOUGH_SKIN)
    assert memory.incisions_needed is None
    memory.update(
        make_state(special_condition_text=TOUGH_SKIN_TEXT, scan_text=HEART_ATTACK),
        CONFIG,
    )
    assert memory.incisions_needed == 3


def test_tough_skin_known_after_the_diagnosis_adds_one_once(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK), CONFIG)
    assert memory.incisions_needed == 2
    for _ in range(3):
        memory.update(
            make_state(scan_text=HEART_ATTACK, special_condition_text=TOUGH_SKIN_TEXT),
            CONFIG,
        )
        assert memory.incisions_needed == 3


def test_condition_text_that_disappears_is_remembered(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(special_condition_text=HYPERACTIVE_TEXT), CONFIG)
    memory.update(make_state(special_condition_text=None), CONFIG)
    assert memory.has_condition(HYPERACTIVE)


def test_hidden_conditions_are_not_assumed_before_the_scan(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK), CONFIG)
    assert memory.assumed_conditions == frozenset()
    assert not memory.has_condition(HEMOPHILIAC)
    assert not memory.has_condition(ANTIBIOTIC_RESISTANT)


def test_revealed_hidden_condition_is_known(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(scan_text=HEART_ATTACK), CONFIG)
    memory.update(
        make_state(scan_text=HEART_ATTACK, special_condition_text=HEMOPHILIAC_TEXT),
        CONFIG,
    )
    assert memory.has_condition(HEMOPHILIAC)
    assert not memory.has_condition(ANTIBIOTIC_RESISTANT)


@pytest.fixture
def nose_job_know(know: Knowledge) -> Knowledge:
    """The fixture data plus a hand-built malady that starts diagnosed."""
    nose_job = dataclasses.replace(
        know.maladies[0],
        name="Nose Job",
        scan_text="Patient wants a nose job.",
        fix_text="The nose is ready.",
        post_fix_text="A fine nose.",
        incisions_needed=1,
        starts_diagnosed=True,
    )
    return Knowledge(maladies=(*know.maladies, nose_job), conditions=know.conditions)


def test_starts_diagnosed_malady_assumes_both_hidden_conditions(
    nose_job_know: Knowledge, make_state: MakeState
) -> None:
    memory = Memory.new(nose_job_know)
    memory.update(make_state(scan_text="Patient wants a nose job."), CONFIG)
    assert memory.diagnosis is not None
    assert memory.diagnosis.starts_diagnosed
    assert memory.assumed_conditions == {ANTIBIOTIC_RESISTANT, HEMOPHILIAC}
    assert memory.has_condition(ANTIBIOTIC_RESISTANT)
    assert memory.has_condition(HEMOPHILIAC)
    assert memory.condition is None
    assert not memory.has_condition(HYPERACTIVE)
    # They stay assumed on later turns.
    memory.update(make_state(scan_text="The nose is ready."), CONFIG)
    assert memory.has_condition(HEMOPHILIAC)


def test_starts_diagnosed_malady_with_a_shown_condition_assumes_nothing(
    nose_job_know: Knowledge, make_state: MakeState
) -> None:
    memory = Memory.new(nose_job_know)
    memory.update(
        make_state(
            scan_text="Patient wants a nose job.",
            special_condition_text=FILTHY_TEXT,
        ),
        CONFIG,
    )
    assert memory.assumed_conditions == frozenset()
    assert not memory.has_condition(HEMOPHILIAC)
    assert memory.has_condition("filthy")


def test_starts_diagnosed_malady_with_tough_skin_needs_two_incisions(
    nose_job_know: Knowledge, make_state: MakeState
) -> None:
    memory = Memory.new(nose_job_know)
    memory.update(
        make_state(
            scan_text="Patient wants a nose job.",
            special_condition_text=TOUGH_SKIN_TEXT,
        ),
        CONFIG,
    )
    assert memory.incisions_needed == 2


# --- Sleep -------------------------------------------------------------------


def dose(memory: Memory, make_state: MakeState, **extra: Any) -> None:
    """Apply a confirmed Anesthetic: the screen shows Unconscious."""
    decided(memory, Tool.ANESTHETIC)
    memory.update(
        make_state(status="unconscious", last_tool_text=ASLEEP, **extra), CONFIG
    )


def test_sleep_counts_down_from_a_normal_dose(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(), CONFIG)
    assert memory.sleep_left == 0
    dose(memory, make_state)
    assert memory.sleep_left == 9
    decided(memory, Tool.SPONGE)
    for expected in range(8, -1, -1):
        memory.update(make_state(status=status_for(expected)), CONFIG)
        assert memory.sleep_left == expected
    # It stays at zero once the patient is awake.
    memory.update(make_state(status="awake"), CONFIG)
    assert memory.sleep_left == 0


def test_sleep_counts_down_from_a_hyperactive_dose(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(special_condition_text=HYPERACTIVE_TEXT), CONFIG)
    dose(memory, make_state, special_condition_text=HYPERACTIVE_TEXT)
    assert memory.sleep_left == 4
    decided(memory, Tool.SPONGE)
    for expected in (3, 2, 1, 0):
        memory.update(
            make_state(
                special_condition_text=HYPERACTIVE_TEXT, status=status_for(expected)
            ),
            CONFIG,
        )
        assert memory.sleep_left == expected


def test_hyperactive_sleep_comes_from_the_profile(
    know: Knowledge, make_state: MakeState
) -> None:
    wiki = Config.for_patient(50, None, profile="wiki")
    memory = memory_for(know)
    memory.update(make_state(special_condition_text=HYPERACTIVE_TEXT), wiki)
    decided(memory, Tool.ANESTHETIC)
    memory.update(
        make_state(
            special_condition_text=HYPERACTIVE_TEXT,
            status="unconscious",
            last_tool_text=ASLEEP,
        ),
        wiki,
    )
    assert memory.sleep_left == wiki.profile.hyperactive_sleep - 1 == 3


def test_a_redose_while_coming_to_resets_the_sleep(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(), CONFIG)
    dose(memory, make_state)
    memory.sleep_left = 2  # as if two turns from waking
    dose(memory, make_state)
    assert memory.sleep_left == 9


def test_sleep_does_not_fall_while_the_heart_is_stopped(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(), CONFIG)
    dose(memory, make_state)
    decided(memory, Tool.SPONGE)
    memory.update(make_state(status="unconscious"), CONFIG)
    assert memory.sleep_left == 8
    # The heart stops: three screens with no countdown.
    decided(memory, Tool.TRANSFUSION)
    for _ in range(3):
        memory.update(make_state(status="heart_stopped"), CONFIG)
        assert memory.sleep_left == 8
    # The Defibrillator works: the heart beats, so that turn counts.
    decided(memory, Tool.DEFIBRILLATOR)
    memory.update(
        make_state(status="unconscious", last_tool_text="You shocked the patient"),
        CONFIG,
    )
    assert memory.sleep_left == 7


def test_a_dose_on_the_turn_the_heart_stops_keeps_its_full_value(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(), CONFIG)
    decided(memory, Tool.ANESTHETIC)
    memory.update(make_state(status="heart_stopped", last_tool_text=ASLEEP), CONFIG)
    assert memory.sleep_left == 10
    decided(memory, Tool.DEFIBRILLATOR)
    memory.update(make_state(status="unconscious", last_tool_text="shocked"), CONFIG)
    assert memory.sleep_left == 9


def test_sleep_is_clamped_into_the_shown_status(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(), CONFIG)
    dose(memory, make_state)
    assert memory.sleep_left == 9
    # The screen says Coming to: sleep can only be 1 or 2.
    memory.update(make_state(status="coming_to"), CONFIG)
    assert memory.sleep_left == 2
    # The screen says Awake: sleep is 0.
    memory.update(make_state(status="awake"), CONFIG)
    assert memory.sleep_left == 0
    # The screen says Unconscious but memory ran out: sleep is at least 3.
    memory.update(make_state(status="unconscious"), CONFIG)
    assert memory.sleep_left == 3
    # Coming to with nothing left: at least 1.
    memory.sleep_left = 0
    memory.update(make_state(status="coming_to"), CONFIG)
    assert memory.sleep_left == 1


def test_first_update_on_an_unconscious_screen_does_not_contradict_it(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(status="unconscious"), CONFIG)
    assert memory.sleep_left == 3


def test_heart_stopped_screen_is_not_clamped(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(status="heart_stopped"), CONFIG)
    assert memory.sleep_left == 0


# --- Fever -------------------------------------------------------------------


def test_fever_negative_after_a_dose_when_the_fever_text_goes_and_temperature_falls(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(temperature=104.6, fever="climbing"), CONFIG)
    decided(memory, Tool.LAB_KIT)
    memory.update(
        make_state(temperature=107.1, fever="climbing", last_tool_text=LAB_DONE), CONFIG
    )
    decided(memory, Tool.ANTIBIOTICS)
    memory.update(
        make_state(temperature=107.1, fever="climbing", last_tool_text=DOSED), CONFIG
    )
    assert memory.antibiotics_dosed
    assert not memory.fever_negative
    memory.update(
        make_state(temperature=105.6, fever=None, last_tool_text=DOSED), CONFIG
    )
    assert memory.fever_negative


def test_fever_negative_stays_while_temperature_falls_or_holds_without_a_word(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(temperature=104.0, fever="climbing"), CONFIG)
    decided(memory, Tool.ANTIBIOTICS)
    memory.update(make_state(temperature=102.0, last_tool_text=DOSED), CONFIG)
    assert memory.fever_negative
    memory.update(make_state(temperature=100.0), CONFIG)
    assert memory.fever_negative
    # Held flat at normal temperature: still negative.
    memory.update(make_state(temperature=98.6), CONFIG)
    memory.update(make_state(temperature=98.6), CONFIG)
    assert memory.fever_negative


def test_fever_negative_clears_when_the_fever_word_reappears(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(temperature=104.0, fever="climbing"), CONFIG)
    decided(memory, Tool.ANTIBIOTICS)
    memory.update(make_state(temperature=102.0, last_tool_text=DOSED), CONFIG)
    assert memory.fever_negative
    # A failed dose adds fever; the word shows again even if the reading is flat.
    decided(memory, Tool.ANTIBIOTICS)
    memory.update(
        make_state(
            temperature=102.0,
            fever="slowly_rising",
            last_tool_text=f"{SKILL_FAIL_MARKER} 18%]: wrong medication",
        ),
        CONFIG,
    )
    assert not memory.fever_negative


def test_fever_negative_clears_when_the_temperature_rises(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(temperature=104.0, fever="climbing"), CONFIG)
    decided(memory, Tool.ANTIBIOTICS)
    memory.update(make_state(temperature=102.0, last_tool_text=DOSED), CONFIG)
    assert memory.fever_negative
    # No fever word (below the display threshold), but the temperature went up.
    memory.update(make_state(temperature=102.4), CONFIG)
    assert not memory.fever_negative


def test_fever_negative_can_return_after_another_fall(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(temperature=104.0, fever="climbing"), CONFIG)
    decided(memory, Tool.ANTIBIOTICS)
    memory.update(make_state(temperature=102.0, last_tool_text=DOSED), CONFIG)
    memory.update(make_state(temperature=102.4), CONFIG)
    assert not memory.fever_negative
    # A dose has been confirmed before, so a fall with no word proves it again.
    memory.update(make_state(temperature=101.0), CONFIG)
    assert memory.fever_negative


def test_fever_negative_needs_a_confirmed_dose(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(temperature=104.0), CONFIG)
    decided(memory, Tool.ANTIBIOTICS)
    memory.update(
        make_state(
            temperature=103.0,
            last_tool_text=f"{SKILL_FAIL_MARKER} 5%]: wrong medication",
        ),
        CONFIG,
    )
    assert not memory.fever_negative
    # No dose at all, temperature falling: not proof either.
    decided(memory, Tool.SPONGE)
    memory.update(make_state(temperature=102.0), CONFIG)
    assert not memory.fever_negative


def test_fever_negative_needs_the_fever_text_gone(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(temperature=104.0, fever="climbing"), CONFIG)
    decided(memory, Tool.ANTIBIOTICS)
    memory.update(
        make_state(temperature=103.0, fever="slowly_rising", last_tool_text=DOSED),
        CONFIG,
    )
    assert not memory.fever_negative


def test_fever_negative_needs_a_fall_not_a_flat_or_rising_temperature(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    memory.update(make_state(temperature=100.5, fever="slowly_rising"), CONFIG)
    decided(memory, Tool.ANTIBIOTICS)
    # Dosed, but the fever is still positive and below the display threshold.
    memory.update(
        make_state(temperature=100.5, fever=None, last_tool_text=DOSED), CONFIG
    )
    assert not memory.fever_negative
    memory.update(make_state(temperature=100.9, fever=None), CONFIG)
    assert not memory.fever_negative
    # An earlier dose counts once the temperature does fall.
    memory.update(make_state(temperature=100.1, fever=None), CONFIG)
    assert memory.fever_negative


# --- Bookkeeping -------------------------------------------------------------


def test_turn_and_previous_values_update_every_call(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    assert memory.turn == 0
    assert memory.prev_state is None
    assert memory.prev_temperature is None
    assert memory.temperature_delta is None
    first = make_state(temperature=100.0)
    memory.update(first, CONFIG)
    assert memory.turn == 1
    assert memory.prev_state is first
    assert memory.prev_temperature == 100.0
    assert memory.temperature_delta is None
    assert not memory.temperature_rising
    second = make_state(temperature=100.5)
    memory.update(second, CONFIG)
    assert memory.turn == 2
    assert memory.prev_state is second
    assert memory.prev_temperature == 100.5
    assert memory.temperature_delta == 0.5
    assert memory.temperature_rising
    memory.update(make_state(temperature=100.5), CONFIG)
    assert memory.temperature_delta == 0.0
    assert not memory.temperature_rising
    memory.update(make_state(temperature=99.0), CONFIG)
    assert memory.temperature_delta == -1.5
    assert not memory.temperature_rising


def test_new_memories_do_not_share_state(
    know: Knowledge, make_state: MakeState
) -> None:
    a, b = memory_for(know), memory_for(know)
    a.update(make_state(scan_text=HEART_ATTACK), CONFIG)
    assert b.diagnosis is None
    assert b.turn == 0
