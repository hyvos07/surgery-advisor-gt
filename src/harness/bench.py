"""Benchmark grid and reports."""

import json
import multiprocessing
import os
import time
from collections import Counter, deque
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
from harness.surge import CONDITION_NAMES, MALADY_NAMES, MODIFIER_NAMES, TOOL_IDS

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


def parse_skills(text: str) -> tuple[int, ...]:
    """Skill levels from a comma list such as `0,25,100`."""
    skills: list[int] = []
    for part in text.split(","):
        try:
            skill = int(part.strip())
        except ValueError:
            raise ValueError(
                f"--skills must be a comma list of whole numbers, got {part.strip()!r}"
            ) from None
        if not 0 <= skill <= 100:
            raise ValueError(f"--skills values must be 0 to 100, got {skill}")
        if skill in skills:
            raise ValueError(f"--skills lists {skill} twice")
        skills.append(skill)
    return tuple(skills)


def parse_modifiers(text: str) -> tuple[str | None, ...]:
    """Modifier ids from a comma list; `none` means no modifier."""
    modifiers: list[str | None] = []
    for part in text.split(","):
        name = part.strip().lower()
        if name != "none" and name not in MODIFIER_NAMES:
            raise ValueError(
                f"unknown modifier {part.strip()!r} in --modifiers; "
                f"choose from none, {', '.join(MODIFIER_NAMES)}"
            )
        value = None if name == "none" else name
        if value in modifiers:
            raise ValueError(f"--modifiers lists {name} twice")
        modifiers.append(value)
    return tuple(modifiers)


def grid_from_options(
    skills: str = ",".join(map(str, SKILLS)), modifiers: str = "none"
) -> Grid:
    """The full malady and condition grid with the chosen skills and modifiers."""
    return Grid(
        MALADY_NAMES,
        tuple(CONDITION_NAMES),
        parse_skills(skills),
        parse_modifiers(modifiers),
    )


def run_cell(
    job: tuple[str, Cell, int]
    | tuple[str, Cell, int, int]
    | tuple[str, Cell, int, int, int],
) -> Report:
    """Play `runs` seeded surgeries (seeds offset to offset+runs-1) of one grid cell.

    The job is (policy, cell, runs), then optionally the death lookback (default 1)
    and the seed offset (default 0).
    """
    policy_name, (malady, condition, skill, modifier), runs, *rest = job
    lookback = rest[0] if rest else 1
    seed_offset = rest[1] if len(rest) > 1 else 0
    outcomes = dict.fromkeys(OUTCOMES, 0)
    tools_on_success = turns = illegal_moves = skill_fails = 0
    fewest: int | None = None
    tools_success: Counter[str] = Counter()
    tools_all: Counter[str] = Counter()
    deaths = []
    # One entry per seed, for pairing. Indexed by position, not by seed: entry i is
    # seed `seed_offset + i`. Reports are only paired when their offsets match.
    seed_tools: list[list[int] | None] = []
    for seed in range(seed_offset, seed_offset + runs):
        last_rules: deque[str] = deque(maxlen=3)
        result = run_surgery(
            Settings(malady, condition, skill, modifier, seed),
            policy_by_name(policy_name),  # fresh per surgery: the advisor has memory
            policy_name,
            lookback=lookback,
            on_record=lambda record, rules=last_rules: rules.append(
                record["decision"]["rule"]
            ),
        )
        outcomes[result.outcome] += 1
        turns += result.turns
        illegal_moves += result.illegal_moves
        skill_fails += result.skill_fails
        tools_all.update(result.tool_counts)
        if result.outcome == SUCCESS:
            tools_on_success += result.tools_used
            tools_success.update(result.tool_counts)
            fewest = (
                result.tools_used if fewest is None else min(fewest, result.tools_used)
            )
            seed_tools.append([result.tool_counts.get(t, 0) for t in TOOL_IDS])
            continue
        seed_tools.append(None)
        if result.outcome != TIMEOUT:
            deaths.append(
                {
                    "seed": seed,
                    "outcome": result.outcome,
                    "turns": result.turns,
                    "last_rules": list(last_rules),
                    "mistake_turns_back": result.mistake_turns_back,
                    "alternative": result.alternative,
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
        "min_tools_on_success": fewest,
        "tool_counts_success": dict(tools_success),
        "tool_counts_all": dict(tools_all),
        "seed_tools": seed_tools,
        "turns": turns,
        "illegal_moves": illegal_moves,
        "skill_fails": skill_fails,
        "deaths": deaths,
    }


def _tally(cells: list[Report]) -> Report:
    runs = sum(c["runs"] for c in cells)
    outcomes = {o: sum(c["outcomes"][o] for c in cells) for o in OUTCOMES}
    tools = sum(c["tools_on_success"] for c in cells)
    fewest = [c["min_tools_on_success"] for c in cells if c["min_tools_on_success"]]
    by_tool_success: Counter[str] = Counter()
    by_tool_all: Counter[str] = Counter()
    for c in cells:
        by_tool_success.update(c["tool_counts_success"])
        by_tool_all.update(c["tool_counts_all"])
    return {
        "runs": runs,
        **outcomes,
        "success_rate": outcomes[SUCCESS] / runs if runs else 0.0,
        "avg_tools_per_success": tools / outcomes[SUCCESS]
        if outcomes[SUCCESS]
        else None,
        "min_tools_on_success": min(fewest) if fewest else None,
        "tool_counts_success": dict(by_tool_success),
        "tool_counts_all": dict(by_tool_all),
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
    lookback: int = 1,
    seed_offset: int = 0,
) -> Report:
    """Run every cell of the grid; `workers=1` runs in this process.

    Each cell plays seeds `seed_offset` to `seed_offset + runs - 1` (D19).
    """
    policy_by_name(policy_name)  # fail fast on an unknown policy
    if lookback < 1:
        raise ValueError(f"--lookback must be at least 1, got {lookback}")
    if seed_offset < 0:
        raise ValueError(f"--seed-offset must be at least 0, got {seed_offset}")
    grid = grid or full_grid()
    cells = grid.cells()
    jobs = [(policy_name, cell, runs, lookback, seed_offset) for cell in cells]
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
            "seed_offset": seed_offset,
            "seeds": f"{seed_offset} to {seed_offset + runs - 1}",
            "max_turns": MAX_TURNS,
            "lookback": lookback,
            "grid": grid.as_dict(),
            "tool_order": list(TOOL_IDS),
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "workers": workers,
            "elapsed_seconds": round(time.perf_counter() - started, 1),
        },
        "summary": summarize(done),
        "cells": done,
    }


# --- comparing and writing reports ----------------------------------------


def _check_comparable(
    current: Report,
    saved: Report,
    keys: tuple[str, ...] = ("runs", "max_turns", "lookback", "seed_offset", "grid"),
) -> None:
    """Refuse reports made with other run counts, grids, turn caps, lookbacks or seeds.

    Reports saved before `--lookback` existed have no such key; they used 1.
    Reports saved before `--seed-offset` existed have none either; they used 0.
    `keys` narrows what must match (`surg report` leaves the lookback out).
    """
    missing = {"lookback": 1, "seed_offset": 0}
    for key in keys:
        now = current["meta"].get(key, missing.get(key))
        then = saved["meta"].get(key, missing.get(key))
        if now != then:
            raise ValueError(
                f"cannot compare: {key} differs ({then!r} saved vs {now!r} now)"
            )


def compare_reports(current: Report, saved: Report) -> Report:
    """Change in every summary number against a saved report (hard rule 6).

    Refuses reports made with other run counts, grids, turn caps, lookbacks or
    seed offsets, because their seeds or death classes don't line up.
    """
    _check_comparable(current, saved)

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
        f"turn cap {meta['max_turns']}, death lookback {meta.get('lookback', 1)}",
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
        header = (
            "| | Runs | Success | Avoidable | Unlucky | Timeout "
            "| Tools/success | Fewest |"
        )
        rule = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
        if deltas:
            header += " Success change | Avoidable change | Tools change |"
            rule += " ---: | ---: | ---: |"
        lines += [header, rule]
        for key, row in rows.items():
            tools = row["avg_tools_per_success"]
            line = (
                f"| {key} | {row['runs']} | {_pct(row['success_rate'])} "
                f"| {row[AVOIDABLE_DEATH]} | {row[UNLUCKY_DEATH]} | {row[TIMEOUT]} "
                f"| {'' if tools is None else f'{tools:.1f}'} "
                f"| {row['min_tools_on_success'] or ''} |"
            )
            if deltas and key in deltas:
                d = deltas[key]
                line += (
                    f" {_signed(d['success_rate'], 100, ' pts')} "
                    f"| {d[AVOIDABLE_DEATH]:+d} "
                    f"| {_signed(d['avg_tools_per_success'])} |"
                )
            lines.append(line)
    lines += _tools_section(summary["overall"])
    return "\n".join(lines) + "\n"


def _tools_section(overall: Report) -> list[str]:
    """Which tools the surgeries used. Fewer per success is better."""
    wins = overall[SUCCESS]
    lines = [
        "",
        "## Tools used",
        "",
        "Per successful surgery, and in total across every surgery (the gap is "
        "tools spent on surgeries that did not succeed).",
        "",
        "| Tool | Per success | Total, all surgeries |",
        "| --- | ---: | ---: |",
    ]
    by_success, by_all = overall["tool_counts_success"], overall["tool_counts_all"]
    for tool in sorted(by_all, key=lambda t: -by_all[t]):
        per = by_success.get(tool, 0) / wins if wins else 0.0
        lines.append(f"| {tool} | {per:.2f} | {by_all[tool]} |")
    return lines


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


# --- pairing tools between two policies -----------------------------------
#
# Tools per success are only fair to compare on the same surgery. A "pair" is
# one seed of one cell that both reports won; `seed_tools` holds the per-tool
# counts of each win, so the two can be lined up.


def _min_or(a: int | None, b: int | None) -> int | None:
    return b if a is None else a if b is None else min(a, b)


def _new_pairs() -> Report:
    return {
        "pairs": 0,
        "runs": 0,
        "a_wins": 0,
        "b_wins": 0,
        "a_tools": 0,
        "b_tools": 0,
        "a_by_tool": Counter(),
        "b_by_tool": Counter(),
        "fewest": None,
        "a_fewest": None,
        "b_fewest": None,
    }


def _add_pairs(total: Report, part: Report) -> None:
    """Fold one tally into another (both are `_new_pairs` shapes)."""
    for key in ("pairs", "runs", "a_wins", "b_wins", "a_tools", "b_tools"):
        total[key] += part[key]
    total["a_by_tool"].update(part["a_by_tool"])
    total["b_by_tool"].update(part["b_by_tool"])
    for key in ("fewest", "a_fewest", "b_fewest"):
        total[key] = _min_or(total[key], part[key])


def _pair_cell(
    runs: int,
    a_seeds: list[list[int] | None],
    b_seeds: list[list[int] | None],
    tools: list[str],
) -> Report:
    """One cell's tally. Entry i of each list is seed i: tool counts, or None."""
    out = _new_pairs()
    out["runs"] = runs
    for a_counts, b_counts in zip(a_seeds, b_seeds, strict=True):
        if a_counts is not None:
            out["a_wins"] += 1
            out["a_fewest"] = _min_or(out["a_fewest"], sum(a_counts))
        if b_counts is not None:
            out["b_wins"] += 1
            out["b_fewest"] = _min_or(out["b_fewest"], sum(b_counts))
        if a_counts is None or b_counts is None:
            continue
        out["pairs"] += 1
        out["a_tools"] += sum(a_counts)
        out["b_tools"] += sum(b_counts)
        out["a_by_tool"].update(dict(zip(tools, a_counts, strict=True)))
        out["b_by_tool"].update(dict(zip(tools, b_counts, strict=True)))
    out["fewest"] = _min_or(out["a_fewest"], out["b_fewest"])
    return out


def _finish_pairs(acc: Report, tools: list[str]) -> Report:
    """Plain dicts and the derived per-success numbers."""
    used = [t for t in tools if acc["a_by_tool"][t] or acc["b_by_tool"][t]]
    pairs = acc["pairs"]
    a_per = acc["a_tools"] / pairs if pairs else None
    b_per = acc["b_tools"] / pairs if pairs else None
    return {
        **{k: v for k, v in acc.items() if k not in ("a_by_tool", "b_by_tool")},
        "a_by_tool": {t: acc["a_by_tool"][t] for t in used},
        "b_by_tool": {t: acc["b_by_tool"][t] for t in used},
        "a_per_success": a_per,
        "b_per_success": b_per,
        "difference": None if a_per is None or b_per is None else a_per - b_per,
    }


def _cell_key(cell: Report) -> Cell:
    return (cell["malady"], cell["condition"], cell["skill"], cell["modifier"])


def pair_tools(a: Report, b: Report) -> Report:
    """Tools per success on the surgeries both reports won (same cell and seed).

    The reports must come from the same `--runs`, seed offset, grid and turn cap,
    and from a version of `surg bench` that records `seed_tools`. Fewer tools is
    better, so a positive difference means `a` used more. The death lookback may
    differ: it changes how deaths are classified, not who wins or which tools
    they use.
    """
    _check_comparable(a, b, ("runs", "max_turns", "seed_offset", "grid"))
    for report in (a, b):
        if "tool_order" not in report["meta"] or any(
            "seed_tools" not in c for c in report["cells"]
        ):
            raise ValueError(
                f"cannot pair tools: the {report['meta']['policy']} report has no "
                "per-seed tool counts; re-run `surg bench` with this version"
            )
    tools: list[str] = list(a["meta"]["tool_order"])
    if tools != list(b["meta"]["tool_order"]):
        raise ValueError(
            "cannot pair tools: the reports list tools in a different order; "
            "re-run `surg bench` with this version"
        )
    b_cells = {_cell_key(c): c for c in b["cells"]}

    overall = _new_pairs()
    groups: dict[str, dict[Any, Report]] = {g: {} for g in GROUPS}
    cells: list[Report] = []
    for cell in a["cells"]:
        other = b_cells.get(_cell_key(cell))
        if other is None:
            raise ValueError(
                f"cannot pair tools: {_cell_key(cell)!r} is missing from the "
                f"{b['meta']['policy']} report"
            )
        tally = _pair_cell(cell["runs"], cell["seed_tools"], other["seed_tools"], tools)
        _add_pairs(overall, tally)
        for group in GROUPS:
            _add_pairs(groups[group].setdefault(cell[group], _new_pairs()), tally)
        done = _finish_pairs(tally, tools)
        cells.append(
            {
                "malady": cell["malady"],
                "condition": cell["condition"],
                "skill": cell["skill"],
                "modifier": cell["modifier"],
                "pairs": done["pairs"],
                "a_per_success": done["a_per_success"],
                "b_per_success": done["b_per_success"],
                "fewest": done["fewest"],
                "a_fewest": done["a_fewest"],
                "b_fewest": done["b_fewest"],
            }
        )

    summary: Report = {"overall": _finish_pairs(overall, tools)}
    for group in GROUPS:
        keys = sorted(groups[group], key=lambda k: (str(type(k)), k))
        summary[group] = {
            str(key): _finish_pairs(groups[group][key], tools) for key in keys
        }
    return {
        "meta": {
            "a": a["meta"]["policy"],
            "b": b["meta"]["policy"],
            "runs": a["meta"]["runs"],
            "seed_offset": a["meta"].get("seed_offset", 0),
            "grid": a["meta"]["grid"],
            "max_turns": a["meta"]["max_turns"],
            "tool_order": tools,
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "summary": summary,
        "cells": cells,
    }


def _fmt(value: float | None, spec: str = "") -> str:
    """A number in the given format, or blank when there is none."""
    return "" if value is None else format(value, spec)


def _tool_differences(row: Report, tools: list[str]) -> dict[str, float]:
    """Per-success difference in each tool (a minus b) over a group's pairs."""
    pairs = row["pairs"]
    if not pairs:
        return {}
    return {
        t: (row["a_by_tool"].get(t, 0) - row["b_by_tool"].get(t, 0)) / pairs
        for t in tools
    }


def render_tools_markdown(paired: Report) -> str:
    meta, summary = paired["meta"], paired["summary"]
    a, b, tools = meta["a"], meta["b"], meta["tool_order"]
    lines = [
        f"# Tools: {a} vs {b}",
        "",
        f"- Runs per cell: {meta['runs']}",
        f"- Cells: {len(paired['cells'])}",
        "- Only surgeries that both policies won are compared (same cell and seed). "
        "Fewer tools is better.",
        f"- Difference is {a} minus {b} per success: +1.2 means {a} uses more tools.",
    ]
    header = (
        f"| | Pairs | Both won | {a} wins | {b} wins | {a} tools/success "
        f"| {b} tools/success | Difference | Fewest (either) | {a} fewest "
        f"| {b} fewest |"
    )
    rule = "| --- |" + " ---: |" * 10
    for title, group in (
        ("Overall", None),
        ("By skill level", "skill"),
        ("By special condition", "condition"),
        ("By malady", "malady"),
    ):
        rows = {"all": summary["overall"]} if group is None else summary[group]
        lines += ["", f"## {title}", "", header, rule]
        for key, r in rows.items():
            both = _pct(r["pairs"] / r["runs"]) if r["runs"] else ""
            lines.append(
                f"| {key} | {r['pairs']} | {both} | {r['a_wins']} | {r['b_wins']} "
                f"| {_fmt(r['a_per_success'], '.1f')} "
                f"| {_fmt(r['b_per_success'], '.1f')} "
                f"| {_signed(r['difference'])} "
                f"| {_fmt(r['fewest'])} | {_fmt(r['a_fewest'])} "
                f"| {_fmt(r['b_fewest'])} |"
            )

    overall = summary["overall"]
    diffs = _tool_differences(overall, tools)
    lines += [
        "",
        "## Where the difference comes from",
        "",
        "Tools per success over the pairs, largest difference first.",
        "",
        f"| Tool | {a} per success | {b} per success | Difference |",
        "| --- | ---: | ---: | ---: |",
    ]
    pairs = overall["pairs"]
    for tool in sorted(diffs, key=lambda t: -abs(diffs[t])):
        lines.append(
            f"| {tool} | {overall['a_by_tool'].get(tool, 0) / pairs:.2f} "
            f"| {overall['b_by_tool'].get(tool, 0) / pairs:.2f} "
            f"| {diffs[tool]:+.2f} |"
        )

    lines += [
        "",
        "## Biggest differences by malady",
        "",
        "| Malady | Difference | Top 3 tools by difference |",
        "| --- | ---: | --- |",
    ]
    maladies = summary["malady"]
    # Largest first; maladies with no pairs have no difference and go last.
    ranked = sorted(
        maladies,
        key=lambda m: (
            maladies[m]["difference"] is None,
            -(maladies[m]["difference"] or 0.0),
        ),
    )
    for malady in ranked:
        row = maladies[malady]
        by_tool = _tool_differences(row, tools)
        top = sorted(by_tool, key=lambda t: -abs(by_tool[t]))[:3]
        shown = ", ".join(f"{t} {by_tool[t]:+.2f}" for t in top if by_tool[t])
        lines.append(f"| {malady} | {_signed(row['difference'])} | {shown} |")
    return "\n".join(lines) + "\n"


def write_tools_report(paired: Report, base: Path) -> tuple[Path, Path]:
    """Write `<base>.json` and `<base>.md` for a paired comparison."""
    base.parent.mkdir(parents=True, exist_ok=True)
    json_path, md_path = base.with_suffix(".json"), base.with_suffix(".md")
    json_path.write_text(json.dumps(paired), encoding="utf-8")
    md_path.write_text(render_tools_markdown(paired), encoding="utf-8")
    return json_path, md_path
