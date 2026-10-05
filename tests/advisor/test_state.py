"""Screen-state parsing: PRD section 8 example, round trip and validation."""

import copy
import dataclasses
from typing import Any

import pytest

from advisor.state import (
    Bleeding,
    Bones,
    Decision,
    Fever,
    Modifier,
    Pulse,
    ScreenState,
    Site,
    Status,
    Tool,
    Visibility,
)

# The example in PRD section 8.
PRD_EXAMPLE: dict[str, Any] = {
    "skill_level": 40,
    "modifier": None,
    "special_condition_text": "The patient is hyperactive.",
    "scan_text": "Patient had a heart attack.",
    "pulse": "steady",
    "status": "unconscious",
    "temperature": 99.1,
    "site": "not_sanitized",
    "visibility": "hard_to_see",
    "incisions": 1,
    "bones": {"broken": 0, "shattered": 0},
    "bleeding": "slowly",
    "fever": None,
    "last_tool_text": "You've made a neat incision.",
    "usable_tools": [
        "sponge",
        "anesthetic",
        "stitches",
        "scalpel",
        "antiseptic",
        "lab_kit",
        "transfusion",
        "splint",
        "pins",
        "clamp",
    ],
}


def example() -> dict[str, Any]:
    return copy.deepcopy(PRD_EXAMPLE)


def test_prd_example_parses() -> None:
    s = ScreenState.from_dict(PRD_EXAMPLE)
    assert s.skill_level == 40
    assert s.modifier is None
    assert s.special_condition_text == "The patient is hyperactive."
    assert s.scan_text == "Patient had a heart attack."
    assert s.pulse is Pulse.STEADY
    assert s.status is Status.UNCONSCIOUS
    assert s.temperature == 99.1
    assert s.site is Site.NOT_SANITIZED
    assert s.visibility is Visibility.HARD_TO_SEE
    assert s.incisions == 1
    assert s.incision_open
    assert s.bones == Bones(broken=0, shattered=0)
    assert s.bleeding is Bleeding.SLOWLY
    assert s.fever is None
    assert s.last_tool_text == "You've made a neat incision."
    assert s.usable_tools[0] is Tool.SPONGE
    assert len(s.usable_tools) == 10
    assert isinstance(s.usable_tools, tuple)


def test_prd_example_round_trips() -> None:
    s = ScreenState.from_dict(PRD_EXAMPLE)
    assert s.to_dict() == PRD_EXAMPLE
    assert list(s.to_dict()) == list(PRD_EXAMPLE)  # same key order
    assert ScreenState.from_dict(s.to_dict()) == s


def test_round_trip_with_nulls_and_optional_values() -> None:
    d = example()
    d.update(
        modifier="exquisite_bone_saw",
        special_condition_text=None,
        scan_text=None,
        bones=None,
        bleeding="very_quickly",
        fever="climbing_fast",
        incisions=0,
        status="heart_stopped",
        usable_tools=["defibrillator", "sponge"],
    )
    s = ScreenState.from_dict(d)
    assert s.modifier is Modifier.EXQUISITE_BONE_SAW
    assert s.bones is None
    assert s.bleeding is Bleeding.VERY_QUICKLY
    assert s.fever is Fever.CLIMBING_FAST
    assert not s.incision_open
    assert s.to_dict() == d


def test_integer_temperature_is_accepted_as_float() -> None:
    d = example()
    d["temperature"] = 98
    s = ScreenState.from_dict(d)
    assert s.temperature == 98.0
    assert isinstance(s.temperature, float)


def test_screen_state_is_frozen() -> None:
    s = ScreenState.from_dict(PRD_EXAMPLE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.incisions = 2  # type: ignore[misc]


def test_missing_key() -> None:
    d = example()
    del d["pulse"]
    with pytest.raises(ValueError, match="missing keys: pulse"):
        ScreenState.from_dict(d)


def test_extra_key() -> None:
    d = example()
    d["sleep_level"] = 9
    with pytest.raises(ValueError, match="unknown keys: sleep_level"):
        ScreenState.from_dict(d)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("pulse", "fast", "pulse must be one of"),
        ("status", "Awake", "status must be one of"),
        ("site", "dirty", "site must be one of"),
        ("visibility", None, "visibility must be a string"),
        ("bleeding", "none", "bleeding must be one of"),
        ("fever", "hot", "fever must be one of"),
        ("modifier", "magic", "modifier must be one of"),
        ("usable_tools", ["sponge", "hammer"], "usable_tools item must be one of"),
    ],
)
def test_bad_enum_value(key: str, value: object, message: str) -> None:
    d = example()
    d[key] = value
    with pytest.raises(ValueError, match=message):
        ScreenState.from_dict(d)


@pytest.mark.parametrize("key", ["skill_level", "incisions"])
def test_bool_is_not_an_int(key: str) -> None:
    d = example()
    d[key] = True
    with pytest.raises(ValueError, match=f"{key} must be an integer"):
        ScreenState.from_dict(d)


def test_bool_is_not_a_bone_count_or_temperature() -> None:
    d = example()
    d["bones"] = {"broken": True, "shattered": 0}
    with pytest.raises(ValueError, match=r"bones\.broken must be an integer"):
        ScreenState.from_dict(d)
    d = example()
    d["temperature"] = True
    with pytest.raises(ValueError, match="temperature must be a number"):
        ScreenState.from_dict(d)


@pytest.mark.parametrize("skill", [-1, 101])
def test_skill_out_of_range(skill: int) -> None:
    d = example()
    d["skill_level"] = skill
    with pytest.raises(ValueError, match="skill_level must be 0-100"):
        ScreenState.from_dict(d)


@pytest.mark.parametrize("skill", [0, 100])
def test_skill_range_edges_are_valid(skill: int) -> None:
    d = example()
    d["skill_level"] = skill
    assert ScreenState.from_dict(d).skill_level == skill


def test_other_type_errors() -> None:
    d = example()
    d["skill_level"] = 40.5
    with pytest.raises(ValueError, match="skill_level must be an integer"):
        ScreenState.from_dict(d)
    d = example()
    d["temperature"] = "99.1"
    with pytest.raises(ValueError, match="temperature must be a number"):
        ScreenState.from_dict(d)
    d = example()
    d["last_tool_text"] = None
    with pytest.raises(ValueError, match="last_tool_text must be a string"):
        ScreenState.from_dict(d)
    d = example()
    d["scan_text"] = 5
    with pytest.raises(ValueError, match="scan_text must be a string"):
        ScreenState.from_dict(d)
    d = example()
    d["incisions"] = -1
    with pytest.raises(ValueError, match="incisions must not be negative"):
        ScreenState.from_dict(d)


def test_bad_bones() -> None:
    d = example()
    d["bones"] = {"broken": 0}
    with pytest.raises(ValueError, match="exactly the keys"):
        ScreenState.from_dict(d)
    d = example()
    d["bones"] = [0, 0]
    with pytest.raises(ValueError, match="bones must be an object"):
        ScreenState.from_dict(d)


def test_bad_usable_tools() -> None:
    d = example()
    d["usable_tools"] = "sponge"
    with pytest.raises(ValueError, match="usable_tools must be an array"):
        ScreenState.from_dict(d)
    d = example()
    d["usable_tools"] = ["sponge", "sponge"]
    with pytest.raises(ValueError, match="must not repeat"):
        ScreenState.from_dict(d)


def test_not_an_object() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        ScreenState.from_dict([])  # type: ignore[arg-type]


def test_enum_values_match_the_prd() -> None:
    assert [t.value for t in Tool] == [
        "defibrillator",
        "sponge",
        "anesthetic",
        "stitches",
        "scalpel",
        "ultrasound",
        "antiseptic",
        "fix_it",
        "lab_kit",
        "antibiotics",
        "transfusion",
        "splint",
        "pins",
        "clamp",
    ]
    assert [m.value for m in Modifier] == [
        "stethoscope",
        "tea",
        "exquisite_bone_saw",
        "nano_nurse_bot",
    ]
    assert [p.value for p in Pulse] == ["strong", "steady", "weak", "extremely_weak"]
    assert [s.value for s in Status] == [
        "awake",
        "coming_to",
        "unconscious",
        "heart_stopped",
    ]


def test_decision_to_dict() -> None:
    d = Decision(tool=Tool.SCALPEL, rule="P5", reason="Heart Attack needs 2 cuts")
    assert d.to_dict() == {
        "tool": "scalpel",
        "rule": "P5",
        "reason": "Heart Attack needs 2 cuts",
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        d.rule = "P6"  # type: ignore[misc]
