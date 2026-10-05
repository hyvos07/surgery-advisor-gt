"""Forecast: the worst case next turn, from the screen words."""

import dataclasses
import itertools
from collections.abc import Callable
from typing import Any

import pytest

from advisor.config import Config
from advisor.forecast import Forecast
from advisor.knowledge import Knowledge
from advisor.memory import Memory
from advisor.state import Pulse, ScreenState

MakeState = Callable[..., ScreenState]

HEMOPHILIAC_TEXT = "The patient is a hemophiliac."
HEART_ATTACK = "Patient had a heart attack."

# Skill 100 has a 5% fail rate (one pulse turn ahead); skill 0 has 30% (two turns).
ONE_TURN = Config.for_patient(100, None)
TWO_TURNS = Config.for_patient(0, None)

# The lowest hidden pulse behind each word, and the highest hidden bleeding.
PULSE_FLOORS = {"strong": 31, "steady": 21, "weak": 11, "extremely_weak": 1}
BLEED_BOUNDS = {None: 0, "slowly": 1, "losing": 3, "very_quickly": 6}


def pulse_word(value: int) -> Pulse:
    if value >= 31:
        return Pulse.STRONG
    if value >= 21:
        return Pulse.STEADY
    if value >= 11:
        return Pulse.WEAK
    return Pulse.EXTREMELY_WEAK


def forecast(
    know: Knowledge,
    state: ScreenState,
    config: Config = ONE_TURN,
    memory: Memory | None = None,
) -> Forecast:
    memory = memory or Memory.new(know)
    memory.update(state, config)
    return Forecast.from_state(state, memory, config)


# --- Pulse -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pulse", "bleeding", "incisions"),
    list(itertools.product(PULSE_FLOORS, BLEED_BOUNDS, (0, 1))),
)
def test_pulse_floor_for_one_turn(
    know: Knowledge,
    make_state: MakeState,
    pulse: str,
    bleeding: str | None,
    incisions: int,
) -> None:
    state = make_state(pulse=pulse, bleeding=bleeding, incisions=incisions)
    expected = PULSE_FLOORS[pulse] - BLEED_BOUNDS[bleeding] - (1 if incisions else 0)
    f = forecast(know, state)
    assert f.pulse_floor == expected
    assert f.pulse_word_next is pulse_word(expected)


@pytest.mark.parametrize(
    ("pulse", "bleeding", "incisions"),
    list(itertools.product(PULSE_FLOORS, BLEED_BOUNDS, (0, 1))),
)
def test_pulse_floor_for_two_turns(
    know: Knowledge,
    make_state: MakeState,
    pulse: str,
    bleeding: str | None,
    incisions: int,
) -> None:
    state = make_state(pulse=pulse, bleeding=bleeding, incisions=incisions)
    loss = BLEED_BOUNDS[bleeding] + (1 if incisions else 0)
    expected = PULSE_FLOORS[pulse] - 2 * loss
    f = forecast(know, state, TWO_TURNS)
    assert f.pulse_floor == expected
    assert f.pulse_word_next is pulse_word(expected)


def test_two_turn_margin_looks_further_down(
    know: Knowledge, make_state: MakeState
) -> None:
    # Steady, "very_quickly" (cap 6) and an incision: 21 - 7 = 14 after one turn
    # (weak), 21 - 14 = 7 after two (extremely weak).
    state = make_state(pulse="steady", bleeding="very_quickly", incisions=1)
    assert forecast(know, state, ONE_TURN).pulse_word_next is Pulse.WEAK
    assert forecast(know, state, TWO_TURNS).pulse_word_next is Pulse.EXTREMELY_WEAK


def test_no_pulse_loss_means_the_turn_count_does_not_matter(
    know: Knowledge, make_state: MakeState
) -> None:
    state = make_state(pulse="weak")
    assert forecast(know, state, ONE_TURN).pulse_floor == 11
    assert forecast(know, state, TWO_TURNS).pulse_floor == 11


def test_open_incisions_cost_one_pulse_per_turn_not_one_per_incision(
    know: Knowledge, make_state: MakeState
) -> None:
    one = forecast(know, make_state(incisions=1)).pulse_floor
    three = forecast(know, make_state(incisions=3)).pulse_floor
    assert one == three == 30


def test_hemophiliac_doubles_the_bleeding_bound(
    know: Knowledge, make_state: MakeState
) -> None:
    state = make_state(
        special_condition_text=HEMOPHILIAC_TEXT,
        pulse="strong",
        bleeding="losing",
        incisions=1,
    )
    f = forecast(know, state)
    assert f.pulse_floor == 31 - 2 * 3 - 1
    f2 = forecast(know, state, TWO_TURNS)
    assert f2.pulse_floor == 31 - 2 * (2 * 3 + 1)
    plain = forecast(know, dataclasses.replace(state, special_condition_text=None))
    assert plain.pulse_floor == 31 - 3 - 1


def test_assumed_hemophiliac_doubles_the_bleeding_bound(
    know: Knowledge, make_state: MakeState
) -> None:
    nose_job = dataclasses.replace(
        know.maladies[0],
        name="Nose Job",
        scan_text="Patient wants a nose job.",
        starts_diagnosed=True,
    )
    assumed = Knowledge(maladies=(*know.maladies, nose_job), conditions=know.conditions)
    state = make_state(
        scan_text="Patient wants a nose job.", pulse="strong", bleeding="slowly"
    )
    f = forecast(assumed, state)
    assert f.pulse_floor == 31 - 2 * 1


def test_very_quickly_uses_the_configured_cap(
    know: Knowledge, make_state: MakeState
) -> None:
    config = dataclasses.replace(ONE_TURN, very_quickly_bleed_cap=8)
    f = forecast(know, make_state(pulse="strong", bleeding="very_quickly"), config)
    assert f.pulse_floor == 31 - 8


# --- Temperature -------------------------------------------------------------


@pytest.mark.parametrize(
    ("fever", "rate"),
    [(None, 0.0), ("slowly_rising", 0.5), ("climbing", 2.0), ("climbing_fast", 4.0)],
)
def test_temperature_worst_case_per_fever_word(
    know: Knowledge, make_state: MakeState, fever: str | None, rate: float
) -> None:
    f = forecast(know, make_state(temperature=102.0, fever=fever))
    assert f.fever_rate == rate
    assert f.temperature_next == pytest.approx(102.0 + rate)
    assert f.temperature_in(0) == 102.0
    assert f.temperature_in(1) == f.temperature_next
    assert f.temperature_in(2) == pytest.approx(102.0 + 2 * rate)
    assert f.temperature_in(5) == pytest.approx(102.0 + 5 * rate)


def test_temperature_uses_the_observed_rise_when_no_fever_word_is_shown(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = Memory.new(know)
    memory.update(make_state(temperature=99.0), ONE_TURN)
    state = make_state(temperature=99.75, fever=None)
    memory.update(state, ONE_TURN)
    f = Forecast.from_state(state, memory, ONE_TURN)
    assert f.fever_rate == 0.75
    assert f.temperature_next == 100.5
    assert f.temperature_in(2) == 101.25


def test_fever_word_wins_over_the_observed_rise(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = Memory.new(know)
    memory.update(make_state(temperature=103.0), ONE_TURN)
    state = make_state(temperature=103.2, fever="climbing")
    memory.update(state, ONE_TURN)
    assert Forecast.from_state(state, memory, ONE_TURN).fever_rate == 2.0


@pytest.mark.parametrize("now", [100.0, 99.0])
def test_temperature_does_not_rise_when_it_is_flat_or_falling(
    know: Knowledge, make_state: MakeState, now: float
) -> None:
    memory = Memory.new(know)
    memory.update(make_state(temperature=100.0), ONE_TURN)
    state = make_state(temperature=now)
    memory.update(state, ONE_TURN)
    f = Forecast.from_state(state, memory, ONE_TURN)
    assert f.fever_rate == 0.0
    assert f.temperature_next == now
    assert f.temperature_in(3) == now


def test_temperature_on_the_first_screen_has_no_observed_rise(
    know: Knowledge, make_state: MakeState
) -> None:
    f = forecast(know, make_state(temperature=104.0))
    assert f.fever_rate == 0.0
    assert f.temperature_next == 104.0


def test_temperature_projection_is_rounded_like_surge(
    know: Knowledge, make_state: MakeState
) -> None:
    f = forecast(know, make_state(temperature=100.1, fever="slowly_rising"))
    assert f.temperature_next == 100.6
    assert f.temperature_in(3) == 101.6


def test_temperature_in_rejects_negative_turns(
    know: Knowledge, make_state: MakeState
) -> None:
    with pytest.raises(ValueError, match="negative"):
        forecast(know, make_state()).temperature_in(-1)


# --- Sleep -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sleep", "expected"), [(0, 0), (1, 0), (2, 1), (9, 8), (10, 9)]
)
def test_sleep_next(
    know: Knowledge, make_state: MakeState, sleep: int, expected: int
) -> None:
    memory = Memory.new(know)
    memory.sleep_left = sleep
    f = Forecast.from_state(make_state(), memory, ONE_TURN)
    assert f.sleep_next == expected


# --- Going blind -------------------------------------------------------------


@pytest.mark.parametrize(
    ("visibility", "bleeding", "incisions", "blind"),
    [
        # clear counts as dirt 3
        ("clear", None, 0, False),
        ("clear", "very_quickly", 0, False),  # 3 + 6 = 9
        ("clear", "very_quickly", 1, True),  # 3 + 6 + 1 = 10
        ("clear", "losing", 3, False),  # 3 + 3 + 3 = 9
        ("clear", "losing", 4, True),  # 10
        ("clear", None, 7, True),  # 3 + 7 = 10
        ("clear", None, 6, False),
        # hard_to_see counts as dirt 9
        ("hard_to_see", None, 0, False),
        ("hard_to_see", "slowly", 0, True),  # 9 + 1 = 10
        ("hard_to_see", None, 1, True),  # 9 + 1 = 10
        ("hard_to_see", None, 2, True),
        # already blind
        ("cant_see", None, 0, True),
    ],
)
def test_may_go_blind_edges(
    know: Knowledge,
    make_state: MakeState,
    visibility: str,
    bleeding: str | None,
    incisions: int,
    blind: bool,
) -> None:
    state = make_state(visibility=visibility, bleeding=bleeding, incisions=incisions)
    assert forecast(know, state).may_go_blind is blind


def test_hemophiliac_doubling_applies_to_may_go_blind(
    know: Knowledge, make_state: MakeState
) -> None:
    state = make_state(visibility="clear", bleeding="losing", incisions=1)
    assert not forecast(know, state).may_go_blind  # 3 + 3 + 1 = 7
    with_condition = dataclasses.replace(state, special_condition_text=HEMOPHILIAC_TEXT)
    assert forecast(know, with_condition).may_go_blind  # 3 + 6 + 1 = 10


# --- Shape -------------------------------------------------------------------


def test_forecast_is_frozen(know: Knowledge, make_state: MakeState) -> None:
    f = forecast(know, make_state())
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.pulse_floor = 0  # type: ignore[misc]


def test_forecast_is_pure(know: Knowledge, make_state: MakeState) -> None:
    state = make_state(
        scan_text=HEART_ATTACK, pulse="steady", bleeding="losing", incisions=1
    )
    memory = Memory.new(know)
    memory.update(state, ONE_TURN)
    before = dataclasses.asdict(memory)
    first = Forecast.from_state(state, memory, ONE_TURN)
    second = Forecast.from_state(state, memory, ONE_TURN)
    assert first == second
    assert dataclasses.asdict(memory) == before


def test_forecast_fields_match_the_documented_names(
    know: Knowledge, make_state: MakeState
) -> None:
    f = forecast(know, make_state())
    names: dict[str, Any] = {
        "pulse_floor": int,
        "pulse_word_next": Pulse,
        "temperature_next": float,
        "sleep_next": int,
        "may_go_blind": bool,
    }
    for name, kind in names.items():
        assert isinstance(getattr(f, name), kind), name
