"""decide(): memory, forecast, the first legal rule, the fallback and the log."""

import json
import logging
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest

from advisor import engine
from advisor.config import Config
from advisor.knowledge import Knowledge
from advisor.memory import CONFIRMATIONS, Memory
from advisor.state import ScreenState, Tool

MakeState = Callable[..., ScreenState]

CONFIG = Config.for_patient(50, None)
HEART_ATTACK = "Patient had a heart attack."


def test_decide_returns_the_first_rule_that_fires(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = Memory.new(know)
    state = make_state(status="heart_stopped", usable_tools=["sponge", "defibrillator"])
    decision = engine.decide(state, memory, CONFIG)
    assert (decision.rule, decision.tool) == ("E1", Tool.DEFIBRILLATOR)


def test_decide_updates_memory_before_the_rules_run(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = Memory.new(know)
    state = make_state(
        scan_text=HEART_ATTACK, usable_tools=["sponge", "ultrasound", "antiseptic"]
    )
    decision = engine.decide(state, memory, CONFIG)
    assert memory.diagnosis is not None
    assert memory.turn == 1
    # P1 would have chosen Ultrasound had the memory not been updated first.
    assert decision.rule != "P1"


def test_decide_sets_last_decision(know: Knowledge, make_state: MakeState) -> None:
    memory = Memory.new(know)
    assert memory.last_decision is None
    decision = engine.decide(make_state(), memory, CONFIG)
    assert memory.last_decision is decision


def test_decide_uses_last_decision_to_confirm_the_next_turns_text(
    know: Knowledge, make_state: MakeState
) -> None:
    memory = Memory.new(know)
    tools = ["sponge", "ultrasound", "lab_kit", "antibiotics", "antiseptic"]
    state = make_state(
        temperature=104.0, fever="climbing", usable_tools=tools, scan_text=HEART_ATTACK
    )
    first = engine.decide(state, memory, CONFIG)
    assert first.tool is Tool.LAB_KIT
    state = make_state(
        temperature=105.0,
        fever="climbing",
        usable_tools=tools,
        scan_text=HEART_ATTACK,
        last_tool_text=CONFIRMATIONS[Tool.LAB_KIT],
    )
    second = engine.decide(state, memory, CONFIG)
    assert memory.lab_kit_done
    assert second.tool is Tool.ANTIBIOTICS


def test_decide_skips_a_rule_whose_tool_is_not_legal(
    know: Knowledge, make_state: MakeState
) -> None:
    # E6 wants the Lab Kit but the tray has it greyed out; the next rules take over.
    memory = Memory.new(know)
    state = make_state(
        fever="climbing_fast",
        temperature=104.0,
        usable_tools=["sponge", "ultrasound"],
    )
    decision = engine.decide(state, memory, CONFIG)
    assert (decision.rule, decision.tool) == ("P1", Tool.ULTRASOUND)


def test_decide_falls_back_when_no_rule_gives_a_legal_tool(
    know: Knowledge, make_state: MakeState
) -> None:
    # Calm, diagnosed, nothing to do; P13 wants the Antiseptic but only the Sponge
    # is usable.
    memory = Memory.new(know)
    state = make_state(scan_text=HEART_ATTACK, usable_tools=["sponge"])
    decision = engine.decide(state, memory, CONFIG)
    assert (decision.rule, decision.tool) == ("F0", Tool.SPONGE)


def test_decide_falls_back_when_no_rule_fires(
    know: Knowledge, make_state: MakeState, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(engine, "RULES", ())
    memory = Memory.new(know)
    state = make_state(usable_tools=["sponge", "antiseptic"])
    decision = engine.decide(state, memory, CONFIG)
    assert (decision.rule, decision.tool) == ("F0", Tool.ANTISEPTIC)
    assert memory.last_decision is decision


def test_decide_uses_the_sponge_in_minimal_mode_when_waiting(
    know: Knowledge, make_state: MakeState
) -> None:
    config = Config.for_patient(50, None, antiseptic_mode="minimal")
    state = make_state(scan_text=HEART_ATTACK, usable_tools=["sponge", "antiseptic"])
    decision = engine.decide(state, Memory.new(know), config)
    assert (decision.rule, decision.tool) == ("P13", Tool.SPONGE)


def test_decide_logs_one_json_line_per_decision(
    know: Knowledge, make_state: MakeState, caplog: pytest.LogCaptureFixture
) -> None:
    memory = Memory.new(know)
    state = make_state(scan_text=HEART_ATTACK, usable_tools=["sponge", "antiseptic"])
    with caplog.at_level(logging.INFO, logger="advisor.decisions"):
        decision = engine.decide(state, memory, CONFIG)
        engine.decide(state, memory, CONFIG)
    records = [r for r in caplog.records if r.name == "advisor.decisions"]
    assert len(records) == 2
    first: dict[str, Any] = json.loads(records[0].getMessage())
    assert first == {
        "turn": 1,
        "rule": decision.rule,
        "tool": decision.tool.value,
        "reason": decision.reason,
        "state": state.to_dict(),
    }
    assert json.loads(records[1].getMessage())["turn"] == 2
    assert all(r.levelno == logging.INFO for r in records)


def test_decide_logs_nothing_when_logging_is_off(
    know: Knowledge, make_state: MakeState, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="advisor.decisions"):
        engine.decide(make_state(), Memory.new(know), CONFIG)
    assert not [r for r in caplog.records if r.name == "advisor.decisions"]


def test_decide_is_deterministic(know: Knowledge, make_state: MakeState) -> None:
    script = [
        make_state(scan_text=None, usable_tools=["sponge", "ultrasound"]),
        make_state(
            scan_text=HEART_ATTACK,
            temperature=103.0,
            fever="climbing",
            usable_tools=["sponge", "lab_kit"],
        ),
        make_state(
            scan_text=HEART_ATTACK,
            temperature=104.0,
            fever="climbing",
            last_tool_text=CONFIRMATIONS[Tool.LAB_KIT],
            usable_tools=["sponge", "antibiotics"],
        ),
    ]

    def play() -> list[dict[str, str]]:
        memory = Memory.new(know)
        return [engine.decide(s, memory, CONFIG).to_dict() for s in script]

    assert play() == play()


def test_decide_closes_the_incisions_before_fix_it(
    know: Knowledge, make_state: MakeState
) -> None:
    # D15: Heart Attack at its 2 needed incisions, Fix It usable, patient asleep.
    memory = Memory.new(know)
    tools = ["sponge", "antiseptic", "stitches", "scalpel", "fix_it"]
    open_state = make_state(
        scan_text=HEART_ATTACK,
        status="unconscious",
        incisions=2,
        bones={"broken": 0, "shattered": 0},
        usable_tools=tools,
    )
    decision = engine.decide(open_state, memory, CONFIG)
    assert (decision.rule, decision.tool) == ("P6", Tool.STITCHES)
    assert memory.fix_unlocked
    # One closed: keep closing. All closed: now Fix It, and no cutting again.
    one = engine.decide(replace(open_state, incisions=1), memory, CONFIG)
    assert (one.rule, one.tool) == ("P6", Tool.STITCHES)
    closed = engine.decide(replace(open_state, incisions=0), memory, CONFIG)
    assert (closed.rule, closed.tool) == ("P3", Tool.FIX_IT)
