"""Benchmark grid and reports."""

import json
import multiprocessing
import os
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from harness.runner import (
    AVOIDABLE_DEATH,
    MAX_TURNS,
    SUCCESS,
    TIMEOUT,
    UNLUCKY_DEATH,
    Settings,
    policy_by_name,
    run_surgery,
)
from harness.surge import CONDITION_NAMES, MALADY_NAMES

OUTCOMES = (SUCCESS, AVOIDABLE_DEATH, UNLUCKY_DEATH, TIMEOUT)
SKILLS = (0, 25, 50, 75, 100)
GROUPS = ("skill", "condition", "malady")

Report = dict[str, Any]
Cell = tuple[str, str, int, str | None]


@dataclass(frozen=True)
class Grid:
    maladies: tuple[str, ...]
    conditions: tuple[str, ...]
    skills: tuple[int, ...]
    modifiers: tuple[str | None, ...]

    def cells(self) -> list[Cell]:
        return [
            (malady, condition, skill, modifier)
            for malady in self.maladies
            for condition in self.conditions
            for skill in self.skills
            for modifier in self.modifiers
        ]

    def as_dict(self) -> dict[str, list[Any]]:
        return {
            "maladies": list(self.maladies),
            "conditions": list(self.conditions),
            "skills": list(self.skills),
            "modifiers": list(self.modifiers),
        }


def full_grid() -> Grid:
    """27 maladies x 6 conditions x 5 skill levels, no modifier (docs/testing.md)."""
    return Grid(MALADY_NAMES, tuple(CONDITION_NAMES), SKILLS, (None,))


def run_cell(job: tuple[str, Cell, int]) -> Report:
    """Play `runs` seeded surgeries (seeds 0 to runs-1) of one grid cell."""
    policy_name, (malady, condition, skill, modifier), runs = job
    policy = policy_by_name(policy_name)
    outcomes = dict.fromkeys(OUTCOMES, 0)
    tools_on_success = turns = illegal_moves = skill_fails = 0
    deaths = []
    for seed in range(runs):
        last_rules: deque[str] = deque(maxlen=3)
        result = run_surgery(
            Settings(malady, condition, skill, modifier, seed),
            policy,
            policy_name,
            on_record=lambda record, rules=last_rules: rules.append(
                record["decision"]["rule"]
            ),
        )
        outcomes[result.outcome] += 1
        turns += result.turns
        illegal_moves += result.illegal_moves
        skill_fails += result.skill_fails
        if result.outcome == SUCCESS:
            tools_on_success += result.tools_used
        elif result.outcome != TIMEOUT:
            deaths.append(
                {
                    "seed": seed,
                    "outcome": result.outcome,
                    "turns": result.turns,
                    "last_rules": list(last_rules),
                }
            )
    return {
        "malady": malady,
        "condition": condition,
        "skill": skill,
        "modifier": modifier,
        "runs": runs,
        "outcomes": outcomes,
        "tools_on_success": tools_on_success,
        "turns": turns,
        "illegal_moves": illegal_moves,
        "skill_fails": skill_fails,
        "deaths": deaths,
    }


def _tally(cells: list[Report]) -> Report:
    runs = sum(c["runs"] for c in cells)
    outcomes = {o: sum(c["outcomes"][o] for c in cells) for o in OUTCOMES}
    tools = sum(c["tools_on_success"] for c in cells)
    return {
        "runs": runs,
        **outcomes,
        "success_rate": outcomes[SUCCESS] / runs if runs else 0.0,
        "avg_tools_per_success": tools / outcomes[SUCCESS]
        if outcomes[SUCCESS]
        else None,
        "illegal_moves": sum(c["illegal_moves"] for c in cells),
    }


def summarize(cells: list[Report]) -> Report:
    """Totals overall and per skill level, condition and malady."""
    summary: Report = {"overall": _tally(cells)}
    for group in GROUPS:
        keys = sorted({c[group] for c in cells}, key=lambda k: (str(type(k)), k))
        summary[group] = {
            str(key): _tally([c for c in cells if c[group] == key]) for key in keys
        }
    return summary


def run_grid(
    policy_name: str,
    runs: int,
    grid: Grid | None = None,
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Report:
    """Run every cell of the grid; `workers=1` runs in this process."""
    policy_by_name(policy_name)  # fail fast on an unknown or unfinished policy
    grid = grid or full_grid()
    cells = grid.cells()
    jobs = [(policy_name, cell, runs) for cell in cells]
    workers = max(1, min(workers or os.cpu_count() or 1, len(jobs)))

    started = time.perf_counter()
    done: list[Report] = []
    if workers == 1:
        for job in jobs:
            done.append(run_cell(job))
            if progress:
                progress(len(done), len(jobs))
    else:
        context = multiprocessing.get_context("spawn")
        with context.Pool(workers) as pool:
            for result in pool.imap_unordered(run_cell, jobs, chunksize=1):
                done.append(result)
                if progress:
                    progress(len(done), len(jobs))
    order = {cell: index for index, cell in enumerate(cells)}
    done.sort(
        key=lambda c: order[(c["malady"], c["condition"], c["skill"], c["modifier"])]
    )

    return {
        "meta": {
            "policy": policy_name,
            "runs": runs,
            "seeds": f"0 to {runs - 1}",
            "max_turns": MAX_TURNS,
            "grid": grid.as_dict(),
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "workers": workers,
            "elapsed_seconds": round(time.perf_counter() - started, 1),
        },
        "summary": summarize(done),
        "cells": done,
    }


# --- comparing and writing reports ----------------------------------------


def compare_reports(current: Report, saved: Report) -> Report:
    """Change in every summary number against a saved report (hard rule 6).

    Refuses reports made with other run counts, grids or turn caps, because their
    seeds don't line up.
    """
    for key in ("runs", "max_turns", "grid"):
        if current["meta"][key] != saved["meta"][key]:
            raise ValueError(
                f"cannot compare: {key} differs "
                f"({saved['meta'][key]!r} saved vs {current['meta'][key]!r} now)"
            )

    def delta(now: Report, then: Report) -> Report:
        out: Report = {"success_rate": now["success_rate"] - then["success_rate"]}
        for outcome in (AVOIDABLE_DEATH, UNLUCKY_DEATH, TIMEOUT):
            out[outcome] = now[outcome] - then[outcome]
        a, b = now["avg_tools_per_success"], then["avg_tools_per_success"]
        out["avg_tools_per_success"] = None if a is None or b is None else a - b
        return out

    comparison: Report = {
        "against": saved["meta"]["policy"],
        "overall": delta(current["summary"]["overall"], saved["summary"]["overall"]),
    }
    for group in GROUPS:
        comparison[group] = {
            key: delta(value, saved["summary"][group][key])
            for key, value in current["summary"][group].items()
            if key in saved["summary"][group]
        }
    return comparison


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _signed(value: float | None, scale: float = 1.0, unit: str = "") -> str:
    return "" if value is None else f"{value * scale:+.1f}{unit}"


def render_markdown(report: Report, comparison: Report | None = None) -> str:
    meta, summary = report["meta"], report["summary"]
    lines = [
        f"# Benchmark: {meta['policy']}",
        "",
        f"- Runs per cell: {meta['runs']} (seeds {meta['seeds']}), "
        f"turn cap {meta['max_turns']}",
        f"- Cells: {len(report['cells'])}, surgeries: {summary['overall']['runs']}",
        f"- Created {meta['created']}, {meta['elapsed_seconds']} s "
        f"on {meta['workers']} workers",
    ]
    if comparison:
        lines.append(
            f"- Change columns are against the saved `{comparison['against']}` report"
        )
    for title, group in (
        ("Overall", None),
        ("By skill level", "skill"),
        ("By special condition", "condition"),
        ("By malady", "malady"),
    ):
        rows = {"all": summary["overall"]} if group is None else summary[group]
        deltas = (
            None
            if comparison is None
            else (
                {"all": comparison["overall"]} if group is None else comparison[group]
            )
        )
        lines += ["", f"## {title}", ""]
        header = "| | Runs | Success | Avoidable | Unlucky | Timeout | Tools/success |"
        rule = "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"
        if deltas:
            header += " Success change | Avoidable change |"
            rule += " ---: | ---: |"
        lines += [header, rule]
        for key, row in rows.items():
            tools = row["avg_tools_per_success"]
            line = (
                f"| {key} | {row['runs']} | {_pct(row['success_rate'])} "
                f"| {row[AVOIDABLE_DEATH]} | {row[UNLUCKY_DEATH]} | {row[TIMEOUT]} "
                f"| {'' if tools is None else f'{tools:.1f}'} |"
            )
            if deltas and key in deltas:
                d = deltas[key]
                line += (
                    f" {_signed(d['success_rate'], 100, ' pts')} "
                    f"| {d[AVOIDABLE_DEATH]:+d} |"
                )
            lines.append(line)
    return "\n".join(lines) + "\n"


def write_report(
    report: Report, base: Path, comparison: Report | None = None
) -> tuple[Path, Path]:
    """Write `<base>.json` and `<base>.md`; returns both paths."""
    base.parent.mkdir(parents=True, exist_ok=True)
    json_path, md_path = base.with_suffix(".json"), base.with_suffix(".md")
    json_path.write_text(json.dumps(report), encoding="utf-8")
    md_path.write_text(render_markdown(report, comparison), encoding="utf-8")
    return json_path, md_path


def default_base(directory: Path = Path("reports")) -> Path:
    return directory / datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
