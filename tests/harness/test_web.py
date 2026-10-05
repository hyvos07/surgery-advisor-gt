"""The web viewer plays a SurgE surgery one Next press at a time."""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import cli
from web import app as web_app
from web.app import app

client = TestClient(app)
BODY = {"malady": "Heart Attack", "condition": "none", "skill": 100, "seed": 5}


def start(**overrides: object) -> dict:
    response = client.post("/surgeries", json={**BODY, **overrides})
    assert response.status_code == 200, response.text
    return response.json()


def test_page_is_served() -> None:
    response = client.get("/")
    assert response.status_code == 200 and "Surgery Advisor" in response.text


def test_options_list_every_choice() -> None:
    options = client.get("/options").json()
    assert len(options["maladies"]) == 27 and len(options["conditions"]) == 6
    assert len(options["tools"]) == 14 and options["policies"] == [
        "baseline",
        "train-e-plus",
    ]


def test_start_returns_turn_zero_and_the_first_pick() -> None:
    view = start()
    assert view["turn"] == 0 and view["ended"] is False and view["log"] == []
    assert view["state"]["status"] == "awake"
    assert view["decision"]["tool"] in view["state"]["usable_tools"]
    assert view["settings"]["seed"] == 5 and view["policy"] == "baseline"


def test_next_applies_the_pending_decision_and_logs_it() -> None:
    view = start()
    pick = view["decision"]
    after = client.post(f"/surgeries/{view['id']}/next").json()
    assert after["turn"] == 1
    (entry,) = after["log"]
    assert entry["tool"] == pick["tool"] and entry["rule"] == pick["rule"]
    assert entry["turn"] == 0 and isinstance(entry["changes"], dict)
    assert client.get(f"/surgeries/{view['id']}").json() == after


def test_a_surgery_plays_to_an_end_card() -> None:
    view = start()
    for _ in range(100):
        if view["ended"]:
            break
        view = client.post(f"/surgeries/{view['id']}/next").json()
    assert view["ended"] and view["decision"] is None
    assert view["end"]["outcome"] in {
        "success",
        "avoidable_death",
        "unlucky_death",
        "timeout",
    }
    assert view["end"]["turns"] == len(view["log"])
    assert sum(view["end"]["tools_used"].values()) == view["end"]["turns"]
    assert view["state"] is not None
    assert client.post(f"/surgeries/{view['id']}/next").status_code == 409


def test_restart_replays_the_same_surgery() -> None:
    first = start()
    played = first
    for _ in range(3):
        played = client.post(f"/surgeries/{first['id']}/next").json()
    restarted = client.post(f"/surgeries/{first['id']}/restart").json()
    assert restarted["turn"] == 0 and restarted["log"] == []
    assert (
        restarted["state"] == first["state"]
        and restarted["decision"] == first["decision"]
    )
    again = restarted
    for _ in range(3):
        again = client.post(f"/surgeries/{first['id']}/next").json()
    assert again["log"] == played["log"] and again["state"] == played["state"]


def test_same_seed_in_two_surgeries_matches() -> None:
    a, b = start(), start()
    assert a["id"] != b["id"]
    for _ in range(4):
        va = client.post(f"/surgeries/{a['id']}/next").json()
        vb = client.post(f"/surgeries/{b['id']}/next").json()
    assert va["log"] == vb["log"]


def test_blank_fields_are_random_but_repeatable_by_seed() -> None:
    a = client.post(
        "/surgeries", json={"seed": 9, "malady": "", "condition": ""}
    ).json()
    b = client.post("/surgeries", json={"seed": 9}).json()
    assert a["settings"] == b["settings"]


def test_train_e_hint_is_listed_while_running() -> None:
    view = start(malady="Broken Arm")
    assert view["train_e"] and {"heading", "description"} <= set(view["train_e"][0])


@pytest.mark.parametrize(
    "bad",
    [
        {"malady": "Hiccups"},
        {"condition": "grumpy"},
        {"skill": 101},
        {"modifier": "magic"},
        {"policy": "advisor"},
        {"policy": "x"},
    ],
)
def test_bad_settings_are_a_400_with_a_message(bad: dict) -> None:
    response = client.post("/surgeries", json={**BODY, **bad})
    assert response.status_code == 400 and response.json()["detail"]


def test_unknown_surgery_is_a_404() -> None:
    assert client.get("/surgeries/nope").status_code == 404
    assert client.post("/surgeries/nope/next").status_code == 404


def test_only_the_newest_surgeries_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_app, "MAX_SURGERIES", 2)
    first, second, third = start(), start(), start()
    assert client.get(f"/surgeries/{first['id']}").status_code == 404
    assert client.get(f"/surgeries/{second['id']}").status_code == 200
    assert client.get(f"/surgeries/{third['id']}").status_code == 200


def test_page_script_never_writes_innerhtml() -> None:
    html = (Path(web_app.STATIC) / "index.html").read_text(encoding="utf-8")
    script = re.search(r"<script>(.*)</script>", html, re.S)
    assert script and "innerHTML" not in script.group(1)


def test_web_command_binds_to_localhost_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    calls: list[dict] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    assert cli.main(["web", "--port", "8123"]) == 0
    assert calls == [{"host": "127.0.0.1", "port": 8123, "log_level": "warning"}]
    with pytest.raises(SystemExit):
        cli.main(["web", "--host", "0.0.0.0"])
