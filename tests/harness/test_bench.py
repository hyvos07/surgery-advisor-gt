"""The benchmark runs a seeded grid, reports it, and compares like with like."""

import json
from pathlib import Path

import pytest

import cli
from harness.bench import (
    OUTCOMES,
    Grid,
    compare_reports,
    full_grid,
    render_markdown,
    run_grid,
    write_report,
)

SMALL = Grid(("Broken Arm", "Heart Attack"), ("none", "filthy"), (0, 100), (None,))


def test_full_grid_is_the_documented_810_cells() -> None:
    grid = full_grid()
    assert len(grid.maladies) == 27 and len(grid.conditions) == 6
    assert grid.skills == (0, 25, 50, 75, 100)
    assert len(grid.cells()) == 810
    assert 810 * 200 == 162_000


def test_every_surgery_gets_exactly_one_outcome() -> None:
    report = run_grid("baseline", 4, SMALL, workers=1)
    assert len(report["cells"]) == 8
    for cell in report["cells"]:
        assert sum(cell["outcomes"].values()) == 4
        assert set(cell["outcomes"]) == set(OUTCOMES)
    assert report["summary"]["overall"]["runs"] == 32


def test_same_grid_gives_the_same_report_on_any_number_of_workers() -> None:
    one = run_grid("baseline", 3, SMALL, workers=1)
    two = run_grid("baseline", 3, SMALL, workers=2)
    assert one["cells"] == two["cells"]
    assert one["summary"] == two["summary"]


def test_deaths_list_seeds_and_last_rules() -> None:
    report = run_grid(
        "baseline", 6, Grid(("Heart Attack",), ("none",), (0,), (None,)), workers=1
    )
    (cell,) = report["cells"]
    assert (
        len(cell["deaths"])
        == cell["outcomes"]["avoidable_death"] + cell["outcomes"]["unlucky_death"]
    )
    for death in cell["deaths"]:
        assert 0 <= death["seed"] < 6 and len(death["last_rules"]) <= 3


def test_summary_groups_by_skill_condition_and_malady() -> None:
    summary = run_grid("baseline", 2, SMALL, workers=1)["summary"]
    assert set(summary["skill"]) == {"0", "100"}
    assert set(summary["condition"]) == {"none", "filthy"}
    assert set(summary["malady"]) == {"Broken Arm", "Heart Attack"}


def test_unfinished_advisor_policy_is_refused() -> None:
    with pytest.raises(NotImplementedError):
        run_grid("advisor", 1, SMALL, workers=1)


def test_compare_against_itself_shows_no_change() -> None:
    report = run_grid("baseline", 3, SMALL, workers=1)
    comparison = compare_reports(report, report)
    assert comparison["overall"]["success_rate"] == 0
    assert all(d["success_rate"] == 0 for d in comparison["malady"].values())


def test_compare_refuses_different_runs_or_grids() -> None:
    a = run_grid("baseline", 2, SMALL, workers=1)
    b = run_grid("baseline", 3, SMALL, workers=1)
    with pytest.raises(ValueError, match="runs differs"):
        compare_reports(a, b)
    other = Grid(("Broken Arm",), ("none",), (0,), (None,))
    c = run_grid("baseline", 2, other, workers=1)
    with pytest.raises(ValueError, match="grid differs"):
        compare_reports(a, c)


def test_markdown_and_json_reports_are_written(tmp_path: Path) -> None:
    report = run_grid("baseline", 2, SMALL, workers=1)
    comparison = compare_reports(report, report)
    json_path, md_path = write_report(report, tmp_path / "out" / "r", comparison)
    assert json.loads(json_path.read_text(encoding="utf-8"))["meta"]["runs"] == 2
    text = md_path.read_text(encoding="utf-8")
    assert "## By malady" in text and "Success change" in text
    assert "Success change" not in render_markdown(report)


def test_cli_bench_writes_a_report_and_compares(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base = tmp_path / "baseline"
    # The CLI always uses the full grid, so keep it to one run per cell.
    code = cli.main(["bench", "--runs", "1", "--out", str(base), "--workers", "4"])
    assert code == 0
    assert (tmp_path / "baseline.json").is_file() and (
        tmp_path / "baseline.md"
    ).is_file()
    second = cli.main(
        [
            "bench",
            "--runs",
            "1",
            "--out",
            str(tmp_path / "again"),
            "--compare",
            str(base) + ".json",
            "--workers",
            "4",
        ]
    )
    assert second == 0
    assert "Success change" in (tmp_path / "again.md").read_text(encoding="utf-8")
    refused = cli.main(
        [
            "bench",
            "--runs",
            "2",
            "--compare",
            str(base) + ".json",
            "--out",
            str(tmp_path / "x"),
        ]
    )
    assert refused == 1
    assert "cannot compare" in capsys.readouterr().err


def test_cli_bench_refuses_the_advisor_until_m2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["bench", "--policy", "advisor", "--runs", "1"]) == 1
    assert "M2" in capsys.readouterr().err


def test_cli_stubs_still_exit_non_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["next", "state.json"]) == 1
    assert "(M2)" in capsys.readouterr().err


def test_tools_used_are_counted_per_tool_and_fewest_is_kept() -> None:
    report = run_grid("baseline", 6, SMALL, workers=1)
    for cell in report["cells"]:
        wins = cell["outcomes"]["success"]
        assert sum(cell["tool_counts_success"].values()) == cell["tools_on_success"]
        assert sum(cell["tool_counts_all"].values()) >= cell["tools_on_success"]
        if wins:
            assert 0 < cell["min_tools_on_success"] <= cell["tools_on_success"] / wins
        else:
            assert cell["min_tools_on_success"] is None
    overall = report["summary"]["overall"]
    assert sum(overall["tool_counts_success"].values()) == sum(
        c["tools_on_success"] for c in report["cells"]
    )
    assert overall["min_tools_on_success"] == min(
        c["min_tools_on_success"] for c in report["cells"] if c["min_tools_on_success"]
    )


def test_markdown_lists_tool_usage_and_the_fewest_column() -> None:
    text = render_markdown(run_grid("baseline", 4, SMALL, workers=1))
    assert "| Fewest |" in text and "## Tools used" in text
    assert "| Tool | Per success | Total, all surgeries |" in text
