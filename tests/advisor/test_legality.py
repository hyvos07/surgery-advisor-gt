"""The legality check, row by row, and a property test over random screens."""

from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from advisor import engine
from advisor.config import NORMAL_TEMPERATURE_F, PROFILES, Config
from advisor.engine import decide
from advisor.forecast import Forecast
from advisor.knowledge import Knowledge, load
from advisor.memory import CONFIRMATIONS, SKILL_FAIL_MARKER, Memory
from advisor.rules import RULES, is_legal
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

MakeState = Callable[..., ScreenState]

KNOW = load(Path(__file__).parent / "fixtures")
RULE_IDS = {f"E{n}" for n in range(1, 8)} | {f"P{n}" for n in range(1, 14)} | {"F0"}
MAX_REASON = 100


def memory_for(know: Knowledge, malady: str | None = None, **fields: Any) -> Memory:
    memory = Memory.new(know)
    if malady is not None:
        found = next(m for m in know.maladies if m.name == malady)
        memory.diagnosis = found
        memory.incisions_needed = found.incisions_needed
        memory.needs_fix = found.needs_fix
    for name, value in fields.items():
        setattr(memory, name, value)
    return memory


ALL_TOOLS = [t.value for t in Tool]


# --- One test per legality-table row -----------------------------------------


def test_tool_not_in_usable_tools_is_illegal(
    know: Knowledge, make_state: MakeState
) -> None:
    state = make_state(usable_tools=["sponge"])
    assert is_legal(Tool.SPONGE, state, memory_for(know))
    assert not is_legal(Tool.ANTISEPTIC, state, memory_for(know))
    assert not is_legal(Tool.DEFIBRILLATOR, state, memory_for(know))


def test_scalpel_while_awake_is_illegal(know: Knowledge, make_state: MakeState) -> None:
    memory = memory_for(know, "Heart Attack")
    assert not is_legal(
        Tool.SCALPEL, make_state(status="awake", usable_tools=ALL_TOOLS), memory
    )
    for status in ("coming_to", "unconscious"):
        state = make_state(status=status, usable_tools=ALL_TOOLS)
        assert is_legal(Tool.SCALPEL, state, memory)


def test_scalpel_while_awake_is_illegal_without_a_diagnosis(
    know: Knowledge, make_state: MakeState
) -> None:
    state = make_state(status="awake", usable_tools=ALL_TOOLS)
    assert not is_legal(Tool.SCALPEL, state, memory_for(know))


def test_anesthetic_while_unconscious_is_illegal(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    assert not is_legal(
        Tool.ANESTHETIC,
        make_state(status="unconscious", usable_tools=ALL_TOOLS),
        memory,
    )
    for status in ("awake", "coming_to"):
        state = make_state(status=status, usable_tools=ALL_TOOLS)
        assert is_legal(Tool.ANESTHETIC, state, memory)


def test_scalpel_at_or_past_the_needed_count_is_illegal(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Heart Attack")  # needs 2
    for incisions, legal in ((0, True), (1, True), (2, False), (3, False)):
        state = make_state(
            status="unconscious", incisions=incisions, usable_tools=ALL_TOOLS
        )
        assert is_legal(Tool.SCALPEL, state, memory) is legal, incisions


def test_scalpel_count_includes_tough_skin(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Heart Attack", incisions_needed=3)
    state = make_state(status="unconscious", incisions=2, usable_tools=ALL_TOOLS)
    assert is_legal(Tool.SCALPEL, state, memory)


def test_clamp_with_no_bleeding_shown_is_illegal(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    assert not is_legal(
        Tool.CLAMP, make_state(bleeding=None, usable_tools=ALL_TOOLS), memory
    )
    for bleeding in ("slowly", "losing", "very_quickly"):
        state = make_state(bleeding=bleeding, usable_tools=ALL_TOOLS)
        assert is_legal(Tool.CLAMP, state, memory)


def test_splint_before_diagnosis_is_illegal(
    know: Knowledge, make_state: MakeState
) -> None:
    state = make_state(bones={"broken": 1, "shattered": 0}, usable_tools=ALL_TOOLS)
    assert not is_legal(Tool.SPLINT, state, memory_for(know))
    assert is_legal(Tool.SPLINT, state, memory_for(know, "Broken Leg"))


def test_splint_with_no_broken_bones_is_illegal(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Broken Leg")
    for bones in (None, {"broken": 0, "shattered": 1}):
        state = make_state(bones=bones, usable_tools=ALL_TOOLS)
        assert not is_legal(Tool.SPLINT, state, memory)


def test_pins_before_diagnosis_is_illegal(
    know: Knowledge, make_state: MakeState
) -> None:
    state = make_state(
        incisions=1, bones={"broken": 0, "shattered": 1}, usable_tools=ALL_TOOLS
    )
    assert not is_legal(Tool.PINS, state, memory_for(know))
    assert is_legal(Tool.PINS, state, memory_for(know, "Broken Leg"))


def test_pins_with_no_shattered_bones_are_illegal(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know, "Broken Leg")
    for bones in (None, {"broken": 1, "shattered": 0}):
        state = make_state(incisions=1, bones=bones, usable_tools=ALL_TOOLS)
        assert not is_legal(Tool.PINS, state, memory)


def test_antibiotics_at_normal_temperature_are_illegal(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = memory_for(know)
    at_normal = make_state(temperature=NORMAL_TEMPERATURE_F, usable_tools=ALL_TOOLS)
    assert not is_legal(Tool.ANTIBIOTICS, at_normal, memory)
    above = make_state(temperature=98.7, usable_tools=ALL_TOOLS)
    assert is_legal(Tool.ANTIBIOTICS, above, memory)


def test_other_usable_tools_are_legal(know: Knowledge, make_state: MakeState) -> None:
    state = make_state(status="unconscious", temperature=101.0, usable_tools=ALL_TOOLS)
    memory = memory_for(know, "Heart Attack")
    for tool in (
        Tool.DEFIBRILLATOR,
        Tool.SPONGE,
        Tool.STITCHES,
        Tool.ULTRASOUND,
        Tool.ANTISEPTIC,
        Tool.FIX_IT,
        Tool.LAB_KIT,
        Tool.TRANSFUSION,
    ):
        assert is_legal(tool, state, memory), tool


# --- Property test -----------------------------------------------------------

SKILL_FAIL_TEXT = f"{SKILL_FAIL_MARKER} 5%]: You somehow messed up."
TOOL_TEXTS = [
    "",
    *CONFIRMATIONS.values(),
    SKILL_FAIL_TEXT,
    "You stitched up an incision.",
]
SCAN_TEXTS = [
    None,
    "The patient has not been diagnosed.",
    *(m.scan_text for m in KNOW.maladies),
    *(m.fix_text for m in KNOW.maladies if m.fix_text),
    *(m.post_fix_text for m in KNOW.maladies if m.post_fix_text),
]
CONDITION_TEXTS = [None, *(c.text for c in KNOW.conditions)]

# The temperatures are in tenths and hundredths, as SurgE reports them.
temperatures = st.integers(9860, 11000).map(lambda x: x / 100)


@st.composite
def screen_states(draw: st.DrawFn) -> ScreenState:
    others = draw(st.sets(st.sampled_from([t for t in Tool if t is not Tool.SPONGE])))
    usable = tuple(t for t in Tool if t is Tool.SPONGE or t in others)
    bones = draw(
        st.none()
        | st.builds(Bones, broken=st.integers(0, 4), shattered=st.integers(0, 4))
    )
    return ScreenState(
        skill_level=draw(st.integers(0, 100)),
        modifier=draw(st.none() | st.sampled_from(Modifier)),
        special_condition_text=draw(st.sampled_from(CONDITION_TEXTS)),
        scan_text=draw(st.sampled_from([None, None, *SCAN_TEXTS])),
        pulse=draw(st.sampled_from(Pulse)),
        status=draw(st.sampled_from(Status)),
        temperature=draw(temperatures),
        site=draw(st.sampled_from(Site)),
        visibility=draw(st.sampled_from(Visibility)),
        incisions=draw(st.integers(0, 5)),
        bones=bones,
        bleeding=draw(st.none() | st.sampled_from(Bleeding)),
        fever=draw(st.none() | st.sampled_from(Fever)),
        last_tool_text=draw(st.sampled_from(TOOL_TEXTS)),
        usable_tools=usable,
    )


@st.composite
def memories(draw: st.DrawFn) -> Memory:
    memory = Memory.new(KNOW)
    diagnosis = draw(st.sampled_from([None, None, *KNOW.maladies]))
    if diagnosis is not None:
        memory.diagnosis = diagnosis
        memory.incisions_needed = diagnosis.incisions_needed
        memory.needs_fix = diagnosis.needs_fix
    memory.fixed = draw(st.booleans())
    memory.lab_kit_done = draw(st.booleans())
    memory.antibiotics_dosed = draw(st.booleans())
    memory.fever_negative = draw(st.booleans())
    memory.sleep_left = draw(st.integers(0, 12))
    memory.condition = draw(st.none() | st.sampled_from(KNOW.conditions))
    memory.assumed_conditions = frozenset(
        draw(st.sets(st.sampled_from([c.id for c in KNOW.conditions])))
    )
    memory.prev_temperature = draw(st.none() | temperatures)
    memory.last_decision = draw(
        st.none()
        | st.builds(
            Decision,
            tool=st.sampled_from(Tool),
            rule=st.just("T0"),
            reason=st.just("test"),
        )
    )
    return memory


@st.composite
def configs(draw: st.DrawFn, state: ScreenState) -> Config:
    return Config.for_patient(
        state.skill_level,
        state.modifier.value if state.modifier else None,
        profile=draw(st.sampled_from(sorted(PROFILES))),
        antiseptic_mode=draw(st.sampled_from(["draft", "minimal"])),
    )


@st.composite
def cases(draw: st.DrawFn) -> tuple[ScreenState, Memory, Config]:
    state = draw(screen_states())
    return state, draw(memories()), draw(configs(state))


def assert_legal(decision: Decision, state: ScreenState, memory: Memory) -> None:
    """Assert `decision` breaks no row of the legality table."""
    tool = decision.tool
    assert tool in state.usable_tools
    assert not (tool is Tool.SCALPEL and state.status is Status.AWAKE)
    assert not (tool is Tool.ANESTHETIC and state.status is Status.UNCONSCIOUS)
    if tool is Tool.SCALPEL:
        needed = memory.incisions_needed
        assert needed is None or state.incisions < needed
    if tool is Tool.CLAMP:
        assert state.bleeding is not None
    if tool is Tool.SPLINT:
        assert memory.diagnosis is not None
        assert state.bones is not None and state.bones.broken > 0
    if tool is Tool.PINS:
        assert memory.diagnosis is not None
        assert state.bones is not None and state.bones.shattered > 0
    if tool is Tool.ANTIBIOTICS:
        assert state.temperature > NORMAL_TEMPERATURE_F
    assert decision.rule in RULE_IDS
    assert decision.reason
    assert len(decision.reason) < MAX_REASON


PROPERTY = settings(
    max_examples=2000,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)


@PROPERTY
@given(cases())
def test_decide_never_breaks_the_legality_table(
    case: tuple[ScreenState, Memory, Config],
) -> None:
    state, memory, config = case
    decision = decide(state, memory, config)
    # `decide` updated the memory, so the checks use what it decided with.
    assert_legal(decision, state, memory)
    assert memory.last_decision is decision


@PROPERTY
@given(cases(), st.sampled_from(Tool))
def test_the_legality_check_stops_a_reckless_rule(
    case: tuple[ScreenState, Memory, Config], reckless: Tool
) -> None:
    # The real rules guard themselves, so on their own they rarely reach the check.
    # Put a rule first that proposes any tool at all: the check must still hold.
    state, memory, config = case

    def reckless_rule(
        s: ScreenState, m: Memory, f: Forecast, c: Config
    ) -> Decision | None:
        return Decision(reckless, "E1", "reckless")

    with patch.object(engine, "RULES", (reckless_rule, *RULES)):
        decision = decide(state, memory, config)
    assert_legal(decision, state, memory)


def reckless_decision(
    reckless: Tool, state: ScreenState, memory: Memory, config: Config
) -> Decision:
    def reckless_rule(
        s: ScreenState, m: Memory, f: Forecast, c: Config
    ) -> Decision | None:
        return Decision(reckless, "E1", "reckless")

    with patch.object(engine, "RULES", (reckless_rule, *RULES)):
        return decide(state, memory, config)


def test_a_reckless_rule_is_stopped_on_every_row_of_the_table(
    know: Knowledge, make_state: MakeState
) -> None:
    config = Config.for_patient(50, None)
    # Awake, undiagnosed, nothing bleeding, normal temperature, bones on the screen.
    awake = make_state(
        status="awake",
        incisions=0,
        bones={"broken": 1, "shattered": 1},
        bleeding=None,
        temperature=NORMAL_TEMPERATURE_F,
        usable_tools=ALL_TOOLS,
    )
    for tool in (
        Tool.SCALPEL,
        Tool.CLAMP,
        Tool.SPLINT,
        Tool.PINS,
        Tool.ANTIBIOTICS,
    ):
        decision = reckless_decision(tool, awake, memory_for(know), config)
        assert decision.tool is not tool, tool
        assert_legal(decision, awake, memory_for(know))
    # Asleep, diagnosed, incisions at the needed count, no bones on the screen.
    asleep = make_state(
        status="unconscious",
        incisions=2,
        bones=None,
        usable_tools=ALL_TOOLS,
    )
    for tool in (Tool.ANESTHETIC, Tool.SCALPEL, Tool.SPLINT, Tool.PINS):
        memory = memory_for(know, "Heart Attack")
        decision = reckless_decision(tool, asleep, memory, config)
        assert decision.tool is not tool, tool
        assert_legal(decision, asleep, memory)
    # A tool the tray has greyed out.
    greyed = make_state(usable_tools=["sponge"])
    decision = reckless_decision(Tool.TRANSFUSION, greyed, memory_for(know), config)
    assert decision.tool is not Tool.TRANSFUSION
