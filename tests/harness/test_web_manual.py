"""The web viewer's manual mode: the player types the screen, the advisor answers."""

import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from advisor.config import ANESTHETIC_SLEEP
from advisor.memory import CONFIRMATIONS, Memory
from advisor.state import Tool
from web import app as web_app
from web.app import app

client = TestClient(app)
ALL_TOOLS = [t.value for t in Tool]
NO_ULTRASOUND = [t for t in ALL_TOOLS if t not in ("ultrasound", "fix_it")]


def screen(**overrides: Any) -> dict[str, Any]:
    """A fresh awake patient with the whole tray usable (PRD section 8 fields)."""
    state: dict[str, Any] = {
        "skill_level": 50,
        "modifier": None,
        "special_condition_text": None,
        "scan_text": None,
        "pulse": "steady",
        "status": "awake",
        "temperature": 98.6,
        "site": "not_sanitized",
        "visibility": "clear",
        "incisions": 0,
        "bones": None,
        "bleeding": None,
        "fever": None,
        "last_tool_text": "",
        "usable_tools": ALL_TOOLS,
    }
    return {**state, **overrides}


def new_session() -> str:
    response = client.post("/manual")
    assert response.status_code == 200, response.text
    return response.json()["id"]


def advise(
    session: str,
    state: dict[str, Any],
    used_tool: str | None = None,
    result: str | None = None,
) -> dict[str, Any]:
    response = client.post(
        f"/manual/{session}/advise",
        json={"state": state, "used_tool": used_tool, "result": result},
    )
    assert response.status_code == 200, response.text
    return response.json()


def memory_of(session: str) -> Memory:
    return web_app._manual[session].policy.memory


def heart_attack() -> dict[str, Any]:
    options = client.get("/manual/options").json()
    return next(m for m in options["maladies"] if m["name"] == "Heart Attack")


def test_options_list_the_enums_and_the_game_texts() -> None:
    options = client.get("/manual/options").json()
    assert options["pulse"] == ["strong", "steady", "weak", "extremely_weak"]
    assert options["status"] == ["awake", "coming_to", "unconscious", "heart_stopped"]
    assert options["site"] == ["clean", "not_sanitized", "unclean", "unsanitary"]
    assert options["visibility"] == ["clear", "hard_to_see", "cant_see"]
    assert options["bleeding"] == ["slowly", "losing", "very_quickly"]
    assert options["fever"] == ["slowly_rising", "climbing", "climbing_fast"]
    assert options["modifier"][0] == "stethoscope" and len(options["modifier"]) == 4
    assert options["tools"] == ALL_TOOLS and len(ALL_TOOLS) == 14
    assert len(options["maladies"]) == 27
    assert set(heart_attack()) == {"name", "scan_text", "fix_text", "post_fix_text"}
    assert heart_attack()["scan_text"]
    conditions = {c["id"]: c for c in options["conditions"]}
    assert "tough_skin" in conditions and conditions["tough_skin"]["text"]
    assert {"id", "text"} <= set(conditions["filthy"])


def test_a_session_starts_with_ultrasound_and_remembers_the_diagnosis() -> None:
    session = new_session()
    first = advise(session, screen())
    assert first["decision"]["tool"] == "ultrasound" and first["turn"] == 1
    assert [row["tool"] for row in first["history"]] == ["ultrasound"]

    scanned = screen(scan_text=heart_attack()["scan_text"], usable_tools=NO_ULTRASOUND)
    second = advise(session, scanned, used_tool="ultrasound", result="worked")
    assert second["turn"] == 2 and len(second["history"]) == 2
    memory = memory_of(session)
    assert memory.diagnosis is not None and memory.diagnosis.name == "Heart Attack"
    # The text for "it worked" was built from the advisor's own confirmation text.
    assert memory.prev_state is not None
    assert memory.prev_state.last_tool_text == CONFIRMATIONS[Tool.ULTRASOUND]

    # The diagnosis is sticky: a later screen that no longer shows the scan text
    # (the player leaves the field blank) does not lose it.
    third = advise(session, screen(usable_tools=NO_ULTRASOUND), result="worked")
    assert third["turn"] == 3
    assert memory_of(session).diagnosis is memory.diagnosis
    assert memory_of(session).incisions_needed == memory.diagnosis.incisions_needed


def test_history_rows_carry_the_key_screen_fields() -> None:
    session = new_session()
    out = advise(session, screen(temperature=100.2, bleeding="losing"))
    (row,) = out["history"]
    assert {"turn", "tool", "rule", "reason", "used_tool", "result", "state"} <= set(
        row
    )
    assert row["state"]["temperature"] == 100.2 and row["state"]["bleeding"] == "losing"
    assert row["used_tool"] is None and row["result"] is None
    assert out["decision"] == {k: row[k] for k in ("tool", "rule", "reason")}


def test_a_skill_fail_leaves_memory_unchanged_for_that_tool() -> None:
    worked, failed = new_session(), new_session()
    for session, result in ((worked, "worked"), (failed, "skill_fail")):
        advise(session, screen())
        advise(session, screen(), used_tool="lab_kit", result=result)
    assert memory_of(worked).lab_kit_done is True
    assert memory_of(failed).lab_kit_done is False
    prev = memory_of(failed).prev_state
    assert prev is not None and "[Skill Fail" in prev.last_tool_text

    # Anesthetic on a stopped heart keeps its full sleep when it worked (sleep does
    # not fall that turn) and sets none when it failed.
    worked, failed = new_session(), new_session()
    for session, result in ((worked, "worked"), (failed, "skill_fail")):
        advise(session, screen())
        advise(
            session,
            screen(status="heart_stopped"),
            used_tool="anesthetic",
            result=result,
        )
    assert memory_of(worked).sleep_left == ANESTHETIC_SLEEP
    assert memory_of(failed).sleep_left == 0


def test_a_blank_result_trusts_the_screen_text_alone() -> None:
    session = new_session()
    advise(session, screen())
    advise(session, screen(), used_tool="lab_kit")  # no result: nothing confirmed
    assert memory_of(session).lab_kit_done is False
    advise(
        session,
        screen(last_tool_text=CONFIRMATIONS[Tool.LAB_KIT]),
        used_tool="lab_kit",
    )
    assert memory_of(session).lab_kit_done is True


def test_a_different_tool_than_advised_is_honoured() -> None:
    advised, other = new_session(), new_session()
    assert advise(advised, screen())["decision"]["tool"] == "ultrasound"
    advise(other, screen())
    advise(advised, screen(), result="worked")  # the advised tool (ultrasound) worked
    advise(other, screen(), used_tool="lab_kit", result="worked")
    assert memory_of(advised).lab_kit_done is False
    assert memory_of(other).lab_kit_done is True
    assert memory_of(other).turn == 2


def test_skill_or_modifier_changes_rebuild_the_config() -> None:
    session = new_session()
    advise(session, screen(skill_level=10))
    entry = web_app._manual[session]
    low = entry.policy.config
    assert low is not None
    advise(session, screen(skill_level=10))
    assert entry.policy.config is low
    advise(session, screen(skill_level=100, modifier="tea"))
    assert entry.policy.config is not low
    assert entry.policy.config is not None
    assert entry.policy.config.fail_rate < low.fail_rate


@pytest.mark.parametrize(
    "body",
    [
        {"state": screen(pulse="fast")},
        {"state": {"skill_level": 50}},
        {"state": screen(skill_level=101)},
        {"state": screen(usable_tools=["laser"])},
        {"state": screen(), "used_tool": "laser"},
        {"state": screen(), "result": "maybe"},
        {"state": None},
    ],
)
def test_an_invalid_request_is_a_400_with_a_message_and_changes_nothing(
    body: dict[str, Any],
) -> None:
    session = new_session()
    response = client.post(f"/manual/{session}/advise", json=body)
    assert response.status_code == 400 and response.json()["detail"]
    assert memory_of(session).turn == 0 and web_app._manual[session].history == []


def test_unknown_session_is_a_404() -> None:
    assert (
        client.post("/manual/nope/advise", json={"state": screen()}).status_code == 404
    )
    assert client.post("/manual/nope/reset").status_code == 404


def test_reset_starts_a_new_patient() -> None:
    session = new_session()
    advise(session, screen())
    advise(session, screen(scan_text=heart_attack()["scan_text"]), result="worked")
    assert memory_of(session).diagnosis is not None
    reset = client.post(f"/manual/{session}/reset").json()
    assert reset == {"id": session, "turn": 0, "history": []}
    assert memory_of(session).diagnosis is None and memory_of(session).turn == 0
    again = advise(session, screen())
    assert again["turn"] == 1 and again["decision"]["tool"] == "ultrasound"
    assert len(again["history"]) == 1


def test_only_the_newest_manual_sessions_are_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(web_app, "MAX_MANUAL_SESSIONS", 2)
    first, second, third = new_session(), new_session(), new_session()
    assert client.post(f"/manual/{first}/reset").status_code == 404
    assert client.post(f"/manual/{second}/reset").status_code == 200
    assert client.post(f"/manual/{third}/reset").status_code == 200


@pytest.mark.parametrize(
    "status", ["awake", "coming_to", "unconscious", "heart_stopped"]
)
def test_the_decision_is_always_legal(status: str) -> None:
    """Awake never gets Scalpel, unconscious never gets Anesthetic, and the tool is
    always one the player said is usable."""
    session = new_session()
    trays = (ALL_TOOLS, NO_ULTRASOUND, ["sponge"], ["sponge", "scalpel", "anesthetic"])
    checked = 0
    for pulse in ("strong", "weak", "extremely_weak"):
        for site in ("clean", "unsanitary"):
            for bleeding in (None, "very_quickly"):
                for tray in trays:
                    state = screen(
                        status=status,
                        pulse=pulse,
                        site=site,
                        bleeding=bleeding,
                        usable_tools=tray,
                        incisions=2,
                        scan_text=heart_attack()["scan_text"],
                    )
                    tool = advise(session, state)["decision"]["tool"]
                    assert tool in tray
                    assert not (status == "awake" and tool == "scalpel")
                    assert not (status == "unconscious" and tool == "anesthetic")
                    checked += 1
    assert checked == 48


def test_the_page_has_the_mode_switch_and_both_panels() -> None:
    html = (Path(web_app.STATIC) / "index.html").read_text(encoding="utf-8")
    for needle in ('id="tab-sim"', 'id="tab-manual"', 'id="manual"', 'id="mform"'):
        assert needle in html
    # The simulator controls are still there, and the URL keeps the mode.
    for needle in ('id="sim"', 'id="form"', 'id="next"', 'id="auto"', 'id="restart"'):
        assert needle in html
    assert re.search(r'get\("mode"\) === "manual"', html)
    # The tray ticks follow observe.py's usable_tools() rules, in one function.
    assert "function defaultTray(" in html and "harness/observe.py" in html
    assert "applyTray();" in html
    assert client.get("/").status_code == 200
