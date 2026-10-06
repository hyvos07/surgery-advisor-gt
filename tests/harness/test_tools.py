"""Paired tool comparison: only surgeries both policies won count."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

import cli
from harness.bench import (
    Grid,
    compare_reports,
    pair_tools,
    render_tools_markdown,
    run_cell,
    run_grid,
    write_tools_report,
)
from harness.runner import SUCCESS, Settings, policy_by_name, run_surgery
from harness.surge import TOOL_IDS

TOOLS = ["antiseptic", "sponge", "scalpel"]
GRID = {
    "maladies": ["Heart Attack", "Broken Arm"],
    "conditions": ["none", "filthy"],
    "skills": [0, 100],
    "modifiers": [None],
}
SMALL = Grid(("Broken Arm", "Heart Attack"), ("none", "filthy"), (0, 100), (None,))

Seeds = list[list[int] | None]


def cell(malady: str, condition: str, skill: int, seed_tools: Seeds) -> dict[str, Any]:
    return {
        "malady": malady,
        "condition": condition,
        "skill": skill,
        "modifier": None,
        "runs": len(seed_tools),
        "seed_tools": seed_tools,
    }


def report(policy: str, cells: list[dict[str, Any]], runs: int = 3) -> dict[str, Any]:
    return {
        "meta": {
            "policy": policy,
            "runs": runs,
            "max_turns": 80,
            "grid": GRID,
            "tool_order": TOOLS,
        },
        "cells": cells,
    }


def hand_built() -> tuple[dict[str, Any], dict[str, Any]]:
    a = report(
        "advisor",
        [
            cell("Heart Attack", "none", 0, [[1, 2, 0], [2, 0, 0], None]),
            cell("Broken Arm", "none", 0, [[1, 0, 0], None, None]),
            cell("Broken Arm", "filthy", 100, [[0, 1, 1], [0, 0, 1], [0, 0, 1]]),
        ],
    )
    b = report(
        "baseline",
        [
            cell("Heart Attack", "none", 0, [[1, 1, 0], None, [3, 0, 0]]),
            cell("Broken Arm", "none", 0, [None, None, None]),
            cell("Broken Arm", "filthy", 100, [[0, 1, 0], [0, 1, 0], [1, 0, 0]]),
        ],
    )
    return a, b


def test_run_cell_records_tool_counts_for_each_won_seed() -> None:
    runs = 6
    result = run_cell(("baseline", ("Heart Attack", "none", 0, None), runs))
    seed_tools = result["seed_tools"]
    assert len(seed_tools) == runs
    wins = [t for t in seed_tools if t is not None]
    assert len(wins) == result["outcomes"][SUCCESS]
    assert 0 < len(wins) < runs  # the cell has both wins and failures
    assert sum(sum(t) for t in wins) == result["tools_on_success"]
    for index, tool in enumerate(TOOL_IDS):
        assert sum(t[index] for t in wins) == result["tool_counts_success"].get(tool, 0)
    for seed, counts in enumerate(seed_tools):
        outcome = run_surgery(
            Settings("Heart Attack", "none", 0, None, seed),
            policy_by_name("baseline"),
            "baseline",
        )
        assert (counts is not None) == (outcome.outcome == SUCCESS)
        if counts is not None:
            assert counts == [outcome.tool_counts.get(t, 0) for t in TOOL_IDS]


def test_run_grid_records_the_tool_order() -> None:
    meta = run_grid("baseline", 1, Grid(("Broken Arm",), ("none",), (0,), (None,)), 1)[
        "meta"
    ]
    assert meta["tool_order"] == list(TOOL_IDS)


def test_pairs_are_the_seeds_both_policies_won() -> None:
    a, b = hand_built()
    paired = pair_tools(a, b)
    overall = paired["summary"]["overall"]
    assert (overall["pairs"], overall["runs"]) == (4, 9)
    assert (overall["a_wins"], overall["b_wins"]) == (6, 5)
    assert (overall["a_tools"], overall["b_tools"]) == (7, 5)
    assert overall["a_per_success"] == 1.75 and overall["b_per_success"] == 1.25
    assert overall["difference"] == pytest.approx(0.5)


def test_fewest_looks_at_every_success_of_either_policy() -> None:
    a, b = hand_built()
    overall = pair_tools(a, b)["summary"]["overall"]
    # The 1-tool win in Broken Arm / none / 0 is in no pair, but still counts.
    assert overall["fewest"] == 1
    assert (overall["a_fewest"], overall["b_fewest"]) == (1, 1)
    cells = {
        (c["malady"], c["condition"], c["skill"]): c for c in pair_tools(a, b)["cells"]
    }
    heart = cells[("Heart Attack", "none", 0)]
    # Seed 0 is the only pair; the other wins (2 tools and 3 tools) set the fewest.
    assert heart["pairs"] == 1 and heart["fewest"] == 2
    assert (heart["a_fewest"], heart["b_fewest"]) == (2, 2)
    assert (heart["a_per_success"], heart["b_per_success"]) == (3, 2)
    lone = cells[("Broken Arm", "none", 0)]
    assert lone["pairs"] == 0 and lone["fewest"] == 1 and lone["b_fewest"] is None
    assert lone["a_per_success"] is None


def test_tools_are_summed_per_tool_over_the_pairs() -> None:
    a, b = hand_built()
    overall = pair_tools(a, b)["summary"]["overall"]
    assert overall["a_by_tool"] == {"antiseptic": 1, "sponge": 3, "scalpel": 3}
    assert overall["b_by_tool"] == {"antiseptic": 2, "sponge": 3, "scalpel": 0}


def test_groups_use_the_same_keys_as_the_summary() -> None:
    a, b = hand_built()
    summary = pair_tools(a, b)["summary"]
    assert set(summary) == {"overall", "skill", "condition", "malady"}
    assert set(summary["skill"]) == {"0", "100"}
    assert set(summary["condition"]) == {"none", "filthy"}
    assert set(summary["malady"]) == {"Heart Attack", "Broken Arm"}
    assert summary["skill"]["0"]["pairs"] == 1
    assert summary["skill"]["100"]["pairs"] == 3
    arm = summary["malady"]["Broken Arm"]
    assert arm["pairs"] == 3 and arm["difference"] == pytest.approx(1 / 3)
    assert arm["fewest"] == 1
    assert summary["malady"]["Heart Attack"]["difference"] == 1


def test_a_group_with_no_pairs_has_no_difference() -> None:
    a, b = hand_built()
    paired = pair_tools(a, b)
    row = {c["condition"]: c for c in paired["cells"] if c["malady"] == "Broken Arm"}
    assert row["none"]["pairs"] == 0
    a2, b2 = copy.deepcopy(a), copy.deepcopy(b)
    for r in (a2, b2):
        r["cells"] = r["cells"][1:2]
    empty = pair_tools(a2, b2)["summary"]["overall"]
    assert empty["pairs"] == 0 and empty["difference"] is None
    assert empty["a_per_success"] is None
    text = render_tools_markdown(pair_tools(a2, b2))
    assert "## Where the difference comes from" in text


def test_pairing_refuses_reports_that_do_not_line_up() -> None:
    a, b = hand_built()
    other_runs = copy.deepcopy(b)
    other_runs["meta"]["runs"] = 4
    with pytest.raises(ValueError, match="runs differs"):
        pair_tools(a, other_runs)
    other_grid = copy.deepcopy(b)
    other_grid["meta"]["grid"] = {**GRID, "skills": [0]}
    with pytest.raises(ValueError, match="grid differs"):
        pair_tools(a, other_grid)
    other_order = copy.deepcopy(b)
    other_order["meta"]["tool_order"] = list(reversed(TOOLS))
    with pytest.raises(ValueError, match="re-run"):
        pair_tools(a, other_order)


def test_pairing_refuses_a_different_seed_offset_either_way() -> None:
    a, b = hand_built()
    shifted = copy.deepcopy(b)
    shifted["meta"]["seed_offset"] = 1000
    with pytest.raises(ValueError, match="seed_offset differs"):
        pair_tools(a, shifted)
    with pytest.raises(ValueError, match="seed_offset differs"):
        pair_tools(shifted, a)
    # A missing key is offset 0; equal offsets pair.
    zero = copy.deepcopy(b)
    zero["meta"]["seed_offset"] = 0
    assert pair_tools(a, zero)["meta"]["seed_offset"] == 0
    both = copy.deepcopy(a)
    both["meta"]["seed_offset"] = 1000
    assert pair_tools(both, shifted)["meta"]["seed_offset"] == 1000


def test_pairing_refuses_reports_without_seed_tools() -> None:
    a, b = hand_built()
    old = copy.deepcopy(b)
    del old["cells"][1]["seed_tools"]
    with pytest.raises(ValueError, match="re-run `surg bench`"):
        pair_tools(a, old)
    no_order = copy.deepcopy(a)
    del no_order["meta"]["tool_order"]
    with pytest.raises(ValueError, match="re-run `surg bench`"):
        pair_tools(no_order, b)


def test_old_reports_still_compare() -> None:
    current = run_grid("baseline", 2, SMALL, workers=1)
    old = copy.deepcopy(current)
    del old["meta"]["tool_order"]
    for c in old["cells"]:
        del c["seed_tools"]
    assert compare_reports(current, old)["overall"]["success_rate"] == 0


def test_markdown_has_every_section_and_a_signed_difference() -> None:
    a, b = hand_built()
    text = render_tools_markdown(pair_tools(a, b))
    assert text.startswith("# Tools: advisor vs baseline\n")
    assert "Only surgeries that both policies won are compared" in text
    for title in (
        "## Overall",
        "## By skill level",
        "## By special condition",
        "## By malady",
        "## Where the difference comes from",
        "## Biggest differences by malady",
    ):
        assert title in text
    assert "| | Pairs | Both won | advisor wins | baseline wins |" in text
    # 4 pairs of 9 runs, 1.8 vs 1.2 tools per success (1.75 and 1.25).
    assert "| all | 4 | 44.4% | 6 | 5 | 1.8 | 1.2 | +0.5 | 1 | 1 | 1 |" in text
    # scalpel differs most (+0.75), then antiseptic (-0.25).
    assert "| scalpel | 0.75 | 0.00 | +0.75 |" in text
    assert "| antiseptic | 0.25 | 0.50 | -0.25 |" in text
    assert text.index("| scalpel |") < text.index("| antiseptic |")
    # Heart Attack (+1.0) ranks above Broken Arm (+0.3).
    assert "| Heart Attack | +1.0 | sponge +1.00 |" in text.split("## Biggest")[1]
    assert text.split("## Biggest")[1].index("Heart Attack") < text.split("## Biggest")[
        1
    ].index("Broken Arm")


def test_a_real_pairing_never_counts_a_non_win() -> None:
    a = run_grid("advisor", 3, SMALL, workers=1)
    b = run_grid("baseline", 3, SMALL, workers=1)
    paired = pair_tools(a, b)
    overall = paired["summary"]["overall"]
    assert overall["pairs"] <= min(overall["a_wins"], overall["b_wins"])
    assert overall["a_wins"] == a["summary"]["overall"][SUCCESS]
    assert overall["b_wins"] == b["summary"]["overall"][SUCCESS]
    assert overall["fewest"] == min(
        x
        for x in (
            a["summary"]["overall"]["min_tools_on_success"],
            b["summary"]["overall"]["min_tools_on_success"],
        )
        if x
    )
    assert len(paired["cells"]) == len(SMALL.cells())
    assert paired["meta"]["a"] == "advisor" and paired["meta"]["b"] == "baseline"


def test_tools_reports_are_written(tmp_path: Path) -> None:
    a, b = hand_built()
    json_path, md_path = write_tools_report(pair_tools(a, b), tmp_path / "x" / "t")
    assert json.loads(json_path.read_text(encoding="utf-8"))["meta"]["a"] == "advisor"
    assert md_path.read_text(encoding="utf-8").startswith("# Tools: advisor vs")


def write_json(path: Path, data: Any) -> str:
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_cli_tools_writes_both_outputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = hand_built()
    out = tmp_path / "out" / "t"
    code = cli.main(
        [
            "tools",
            write_json(tmp_path / "a.json", a),
            write_json(tmp_path / "b.json", b),
        ]
        + ["--out", str(out)]
    )
    assert code == 0
    assert out.with_suffix(".json").is_file() and out.with_suffix(".md").is_file()
    printed = capsys.readouterr().out
    assert "# Tools: advisor vs baseline" in printed and "Wrote " in printed


def test_cli_tools_default_output_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = hand_built()
    paths = [write_json(tmp_path / "a.json", a), write_json(tmp_path / "b.json", b)]
    monkeypatch.chdir(tmp_path)
    assert cli.main(["tools", *paths]) == 0
    assert (tmp_path / "reports" / "tools-advisor-vs-baseline.md").is_file()


def test_cli_tools_reports_problems_and_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a, b = hand_built()
    good = write_json(tmp_path / "a.json", a)
    assert cli.main(["tools", good, str(tmp_path / "missing.json")]) == 1
    assert "surg tools: cannot read" in capsys.readouterr().err

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert cli.main(["tools", good, str(broken)]) == 1
    assert "not valid JSON" in capsys.readouterr().err

    assert cli.main(["tools", good, write_json(tmp_path / "list.json", [])]) == 1
    assert "surg tools:" in capsys.readouterr().err

    del b["cells"][0]["seed_tools"]
    old = write_json(tmp_path / "old.json", b)
    assert cli.main(["tools", good, old]) == 1
    assert "re-run" in capsys.readouterr().err
