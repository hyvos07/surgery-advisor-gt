"""One-step lookahead using the game's formulas.

The forecast is pessimistic on purpose: it uses the upper bound of each hidden
range behind the screen words (docs/decision-engine.md, "Forecast"). It is pure
and frozen: the same state, memory and config always give the same forecast.
"""

from __future__ import annotations

from dataclasses import dataclass

from advisor.config import (
    DIRT_CANT_SEE,
    HEMOPHILIAC_BLEED_FACTOR,
    INCISION_PULSE_LOSS,
    PULSE_WORD_FLOOR,
    SLEEP_DROP_PER_TURN,
    Config,
    pulse_word_for,
)
from advisor.knowledge import HEMOPHILIAC
from advisor.memory import Memory
from advisor.state import Pulse, ScreenState

TEMPERATURE_DECIMALS = 2  # SurgE rounds the temperature to hundredths


def bleeding_bound(state: ScreenState, memory: Memory, config: Config) -> int:
    """Worst-case bleeding per turn behind the bleeding word.

    A hemophiliac (known or assumed) doubles every bleed, so the bound doubles.
    """
    bound = config.bleeding_upper(state.bleeding)
    if memory.has_condition(HEMOPHILIAC):
        bound *= HEMOPHILIAC_BLEED_FACTOR
    return bound


def fever_rate(state: ScreenState, memory: Memory, config: Config) -> float:
    """Worst-case temperature rise per turn (deg F).

    The fever word's upper rate when a word is shown. With no word, the rise seen
    since the previous screen (a fever that is real but hidden below 100 F), or 0.
    """
    if state.fever is not None:
        return config.fever_upper(state.fever)
    if memory.temperature_delta is not None and memory.temperature_delta > 0:
        return memory.temperature_delta
    return 0.0


def _project(temperature: float, rate: float, turns: int) -> float:
    return round(temperature + rate * turns, TEMPERATURE_DECIMALS)


@dataclass(frozen=True)
class Forecast:
    pulse_floor: int  # lowest pulse after `margins.pulse_turns_ahead` turns
    pulse_word_next: Pulse  # the pulse word for `pulse_floor`
    temperature: float  # current temperature
    fever_rate: float  # worst-case rise per turn
    temperature_next: float  # worst-case temperature after 1 turn
    sleep_next: int
    may_go_blind: bool  # dirt could reach `cant_see` next turn

    def temperature_in(self, turns: int) -> float:
        """Worst-case temperature `turns` turns ahead (0 or more)."""
        if turns < 0:
            raise ValueError(f"turns must not be negative, got {turns}")
        return _project(self.temperature, self.fever_rate, turns)

    @classmethod
    def from_state(cls, state: ScreenState, memory: Memory, config: Config) -> Forecast:
        bleed = bleeding_bound(state, memory, config)
        loss_per_turn = bleed + (INCISION_PULSE_LOSS if state.incision_open else 0)
        pulse_floor = (
            PULSE_WORD_FLOOR[state.pulse]
            - loss_per_turn * config.margins.pulse_turns_ahead
        )
        rate = fever_rate(state, memory, config)
        dirt = config.dirt_upper(state.visibility) + bleed + state.incisions
        return cls(
            pulse_floor=pulse_floor,
            pulse_word_next=pulse_word_for(pulse_floor),
            temperature=state.temperature,
            fever_rate=rate,
            temperature_next=_project(state.temperature, rate, 1),
            sleep_next=max(memory.sleep_left - SLEEP_DROP_PER_TURN, 0),
            may_go_blind=dirt >= DIRT_CANT_SEE,
        )
