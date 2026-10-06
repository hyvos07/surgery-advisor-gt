"""`surg report`: side by side numbers, death analysis and viewer links."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import cli
from harness.bench import Grid, run_grid
from harness.report import (
    build_report,
    death_analysis,
    death_link,
    render_report_markdown,
    side_by_side,
    write_comparison_report,
)

TOOLS = ["antiseptic", "sponge", "scalpel"]
GRID = {
    "maladies": ["Heart Attack", "Broken Arm"],
    "conditions": ["none"],
    "skills": [0, 100],
    "modifiers": [None, "tea"],
}

Seeds = list[list[int] | None]


def death(
    seed: int,
    outcome: str,
    rules: list[str],
    back: int | None,
    alternative: str | None,
) -> dict[str, Any]:
    return {
        "seed": seed,
        "outcome": outcome,
        "turns": 10,
        "last_rules": rules,
        "mistake_turns_back": back,
        "alternative": alternative,
    }


AVOID, UNLUCKY = "avoidable_death", "unlucky_death"


def cell(
    malady: str,
    skill: int,
    modifier: str | None,
    counts: tuple[int, int, int, int],
    seed_tools: Seeds,
    deaths: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """`counts` is success, avoidable, unlucky and timeout."""
    return {
        "malady": malady,
        "condition": "none",
        "skill": skill,
        "modifier": modifier,
        "runs": 5,
        "outcomes": dict(
            zip(
                ["success", "avoidable_death", "unlucky_death", "timeout"],
                counts,
                strict=True,
            )
        ),
        "tools_on_success": 0,
        "min_tools_on_success": None,
        "tool_counts_success": {},
        "tool_counts_all": {},
        "illegal_moves": 0,
        "seed_tools": seed_tools,
        "deaths": deaths or [],
    }


def report(policy: str, cells: list[dict[str, Any]], **meta: Any) -> dict[str, Any]:
    return {
        "meta": {
            "policy": policy,
            "runs": 5,
            "max_turns": 80,
            "grid": GRID,
            "tool_order": TOOLS,
            **meta,
        },
        "cells": cells,
    }


def one() -> list[int]:
    return [1, 0, 0]


def hand_built() -> tuple[dict[str, Any], dict[str, Any]]:
    a = report(
        "advisor",
        [
            cell(
                "Heart Attack",
                0,
                None,
                (2, 2, 1, 0),
                [[1, 1, 0], None, None, None, one()],
                [
                    death(1, AVOID, ["P1", "E5", "E5"], 0, "clamp"),
                    death(2, AVOID, ["P1", "E5", "P3"], 2, "sponge"),
                    death(3, UNLUCKY, ["E5", "P1", "P3"], None, None),
                ],
            ),
            cell(
                "Broken Arm",
                100,
                "tea",
                (3, 1, 0, 1),
                [None, [1, 1, 0], [0, 0, 2], [1, 1, 1], None],
                [death(0, AVOID, ["P3"], 0, "sponge")],
            ),
            cell(
                "Heart Attack",
                100,
                None,
                (3, 2, 0, 0),
                [one(), [1, 1, 0], None, [2, 0, 0], None],
                [
                    death(2, AVOID, ["E5", "P1", "P1"], 1, "sponge"),
                    death(4, AVOID, ["P1", "P1", "P1"], None, None),
                ],
            ),
            cell("Broken Arm", 0, None, (5, 0, 0, 0), [one()] * 5),
        ],
        lookback=3,
    )
    b = report(
        "baseline",
        [
            cell(
                "Heart Attack", 0, None, (1, 2, 2, 0), [one(), None, None, None, None]
            ),
            cell(
                "Broken Arm",
                100,
                "tea",
                (2, 2, 0, 1),
                [None, [1, 0, 0], [0, 0, 1], None, None],
            ),
            cell(
                "Heart Attack",
                100,
                None,
                (2, 2, 1, 0),
                [one(), None, None, one(), None],
            ),
            cell("Broken Arm", 0, None, (4, 0, 1, 0), [one()] * 4 + [None]),
        ],
    )
    return a, b


# --- side by side ------------------------------------------------------------


def test_overall_and_group_numbers() -> None:
    a, b = hand_built()
    sides = side_by_side(a, b)
    overall = sides["overall"]["all"]
    assert overall["a_success_rate"] == 0.65 and overall["b_success_rate"] == 0.45
    assert overall["difference_pts"] == pytest.approx(20.0)
    assert (overall["a_avoidable"], overall["a_unlucky"], overall["a_timeout"]) == (
        5,
        1,
        1,
    )
    assert overall["b_avoidable"] == 6
    # 9 pairs: advisor 2+4+3+4 = 13 tools, baseline 1+2+2+4 = 9.
    assert overall["pairs"] == 9
    assert overall["a_tools_per_success"] == pytest.approx(13 / 9)
    assert overall["b_tools_per_success"] == pytest.approx(1.0)

    skill0 = sides["skill"]["0"]
    assert skill0["a_success_rate"] == 0.7 and skill0["b_success_rate"] == 0.5
    assert skill0["a_tools_per_success"] == pytest.approx(1.2)  # 6 tools, 5 pairs
    assert sides["skill"]["100"]["runs"] == 10
    assert sides["malady"]["Heart Attack"]["a_avoidable"] == 4
    assert sides["condition"]["none"]["runs"] == 20


def test_modifier_group_appears_only_with_several_modifiers() -> None:
    a, b = hand_built()
    sides = side_by_side(a, b)
    assert list(sides["modifier"]) == ["none", "tea"]
    tea = sides["modifier"]["tea"]
    assert tea["runs"] == 5 and tea["a_success_rate"] == 0.6
    assert tea["a_tools_per_success"] == 2.0 and tea["b_tools_per_success"] == 1.0
    assert sides["modifier"]["none"]["pairs"] == 7

    one_modifier = {**GRID, "modifiers": [None]}
    for r in (a, b):
        r["meta"]["grid"] = one_modifier
        for c in r["cells"]:
            c["modifier"] = None
    assert "modifier" not in side_by_side(a, b)


def test_paired_columns_are_blank_without_seed_tools() -> None:
    a, b = hand_built()
    for c in b["cells"]:
        del c["seed_tools"]
    sides = side_by_side(a, b)
    overall = sides["overall"]["all"]
    assert overall["pairs"] is None and overall["a_tools_per_success"] is None
    assert overall["a_success_rate"] == 0.65  # the rest still works
    text = render_report_markdown(build_report(a, b))
    assert "| all | 65.0% | 45.0% | +20.0 | 5 | 1 | 1 | 6 |  |  |" in text


def test_reports_must_share_runs_grid_and_turn_cap() -> None:
    a, b = hand_built()
    runs = copy.deepcopy(b)
    runs["meta"]["runs"] = 6
    with pytest.raises(ValueError, match="runs differs"):
        side_by_side(a, runs)
    grid = copy.deepcopy(b)
    grid["meta"]["grid"] = {**GRID, "skills": [0]}
    with pytest.raises(ValueError, match="grid differs"):
        side_by_side(a, grid)
    cap = copy.deepcopy(b)
    cap["meta"]["max_turns"] = 40
    with pytest.raises(ValueError, match="max_turns differs"):
        side_by_side(a, cap)
    missing = copy.deepcopy(b)
    missing["cells"] = missing["cells"][:-1]
    with pytest.raises(ValueError, match="same cells"):
        side_by_side(a, missing)


def test_reports_must_share_the_seed_offset() -> None:
    a, b = hand_built()
    shifted = copy.deepcopy(b)
    shifted["meta"]["seed_offset"] = 1000
    with pytest.raises(ValueError, match="seed_offset differs"):
        side_by_side(a, shifted)
    with pytest.raises(ValueError, match="seed_offset differs"):
        side_by_side(shifted, a)
    zero = copy.deepcopy(b)
    zero["meta"]["seed_offset"] = 0  # same as the key missing from `a`
    assert build_report(a, zero)["meta"]["seed_offset"] == 0
    both = copy.deepcopy(a)
    both["meta"]["seed_offset"] = 1000
    assert build_report(both, shifted)["meta"]["seed_offset"] == 1000


def test_a_death_link_carries_the_real_seed_not_the_position() -> None:
    grid = Grid(("Heart Attack",), ("filthy",), (0,), (None,))
    run = run_grid("baseline", 6, grid, workers=1, seed_offset=5)
    deaths = run["cells"][0]["deaths"]
    assert deaths and all(5 <= d["seed"] < 11 for d in deaths)
    found = death_analysis(run)["deaths"]
    assert [d["seed"] for d in found] == [d["seed"] for d in deaths]
    for d in found:
        assert f"&seed={d['seed']}&" in d["link"]


def test_a_different_lookback_is_allowed() -> None:
    a, b = hand_built()
    assert a["meta"]["lookback"] == 3 and "lookback" not in b["meta"]
    built = build_report(a, b)
    assert (built["meta"]["a_lookback"], built["meta"]["b_lookback"]) == (3, 1)
    # Pairing the tools doesn't care either.
    assert built["side_by_side"]["overall"]["all"]["pairs"] == 9
    b["meta"]["lookback"] = 5
    build_report(a, b)


# --- the death analysis ------------------------------------------------------


def test_rules_in_the_last_turns_are_ranked_by_deaths() -> None:
    analysis = death_analysis(hand_built()[0])
    assert (analysis["deaths_total"], analysis["avoidable_total"]) == (6, 5)
    rows = {r["rule"]: r for r in analysis["rules_last_turns"]}
    assert [r["rule"] for r in analysis["rules_last_turns"]] == ["P1", "E5", "P3"]
    assert (rows["P1"]["deaths"], rows["P1"]["avoidable"], rows["P1"]["unlucky"]) == (
        5,
        4,
        1,
    )
    assert rows["P1"]["share_of_deaths"] == pytest.approx(5 / 6)
    # P1 fires 1+1+1+2+3 times in those turns, but a death counts once.
    assert rows["P1"]["appearances"] == 8
    assert (rows["E5"]["deaths"], rows["E5"]["appearances"]) == (4, 5)
    assert (rows["E5"]["avoidable"], rows["E5"]["unlucky"]) == (3, 1)
    assert (rows["P3"]["deaths"], rows["P3"]["appearances"]) == (3, 3)


def test_rule_at_the_mistake_turn_counts_back_from_the_last_rule() -> None:
    analysis = death_analysis(hand_built()[0])
    by_death = {(d["malady"], d["seed"], d["skill"]): d for d in analysis["deaths"]}
    # k = 0 is the fatal turn: the last rule. k = 2 is the first of three.
    assert by_death[("Heart Attack", 1, 0)]["mistake_rule"] == "E5"
    assert by_death[("Heart Attack", 2, 0)]["mistake_rule"] == "P1"
    assert by_death[("Heart Attack", 2, 100)]["mistake_rule"] == "P1"  # k = 1
    assert by_death[("Broken Arm", 0, 100)]["mistake_rule"] == "P3"
    assert by_death[("Heart Attack", 3, 0)]["mistake_rule"] is None  # unlucky
    assert by_death[("Heart Attack", 4, 100)]["mistake_rule"] is None  # illegal

    rows = {r["rule"]: r for r in analysis["mistake_rules"]}
    assert [r["rule"] for r in analysis["mistake_rules"]] == ["P1", "E5", "P3"]
    assert rows["P1"]["avoidable"] == 2
    assert (rows["P1"]["top_better_tool"], rows["P1"]["top_better_tool_count"]) == (
        "sponge",
        2,
    )
    assert rows["P1"]["mean_turns_back"] == pytest.approx(1.5)  # k 2 and 1
    assert rows["E5"]["top_better_tool"] == "clamp"
    assert rows["E5"]["mean_turns_back"] == 0


def test_mistake_beyond_the_kept_rules_is_counted_apart() -> None:
    a, _ = hand_built()
    a["cells"][0]["deaths"][0]["mistake_turns_back"] = 4  # only 3 rules are kept
    analysis = death_analysis(a)
    assert analysis["mistake_outside_last_rules"] == 1
    assert sum(r["avoidable"] for r in analysis["mistake_rules"]) == 3
    assert analysis["mistake_depth"][-1] == {"turns_back": 4, "avoidable": 1}
    assert "mistake further back than the last 3 turns" in render_report_markdown(
        build_report(a, hand_built()[1])
    )


def test_mistake_depth_better_tools_and_illegal_moves() -> None:
    analysis = death_analysis(hand_built()[0])
    assert analysis["mistake_depth"] == [
        {"turns_back": 0, "avoidable": 2},
        {"turns_back": 1, "avoidable": 1},
        {"turns_back": 2, "avoidable": 1},
    ]
    assert analysis["illegal_move_deaths"] == 1
    # hand_built() is an old-format report: no `alternatives`, so that column is blank.
    assert analysis["better_tools"] == [
        {"tool": "sponge", "avoidable": 3, "among_all": None},
        {"tool": "clamp", "avoidable": 1, "among_all": None},
    ]


def test_better_tools_among_all_working_alternatives() -> None:
    a, b = hand_built()
    working = {1: ["clamp", "sponge"], 2: ["sponge", "stitches"]}
    for c in a["cells"]:
        for d in c["deaths"]:
            if d["outcome"] == AVOID and d["mistake_turns_back"] is not None:
                d["alternatives"] = working.get(d["seed"], [d["alternative"]])
    # Seed 2 is in two cells, so sponge is listed in 4 deaths and credited in 3.
    analysis = death_analysis(a)
    assert analysis["better_tools"] == [
        {"tool": "sponge", "avoidable": 3, "among_all": 4},
        {"tool": "clamp", "avoidable": 1, "among_all": 1},
        {"tool": "stitches", "avoidable": 0, "among_all": 2},
    ]
    text = render_report_markdown(build_report(a, b))
    assert "| Tool | Avoidable deaths | Among all working alternatives |" in text
    assert "| sponge | 3 | 4 |" in text
    assert "| stitches | 0 | 2 |" in text


def test_a_report_without_alternatives_renders_a_blank_column() -> None:
    text = render_report_markdown(build_report(*hand_built()))
    assert "| sponge | 3 |  |" in text
    assert "| clamp | 1 |  |" in text


def test_maladies_are_ranked_by_avoidable_deaths() -> None:
    maladies = death_analysis(hand_built()[0])["maladies"]
    assert [m["malady"] for m in maladies] == ["Heart Attack", "Broken Arm"]
    heart, arm = maladies
    assert (heart["deaths"], heart["avoidable"]) == (5, 4)
    assert (heart["top_mistake_rule"], heart["top_mistake_rule_count"]) == ("P1", 2)
    assert (heart["top_better_tool"], heart["top_better_tool_count"]) == ("sponge", 2)
    assert (arm["deaths"], arm["avoidable"], arm["top_mistake_rule"]) == (1, 1, "P3")


def test_no_deaths_gives_empty_tables() -> None:
    a, b = hand_built()
    for c in a["cells"]:
        c["deaths"] = []
    analysis = death_analysis(a)
    assert analysis["deaths_total"] == 0 and analysis["rules_last_turns"] == []
    assert analysis["mistake_depth"] == [] and analysis["examples"] == []
    assert "## Better tools" in render_report_markdown(build_report(a, b))


# --- links and examples ------------------------------------------------------


def test_link_format_with_and_without_modifier() -> None:
    plain = {
        "malady": "Heart Attack",
        "condition": "none",
        "skill": 0,
        "seed": 1,
        "modifier": None,
    }
    assert death_link(plain, "advisor") == (
        "http://127.0.0.1:8000/"
        "?malady=Heart%20Attack&condition=none&skill=0&seed=1&policy=advisor"
    )
    with_modifier = {**plain, "modifier": "tea"}
    assert death_link(with_modifier, "advisor").endswith("&policy=advisor&modifier=tea")


def test_examples_are_limited_per_malady_but_json_keeps_every_death() -> None:
    a, _ = hand_built()
    one_each = death_analysis(a, examples=1)
    assert [(d["malady"], d["seed"]) for d in one_each["examples"]] == [
        ("Heart Attack", 1),
        ("Broken Arm", 0),
    ]
    assert one_each["examples"][1]["link"] == (
        "http://127.0.0.1:8000/?malady=Broken%20Arm&condition=none&skill=100"
        "&seed=0&policy=advisor&modifier=tea"
    )
    assert len(death_analysis(a, examples=3)["examples"]) == 4  # 3 + 1
    nothing = death_analysis(a, examples=0)
    assert nothing["examples"] == []
    assert len(nothing["avoidable_deaths"]) == 5
    assert all(
        d["link"].startswith("http://127.0.0.1:8000/?") for d in nothing["deaths"]
    )


# --- markdown and files ------------------------------------------------------


def test_markdown_has_every_section_and_the_numbers() -> None:
    a, b = hand_built()
    text = render_report_markdown(build_report(a, b, examples=1))
    assert text.startswith("# Report: advisor vs baseline\n")
    assert "Death lookback: 3 for advisor, 1 for baseline" in text
    assert "later play win" in text
    for title in (
        "## Overall",
        "## By skill level",
        "## By modifier",
        "## By special condition",
        "## By malady",
        "## Deaths: rules in the last 3 turns",
        "## Rule at the mistake turn",
        "## Mistake depth",
        "## Better tools",
        "## Examples with viewer links",
    ):
        assert title in text
    assert (
        "| | advisor success | baseline success | Difference (pts) | advisor avoidable "
        "| advisor unlucky | advisor timeout | baseline avoidable "
        "| Tools/success on paired wins advisor | baseline |"
    ) in text
    assert "| all | 65.0% | 45.0% | +20.0 | 5 | 1 | 1 | 6 | 1.4 | 1.0 |" in text
    assert "| P1 | 5 | 4 | 1 | 83.3% | 8 |" in text
    assert "| P1 | 2 | sponge (2) | 1.50 |" in text
    assert "| illegal move | 1 |" in text
    assert "| sponge | 3 |" in text
    assert "| Heart Attack | 5 | 4 | P1 (2) | sponge (2) |" in text
    assert text.index("| P1 | 5 |") < text.index("| E5 | 4 |")
    assert (
        "- **Heart Attack**, none, skill 0, modifier none, seed 1: 0 turns back, "
        "better tool clamp, rules P1 > E5 > E5 ([view](http://127.0.0.1:8000/?"
    ) in text
    assert "modifier tea, seed 0" in text
    assert text.count("([view](") == 2  # one example per malady


def test_report_files_are_written(tmp_path: Path) -> None:
    built = build_report(*hand_built())
    json_path, md_path = write_comparison_report(built, tmp_path / "out" / "r")
    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert data["meta"]["a"] == "advisor" and len(data["analysis"]["deaths"]) == 6
    assert md_path.read_text(encoding="utf-8").startswith("# Report: advisor vs")


# --- the command ---------------------------------------------------------------


def write_json(path: Path, data: Any) -> str:
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_cli_report_writes_both_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = hand_built()
    out = tmp_path / "out" / "r"
    code = cli.main(
        [
            "report",
            write_json(tmp_path / "a.json", a),
            write_json(tmp_path / "b.json", b),
        ]
        + ["--out", str(out), "--examples", "1"]
    )
    assert code == 0
    assert out.with_suffix(".json").is_file() and out.with_suffix(".md").is_file()
    assert (
        json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))["meta"][
            "examples_per_malady"
        ]
        == 1
    )
    printed = capsys.readouterr().out
    assert "# Report: advisor vs baseline" in printed and "Wrote " in printed


def test_cli_report_default_output_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = hand_built()
    paths = [write_json(tmp_path / "a.json", a), write_json(tmp_path / "b.json", b)]
    monkeypatch.chdir(tmp_path)
    assert cli.main(["report", *paths]) == 0
    assert (tmp_path / "reports" / "report-advisor-vs-baseline.md").is_file()
    assert (tmp_path / "reports" / "report-advisor-vs-baseline.json").is_file()


def test_cli_report_problems_exit_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = hand_built()
    good = write_json(tmp_path / "a.json", a)
    assert cli.main(["report", good, str(tmp_path / "missing.json")]) == 1
    assert "surg report: cannot read" in capsys.readouterr().err

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert cli.main(["report", good, str(broken)]) == 1
    assert "surg report: " in capsys.readouterr().err

    assert cli.main(["report", good, write_json(tmp_path / "list.json", [])]) == 1
    assert "not a benchmark report" in capsys.readouterr().err

    b["meta"]["runs"] = 9
    assert cli.main(["report", good, write_json(tmp_path / "b9.json", b)]) == 1
    assert "surg report: cannot compare: runs differs" in capsys.readouterr().err

    assert cli.main(["report", good, good, "--examples", "-1"]) == 1
    assert "--examples" in capsys.readouterr().err
