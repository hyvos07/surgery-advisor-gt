"""decide(state, memory) -> Decision, plus the legality check."""

from __future__ import annotations

import json
import logging

from advisor.config import Config
from advisor.forecast import Forecast
from advisor.memory import Memory
from advisor.rules import RULES, fallback, is_legal
from advisor.state import Decision, ScreenState

# One JSON line per decision. Library code configures no handlers; the caller does.
decision_log = logging.getLogger("advisor.decisions")


def decide(state: ScreenState, memory: Memory, config: Config) -> Decision:
    """Update memory, then return the first legal rule's decision (else the fallback).

    Sets `memory.last_decision` so the next call can tell whether the tool worked.
    """
    memory.update(state, config)
    forecast = Forecast.from_state(state, memory, config)
    decision = next(
        (
            d
            for rule in RULES
            if (d := rule(state, memory, forecast, config)) is not None
            and is_legal(d.tool, state, memory)
        ),
        None,
    )
    if decision is None:
        decision = fallback(state, config)
    memory.last_decision = decision
    if decision_log.isEnabledFor(logging.INFO):
        decision_log.info(
            json.dumps(
                {
                    "turn": memory.turn,
                    "rule": decision.rule,
                    "tool": decision.tool.value,
                    "reason": decision.reason,
                    "state": state.to_dict(),
                }
            )
        )
    return decision
