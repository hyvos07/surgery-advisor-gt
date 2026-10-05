"""Every rule fires on a hand-built state and stays quiet on a close one."""

import dataclasses
from collections.abc import Callable
from typing import Any

import pytest

from advisor import rules
from advisor.config import Config
from advisor.forecast import Forecast
from advisor.knowledge import (
    ANTIBIOTIC_RESISTANT,
    HEMOPHILIAC,
    Knowledge,
)
from advisor.memory import CONFIRMATIONS, Memory
from advisor.rules import RuleFn
from advisor.state import Decision, ScreenState, Tool

MakeState = Callable[..., ScreenState]

# Skill 50 has an 18% fail rate: crisis temperature 107 F, one pulse turn ahead.
# The surge profile needs a temperature under 101 F.
CONFIG = Config.for_patient(50, None)
MINIMAL = Config.for_patient(50, None, antiseptic_mode="minimal")
WIKI = Config.for_patient(50, None, profile="wiki")

MAX_REASON = 100


def memory_for(know: Knowledge, malady: str | None = None, **fields: Any) -> Memory:
    """A memory as the engine would hold it after diagnosing `malady`."""
    memory = Memory.new(know)
    if malady is not None:
        found = next(m for m in know.maladies if m.name == malady)
        memory.diagnosis = found
        memory.incisions_needed = found.incisions_needed
        memory.needs_fix = found.needs_fix
    for name, value in fields.items():
        setattr(memory, name, value)
    return memory


def run(
    rule: RuleFn, state: ScreenState, memory: Memory, config: Config = CONFIG
) -> Decision | None:
    return rule(state, memory, Forecast.from_state(state, memory, config), config)


def fires(
    rule: RuleFn,
    rule_id: str,
    tool: Tool,
    state: ScreenState,
    memory: Memory,
    config: Config = CONFIG,
) -> None:
    decision = run(rule, state, memory, config)
    assert decision is not None, f"{rule_id} did not fire"
    assert (decision.rule, decision.tool) == (rule_id, tool)
    assert decision.reason
    assert len(decision.reason) < MAX_REASON


def silent(
    rule: RuleFn, state: ScreenState, memory: Memory, config: Config = CONFIG
) -> None:
    assert run(rule, state, memory, config) is None


# --- The list ----------------------------------------------------------------


def test_rules_are_in_doc_order() -> None:
    ids = [fn.__name__.split("_")[1].upper() for fn in rules.RULES]
    expected = [f"E{n}" for n in range(1, 8)] + [f"P{n}" for n in range(1, 14)]
    assert ids == expected


# --- Emergency rules ---------------------------------------------------------


def test_e1_revives_a_stopped_heart(know: Knowledge, make_state: MakeState) -> None:
    memory = memory_for(know)
    fires(
        rules.rule_e1_revive,
        "E1",
        Tool.DEFIBRILLATOR,
        make_state(status="heart_stopped"),
        memory,
    )
    silent(rules.rule_e1_revive, make_state(status="unconscious"), memory)


def test_e2_sponges_when_the_site_cant_be_seen(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    fires(
        rules.rule_e2_clear_view,
        "E2",
        Tool.SPONGE,
        make_state(visibility="cant_see"),
        memory,
    )
    silent(rules.rule_e2_clear_view, make_state(visibility="clear"), memory)


def test_e2_ignores_a_hard_to_see_site_even_with_heavy_dirt_sources(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    # E2 no longer sponges pre-emptively: hard_to_see with heavy bleeding and open
    # incisions is left to the other rules (P12 tidies it later).
    state = make_state(visibility="hard_to_see", bleeding="very_quickly", incisions=2)
    for config in (
        CONFIG,
        Config.for_patient(0, None),
        Config.for_patient(100, None),
    ):
        silent(rules.rule_e2_clear_view, state, memory, config)
    silent(
        rules.rule_e2_clear_view,
        make_state(visibility="hard_to_see", bleeding="losing"),
        memory,
    )


def test_e2_fires_on_cant_see_with_heavy_bleeding_and_open_incisions(
    know: Knowledge, make_state: MakeState
) -> None:
    fires(
        rules.rule_e2_clear_view,
        "E2",
        Tool.SPONGE,
        make_state(visibility="cant_see", bleeding="very_quickly", incisions=2),
        memory_for(know),
    )


def test_e3_transfuses_when_the_pulse_may_hit_extremely_weak(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    # Weak is 11 or more; very quickly counts as 6, so the worst case is 5.
    fires(
        rules.rule_e3_save_pulse,
        "E3",
        Tool.TRANSFUSION,
        make_state(pulse="weak", bleeding="very_quickly"),
        memory,
    )
    silent(
        rules.rule_e3_save_pulse,
        make_state(pulse="strong", bleeding="very_quickly"),
        memory,
    )
    silent(rules.rule_e3_save_pulse, make_state(pulse="weak"), memory)


def test_e3_fires_one_step_earlier_for_a_hemophiliac(
    know: Knowledge, make_state: MakeState
) -> None:
    state = make_state(pulse="steady", bleeding="very_quickly")
    # Steady is 21 or more: 21 - 6 = 15 is still weak, 21 - 12 = 9 is not.
    silent(rules.rule_e3_save_pulse, state, memory_for(know))
    fires(
        rules.rule_e3_save_pulse,
        "E3",
        Tool.TRANSFUSION,
        state,
        memory_for(know, condition=know.condition(HEMOPHILIAC)),
    )


def test_e4_keeps_an_operated_patient_asleep(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    for status in ("awake", "coming_to"):
        fires(
            rules.rule_e4_keep_asleep,
            "E4",
            Tool.ANESTHETIC,
            make_state(status=status, incisions=1),
            memory,
        )
    silent(
        rules.rule_e4_keep_asleep,
        make_state(status="unconscious", incisions=1),
        memory,
    )
    silent(rules.rule_e4_keep_asleep, make_state(status="awake", incisions=0), memory)


def test_e5_clamps_heavy_bleeding_with_an_incision_open(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    for bleeding in ("losing", "very_quickly"):
        fires(
            rules.rule_e5_stop_heavy_bleeding,
            "E5",
            Tool.CLAMP,
            make_state(bleeding=bleeding, incisions=1),
            memory,
        )
    silent(
        rules.rule_e5_stop_heavy_bleeding,
        make_state(bleeding="losing", incisions=0),
        memory,
    )
    silent(
        rules.rule_e5_stop_heavy_bleeding,
        make_state(bleeding="slowly", incisions=1),
        memory,
    )
    silent(
        rules.rule_e5_stop_heavy_bleeding,
        make_state(bleeding=None, incisions=1),
        memory,
    )


def test_e5_fires_one_step_earlier_for_a_hemophiliac(
    know: Knowledge, make_state: MakeState
) -> None:
    state = make_state(bleeding="slowly", incisions=1)
    silent(rules.rule_e5_stop_heavy_bleeding, state, memory_for(know))
    for memory in (
        memory_for(know, condition=know.condition(HEMOPHILIAC)),
        # Assumed, not shown (Nose Job).
        memory_for(know, assumed_conditions=frozenset({HEMOPHILIAC})),
    ):
        fires(rules.rule_e5_stop_heavy_bleeding, "E5", Tool.CLAMP, state, memory)
    silent(
        rules.rule_e5_stop_heavy_bleeding,
        make_state(bleeding="slowly", incisions=0),
        memory_for(know, condition=know.condition(HEMOPHILIAC)),
    )


def test_e6_fires_on_a_fast_climbing_fever(
    know: Knowledge, make_state: MakeState
) -> None:
    fires(
        rules.rule_e6_fever_crisis,
        "E6",
        Tool.LAB_KIT,
        make_state(fever="climbing_fast", temperature=100.0),
        memory_for(know),
    )
    silent(
        rules.rule_e6_fever_crisis,
        make_state(fever="slowly_rising", temperature=100.0),
        memory_for(know),
    )


def test_e6_fires_when_the_crisis_temperature_is_two_turns_away(
    know: Knowledge, make_state: MakeState
) -> None:
    # Climbing is up to 2.0 per turn: 103.5 reaches 107.5 in two turns, 102.5 does not.
    fires(
        rules.rule_e6_fever_crisis,
        "E6",
        Tool.LAB_KIT,
        make_state(fever="climbing", temperature=103.5),
        memory_for(know),
    )
    silent(
        rules.rule_e6_fever_crisis,
        make_state(fever="climbing", temperature=102.5),
        memory_for(know),
    )


def test_e6_uses_antibiotics_once_the_lab_kit_is_done(
    know: Knowledge, make_state: MakeState
) -> None:
    fires(
        rules.rule_e6_fever_crisis,
        "E6",
        Tool.ANTIBIOTICS,
        make_state(fever="climbing_fast", temperature=104.0),
        memory_for(know, lab_kit_done=True),
    )


def test_e6_stays_quiet_once_the_fever_is_known_to_be_negative(
    know: Knowledge, make_state: MakeState
) -> None:
    silent(
        rules.rule_e6_fever_crisis,
        make_state(temperature=109.0),
        memory_for(know, lab_kit_done=True, fever_negative=True),
    )


def test_e7_cleans_an_unclean_site_with_an_incision_open(
    know: Knowledge, make_state: MakeState
) -> None:
    for site in ("not_sanitized", "unclean", "unsanitary"):
        fires(
            rules.rule_e7_clean_open_site,
            "E7",
            Tool.ANTISEPTIC,
            make_state(site=site, incisions=1),
            memory_for(know),
        )
    silent(
        rules.rule_e7_clean_open_site,
        make_state(site="clean", incisions=1),
        memory_for(know),
    )
    silent(
        rules.rule_e7_clean_open_site,
        make_state(site="unclean", incisions=0),
        memory_for(know),
    )
    silent(
        rules.rule_e7_clean_open_site,
        make_state(site="unclean", incisions=1),
        memory_for(know, fever_negative=True),
    )


def test_e7_never_fires_in_minimal_mode(know: Knowledge, make_state: MakeState) -> None:
    silent(
        rules.rule_e7_clean_open_site,
        make_state(site="unsanitary", incisions=1),
        memory_for(know),
        MINIMAL,
    )


# --- Phase rules -------------------------------------------------------------


def test_p1_diagnoses_an_undiagnosed_patient(
    know: Knowledge, make_state: MakeState
) -> None:
    fires(
        rules.rule_p1_diagnose,
        "P1",
        Tool.ULTRASOUND,
        make_state(),
        memory_for(know),
    )
    silent(rules.rule_p1_diagnose, make_state(), memory_for(know, "Heart Attack"))


def test_p2_breaks_a_visible_fever(know: Knowledge, make_state: MakeState) -> None:
    fires(
        rules.rule_p2_break_fever,
        "P2",
        Tool.LAB_KIT,
        make_state(fever="slowly_rising", temperature=101.0),
        memory_for(know),
    )
    fires(
        rules.rule_p2_break_fever,
        "P2",
        Tool.ANTIBIOTICS,
        make_state(fever="climbing", temperature=101.0),
        memory_for(know, lab_kit_done=True),
    )


def test_p2_breaks_a_hidden_fever_when_the_temperature_rose(
    know: Knowledge, make_state: MakeState
) -> None:
    state = make_state(temperature=100.2)
    fires(
        rules.rule_p2_break_fever,
        "P2",
        Tool.LAB_KIT,
        state,
        memory_for(know, temperature_delta=0.3),
    )
    silent(rules.rule_p2_break_fever, state, memory_for(know, temperature_delta=0.0))
    silent(rules.rule_p2_break_fever, state, memory_for(know, temperature_delta=-0.3))
    silent(rules.rule_p2_break_fever, state, memory_for(know))


def test_p2_stays_quiet_once_the_fever_is_known_to_be_negative(
    know: Knowledge, make_state: MakeState
) -> None:
    silent(
        rules.rule_p2_break_fever,
        make_state(fever="climbing", temperature=101.0),
        memory_for(know, lab_kit_done=True, fever_negative=True),
    )


def test_p3_uses_fix_it_when_it_is_usable(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Heart Attack")
    fires(
        rules.rule_p3_fix,
        "P3",
        Tool.FIX_IT,
        make_state(usable_tools=["sponge", "fix_it"]),
        memory,
    )
    silent(rules.rule_p3_fix, make_state(usable_tools=["sponge"]), memory)


def test_p4_pins_shattered_bones_with_an_incision_open(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Broken Leg")
    fires(
        rules.rule_p4_pin,
        "P4",
        Tool.PINS,
        make_state(incisions=1, bones={"broken": 1, "shattered": 1}),
        memory,
    )
    silent(
        rules.rule_p4_pin,
        make_state(incisions=0, bones={"broken": 1, "shattered": 1}),
        memory,
    )
    silent(
        rules.rule_p4_pin,
        make_state(incisions=1, bones={"broken": 2, "shattered": 0}),
        memory,
    )


def test_p5_cuts_a_sleeping_patient_below_the_needed_count(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Heart Attack")
    for status in ("unconscious", "coming_to"):
        fires(
            rules.rule_p5_cut,
            "P5",
            Tool.SCALPEL,
            make_state(status=status, incisions=1, bones={"broken": 0, "shattered": 0}),
            memory,
        )
    # The needed count is reached, or the patient is awake, or nothing is known.
    silent(rules.rule_p5_cut, make_state(status="unconscious", incisions=2), memory)
    silent(rules.rule_p5_cut, make_state(status="awake", incisions=0), memory)
    silent(
        rules.rule_p5_cut,
        make_state(status="unconscious", incisions=0),
        memory_for(know),
    )


def test_p5_counts_tough_skin_in_the_needed_incisions(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Heart Attack", incisions_needed=3)
    fires(
        rules.rule_p5_cut,
        "P5",
        Tool.SCALPEL,
        make_state(status="unconscious", incisions=2),
        memory,
    )


def test_p5_cuts_for_shattered_bones_when_no_incision_is_open(
    know: Knowledge, make_state: MakeState
) -> None:
    # Even with the needed count met, shattered bones and no incision need a cut;
    # the legality check is what stops a Scalpel past the needed count.
    memory = memory_for(know, "Broken Leg", incisions_needed=0)
    state = make_state(
        status="unconscious",
        incisions=0,
        bones={"broken": 1, "shattered": 1},
        usable_tools=["sponge", "scalpel"],
    )
    fires(rules.rule_p5_cut, "P5", Tool.SCALPEL, state, memory)
    assert not rules.is_legal(Tool.SCALPEL, state, memory)
    silent(
        rules.rule_p5_cut,
        dataclasses.replace(state, bones=None),
        memory,
    )


def test_p5_cuts_an_unfixed_malady_below_the_needed_count(
    know: Knowledge, make_state: MakeState
) -> None:
    fires(
        rules.rule_p5_cut,
        "P5",
        Tool.SCALPEL,
        make_state(status="unconscious", incisions=1),
        memory_for(know, "Heart Attack"),
    )


def test_p5_does_not_cut_a_fixed_malady_and_p6_closes_it(
    know: Knowledge, make_state: MakeState
) -> None:
    # Heart Attack needs 2 incisions; Fix It is done and Stitches took one away.
    memory = memory_for(know, "Heart Attack", fixed=True)
    state = make_state(status="unconscious", incisions=1)
    silent(rules.rule_p5_cut, state, memory)
    fires(rules.rule_p6_close, "P6", Tool.STITCHES, state, memory)
    # With no incision left there is nothing to cut either.
    silent(rules.rule_p5_cut, make_state(status="unconscious", incisions=0), memory)


def test_p5_does_not_cut_a_malady_that_needs_no_fix_it(
    know: Knowledge, make_state: MakeState
) -> None:
    # Broken Leg: diagnosed, no shattered bones, nothing open.
    silent(
        rules.rule_p5_cut,
        make_state(
            status="unconscious", incisions=0, bones={"broken": 1, "shattered": 0}
        ),
        memory_for(know, "Broken Leg", incisions_needed=1),
    )


def test_p5_cuts_a_sleeping_broken_leg_with_a_shattered_bone(
    know: Knowledge, make_state: MakeState
) -> None:
    fires(
        rules.rule_p5_cut,
        "P5",
        Tool.SCALPEL,
        make_state(
            status="unconscious", incisions=0, bones={"broken": 1, "shattered": 1}
        ),
        memory_for(know, "Broken Leg"),
    )


def test_a_fixed_malady_is_not_prepared_for_another_cut(
    know: Knowledge, make_state: MakeState
) -> None:
    # P9 and P10 share the cut-needed guard with P5.
    memory = memory_for(know, "Heart Attack", fixed=True)
    silent(
        rules.rule_p9_clean_before_cutting,
        make_state(site="unclean", incisions=1),
        memory,
    )
    silent(
        rules.rule_p10_prep_for_cutting,
        make_state(status="awake", incisions=1),
        memory,
    )


def test_p6_closes_once_the_malady_is_fixed(
    know: Knowledge, make_state: MakeState
) -> None:
    open_site = {"incisions": 2, "bones": {"broken": 0, "shattered": 0}}
    # Fixed by Fix It.
    fires(
        rules.rule_p6_close,
        "P6",
        Tool.STITCHES,
        make_state(**open_site),
        memory_for(know, "Heart Attack", fixed=True),
    )
    # No Fix It needed.
    fires(
        rules.rule_p6_close,
        "P6",
        Tool.STITCHES,
        make_state(incisions=1, bones={"broken": 1, "shattered": 0}),
        memory_for(know, "Broken Leg"),
    )
    # Not fixed yet.
    silent(
        rules.rule_p6_close, make_state(**open_site), memory_for(know, "Heart Attack")
    )
    # Shattered bones are still there.
    silent(
        rules.rule_p6_close,
        make_state(incisions=1, bones={"broken": 1, "shattered": 1}),
        memory_for(know, "Broken Leg"),
    )
    # No incision to close.
    silent(
        rules.rule_p6_close,
        make_state(incisions=0),
        memory_for(know, "Heart Attack", fixed=True),
    )


def test_p6_waits_for_a_diagnosis(know: Knowledge, make_state: MakeState) -> None:
    # `needs_fix` is unknown before diagnosis, which must not count as fixed.
    silent(rules.rule_p6_close, make_state(incisions=1), memory_for(know))


def test_p7_splints_broken_bones_with_no_incision_open(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Broken Leg")
    fires(
        rules.rule_p7_splint,
        "P7",
        Tool.SPLINT,
        make_state(incisions=0, bones={"broken": 1, "shattered": 0}),
        memory,
    )
    silent(
        rules.rule_p7_splint,
        make_state(incisions=1, bones={"broken": 1, "shattered": 0}),
        memory,
    )
    silent(
        rules.rule_p7_splint,
        make_state(incisions=0, bones={"broken": 0, "shattered": 0}),
        memory,
    )
    silent(
        rules.rule_p7_splint,
        make_state(incisions=0, bones={"broken": 1, "shattered": 0}),
        memory_for(know),
    )


def test_p8_stitches_surface_bleeding(know: Knowledge, make_state: MakeState) -> None:
    memory = memory_for(know)
    fires(
        rules.rule_p8_surface_bleeding,
        "P8",
        Tool.STITCHES,
        make_state(bleeding="slowly", incisions=0),
        memory,
    )
    silent(
        rules.rule_p8_surface_bleeding,
        make_state(bleeding="slowly", incisions=1),
        memory,
    )
    silent(
        rules.rule_p8_surface_bleeding,
        make_state(bleeding=None, incisions=0),
        memory,
    )


def test_p9_cleans_before_a_cut_in_draft_mode(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Heart Attack")
    fires(
        rules.rule_p9_clean_before_cutting,
        "P9",
        Tool.ANTISEPTIC,
        make_state(site="unclean", incisions=0),
        memory,
    )
    # Mid-surgery cuts count too in draft mode.
    fires(
        rules.rule_p9_clean_before_cutting,
        "P9",
        Tool.ANTISEPTIC,
        make_state(site="not_sanitized", incisions=1),
        memory,
    )
    silent(
        rules.rule_p9_clean_before_cutting,
        make_state(site="clean", incisions=0),
        memory,
    )
    # No cut needed any more.
    silent(
        rules.rule_p9_clean_before_cutting,
        make_state(site="unclean", incisions=2),
        memory,
    )
    # No diagnosis, so never a cut.
    silent(
        rules.rule_p9_clean_before_cutting,
        make_state(site="unclean", incisions=0),
        memory_for(know),
    )
    silent(
        rules.rule_p9_clean_before_cutting,
        make_state(site="unclean", incisions=0),
        memory_for(know, "Heart Attack", fever_negative=True),
    )


def test_p9_in_minimal_mode_fires_only_for_the_deepest_surgeries_before_cutting(
    know: Knowledge, make_state: MakeState
) -> None:
    dirty = make_state(site="unclean", incisions=0)
    # Heart Attack needs 2 incisions, under the default minimum of 5.
    silent(
        rules.rule_p9_clean_before_cutting,
        dirty,
        memory_for(know, "Heart Attack"),
        MINIMAL,
    )
    # A malady needing 5 incisions (Brain Tumor, or Tough Skin on 4).
    deep = memory_for(know, "Heart Attack", incisions_needed=5)
    fires(
        rules.rule_p9_clean_before_cutting, "P9", Tool.ANTISEPTIC, dirty, deep, MINIMAL
    )
    # Never once an incision has been made.
    silent(
        rules.rule_p9_clean_before_cutting,
        make_state(site="unclean", incisions=1),
        deep,
        MINIMAL,
    )
    # Still not when the site is already clean.
    silent(
        rules.rule_p9_clean_before_cutting,
        make_state(site="clean", incisions=0),
        deep,
        MINIMAL,
    )


def test_p9_minimal_threshold_is_configurable(
    know: Knowledge, make_state: MakeState
) -> None:
    config = dataclasses.replace(MINIMAL, antiseptic_min_incisions=2)
    fires(
        rules.rule_p9_clean_before_cutting,
        "P9",
        Tool.ANTISEPTIC,
        make_state(site="unsanitary", incisions=0),
        memory_for(know, "Heart Attack"),
        config,
    )


def test_p10_puts_an_awake_patient_to_sleep_before_cutting(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Heart Attack")
    fires(
        rules.rule_p10_prep_for_cutting,
        "P10",
        Tool.ANESTHETIC,
        make_state(status="awake", incisions=0),
        memory,
    )
    silent(
        rules.rule_p10_prep_for_cutting,
        make_state(status="coming_to", incisions=0),
        memory,
    )
    silent(
        rules.rule_p10_prep_for_cutting,
        make_state(status="awake", incisions=2),
        memory,
    )
    # Without a diagnosis the advisor never anesthetizes.
    silent(
        rules.rule_p10_prep_for_cutting,
        make_state(status="awake", incisions=0),
        memory_for(know),
    )


def test_p11_finishes_a_fever_above_the_success_temperature(
    know: Knowledge, make_state: MakeState
) -> None:
    fires(
        rules.rule_p11_finish_fever,
        "P11",
        Tool.LAB_KIT,
        make_state(temperature=101.5),
        memory_for(know),
    )
    fires(
        rules.rule_p11_finish_fever,
        "P11",
        Tool.ANTIBIOTICS,
        make_state(temperature=101.0),
        memory_for(know, lab_kit_done=True),
    )
    silent(rules.rule_p11_finish_fever, make_state(temperature=100.9), memory_for(know))
    silent(
        rules.rule_p11_finish_fever,
        make_state(temperature=101.5),
        memory_for(know, lab_kit_done=True, fever_negative=True),
    )


def test_p11_uses_the_profile_success_temperature(
    know: Knowledge, make_state: MakeState
) -> None:
    state = make_state(temperature=100.5)
    silent(rules.rule_p11_finish_fever, state, memory_for(know), CONFIG)
    fires(
        rules.rule_p11_finish_fever,
        "P11",
        Tool.LAB_KIT,
        state,
        memory_for(know),
        WIKI,
    )


def test_p12_tidies_a_hard_to_see_site(know: Knowledge, make_state: MakeState) -> None:
    fires(
        rules.rule_p12_tidy,
        "P12",
        Tool.SPONGE,
        make_state(visibility="hard_to_see"),
        memory_for(know),
    )
    silent(rules.rule_p12_tidy, make_state(visibility="clear"), memory_for(know))


def test_p13_waits_with_the_antiseptic(know: Knowledge, make_state: MakeState) -> None:
    fires(rules.rule_p13_wait, "P13", Tool.ANTISEPTIC, make_state(), memory_for(know))


def test_p13_waits_with_the_sponge_in_minimal_mode(
    know: Knowledge, make_state: MakeState
) -> None:
    fires(
        rules.rule_p13_wait,
        "P13",
        Tool.SPONGE,
        make_state(),
        memory_for(know),
        MINIMAL,
    )


# --- Fallback ----------------------------------------------------------------


def test_fallback_prefers_the_antiseptic(make_state: MakeState) -> None:
    decision = rules.fallback(make_state(usable_tools=["sponge", "antiseptic"]), CONFIG)
    assert (decision.rule, decision.tool) == ("F0", Tool.ANTISEPTIC)
    assert decision.reason
    assert len(decision.reason) < MAX_REASON


def test_fallback_uses_the_sponge_when_the_antiseptic_is_not_usable(
    make_state: MakeState,
) -> None:
    decision = rules.fallback(make_state(usable_tools=["sponge"]), CONFIG)
    assert (decision.rule, decision.tool) == ("F0", Tool.SPONGE)


def test_fallback_uses_the_sponge_in_minimal_mode(make_state: MakeState) -> None:
    decision = rules.fallback(
        make_state(usable_tools=["sponge", "antiseptic"]), MINIMAL
    )
    assert (decision.rule, decision.tool) == ("F0", Tool.SPONGE)


# --- Conditions the rules adapt to -------------------------------------------


def test_antibiotic_resistant_keeps_dosing_until_the_fever_is_known_negative(
    know: Knowledge, make_state: MakeState
) -> None:
    # The condition changes nothing in the rule itself: while the fever word is
    # shown, P2 keeps choosing Antibiotics.
    memory = memory_for(
        know,
        lab_kit_done=True,
        antibiotics_dosed=True,
        condition=know.condition(ANTIBIOTIC_RESISTANT),
    )
    fires(
        rules.rule_p2_break_fever,
        "P2",
        Tool.ANTIBIOTICS,
        make_state(
            fever="slowly_rising",
            temperature=102.0,
            last_tool_text=CONFIRMATIONS[Tool.ANTIBIOTICS],
        ),
        memory,
    )


@pytest.mark.parametrize("rule", rules.RULES)
def test_rules_do_not_change_memory(
    rule: RuleFn, know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Heart Attack")
    before = dataclasses.asdict(memory)
    run(rule, make_state(incisions=1, bleeding="losing", fever="climbing"), memory)
    assert dataclasses.asdict(memory) == before
