"""Safety margins per skill band, and the surge and wiki threshold profiles.

Every threshold that a rule or the forecast uses lives here, so `rules.py` and
`forecast.py` contain no numeric literals. Sources: docs/decision-engine.md
(margins, profiles) and docs/game-model.md (mechanics).
"""

from __future__ import annotations

from dataclasses import dataclass

from advisor.state import Bleeding, Fever, Modifier, Pulse, Visibility

# --- Game mechanics (docs/game-model.md) -----------------------------------

ANESTHETIC_SLEEP = 10  # sleep set by the Anesthetic (the same turn's update takes 1)
SLEEP_DROP_PER_TURN = 1  # sleep falls by 1 per turn while the heart beats
SLEEP_COMING_TO_MAX = 2  # sleep 1-2 shows Coming to; 0 is Awake
SLEEP_UNCONSCIOUS_MIN = 3  # sleep 3+ shows Unconscious

NORMAL_TEMPERATURE_F = 98.6  # Antibiotics do nothing at or below this
INFECTION_DEATH_F = 111.0  # temperature at or above this kills

PULSE_MAX = 40
TRANSFUSION_PULSE_GAIN = 15

# Lowest hidden pulse behind each pulse word ("extremely weak" is 10 or less;
# 1 is the lowest pulse the patient can have and still be alive).
PULSE_WORD_FLOOR: dict[Pulse, int] = {
    Pulse.STRONG: 31,
    Pulse.STEADY: 21,
    Pulse.WEAK: 11,
    Pulse.EXTREMELY_WEAK: 1,
}

# Highest hidden bleeding behind each bleeding word. `very_quickly` (4 or more)
# has no upper bound, so it uses Config.very_quickly_bleed_cap.
BLEEDING_UPPER: dict[Bleeding | None, int] = {
    None: 0,
    Bleeding.SLOWLY: 1,
    Bleeding.LOSING: 3,
}
HEMOPHILIAC_BLEED_FACTOR = 2  # a hemophiliac treats every bleed as double
INCISION_PULSE_LOSS = 1  # pulse falls 1 per turn while any incision is open

# Highest fever rate (deg F per turn) behind each fever word. SurgE caps the
# fever at 4 per turn, which is the `climbing_fast` bound.
FEVER_UPPER: dict[Fever | None, float] = {
    None: 0.0,
    Fever.SLOWLY_RISING: 0.5,
    Fever.CLIMBING: 2.0,
    Fever.CLIMBING_FAST: 4.0,
}
FEVER_CRISIS_TURNS = 2  # E6 looks this many turns ahead for the crisis temperature
# P2 treats a fever only above this temperature, the real game's finish threshold
# (D16). The same under the `surge` and `wiki` profiles.
FEVER_TREAT_F = 100.4

# Highest hidden dirt behind each visibility word. `cant_see` is dirt 10 or
# more, so its entry is that lower bound, not an upper one.
DIRT_CANT_SEE = 10
DIRT_UPPER: dict[Visibility, int] = {
    Visibility.CLEAR: 3,
    Visibility.HARD_TO_SEE: 9,
    Visibility.CANT_SEE: DIRT_CANT_SEE,
}

TOUGH_SKIN_EXTRA_INCISIONS = 1

# --- Margin bands by fail rate ----------------------------------------------

MARGIN_MID_FAIL_RATE = 10  # fail rate at which the middle band starts
MARGIN_HIGH_FAIL_RATE = 20  # fail rate at which the high band starts

# --- Antiseptic modes --------------------------------------------------------

ANTISEPTIC_DRAFT = "draft"
ANTISEPTIC_MINIMAL = "minimal"
ANTISEPTIC_MODES = (ANTISEPTIC_DRAFT, ANTISEPTIC_MINIMAL)
ANTISEPTIC_MIN_INCISIONS_DEFAULT = 5  # minimal mode: only Brain Tumor needs it
VERY_QUICKLY_BLEED_CAP_DEFAULT = 6

# Fail-rate formulas, as in SurgE's Patient._CalculateSkillFailRate.
_STETHOSCOPE_BASE = 30
_STETHOSCOPE_DIVISOR = 2
_OTHER_MODIFIER_BASE = 35
_OTHER_MODIFIER_SKILL_DIVISOR = 3
_NO_MODIFIER_BASE = 30
_NO_MODIFIER_SKILL_DIVISOR = 4


@dataclass(frozen=True)
class Profile:
    """Thresholds that differ between SurgE and the real game."""

    name: str
    success_temp_f: float
    hyperactive_sleep: int
    dirt_raises_fails: bool


SURGE = Profile(
    name="surge", success_temp_f=101.0, hyperactive_sleep=5, dirt_raises_fails=False
)
WIKI = Profile(
    name="wiki", success_temp_f=100.4, hyperactive_sleep=4, dirt_raises_fails=True
)
PROFILES: dict[str, Profile] = {SURGE.name: SURGE, WIKI.name: WIKI}


@dataclass(frozen=True)
class Margins:
    """Safety margins that depend on the fail rate."""

    fever_crisis_f: float  # E6: crisis temperature
    pulse_turns_ahead: int  # forecast turns used for the pulse


_MARGINS_LOW = Margins(fever_crisis_f=108.0, pulse_turns_ahead=1)
_MARGINS_MID = Margins(fever_crisis_f=107.0, pulse_turns_ahead=1)
_MARGINS_HIGH = Margins(fever_crisis_f=106.0, pulse_turns_ahead=2)


def fail_rate(skill: int, modifier: str | None) -> int:
    """Skill-fail percentage, identical to SurgE's `_CalculateSkillFailRate`.

    Uses Python's `round` (banker's rounding) exactly as SurgE does.
    """
    if isinstance(skill, bool) or not isinstance(skill, int):
        raise ValueError(f"skill must be an integer, got {skill!r}")
    if not 0 <= skill <= 100:
        raise ValueError(f"skill must be 0-100, got {skill}")
    if modifier is None:
        return round(_NO_MODIFIER_BASE - skill / _NO_MODIFIER_SKILL_DIVISOR)
    if modifier not in {m.value for m in Modifier}:
        raise ValueError(f"unknown modifier {modifier!r}")
    if modifier == Modifier.STETHOSCOPE:
        return round(
            (_STETHOSCOPE_BASE - skill / _NO_MODIFIER_SKILL_DIVISOR)
            / _STETHOSCOPE_DIVISOR
        )
    return round(_OTHER_MODIFIER_BASE - skill / _OTHER_MODIFIER_SKILL_DIVISOR)


def margins_for(rate: int) -> Margins:
    """Margins for a fail rate: under 10, 10-19, or 20 and above."""
    if rate >= MARGIN_HIGH_FAIL_RATE:
        return _MARGINS_HIGH
    if rate >= MARGIN_MID_FAIL_RATE:
        return _MARGINS_MID
    return _MARGINS_LOW


def pulse_word_for(value: int) -> Pulse:
    """The pulse word the screen shows for a hidden pulse value."""
    for word in (Pulse.STRONG, Pulse.STEADY, Pulse.WEAK):
        if value >= PULSE_WORD_FLOOR[word]:
            return word
    return Pulse.EXTREMELY_WEAK


@dataclass(frozen=True)
class Config:
    profile: Profile
    fail_rate: int
    margins: Margins
    very_quickly_bleed_cap: int = VERY_QUICKLY_BLEED_CAP_DEFAULT
    antiseptic_mode: str = ANTISEPTIC_MINIMAL  # "minimal" (default, D14) | "draft"
    antiseptic_min_incisions: int = ANTISEPTIC_MIN_INCISIONS_DEFAULT

    def __post_init__(self) -> None:
        if self.antiseptic_mode not in ANTISEPTIC_MODES:
            raise ValueError(
                f"antiseptic_mode must be one of {', '.join(ANTISEPTIC_MODES)}; "
                f"got {self.antiseptic_mode!r}"
            )

    @classmethod
    def for_patient(
        cls,
        skill: int,
        modifier: str | None,
        profile: str = "surge",
        antiseptic_mode: str = ANTISEPTIC_MINIMAL,
    ) -> Config:
        if profile not in PROFILES:
            raise ValueError(
                f"unknown profile {profile!r}; choose from {', '.join(PROFILES)}"
            )
        rate = fail_rate(skill, modifier)
        return cls(
            profile=PROFILES[profile],
            fail_rate=rate,
            margins=margins_for(rate),
            antiseptic_mode=antiseptic_mode,
        )

    @property
    def minimal_antiseptic(self) -> bool:
        return self.antiseptic_mode == ANTISEPTIC_MINIMAL

    def bleeding_upper(self, word: Bleeding | None) -> int:
        """Highest bleeding behind a bleeding word, per turn."""
        if word is Bleeding.VERY_QUICKLY:
            return self.very_quickly_bleed_cap
        return BLEEDING_UPPER[word]

    @staticmethod
    def fever_upper(word: Fever | None) -> float:
        """Highest fever rate (deg F per turn) behind a fever word."""
        return FEVER_UPPER[word]

    @staticmethod
    def dirt_upper(word: Visibility) -> int:
        """Highest dirt behind a visibility word (the lower bound for cant_see)."""
        return DIRT_UPPER[word]
