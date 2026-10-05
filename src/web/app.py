"""FastAPI server for the step-by-step viewer."""

import secrets
import threading
from collections import Counter, OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from harness.baseline import parse_tips
from harness.observe import observe
from harness.runner import Surgery, policy_by_name, resolve_settings
from harness.surge import (
    CONDITION_NAMES,
    MALADY_NAMES,
    MODIFIER_NAMES,
    TOOL_IDS,
    train_e_tips,
)

STATIC = Path(__file__).parent / "static"
MAX_SURGERIES = 100  # the oldest is dropped beyond this; surgeries live in memory only
POLICIES = ["baseline"]  # the advisor joins in M2

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
    policy: str = "baseline"
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
    except (NotImplementedError, ValueError) as error:
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
        entry.surgery = Surgery(
            old.settings, policy_by_name(entry.policy), entry.policy
        )
        entry.log = []
        entry.final_state = None
        return _view(surgery_id, entry)
