"""Fail rates, margin bands, profiles and the config constructor."""

import dataclasses

import pytest

from advisor import config
from advisor.config import (
    PROFILES,
    SURGE,
    WIKI,
    Config,
    Margins,
    fail_rate,
    margins_for,
    pulse_word_for,
)
from advisor.state import Bleeding, Fever, Pulse, Visibility


@pytest.mark.parametrize(
    ("skill", "none", "stethoscope", "other"),
    [
        (0, 30, 15, 35),
        (50, 18, 9, 18),  # round(17.5) == 18, round(8.75) == 9, round(18.33) == 18
        (100, 5, 2, 2),  # Python rounds 2.5 to 2, as SurgE does
    ],
)
def test_fail_rate_table(skill: int, none: int, stethoscope: int, other: int) -> None:
    assert fail_rate(skill, None) == none
    assert fail_rate(skill, "stethoscope") == stethoscope
    for modifier in ("tea", "exquisite_bone_saw", "nano_nurse_bot"):
        assert fail_rate(skill, modifier) == other


def test_owner_setup_fail_rates() -> None:
    assert fail_rate(100, "exquisite_bone_saw") == 2
    assert fail_rate(100, None) == 5


def test_fail_rate_rejects_bad_input() -> None:
    with pytest.raises(ValueError, match="0-100"):
        fail_rate(101, None)
    with pytest.raises(ValueError, match="0-100"):
        fail_rate(-1, None)
    with pytest.raises(ValueError, match="integer"):
        fail_rate(True, None)
    with pytest.raises(ValueError, match="modifier"):
        fail_rate(50, "magic_wand")


def test_margin_bands_at_their_edges() -> None:
    low = Margins(fever_crisis_f=108.0, pulse_turns_ahead=1)
    mid = Margins(fever_crisis_f=107.0, pulse_turns_ahead=1)
    high = Margins(fever_crisis_f=106.0, pulse_turns_ahead=2)
    assert margins_for(0) == low
    assert margins_for(9) == low
    assert margins_for(10) == mid
    assert margins_for(19) == mid
    assert margins_for(20) == high
    assert margins_for(35) == high


def test_profiles() -> None:
    assert PROFILES == {"surge": SURGE, "wiki": WIKI}
    assert (SURGE.success_temp_f, SURGE.hyperactive_sleep) == (101.0, 5)
    assert SURGE.dirt_raises_fails is False
    assert (WIKI.success_temp_f, WIKI.hyperactive_sleep) == (100.4, 4)
    assert WIKI.dirt_raises_fails is True


def test_for_patient_defaults() -> None:
    c = Config.for_patient(50, None)
    assert c.profile is SURGE
    assert c.fail_rate == 18
    assert c.margins == margins_for(18)
    assert c.very_quickly_bleed_cap == 6
    assert c.antiseptic_mode == "minimal"  # D14
    assert c.antiseptic_min_incisions == 5
    assert c.minimal_antiseptic is True


def test_minimal_is_the_default_antiseptic_mode_and_draft_stays_selectable() -> None:
    assert Config.for_patient(50, None).antiseptic_mode == "minimal"
    assert Config(profile=SURGE, fail_rate=5, margins=margins_for(5)).minimal_antiseptic
    draft = Config.for_patient(50, None, antiseptic_mode="draft")
    assert draft.antiseptic_mode == "draft" and draft.minimal_antiseptic is False


def test_for_patient_picks_band_from_fail_rate_not_skill() -> None:
    # Skill 100 alone is 5% (low band); skill 0 with a Stethoscope is 15% (mid).
    assert Config.for_patient(100, None).margins.fever_crisis_f == 108.0
    assert Config.for_patient(0, "stethoscope").margins.fever_crisis_f == 107.0
    assert Config.for_patient(0, None).margins.fever_crisis_f == 106.0
    assert Config.for_patient(100, "exquisite_bone_saw").fail_rate == 2


def test_for_patient_options() -> None:
    c = Config.for_patient(75, "tea", profile="wiki", antiseptic_mode="minimal")
    assert c.profile is WIKI
    assert c.minimal_antiseptic is True
    assert c.fail_rate == 10  # round(35 - 25)
    assert c.margins == margins_for(10)


def test_for_patient_rejects_bad_options() -> None:
    with pytest.raises(ValueError, match="profile"):
        Config.for_patient(50, None, profile="real")
    with pytest.raises(ValueError, match="antiseptic_mode"):
        Config.for_patient(50, None, antiseptic_mode="none")
    with pytest.raises(ValueError, match="antiseptic_mode"):
        Config(profile=SURGE, fail_rate=5, margins=margins_for(5), antiseptic_mode="x")


def test_config_is_frozen() -> None:
    c = Config.for_patient(50, None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.fail_rate = 1  # type: ignore[misc]


def test_pulse_word_for_value() -> None:
    assert pulse_word_for(40) is Pulse.STRONG
    assert pulse_word_for(31) is Pulse.STRONG
    assert pulse_word_for(30) is Pulse.STEADY
    assert pulse_word_for(21) is Pulse.STEADY
    assert pulse_word_for(20) is Pulse.WEAK
    assert pulse_word_for(11) is Pulse.WEAK
    assert pulse_word_for(10) is Pulse.EXTREMELY_WEAK
    assert pulse_word_for(1) is Pulse.EXTREMELY_WEAK
    assert pulse_word_for(-3) is Pulse.EXTREMELY_WEAK


def test_word_upper_bounds() -> None:
    c = Config.for_patient(50, None)
    assert [c.bleeding_upper(b) for b in (None, *Bleeding)] == [0, 1, 3, 6]
    assert [c.fever_upper(f) for f in (None, *Fever)] == [0.0, 0.5, 2.0, 4.0]
    assert c.dirt_upper(Visibility.CLEAR) == 3
    assert c.dirt_upper(Visibility.HARD_TO_SEE) == 9
    capped = dataclasses.replace(c, very_quickly_bleed_cap=8)
    assert capped.bleeding_upper(Bleeding.VERY_QUICKLY) == 8


def test_named_constants() -> None:
    assert config.ANESTHETIC_SLEEP == 10
    assert config.NORMAL_TEMPERATURE_F == 98.6
    assert config.INFECTION_DEATH_F == 111.0
    assert [config.PULSE_WORD_FLOOR[p] for p in Pulse] == [31, 21, 11, 1]
    assert config.SLEEP_COMING_TO_MAX == 2
    assert config.SLEEP_UNCONSCIOUS_MIN == 3
