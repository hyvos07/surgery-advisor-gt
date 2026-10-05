"""The observation adapter turns a real SurgE patient into PRD section 8 JSON."""

import random
import re
from pathlib import Path

import pytest

from harness.observe import observe, strip_formatting
from harness.surge import (
    CONDITION_NAMES,
    MALADY_NAMES,
    MODIFIER_NAMES,
    TOOL_IDS,
    TOOL_TYPES,
    Patient,
    TextManager,
    start_surgery,
)

OBSERVE_SOURCE = Path(__file__).parents[2] / "src" / "harness" / "observe.py"

SCREEN_KEYS = [
    "skill_level",
    "modifier",
    "special_condition_text",
    "scan_text",
    "pulse",
    "status",
    "temperature",
    "site",
    "visibility",
    "incisions",
    "bones",
    "bleeding",
    "fever",
    "last_tool_text",
    "usable_tools",
]


# Tests may set hidden values to build a state; observe.py itself may not read them.
def patient_with(malady: str = "Heart Attack", **attrs: object) -> Patient:
    """A started surgery with hidden values overridden, then the screen refreshed."""
    patient = start_surgery(malady, "none", 100)
    for name, value in attrs.items():
        setattr(patient, name, value)
    patient.UpdatePatientUITexts()
    return patient


def test_turn_zero_screen_matches_the_prd_example() -> None:
    state = observe(start_surgery("Heart Attack", "hyperactive", 40))
    assert state == {
        "skill_level": 40,
        "modifier": None,
        "special_condition_text": "The patient is hyperactive.",
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
        "usable_tools": [
            "sponge",
            "anesthetic",
            "stitches",
            "scalpel",
            "ultrasound",
            "antiseptic",
            "lab_kit",
            "transfusion",
            "splint",
        ],
    }


def test_screen_has_exactly_the_prd_fields_in_order() -> None:
    assert list(observe(start_surgery("Bird Flu"))) == SCREEN_KEYS


@pytest.mark.parametrize(
    ("attrs", "field", "expected"),
    [
        # pulse
        ({"Pulse": 40}, "pulse", "strong"),
        ({"Pulse": 25}, "pulse", "steady"),
        ({"Pulse": 15}, "pulse", "weak"),
        ({"Pulse": 5}, "pulse", "extremely_weak"),
        # status
        ({"SleepLevel": 0}, "status", "awake"),
        ({"SleepLevel": 2}, "status", "coming_to"),
        ({"SleepLevel": 7}, "status", "unconscious"),
        ({"HeartDamage": 1}, "status", "heart_stopped"),
        # operation site
        ({"SiteSanitation": 20}, "site", "clean"),
        ({"SiteSanitation": 0}, "site", "not_sanitized"),
        ({"SiteSanitation": -2}, "site", "unclean"),
        ({"SiteSanitation": -5}, "site", "unsanitary"),
        # visibility
        ({"SiteDirtyness": 0}, "visibility", "clear"),
        ({"SiteDirtyness": 5}, "visibility", "hard_to_see"),
        ({"SiteDirtyness": 12}, "visibility", "cant_see"),
        # bleeding
        ({"BleedingLevel": 0}, "bleeding", None),
        ({"BleedingLevel": 1}, "bleeding", "slowly"),
        ({"BleedingLevel": 3}, "bleeding", "losing"),
        ({"BleedingLevel": 4}, "bleeding", "very_quickly"),
        # fever shows only above 100 degrees
        ({"Fever": 0.3, "Temp": 101.0}, "fever", "slowly_rising"),
        ({"Fever": 1.0, "Temp": 101.0}, "fever", "climbing"),
        ({"Fever": 3.0, "Temp": 101.0}, "fever", "climbing_fast"),
        ({"Fever": 3.0, "Temp": 99.0}, "fever", None),
        ({"Fever": 0.0, "Temp": 101.0}, "fever", None),
        # temperature, incisions
        ({"Temp": 104.6}, "temperature", 104.6),
        ({"Incisions": 1}, "incisions", 1),
    ],
)
def test_each_enum_value_maps_from_its_screen_text(
    attrs: dict[str, object], field: str, expected: object
) -> None:
    assert observe(patient_with(**attrs))[field] == expected


def test_bones_are_hidden_until_the_ultrasound() -> None:
    patient = start_surgery("Broken Everything")
    assert observe(patient)["bones"] is None
    patient.UseTool(TOOL_TYPES["ultrasound"])
    for _ in range(20):  # the ultrasound can skill-fail
        if observe(patient)["bones"] is not None:
            break
        patient.UseTool(TOOL_TYPES["ultrasound"])
    assert observe(patient)["bones"] == {"broken": 0, "shattered": 4}


def test_diagnosed_patient_without_bones_shows_zero_not_null() -> None:
    state = observe(start_surgery("Nose Job"))  # starts already diagnosed
    assert state["scan_text"] == "Patient wants a nose job."
    assert state["bones"] == {"broken": 0, "shattered": 0}


def test_mixed_bone_text_is_parsed() -> None:
    state = observe(patient_with("Serious Trauma", IsUltrasoundUsed=True))
    assert state["bones"] == {"broken": 2, "shattered": 1}


def test_hidden_condition_text_appears_only_after_diagnosis() -> None:
    patient = start_surgery("Heart Attack", "hemophiliac")
    assert observe(patient)["special_condition_text"] is None
    patient = patient_with(IsUltrasoundUsed=True)
    patient.SpecialCondition = "Hemophiliac"
    patient.SpecialConditionVisibility = True
    patient.UpdatePatientUITexts()
    assert observe(patient)["special_condition_text"]


def test_visible_condition_text_shows_from_the_start() -> None:
    assert observe(start_surgery("Heart Attack", "filthy"))["special_condition_text"]
    assert (
        observe(start_surgery("Heart Attack", "none"))["special_condition_text"] is None
    )


@pytest.mark.parametrize("modifier", MODIFIER_NAMES)
def test_modifier_id_round_trips(modifier: str) -> None:
    assert (
        observe(start_surgery("Bird Flu", "none", 50, modifier))["modifier"] == modifier
    )


def test_skill_fail_marker_survives_formatting() -> None:
    patient = start_surgery("Heart Attack", "none", 0)
    random.seed(0)
    for _ in range(50):
        patient.UseTool(TOOL_TYPES["sponge"])
        text = observe(patient)["last_tool_text"]
        if "Skill Fail" in text:
            assert text.startswith("[Skill Fail ")
            return
    pytest.fail("no skill fail in 50 tries at skill 0")


@pytest.mark.parametrize(
    ("styled", "plain"),
    [
        (TextManager.ErrorText("Awake"), "Awake"),
        (TextManager.WarningText("Coming To"), "Coming To"),
        (TextManager.PositiveText("Unconscious"), "Unconscious"),
        (TextManager.SoftText("Steady"), "Steady"),
        (TextManager.PurpieText("Defiblirator"), "Defiblirator"),
        (
            TextManager.BoldText("Patient wants a nose job."),
            "Patient wants a nose job.",
        ),
        (
            TextManager.ErrorText("[Skill Fail 30%]: ") + TextManager.SoftText("Oops."),
            "[Skill Fail 30%]: Oops.",
        ),
        (TextManager.PositiveText(2), "2"),
    ],
)
def test_strip_formatting(styled: str, plain: str) -> None:
    assert strip_formatting(styled) == plain


def test_incision_count_does_not_reveal_how_many_are_needed() -> None:
    """The count is drawn green when it equals the need; the state must not show it."""
    at_need = observe(patient_with(Incisions=2))  # Heart Attack needs 2
    below_need = observe(patient_with(Incisions=1))
    assert at_need["incisions"] == 2 and below_need["incisions"] == 1
    assert set(at_need) == set(below_need)


# --- usable_tools ----------------------------------------------------------

# SurgE's own tray conditions, copied from `_TOOL_LAYOUT` in ui/surgery_view.py
# (which can't be imported: it needs discord). `c` is "the site is clean enough".
REFERENCE_TRAY = {
    "defibrillator": lambda p, c: c and p.HeartDamage > 0,
    "sponge": lambda p, c: True,
    "anesthetic": lambda p, c: c,
    "stitches": lambda p, c: c,
    "scalpel": lambda p, c: c,
    "ultrasound": lambda p, c: not p.IsUltrasoundUsed and c,
    "antiseptic": lambda p, c: c,
    "fix_it": lambda p, c: (
        (
            p.IsFixable
            and (
                not p.IsPatientFixed
                or p.IsBrainWorms
                or p.IncisionsNeeded == p.Incisions
            )
        )
        and c
    ),
    "lab_kit": lambda p, c: not p.IsLabKitUsed and c,
    "antibiotics": lambda p, c: p.LabWorked and c,
    "transfusion": lambda p, c: c,
    "splint": lambda p, c: c,
    "pins": lambda p, c: c and p.Incisions > 0,
    "clamp": lambda p, c: c and p.Incisions > 0,
}


def reference_tools(patient: Patient) -> list[str]:
    clean = patient.SiteDirtyness < 10
    return [tool for tool in TOOL_IDS if REFERENCE_TRAY[tool](patient, clean)]


def test_usable_tools_match_surges_tray_on_random_surgeries() -> None:
    """Derived from the screen, the tool list must equal what SurgE's tray enables."""
    seen: set[str] = set()
    turns = 0
    for seed in range(300):
        rng = random.Random(seed)
        random.seed(seed)
        patient = start_surgery(
            rng.choice(MALADY_NAMES),
            rng.choice(list(CONDITION_NAMES)),
            rng.choice([0, 25, 50, 75, 100]),
            rng.choice([None, *MODIFIER_NAMES]),
        )
        for _ in range(80):
            usable = observe(patient)["usable_tools"]
            assert usable == reference_tools(patient), (seed, patient.diagnostic)
            seen.update(usable)
            turns += 1
            # Random play minus the instant-death moves, to reach deep states.
            status = observe(patient)["status"]
            choices = [
                t
                for t in usable
                if not (t == "scalpel" and status == "awake")
                and not (t == "anesthetic" and status == "unconscious")
            ]
            patient.UseTool(TOOL_TYPES[rng.choice(choices)])
            if patient.IsSurgeryEnded:
                break
    assert turns > 3000
    assert seen == set(TOOL_IDS), f"never usable: {set(TOOL_IDS) - seen}"


# --- hard rule 2 -----------------------------------------------------------

HIDDEN = [
    "Pulse",
    "SleepLevel",
    "SiteDirtyness",
    "SiteSanitation",
    "Fever",
    "HeartDamage",
    "IncisionsNeeded",
]


def test_observe_never_reads_hidden_values() -> None:
    source = OBSERVE_SOURCE.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    found = [name for name in HIDDEN if re.search(rf"\.{name}\b", code)]
    assert found == []
