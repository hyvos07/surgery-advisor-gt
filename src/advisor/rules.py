"""One function per rule, and the RULES priority list.

The rules are in docs/decision-engine.md, in the same order: emergency rules E1-E7,
then phase rules P1-P13. Each rule is a pure function that returns a `Decision` when
it fires and `None` otherwise. Rule IDs are permanent. Thresholds and margins come
from `config.py`, never from literals here.

`is_legal` is the legality check and `fallback` is the last resort (rule `F0`); the
engine uses all three (see `engine.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum

from advisor.config import FEVER_CRISIS_TURNS, NORMAL_TEMPERATURE_F, Config
from advisor.forecast import Forecast
from advisor.knowledge import HEMOPHILIAC
from advisor.memory import Memory
from advisor.state import (
    Bleeding,
    Decision,
    Fever,
    Pulse,
    ScreenState,
    Site,
    Status,
    Tool,
    Visibility,
)

RuleFn = Callable[[ScreenState, Memory, Forecast, Config], Decision | None]

FALLBACK_RULE = "F0"

# Bleeding words that call for the Clamp when an incision is open.
_HEAVY_BLEEDING = (Bleeding.LOSING, Bleeding.VERY_QUICKLY)
# Statuses where the Scalpel is safe: only a fully awake patient is killed by it.
_SCALPEL_SAFE = (Status.UNCONSCIOUS, Status.COMING_TO)
# Statuses where an open incision needs another Anesthetic dose.
_NEEDS_ANESTHETIC = (Status.AWAKE, Status.COMING_TO)


# --- Helpers ------------------------------------------------------------------


def _words(value: StrEnum) -> str:
    """An enum value as plain words: `coming_to` becomes `coming to`."""
    return value.value.replace("_", " ")


def _shattered(s: ScreenState) -> bool:
    """True if the screen shows shattered bones."""
    return bool(s.bones and s.bones.shattered)


def _broken(s: ScreenState) -> bool:
    """True if the screen shows broken bones."""
    return bool(s.bones and s.bones.broken)


def _cut_needed(s: ScreenState, m: Memory) -> bool:
    """True if more incisions are needed. Always False without a diagnosis."""
    if m.diagnosis is None or m.incisions_needed is None:
        return False
    return s.incisions < m.incisions_needed or (_shattered(s) and not s.incision_open)


def _fixed(m: Memory) -> bool:
    """True if the malady is fixed, or never needed Fix It. False before diagnosis."""
    return m.diagnosis is not None and (m.fixed or not m.needs_fix)


def _fever_tool(m: Memory) -> Tool:
    """Lab Kit if it has not been done yet, else Antibiotics."""
    return Tool.ANTIBIOTICS if m.lab_kit_done else Tool.LAB_KIT


def _fever_decision(rule: str, m: Memory, reason: str) -> Decision:
    return Decision(_fever_tool(m), rule, reason)


def _wait_tool(c: Config) -> Tool:
    """The safe waiting tool: Antiseptic, or Sponge in minimal mode."""
    return Tool.SPONGE if c.minimal_antiseptic else Tool.ANTISEPTIC


# --- Emergency rules ----------------------------------------------------------


def rule_e1_revive(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if s.status is Status.HEART_STOPPED:
        return Decision(Tool.DEFIBRILLATOR, "E1", "The patient's heart has stopped")
    return None


def rule_e2_clear_view(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if s.visibility is Visibility.CANT_SEE:
        return Decision(
            Tool.SPONGE, "E2", "The site can't be seen; only the Sponge works"
        )
    if s.visibility is Visibility.HARD_TO_SEE:
        # Dirt rises by bleeding plus open incisions each turn.
        dirt_rise = c.bleeding_upper(s.bleeding) + s.incisions
        if dirt_rise >= c.margins.dirt_guard:
            return Decision(
                Tool.SPONGE, "E2", "Site is hard to see and bleeding and cuts add dirt"
            )
    return None


def rule_e3_save_pulse(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if f.pulse_word_next is Pulse.EXTREMELY_WEAK:
        return Decision(
            Tool.TRANSFUSION, "E3", "Pulse may drop to extremely weak next turn"
        )
    return None


def rule_e4_keep_asleep(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if s.incision_open and s.status in _NEEDS_ANESTHETIC:
        return Decision(
            Tool.ANESTHETIC,
            "E4",
            f"An incision is open and the patient is {_words(s.status)}",
        )
    return None


def rule_e5_stop_heavy_bleeding(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if not s.incision_open:
        return None
    if s.bleeding in _HEAVY_BLEEDING:
        return Decision(
            Tool.CLAMP, "E5", f"Bleeding is {_words(s.bleeding)} with an incision open"
        )
    # A hemophiliac bleeds double, so even slow bleeding is clamped one step earlier.
    if s.bleeding is Bleeding.SLOWLY and m.has_condition(HEMOPHILIAC):
        return Decision(
            Tool.CLAMP, "E5", "Hemophiliac is bleeding with an incision open"
        )
    return None


def rule_e6_fever_crisis(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if m.fever_negative:
        return None
    if s.fever is Fever.CLIMBING_FAST:
        return _fever_decision("E6", m, "Fever is climbing fast")
    if f.temperature_in(FEVER_CRISIS_TURNS) >= c.margins.fever_crisis_f:
        return _fever_decision(
            "E6",
            m,
            f"Temperature may reach {c.margins.fever_crisis_f} F within "
            f"{FEVER_CRISIS_TURNS} turns",
        )
    return None


def rule_e7_clean_open_site(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if c.minimal_antiseptic:
        return None
    if s.site is not Site.CLEAN and s.incision_open and not m.fever_negative:
        return Decision(
            Tool.ANTISEPTIC, "E7", f"Site is {_words(s.site)} with an incision open"
        )
    return None


# --- Phase rules --------------------------------------------------------------


def rule_p1_diagnose(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if m.diagnosis is None:
        return Decision(Tool.ULTRASOUND, "P1", "The patient is not diagnosed yet")
    return None


def rule_p2_break_fever(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    positive = s.fever is not None or m.temperature_rising
    if positive and not m.fever_negative:
        return _fever_decision("P2", m, "Fever is positive and not yet broken")
    return None


def rule_p3_fix(s: ScreenState, m: Memory, f: Forecast, c: Config) -> Decision | None:
    if Tool.FIX_IT in s.usable_tools:
        return Decision(Tool.FIX_IT, "P3", "Fix It is ready to use")
    return None


def rule_p4_pin(s: ScreenState, m: Memory, f: Forecast, c: Config) -> Decision | None:
    if _shattered(s) and s.incision_open:
        return Decision(Tool.PINS, "P4", "Shattered bones and an incision is open")
    return None


def rule_p5_cut(s: ScreenState, m: Memory, f: Forecast, c: Config) -> Decision | None:
    if _cut_needed(s, m) and s.status in _SCALPEL_SAFE:
        return Decision(
            Tool.SCALPEL,
            "P5",
            f"More incisions are needed and the patient is {_words(s.status)}",
        )
    return None


def rule_p6_close(s: ScreenState, m: Memory, f: Forecast, c: Config) -> Decision | None:
    if s.incision_open and _fixed(m) and not _shattered(s):
        return Decision(Tool.STITCHES, "P6", "Malady is fixed; close the incision")
    return None


def rule_p7_splint(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if m.diagnosis is not None and _broken(s) and not s.incision_open:
        return Decision(Tool.SPLINT, "P7", "Broken bones and no incision is open")
    return None


def rule_p8_surface_bleeding(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if s.bleeding is not None and not s.incision_open:
        return Decision(
            Tool.STITCHES,
            "P8",
            f"Bleeding is {_words(s.bleeding)} and no incision is open",
        )
    return None


def rule_p9_clean_before_cutting(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if not _cut_needed(s, m) or s.site is Site.CLEAN or m.fever_negative:
        return None
    if c.minimal_antiseptic:
        # Only the deepest surgeries are worth the turn, and only before cutting.
        deep = (
            m.incisions_needed is not None
            and m.incisions_needed >= c.antiseptic_min_incisions
        )
        if not deep or s.incision_open:
            return None
    return Decision(
        Tool.ANTISEPTIC, "P9", f"Site is {_words(s.site)} and a cut is needed next"
    )


def rule_p10_prep_for_cutting(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if _cut_needed(s, m) and s.status is Status.AWAKE:
        return Decision(Tool.ANESTHETIC, "P10", "A cut is needed next; put to sleep")
    return None


def rule_p11_finish_fever(
    s: ScreenState, m: Memory, f: Forecast, c: Config
) -> Decision | None:
    if s.temperature >= c.profile.success_temp_f and not m.fever_negative:
        return _fever_decision(
            "P11", m, f"Temperature is too high to finish ({s.temperature} F)"
        )
    return None


def rule_p12_tidy(s: ScreenState, m: Memory, f: Forecast, c: Config) -> Decision | None:
    if s.visibility is Visibility.HARD_TO_SEE:
        return Decision(Tool.SPONGE, "P12", "The site is hard to see")
    return None


def rule_p13_wait(s: ScreenState, m: Memory, f: Forecast, c: Config) -> Decision | None:
    return Decision(_wait_tool(c), "P13", "Nothing else to do; waiting")


RULES: tuple[RuleFn, ...] = (
    rule_e1_revive,
    rule_e2_clear_view,
    rule_e3_save_pulse,
    rule_e4_keep_asleep,
    rule_e5_stop_heavy_bleeding,
    rule_e6_fever_crisis,
    rule_e7_clean_open_site,
    rule_p1_diagnose,
    rule_p2_break_fever,
    rule_p3_fix,
    rule_p4_pin,
    rule_p5_cut,
    rule_p6_close,
    rule_p7_splint,
    rule_p8_surface_bleeding,
    rule_p9_clean_before_cutting,
    rule_p10_prep_for_cutting,
    rule_p11_finish_fever,
    rule_p12_tidy,
    rule_p13_wait,
)


# --- Legality and fallback ----------------------------------------------------


def is_legal(tool: Tool, state: ScreenState, memory: Memory) -> bool:
    """False if `tool` would break the legality table in decision-engine.md."""
    if tool not in state.usable_tools:
        return False
    if tool is Tool.SCALPEL:
        if state.status is Status.AWAKE:
            return False
        needed = memory.incisions_needed
        return needed is None or state.incisions < needed
    if tool is Tool.ANESTHETIC:
        return state.status is not Status.UNCONSCIOUS
    if tool is Tool.CLAMP:
        return state.bleeding is not None
    if tool is Tool.SPLINT:
        return memory.diagnosis is not None and _broken(state)
    if tool is Tool.PINS:
        return memory.diagnosis is not None and _shattered(state)
    if tool is Tool.ANTIBIOTICS:
        return state.temperature > NORMAL_TEMPERATURE_F
    return True


def fallback(state: ScreenState, config: Config) -> Decision:
    """Antiseptic if usable, else Sponge (always Sponge in minimal mode)."""
    if not config.minimal_antiseptic and Tool.ANTISEPTIC in state.usable_tools:
        return Decision(
            Tool.ANTISEPTIC, FALLBACK_RULE, "No rule applies; safe waiting move"
        )
    return Decision(Tool.SPONGE, FALLBACK_RULE, "No rule applies; safe waiting move")
