"""The Train-E baseline takes SurgE's first usable tip without changing the game."""

import random
from typing import Any

import pytest

from harness.baseline import baseline_policy, parse_tips, tip_tool
from harness.observe import observe, strip_formatting
from harness.runner import SUCCESS, Settings, run_surgery
from harness.surge import MALADY_NAMES, Patient, start_surgery, train_e_tips


def patient_with(malady: str = "Heart Attack", **attrs: object) -> Patient:
    patient = start_surgery(malady, "none", 100)
    for name, value in attrs.items():
        setattr(patient, name, value)
    patient.UpdatePatientUITexts()
    return patient


def pick(patient: Patient) -> dict[str, str]:
    return baseline_policy(observe(patient), patient)


@pytest.mark.parametrize(
    ("heading", "description", "incisions", "tool"),
    [
        (
            "Heart Stopped",
            "You need to Revive your patient with a Defiblirator!",
            0,
            "defibrillator",
        ),
        ("Awake", "Your patient is Awake. Use Anesthetic ...", 1, "anesthetic"),
        ("Stitch it Up!", "The issue is fixed! ...", 1, "stitches"),
        ("Fix It!", "You have found the issue ...", 2, "fix_it"),
        ("Clean the Area", "Clean the area with Antiseptic.", 0, "antiseptic"),
        (
            "Prep Patient",
            "Apply Anesthetic to put the patient to sleep.",
            0,
            "anesthetic",
        ),
        ("Make an Incision!", "Use Scalpel to make an incision.", 0, "scalpel"),
        ("Poor Visibility", "Apply a Sponge. ...", 0, "sponge"),
        (
            "Diagnosis",
            "You can use the Ultrasound or Lab Kit to diagnose ...",
            0,
            "ultrasound",
        ),
        ("Losing Blood", "", 1, "clamp"),
        ("Losing Blood", "", 0, "stitches"),
        (
            "Losing Blood very quickly",
            "Apply Clamps to reduce Bleeding during surgery.",
            2,
            "clamp",
        ),
        (
            "Losing Blood very quickly",
            "Apply Stitches to reduce Bleeding.",
            0,
            "stitches",
        ),
        ("Shattered Bone", "Apply Pins. ...", 1, "pins"),
        ("Broken Bone", "Apply a Splint.", 0, "splint"),
        (
            "Fever",
            "Diagnose the Infection With a Lab Kit then apply Antibiotics to ...",
            0,
            "lab_kit",
        ),
        ("High Fever", "Apply Antibiotics to bring down Temp", 0, "antibiotics"),
        (
            "Antibiotics",
            "Apply Antibiotics to prevent any infection. ...",
            0,
            "antibiotics",
        ),
        (
            "Extremely Weak Pulse",
            "You can increase the Pulse with a Blood Transfusion.",
            0,
            "transfusion",
        ),
        ("Coming To", "Your patient is about to wake up ...", 1, "anesthetic"),
        ("Something New", "", 0, None),
    ],
)
def test_each_tip_heading_maps_to_one_tool(
    heading: str, description: str, incisions: int, tool: str | None
) -> None:
    assert tip_tool(heading, description, incisions) == tool


def test_tips_are_parsed_in_surges_order() -> None:
    patient = patient_with(SleepLevel=0, Incisions=1, SiteSanitation=0, SiteDirtyness=5)
    headings = [h for h, _ in parse_tips(train_e_tips(patient))]
    assert headings[:3] == ["Awake", "Clean the Area", "Poor Visibility"]


def test_a_tip_glued_to_a_low_bleeding_tip_is_not_lost() -> None:
    """SurgE writes "Losing Blood" without a newline when bleeding is under 4."""
    patient = patient_with(
        "Broken Leg",
        SleepLevel=5,
        IsUltrasoundUsed=True,
        ShatteredBoneCount=1,
        BleedingLevel=2,
        SiteSanitation=20,
    )
    assert "Losing BloodShattered" in strip_formatting(train_e_tips(patient))
    headings = [h for h, _ in parse_tips(train_e_tips(patient))]
    assert headings[:3] == ["Losing Blood", "Shattered Bone", "Broken Bone"]


def test_very_quick_bleeding_keeps_its_description() -> None:
    patient = patient_with("Broken Leg", BleedingLevel=5, SiteSanitation=20)
    tips = dict(parse_tips(train_e_tips(patient)))
    assert "Apply" in tips["Losing Blood very quickly"]


def test_heart_stopped_picks_the_defibrillator() -> None:
    assert pick(patient_with(HeartDamage=1))["tool"] == "defibrillator"


def test_awake_with_an_open_wound_picks_the_anesthetic() -> None:
    assert pick(patient_with(SleepLevel=0, Incisions=1))["tool"] == "anesthetic"


def test_fix_it_when_the_issue_can_be_fixed() -> None:
    patient = patient_with(
        SleepLevel=5,
        IsUltrasoundUsed=True,
        IsFixable=True,
        Incisions=2,
        SiteSanitation=20,
    )
    assert pick(patient)["tool"] == "fix_it"


def test_unreadable_site_leaves_only_the_sponge() -> None:
    decision = pick(patient_with(SiteDirtyness=12))
    assert decision["tool"] == "sponge"
    assert decision["rule"] == "TE"  # the Poor Visibility tip itself


def test_stopped_heart_in_the_dark_falls_back_to_the_sponge() -> None:
    decision = pick(patient_with(HeartDamage=1, SiteDirtyness=12))
    assert decision == {
        "tool": "sponge",
        "rule": "TE0",
        "reason": "No usable Train-E tip; using the Sponge",
    }


def test_decisions_have_rule_and_short_reason() -> None:
    decision = pick(start_surgery("Heart Attack"))
    assert set(decision) == {"tool", "rule", "reason"}
    assert len(decision["reason"]) < 100


def test_generating_tips_leaves_the_game_unchanged() -> None:
    patient = start_surgery("Heart Attack", "none", 50)
    screen = observe(patient)
    state = random.getstate()
    train_e_tips(patient)
    assert patient.TrainE is False
    assert observe(patient) == screen
    assert random.getstate() == state


def test_anesthetic_on_an_unconscious_patient_kills_with_train_e_off() -> None:
    """The real rule; Train-E mode would give Near Coma instead, so it stays off."""
    from harness.surge import TOOL_TYPES

    normal = patient_with(SleepLevel=5)
    random.seed(0)
    normal.UseTool(TOOL_TYPES["anesthetic"])
    assert normal.IsSurgeryEnded and "Permanently" in normal.EndText


def test_baseline_plays_every_malady_legally_to_an_end() -> None:
    outcomes = []
    for number, malady in enumerate(MALADY_NAMES):
        result = run_surgery(
            Settings(malady, "none", 100, None, seed=number),
            baseline_policy,
            "baseline",
        )
        assert result.illegal_moves == 0, malady
        outcomes.append(result.outcome)
    assert SUCCESS in outcomes


def test_baseline_can_succeed_on_a_simple_malady() -> None:
    wins = sum(
        run_surgery(
            Settings("Broken Arm", "none", 100, None, seed=s), baseline_policy
        ).outcome
        == SUCCESS
        for s in range(30)
    )
    assert wins >= 10


def test_baseline_ignores_the_patient_beyond_tips() -> None:
    """The state it receives is the screen; decisions follow from tips plus that."""
    states: list[Any] = []

    def spy(state: dict[str, Any], patient: Patient) -> dict[str, str]:
        states.append(state)
        return baseline_policy(state, patient)

    run_surgery(Settings("Broken Arm", "none", 100, None, seed=1), spy, max_turns=3)
    assert states and all(list(s)[0] == "skill_level" for s in states)


# --- train-e-plus -----------------------------------------------------------

from harness.baseline import train_e_plus_policy  # noqa: E402
from harness.runner import Surgery  # noqa: E402


def plus_pick(patient: Patient) -> dict[str, str]:
    return train_e_plus_policy(observe(patient), patient)


def test_plus_matches_the_baseline_whenever_train_e_has_an_answer() -> None:
    differing = 0
    for number, malady in enumerate(MALADY_NAMES):
        surgery = Surgery(
            Settings(malady, "none", 50, None, seed=number), baseline_policy
        )
        while not surgery.ended:
            plain = baseline_policy(surgery.state, surgery.patient)
            plus = train_e_plus_policy(surgery.state, surgery.patient)
            if plus["rule"] == "TP3":  # the one override: Pins before closing
                assert plain["tool"] == "stitches" and plus["tool"] == "pins"
            elif plain["rule"] != "TE0":
                assert plus == plain, (malady, surgery.turn)
            differing += plus != plain
            surgery.step()
    assert differing > 0  # the patches do fire somewhere


def test_plus_cuts_for_pins_when_train_e_stalls() -> None:
    stalled = {
        "IsUltrasoundUsed": True,
        "ShatteredBoneCount": 1,
        "BrokenBoneCount": 0,
        "SiteSanitation": 20,
        "BleedingLevel": 0,
    }
    asleep = patient_with("Broken Leg", SleepLevel=5, **stalled)
    assert pick(asleep)["rule"] == "TE0"  # Train-E asks for Pins, which are unusable
    assert plus_pick(asleep)["tool"] == "scalpel"

    awake = patient_with("Broken Leg", SleepLevel=0, **stalled)
    decision = plus_pick(awake)
    assert decision["tool"] == "anesthetic"  # never the Scalpel on an awake patient


def test_plus_treats_a_hot_patient_with_no_fever_text() -> None:
    # Broken Arm needs no cut and no Fix It, so Train-E has nothing to say.
    hot = {
        "Temp": 104.6,
        "Fever": 0.0,
        "IsUltrasoundUsed": True,
        "SiteSanitation": 20,
        "BleedingLevel": 0,
    }
    patient = patient_with("Broken Arm", BrokenBoneCount=0, **hot)
    state = observe(patient)
    assert state["fever"] is None and state["temperature"] >= 101
    assert pick(patient)["rule"] == "TE0"
    assert plus_pick(patient) == {
        "tool": "lab_kit",
        "rule": "TP1",
        "reason": "Hot, no fever shown: Train-E is silent",
    }
    patient.IsLabKitUsed = patient.LabWorked = True
    patient.UpdatePatientUITexts()
    assert plus_pick(patient)["tool"] == "antibiotics"


def test_plus_does_not_repeat_antibiotics_right_after_a_dose() -> None:
    patient = patient_with(
        "Broken Arm",
        BrokenBoneCount=0,
        Temp=104.6,
        Fever=-3.0,
        IsUltrasoundUsed=True,
        IsLabKitUsed=True,
        LabWorked=True,
        SiteSanitation=20,
        ToolText="You used antibiotics to reduce the patient's infection.",
    )
    state = observe(patient)
    assert "antibiotics" in state["usable_tools"]
    decision = train_e_plus_policy(state, patient)
    assert decision["tool"] != "antibiotics"


def test_plus_never_picks_an_unusable_tool() -> None:
    for number, malady in enumerate(MALADY_NAMES):
        result = run_surgery(
            Settings(malady, "none", 100, None, seed=number), train_e_plus_policy
        )
        assert result.illegal_moves == 0, malady


def test_plus_pins_before_closing_the_incision() -> None:
    open_wound = patient_with(
        "Broken Leg",
        SleepLevel=5,
        Incisions=1,
        IsUltrasoundUsed=True,
        ShatteredBoneCount=1,
        BrokenBoneCount=0,
        BleedingLevel=0,
        SiteSanitation=20,
    )
    assert pick(open_wound)["tool"] == "stitches"  # Train-E closes it first
    assert plus_pick(open_wound) == {
        "tool": "pins",
        "rule": "TP3",
        "reason": "Pin the bones before closing the incision",
    }
