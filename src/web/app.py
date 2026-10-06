"""FastAPI server for the step-by-step viewer."""

import secrets
import threading
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from advisor import knowledge
from advisor.config import Config
from advisor.engine import decide
from advisor.memory import CONFIRMATIONS, SKILL_FAIL_MARKER
from advisor.state import (
    Bleeding,
    Fever,
    Modifier,
    Pulse,
    ScreenState,
    Site,
    Status,
    Tool,
    Visibility,
)
from harness.baseline import parse_tips
from harness.observe import observe
from harness.runner import (
    POLICY_NAMES,
    AdvisorPolicy,
    Surgery,
    policy_by_name,
    resolve_settings,
)
from harness.surge import (
    CONDITION_NAMES,
    MALADY_NAMES,
    MODIFIER_NAMES,
    TOOL_IDS,
    train_e_tips,
)

STATIC = Path(__file__).parent / "static"
MAX_SURGERIES = 100  # the oldest is dropped beyond this; surgeries live in memory only
POLICIES = list(POLICY_NAMES)

# Fields whose change is worth showing in the turn log.
_WATCHED = (
    "pulse",
    "status",
    "temperature",
    "site",
    "visibility",
    "incisions",
    "bones",
    "bleeding",
    "fever",
)

app = FastAPI(title="Surgery Advisor viewer")


class StartRequest(BaseModel):
    """Blank fields are chosen at random (a blank modifier means none)."""

    malady: str | None = None
    condition: str | None = None
    skill: int | None = None
    modifier: str | None = None
    policy: str = "advisor"
    seed: int | None = None


@dataclass
class Entry:
    surgery: Surgery
    policy: str
    log: list[dict[str, Any]] = field(default_factory=list)
    final_state: dict[str, Any] | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_surgeries: OrderedDict[str, Entry] = OrderedDict()
_registry_lock = threading.Lock()


def _changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[Any]]:
    return {k: [before[k], after[k]] for k in _WATCHED if before[k] != after[k]}


def _view(surgery_id: str, entry: Entry) -> dict[str, Any]:
    surgery = entry.surgery
    ended = surgery.ended
    tips = []
    if not ended:
        tips = [
            {"heading": heading, "description": description}
            for heading, description in parse_tips(train_e_tips(surgery.patient))
        ]
    result = surgery.result() if ended else None
    return {
        "id": surgery_id,
        "settings": asdict(surgery.settings),
        "policy": entry.policy,
        "turn": surgery.turn,
        "state": entry.final_state if ended else surgery.state,
        "decision": surgery.decision,
        "ended": ended,
        "outcome": surgery.outcome,
        "end": None
        if result is None
        else {
            "text": result.end_text or "Turn cap reached",
            "outcome": result.outcome,
            "turns": result.turns,
            "tools_used": dict(Counter(surgery.applied)),
            "skill_fails": result.skill_fails,
            "illegal_moves": result.illegal_moves,
        },
        "log": entry.log,
        "train_e": tips,
    }


def _entry(surgery_id: str) -> Entry:
    with _registry_lock:
        entry = _surgeries.get(surgery_id)
    if entry is None:
        raise HTTPException(404, "no such surgery (the server forgets them on restart)")
    return entry


@app.get("/")
def page() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/options")
def options() -> dict[str, list[str]]:
    return {
        "maladies": list(MALADY_NAMES),
        "conditions": list(CONDITION_NAMES),
        "modifiers": list(MODIFIER_NAMES),
        "policies": POLICIES,
        "tools": list(TOOL_IDS),
    }


@app.post("/surgeries")
def start(request: StartRequest) -> dict[str, Any]:
    try:
        settings = resolve_settings(
            request.malady or None,
            request.condition or None,
            request.skill,
            request.modifier or None,
            request.seed,
        )
        surgery = Surgery(settings, policy_by_name(request.policy), request.policy)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    surgery_id = secrets.token_urlsafe(6)
    entry = Entry(surgery, request.policy)
    with _registry_lock:
        _surgeries[surgery_id] = entry
        while len(_surgeries) > MAX_SURGERIES:
            _surgeries.popitem(last=False)
    return _view(surgery_id, entry)


@app.get("/surgeries/{surgery_id}")
def get_surgery(surgery_id: str) -> dict[str, Any]:
    entry = _entry(surgery_id)
    with entry.lock:
        return _view(surgery_id, entry)


@app.post("/surgeries/{surgery_id}/next")
def next_turn(surgery_id: str) -> dict[str, Any]:
    entry = _entry(surgery_id)
    with entry.lock:
        surgery = entry.surgery
        if surgery.ended:
            raise HTTPException(409, "the surgery has ended; press Restart")
        before = surgery.state
        record = surgery.step()
        after = observe(surgery.patient)
        if surgery.ended:
            entry.final_state = after
        entry.log.append(
            {
                "turn": record["turn"],
                "tool": record["applied_tool"],
                "legal": record["legal"],
                "skill_fail": record["skill_fail"],
                "rule": record["decision"]["rule"],
                "reason": record["decision"]["reason"],
                "text": record["tool_text"],
                "changes": _changes(before, after),
            }
        )
        return _view(surgery_id, entry)


@app.post("/surgeries/{surgery_id}/restart")
def restart(surgery_id: str) -> dict[str, Any]:
    entry = _entry(surgery_id)
    with entry.lock:
        old = entry.surgery
        # A fresh policy: the advisor's memory must start empty again.
        entry.surgery = Surgery(
            old.settings, policy_by_name(entry.policy), entry.policy
        )
        entry.log = []
        entry.final_state = None
        return _view(surgery_id, entry)


# --- Manual mode (D21): the player types what their own game screen shows. ---
# Nothing here talks to the game; the page only sends the screen-state fields.

MAX_MANUAL_SESSIONS = 100  # the oldest is dropped beyond this
RESULT_WORKED = "worked"
RESULT_SKILL_FAIL = "skill_fail"
RESULTS = (RESULT_WORKED, RESULT_SKILL_FAIL)
# Used as `last_tool_text` when the player says a tool worked and it has no
# confirmation text in `memory.CONFIRMATIONS` (memory then changes nothing, as in
# the game).
NEUTRAL_WORKED_TEXT = "The tool worked (reported by the player)."
SKILL_FAIL_TEXT = (
    f"{SKILL_FAIL_MARKER}]: the tool did nothing (reported by the player)."
)


class ManualAdviseRequest(BaseModel):
    """`state` is a PRD section 8 screen state; the other two describe the last turn."""

    state: Any
    used_tool: str | None = None
    result: str | None = None


@dataclass
class ManualEntry:
    policy: AdvisorPolicy = field(default_factory=AdvisorPolicy)
    config_key: tuple[int, str | None] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


_manual: OrderedDict[str, ManualEntry] = OrderedDict()


def _manual_entry(session_id: str) -> ManualEntry:
    with _registry_lock:
        entry = _manual.get(session_id)
    if entry is None:
        raise HTTPException(
            404, "no such manual session (the server forgets them on restart)"
        )
    return entry


def _confirmation_text(tool: Tool | None, result: str) -> str:
    if result == RESULT_SKILL_FAIL:
        return SKILL_FAIL_TEXT
    return CONFIRMATIONS.get(tool, NEUTRAL_WORKED_TEXT) if tool else NEUTRAL_WORKED_TEXT


@app.get("/manual/options")
def manual_options() -> dict[str, Any]:
    """Everything the manual form offers as a choice, in PRD section 8 order."""
    known = knowledge.load()
    return {
        "pulse": [v.value for v in Pulse],
        "status": [v.value for v in Status],
        "site": [v.value for v in Site],
        "visibility": [v.value for v in Visibility],
        "bleeding": [v.value for v in Bleeding],
        "fever": [v.value for v in Fever],
        "modifier": [v.value for v in Modifier],
        "tools": [v.value for v in Tool],
        "maladies": [
            {
                "name": m.name,
                "scan_text": m.scan_text,
                "fix_text": m.fix_text,
                "post_fix_text": m.post_fix_text,
            }
            for m in known.maladies
        ],
        "conditions": [
            {
                "id": c.id,
                "name": c.name,
                "text": c.text,
                "visible_at_start": c.visible_at_start,
            }
            for c in known.conditions
        ],
    }


@app.post("/manual")
def manual_start() -> dict[str, str]:
    session_id = secrets.token_urlsafe(6)
    with _registry_lock:
        _manual[session_id] = ManualEntry()
        while len(_manual) > MAX_MANUAL_SESSIONS:
            _manual.popitem(last=False)
    return {"id": session_id}


@app.post("/manual/{session_id}/reset")
def manual_reset(session_id: str) -> dict[str, Any]:
    """A new patient: empty memory and history. The skill and modifier come from
    the next state, so the form's values carry over."""
    entry = _manual_entry(session_id)
    with entry.lock:
        entry.policy = AdvisorPolicy()
        entry.config_key = None
        entry.history = []
    return {"id": session_id, "turn": 0, "history": []}


@app.post("/manual/{session_id}/advise")
def manual_advise(session_id: str, request: ManualAdviseRequest) -> dict[str, Any]:
    entry = _manual_entry(session_id)
    try:
        state = ScreenState.from_dict(request.state)
        used = None if request.used_tool is None else Tool(request.used_tool)
    except ValueError as error:
        raise HTTPException(400, str(error)) from None
    if request.result is not None and request.result not in RESULTS:
        raise HTTPException(400, f"result must be one of {', '.join(RESULTS)} or null")
    with entry.lock:
        policy = entry.policy
        memory = policy.memory
        # The player may have used another tool than the one advised; memory must
        # confirm the tool that was really used.
        if used is not None and (
            memory.last_decision is None or memory.last_decision.tool is not used
        ):
            policy.note_override(used.value)
        previous = memory.last_decision.tool if memory.last_decision else None
        if request.result is not None and not state.last_tool_text.strip():
            state = replace(
                state, last_tool_text=_confirmation_text(previous, request.result)
            )
        # Fixed per patient, but rebuilt if the player corrects the skill or modifier.
        key = (state.skill_level, state.modifier.value if state.modifier else None)
        if policy.config is None or entry.config_key != key:
            policy.config = Config.for_patient(*key)
            entry.config_key = key
        decision = decide(state, memory, policy.config)
        row = {
            "turn": memory.turn,
            "tool": decision.tool.value,
            "rule": decision.rule,
            "reason": decision.reason,
            "used_tool": previous.value if previous and request.result else None,
            "result": request.result,
            "state": {k: v for k, v in state.to_dict().items() if k in _WATCHED},
        }
        entry.history.append(row)
        return {
            "decision": decision.to_dict(),
            "turn": memory.turn,
            "history": list(entry.history),
        }
