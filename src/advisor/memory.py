"""What the advisor remembers between turns.

The screen stops showing some facts (which malady it was, how long the patient
will sleep, whether the lab kit ran), so memory keeps them. It never reads hidden
values: everything is worked out from the screen state, from the advisor's own
last decision, and from counting turns.

`Memory` is the only mutable object in the advisor, and only `Memory.update()`
changes it. The engine sets `last_decision` after each decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from advisor.config import (
    ANESTHETIC_SLEEP,
    SLEEP_COMING_TO_MAX,
    SLEEP_DROP_PER_TURN,
    SLEEP_UNCONSCIOUS_MIN,
    TOUGH_SKIN_EXTRA_INCISIONS,
    Config,
)
from advisor.knowledge import (
    ANTIBIOTIC_RESISTANT,
    HEMOPHILIAC,
    HYPERACTIVE,
    TOUGH_SKIN,
    Condition,
    Knowledge,
    Malady,
    normalize_text,
)
from advisor.state import Decision, ScreenState, Status, Tool

# A tool text containing this means the tool did nothing (AGENTS.md hard rule 4).
SKILL_FAIL_MARKER = "[Skill Fail"

# What `last_tool_text` starts with when a tool worked, copied from SurgE's
# core/patient.py. Memory trusts a tool's effect only if its text is here and the
# tool is the one the advisor chose last turn (SurgE leaves the old text on screen
# when a tool does nothing, e.g. Antibiotics at 98.6 F).
CONFIRMATIONS: dict[Tool, str] = {
    Tool.ANESTHETIC: "The patient is now asleep.",
    Tool.FIX_IT: "You fixed the issue!",
    Tool.LAB_KIT: (
        "You performed lab work on the patient, and have antibiotics at the ready."
    ),
    Tool.ANTIBIOTICS: "You used antibiotics to reduce the patient's infection.",
    Tool.ULTRASOUND: "You scanned the patient with ultrasound",
}

# Nose Job starts diagnosed, so Ultrasound never runs and a hidden condition is
# never revealed. Assume both until a condition text is shown.
ASSUMED_WHEN_STARTS_DIAGNOSED: frozenset[str] = frozenset(
    {ANTIBIOTIC_RESISTANT, HEMOPHILIAC}
)


def is_confirmed(tool: Tool, tool_text: str) -> bool:
    """True if `tool_text` shows that `tool` worked (not a skill fail)."""
    text = " ".join(tool_text.split())
    if SKILL_FAIL_MARKER in text:
        return False
    wanted = CONFIRMATIONS.get(tool)
    return wanted is not None and text.startswith(wanted)


@dataclass
class Memory:
    knowledge: Knowledge
    diagnosis: Malady | None = None
    incisions_needed: int | None = None  # with Tough Skin; None until diagnosed
    needs_fix: bool | None = None  # None until diagnosed
    fixed: bool = False
    condition: Condition | None = None  # the condition whose text was shown
    assumed_conditions: frozenset[str] = frozenset()  # ids assumed while hidden
    sleep_left: int = 0
    lab_kit_done: bool = False
    antibiotics_dosed: bool = False
    fever_negative: bool = False
    prev_temperature: float | None = None  # temperature on the latest screen seen
    # Change in temperature from the screen before the latest one to the latest
    # one; None on the first update. `prev_temperature` and `prev_state` already
    # hold the latest screen once `update()` returns, so use this to see "the
    # temperature rose since last turn".
    temperature_delta: float | None = None
    prev_state: ScreenState | None = None  # the latest screen seen
    turn: int = 0  # number of `update()` calls so far (1 while deciding turn 1)
    last_decision: Decision | None = None  # set by the engine after deciding

    @classmethod
    def new(cls, knowledge: Knowledge) -> Memory:
        return cls(knowledge)

    def has_condition(self, condition_id: str) -> bool:
        """True if the patient has this condition, known or assumed."""
        known = self.condition is not None and self.condition.id == condition_id
        return known or condition_id in self.assumed_conditions

    @property
    def temperature_rising(self) -> bool:
        """True if the temperature rose since the previous screen."""
        return self.temperature_delta is not None and self.temperature_delta > 0

    def update(self, state: ScreenState, config: Config) -> None:
        """Fold in the newest screen state. The only method that mutates memory."""
        confirmed = self._confirmed_tool(state)
        self._update_condition(state)
        self._update_diagnosis(state)
        self._update_assumptions()
        self._update_incisions_needed()
        self._update_tool_effects(confirmed, state)
        self._update_sleep(confirmed, state, config)
        if self.prev_temperature is None:
            self.temperature_delta = None
        else:
            self.temperature_delta = round(state.temperature - self.prev_temperature, 2)
        self._update_fever(state)
        self.prev_temperature = state.temperature
        self.prev_state = state
        self.turn += 1

    def _confirmed_tool(self, state: ScreenState) -> Tool | None:
        """The last decision's tool if the screen confirms it worked, else None."""
        if self.last_decision is None:
            return None
        tool = self.last_decision.tool
        return tool if is_confirmed(tool, state.last_tool_text) else None

    def _update_condition(self, state: ScreenState) -> None:
        if self.condition is not None or state.special_condition_text is None:
            return
        self.condition = self.knowledge.condition_for_text(state.special_condition_text)

    def _update_diagnosis(self, state: ScreenState) -> None:
        # Locked the first time a scan or fix text names a malady. Post-fix texts
        # are not unique, so they never identify one (see `_update_tool_effects`).
        if self.diagnosis is None and state.scan_text is not None:
            self.diagnosis = self.knowledge.malady_for_scan(state.scan_text)
            if self.diagnosis is not None:
                self.needs_fix = self.diagnosis.needs_fix

    def _update_assumptions(self) -> None:
        starts_diagnosed = (
            self.diagnosis is not None and self.diagnosis.starts_diagnosed
        )
        if starts_diagnosed and self.condition is None:
            self.assumed_conditions = ASSUMED_WHEN_STARTS_DIAGNOSED
        else:
            self.assumed_conditions = frozenset()

    def _update_incisions_needed(self) -> None:
        # Worked out from the diagnosis and the condition every time, so Tough Skin
        # adds its extra incision once, whether it was seen before or after the scan.
        if self.diagnosis is None:
            return
        extra = TOUGH_SKIN_EXTRA_INCISIONS if self.has_condition(TOUGH_SKIN) else 0
        self.incisions_needed = self.diagnosis.incisions_needed + extra

    def _update_tool_effects(self, confirmed: Tool | None, state: ScreenState) -> None:
        if confirmed is Tool.LAB_KIT:
            self.lab_kit_done = True
        elif confirmed is Tool.ANTIBIOTICS:
            self.antibiotics_dosed = True
        elif confirmed is Tool.FIX_IT:
            self.fixed = True
        if (
            self.diagnosis is not None
            and self.diagnosis.post_fix_text is not None
            and state.scan_text is not None
            and normalize_text(state.scan_text)
            == normalize_text(self.diagnosis.post_fix_text)
        ):
            self.fixed = True

    def _update_sleep(
        self, confirmed: Tool | None, state: ScreenState, config: Config
    ) -> None:
        if confirmed is Tool.ANESTHETIC:
            self.sleep_left = (
                config.profile.hyperactive_sleep
                if self.has_condition(HYPERACTIVE)
                else ANESTHETIC_SLEEP
            )
        # Sleep does not fall on a turn the heart is stopped (SurgE only counts it
        # down while the heart beats). A dose on that turn stays at its full value.
        if state.status is Status.HEART_STOPPED:
            return
        self.sleep_left = max(self.sleep_left - SLEEP_DROP_PER_TURN, 0)
        # Never contradict the screen.
        if state.status is Status.AWAKE:
            self.sleep_left = 0
        elif state.status is Status.COMING_TO:
            self.sleep_left = min(max(self.sleep_left, 1), SLEEP_COMING_TO_MAX)
        else:
            self.sleep_left = max(self.sleep_left, SLEEP_UNCONSCIOUS_MIN)

    def _update_fever(self, state: ScreenState) -> None:
        # A fever word, or a temperature that rose, means the fever is positive:
        # a failed Antibiotics dose adds fever and can lift a negative one above 0.
        if state.fever is not None or self.temperature_rising:
            self.fever_negative = False
            return
        # Negative fever sticks: once a dose has made the fever text vanish and the
        # temperature fall, the temperature keeps falling until 98.6 F.
        if (
            not self.fever_negative
            and self.antibiotics_dosed
            and self.prev_temperature is not None
            and state.temperature < self.prev_temperature
        ):
            self.fever_negative = True
