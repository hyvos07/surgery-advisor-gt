"""Side-by-side report of two benchmark reports, and the death analysis of one.

`surg report A.json B.json`: A is the policy being studied, B the reference.
Success rates come from both; the death analysis (which rules fired before
each death, where the mistake was, links to the viewer) is for A only.
"""

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from harness.bench import (
    Report,
    _check_comparable,
    _fmt,
    _pct,
    _tally,
    pair_tools,
)
from harness.runner import AVOIDABLE_DEATH, TIMEOUT, UNLUCKY_DEATH

VIEWER = "http://127.0.0.1:8000/"
# Unlike `--compare`, the lookback may differ: it never changes who succeeds.
COMPARABLE = ("runs", "max_turns", "seed_offset", "grid")
LAST_TURNS = 3  # how many turns of rules each death entry keeps


def _rule_order(rule: str) -> tuple[str, int]:
    """E2 before E10 before P1."""
    match = re.fullmatch(r"([A-Za-z]+)(\d+)", rule)
    return (match.group(1), int(match.group(2))) if match else (rule, 0)


def _top(counter: Counter[str]) -> tuple[str, int] | None:
    """Most common key and its count; ties go to the smaller name."""
    if not counter:
        return None
    key = min(counter, key=lambda k: (-counter[k], k))
    return key, counter[key]


def _ranked(counter: Counter[str]) -> list[str]:
    return sorted(counter, key=lambda k: (-counter[k], _rule_order(k), k))


def _modifier_name(modifier: str | None) -> str:
    return "none" if modifier is None else modifier


# --- side by side ----------------------------------------------------------


def _group_keys(cells: list[Report], group: str) -> list[Any]:
    keys = {c[group] for c in cells}
    if group == "modifier":  # keep the grid's order, with `none` first if present
        return sorted(keys, key=lambda k: (k is not None, str(k)))
    return sorted(keys, key=lambda k: (str(type(k)), k))


def _paired_rows(a: Report, b: Report) -> Report | None:
    """Paired tools per success by group, or None when the reports can't be paired.

    `pair_tools` groups by skill, condition and malady; the modifier groups come
    from pairing the cells of each modifier on its own.
    """
    try:
        paired = pair_tools(a, b)
        rows: Report = {
            "overall": {"all": paired["summary"]["overall"]},
            "skill": paired["summary"]["skill"],
            "condition": paired["summary"]["condition"],
            "malady": paired["summary"]["malady"],
            "modifier": {},
        }
        for modifier in {c["modifier"] for c in a["cells"]}:

            def keep(report: Report, modifier: str | None = modifier) -> Report:
                kept = [c for c in report["cells"] if c["modifier"] == modifier]
                return {**report, "cells": kept}

            sub = pair_tools(keep(a), keep(b))
            rows["modifier"][_modifier_name(modifier)] = sub["summary"]["overall"]
    except ValueError:
        return None
    return rows


def _side_row(a: Report, b: Report, paired: Report | None) -> Report:
    return {
        "runs": a["runs"],
        "a_success_rate": a["success_rate"],
        "b_success_rate": b["success_rate"],
        "difference_pts": (a["success_rate"] - b["success_rate"]) * 100,
        "a_avoidable": a[AVOIDABLE_DEATH],
        "a_unlucky": a[UNLUCKY_DEATH],
        "a_timeout": a[TIMEOUT],
        "b_avoidable": b[AVOIDABLE_DEATH],
        "pairs": None if paired is None else paired["pairs"],
        "a_tools_per_success": None if paired is None else paired["a_per_success"],
        "b_tools_per_success": None if paired is None else paired["b_per_success"],
    }


def side_by_side(a: Report, b: Report) -> Report:
    """Success and death counts of both policies, overall and by group.

    The `modifier` group is there only when the grid has more than one modifier.
    Refuses reports with different runs, seed offset, grid or turn cap.
    """
    _check_comparable(a, b, COMPARABLE)
    paired = _paired_rows(a, b)
    groups = ["skill", "condition", "malady"]
    if len(a["meta"]["grid"]["modifiers"]) > 1:
        groups.insert(1, "modifier")
    b_cells = {_cell_id(c): c for c in b["cells"]}
    if {_cell_id(c) for c in a["cells"]} != set(b_cells):
        raise ValueError("cannot compare: the reports do not hold the same cells")

    def rows_for(group: str | None) -> dict[str, Report]:
        if group is None:
            a_cells, keys = [a["cells"]], ["all"]
        else:
            ks = _group_keys(a["cells"], group)
            a_cells = [[c for c in a["cells"] if c[group] == k] for k in ks]
            keys = [_modifier_name(k) if group == "modifier" else str(k) for k in ks]
        out: dict[str, Report] = {}
        for key, cells in zip(keys, a_cells, strict=True):
            other = [b_cells[_cell_id(c)] for c in cells]
            pair = None
            if paired is not None:
                pair = paired["overall" if group is None else group].get(key)
            out[key] = _side_row(_tally(cells), _tally(other), pair)
        return out

    result: Report = {"overall": rows_for(None)}
    for group in groups:
        result[group] = rows_for(group)
    return result


def _cell_id(cell: Report) -> tuple[str, str, int, str | None]:
    return (cell["malady"], cell["condition"], cell["skill"], cell["modifier"])


# --- death analysis --------------------------------------------------------


def death_link(death: Report, policy: str) -> str:
    """Viewer URL that replays this death: its settings, seed and policy."""
    params = {
        "malady": death["malady"],
        "condition": death["condition"],
        "skill": death["skill"],
        "seed": death["seed"],
        "policy": policy,
    }
    if death["modifier"]:
        params["modifier"] = death["modifier"]
    return VIEWER + "?" + urlencode(params, quote_via=quote)


def _mistake_rule(death: Report) -> str | None:
    """The rule that fired `mistake_turns_back` turns before the end, if kept."""
    k, rules = death["mistake_turns_back"], death["last_rules"]
    if k is None or k >= len(rules):
        return None
    result: str = rules[-1 - k]
    return result


def death_analysis(a: Report, examples: int = 3) -> Report:
    """What the rules did before each of A's deaths (all of them, not a sample)."""
    policy = a["meta"]["policy"]
    deaths: list[Report] = []
    for cell in a["cells"]:
        for d in cell["deaths"]:
            death = {
                "malady": cell["malady"],
                "condition": cell["condition"],
                "skill": cell["skill"],
                "modifier": cell["modifier"],
                "seed": d["seed"],
                "outcome": d["outcome"],
                "turns": d["turns"],
                "last_rules": list(d["last_rules"]),
                "mistake_turns_back": d.get("mistake_turns_back"),
                "alternative": d.get("alternative"),
            }
            death["mistake_rule"] = _mistake_rule(death)
            death["link"] = death_link(death, policy)
            deaths.append(death)
    avoidable = [d for d in deaths if d["outcome"] == AVOIDABLE_DEATH]

    # Rules in the last turns of every death.
    in_deaths: Counter[str] = Counter()
    in_avoidable: Counter[str] = Counter()
    in_unlucky: Counter[str] = Counter()
    appearances: Counter[str] = Counter()
    for d in deaths:
        appearances.update(d["last_rules"])
        for rule in set(d["last_rules"]):
            in_deaths[rule] += 1
            (in_avoidable if d["outcome"] == AVOIDABLE_DEATH else in_unlucky)[rule] += 1
    rules_last = [
        {
            "rule": rule,
            "deaths": in_deaths[rule],
            "avoidable": in_avoidable[rule],
            "unlucky": in_unlucky[rule],
            "share_of_deaths": in_deaths[rule] / len(deaths),
            "appearances": appearances[rule],
        }
        for rule in _ranked(in_deaths)
    ]

    # The rule at the turn where a different tool would have won.
    at_mistake: dict[str, list[Report]] = {}
    outside = 0
    for d in avoidable:
        if d["mistake_turns_back"] is None:
            continue
        if d["mistake_rule"] is None:
            outside += 1
        else:
            at_mistake.setdefault(d["mistake_rule"], []).append(d)
    counts = Counter({rule: len(group) for rule, group in at_mistake.items()})
    mistake_rules = []
    for rule in _ranked(counts):
        group = at_mistake[rule]
        better = Counter(str(d["alternative"]) for d in group if d["alternative"])
        top = _top(better)
        mistake_rules.append(
            {
                "rule": rule,
                "avoidable": len(group),
                "top_better_tool": top[0] if top else None,
                "top_better_tool_count": top[1] if top else 0,
                "mean_turns_back": sum(d["mistake_turns_back"] for d in group)
                / len(group),
            }
        )

    depth: Counter[int] = Counter(
        d["mistake_turns_back"]
        for d in avoidable
        if d["mistake_turns_back"] is not None
    )
    mistake_depth = [
        {"turns_back": k, "avoidable": depth[k]}
        for k in range(max(depth, default=-1) + 1)
    ]
    illegal = sum(1 for d in avoidable if d["mistake_turns_back"] is None)
    better_tools = Counter(str(d["alternative"]) for d in avoidable if d["alternative"])

    maladies = []
    for malady in sorted({d["malady"] for d in deaths}):
        mine = [d for d in deaths if d["malady"] == malady]
        mine_avoidable = [d for d in mine if d["outcome"] == AVOIDABLE_DEATH]
        rule_top = _top(
            Counter(d["mistake_rule"] for d in mine_avoidable if d["mistake_rule"])
        )
        tool_top = _top(
            Counter(str(d["alternative"]) for d in mine_avoidable if d["alternative"])
        )
        maladies.append(
            {
                "malady": malady,
                "deaths": len(mine),
                "avoidable": len(mine_avoidable),
                "top_mistake_rule": rule_top[0] if rule_top else None,
                "top_mistake_rule_count": rule_top[1] if rule_top else 0,
                "top_better_tool": tool_top[0] if tool_top else None,
                "top_better_tool_count": tool_top[1] if tool_top else 0,
            }
        )
    maladies.sort(key=lambda m: (-m["avoidable"], -m["deaths"], m["malady"]))

    shown: list[Report] = []
    for m in maladies:
        shown += [d for d in avoidable if d["malady"] == m["malady"]][:examples]

    return {
        "policy": policy,
        "lookback": a["meta"].get("lookback", 1),
        "deaths_total": len(deaths),
        "avoidable_total": len(avoidable),
        "unlucky_total": len(deaths) - len(avoidable),
        "rules_last_turns": rules_last,
        "mistake_rules": mistake_rules,
        "mistake_outside_last_rules": outside,
        "mistake_depth": mistake_depth,
        "illegal_move_deaths": illegal,
        "better_tools": [
            {"tool": t, "avoidable": better_tools[t]} for t in _ranked(better_tools)
        ],
        "maladies": maladies,
        "examples": shown,
        "deaths": deaths,
        "avoidable_deaths": avoidable,
    }


# --- the report ------------------------------------------------------------


def build_report(a: Report, b: Report, examples: int = 3) -> Report:
    """Everything `surg report` writes: side by side, then A's death analysis."""
    sides = side_by_side(a, b)
    meta = a["meta"]
    return {
        "meta": {
            "a": meta["policy"],
            "b": b["meta"]["policy"],
            "runs": meta["runs"],
            "seed_offset": meta.get("seed_offset", 0),
            "max_turns": meta["max_turns"],
            "grid": meta["grid"],
            "cells": len(a["cells"]),
            "a_lookback": meta.get("lookback", 1),
            "b_lookback": b["meta"].get("lookback", 1),
            "examples_per_malady": examples,
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "side_by_side": sides,
        "analysis": death_analysis(a, examples),
    }


SIDE_TITLES = (
    ("overall", "Overall"),
    ("skill", "By skill level"),
    ("modifier", "By modifier"),
    ("condition", "By special condition"),
    ("malady", "By malady"),
)


def _count(value: tuple[str, int] | None) -> str:
    return "" if value is None else f"{value[0]} ({value[1]})"


def render_report_markdown(report: Report) -> str:
    meta, sides, an = report["meta"], report["side_by_side"], report["analysis"]
    a, b, lookback = meta["a"], meta["b"], meta["a_lookback"]
    lines = [
        f"# Report: {a} vs {b}",
        "",
        f"- {a} is the policy studied and {b} the reference. Runs per cell: "
        f"{meta['runs']}, cells: {meta['cells']}, turn cap {meta['max_turns']}",
        f"- Death lookback: {lookback} for {a}, {meta['b_lookback']} for {b}",
        f"- Avoidable under lookback {lookback}: some other usable tool, up to "
        f"{lookback} turn{'s' if lookback != 1 else ''} back, would have let the same "
        "policy's later play win, or the policy made an illegal move (see "
        "docs/testing.md). Any other death is unlucky.",
        f"- Deaths of {a}: {an['deaths_total']} ({an['avoidable_total']} avoidable, "
        f"{an['unlucky_total']} unlucky)",
    ]

    header = (
        f"| | {a} success | {b} success | Difference (pts) | {a} avoidable "
        f"| {a} unlucky | {a} timeout | {b} avoidable "
        f"| Tools/success on paired wins {a} | {b} |"
    )
    rule = "| --- |" + " ---: |" * 9
    for key, title in SIDE_TITLES:
        if key not in sides:
            continue
        lines += ["", f"## {title}", "", header, rule]
        for name, r in sides[key].items():
            lines.append(
                f"| {name} | {_pct(r['a_success_rate'])} | {_pct(r['b_success_rate'])} "
                f"| {r['difference_pts']:+.1f} | {r['a_avoidable']} | {r['a_unlucky']} "
                f"| {r['a_timeout']} | {r['b_avoidable']} "
                f"| {_fmt(r['a_tools_per_success'], '.1f')} "
                f"| {_fmt(r['b_tools_per_success'], '.1f')} |"
            )

    lines += [
        "",
        f"## Deaths: rules in the last {LAST_TURNS} turns",
        "",
        f"Every death of {a}, ranked by how many deaths have the rule among the "
        f"rules that fired in their last {LAST_TURNS} turns. A rule can appear "
        "more than once in one death, so Appearances can exceed Deaths with it.",
        "",
        "| Rule | Deaths with it | Avoidable | Unlucky | Share of all deaths "
        "| Appearances |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in an["rules_last_turns"]:
        lines.append(
            f"| {r['rule']} | {r['deaths']} | {r['avoidable']} | {r['unlucky']} "
            f"| {_pct(r['share_of_deaths'])} | {r['appearances']} |"
        )

    lines += [
        "",
        "## Rule at the mistake turn",
        "",
        "Avoidable deaths with a known mistake turn: the rule that fired that many "
        "turns before the end, the tool that would have won, and how far back it was.",
        "",
        "| Rule | Avoidable deaths | Most common better tool (count) "
        "| Mean turns back |",
        "| --- | ---: | --- | ---: |",
    ]
    for r in an["mistake_rules"]:
        top = (
            ""
            if r["top_better_tool"] is None
            else f"{r['top_better_tool']} ({r['top_better_tool_count']})"
        )
        lines.append(
            f"| {r['rule']} | {r['avoidable']} | {top} | {r['mean_turns_back']:.2f} |"
        )
    if an["mistake_outside_last_rules"]:
        lines += [
            "",
            f"{an['mistake_outside_last_rules']} more avoidable deaths had their "
            f"mistake further back than the last {LAST_TURNS} turns kept per death.",
        ]

    lines += [
        "",
        "## Mistake depth",
        "",
        "Turns before the fatal turn at which a different tool would have won "
        "(0 is the fatal turn itself).",
        "",
        "| Turns back | Avoidable deaths |",
        "| --- | ---: |",
    ]
    for r in an["mistake_depth"]:
        lines.append(f"| {r['turns_back']} | {r['avoidable']} |")
    lines.append(f"| illegal move | {an['illegal_move_deaths']} |")

    lines += [
        "",
        "## Better tools",
        "",
        "The first usable tool that would have won, over all avoidable deaths.",
        "",
        "| Tool | Avoidable deaths |",
        "| --- | ---: |",
    ]
    for r in an["better_tools"]:
        lines.append(f"| {r['tool']} | {r['avoidable']} |")

    lines += [
        "",
        "## By malady",
        "",
        "| Malady | Deaths | Avoidable | Top mistake rule | Top better tool |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for m in an["maladies"]:
        rule_top = (
            None
            if m["top_mistake_rule"] is None
            else (m["top_mistake_rule"], m["top_mistake_rule_count"])
        )
        tool_top = (
            None
            if m["top_better_tool"] is None
            else (m["top_better_tool"], m["top_better_tool_count"])
        )
        lines.append(
            f"| {m['malady']} | {m['deaths']} | {m['avoidable']} "
            f"| {_count(rule_top)} | {_count(tool_top)} |"
        )

    lines += [
        "",
        "## Examples with viewer links",
        "",
        f"Up to {meta['examples_per_malady']} avoidable deaths per malady. The links "
        "need `uv run surg web`. The JSON holds every avoidable death with its link.",
        "",
    ]
    for d in an["examples"]:
        back = (
            "illegal move"
            if d["mistake_turns_back"] is None
            else f"{d['mistake_turns_back']} turns back"
        )
        lines.append(
            f"- **{d['malady']}**, {d['condition']}, skill {d['skill']}, "
            f"modifier {_modifier_name(d['modifier'])}, seed {d['seed']}: {back}, "
            f"better tool {d['alternative'] or '-'}, rules "
            f"{' > '.join(d['last_rules'])} ([view]({d['link']}))"
        )
    return "\n".join(lines) + "\n"


def write_comparison_report(report: Report, base: Path) -> tuple[Path, Path]:
    """Write `<base>.json` and `<base>.md`; returns both paths."""
    base.parent.mkdir(parents=True, exist_ok=True)
    json_path, md_path = base.with_suffix(".json"), base.with_suffix(".md")
    json_path.write_text(json.dumps(report), encoding="utf-8")
    md_path.write_text(render_report_markdown(report), encoding="utf-8")
    return json_path, md_path


def default_report_base(report: Report) -> Path:
    meta = report["meta"]
    return Path("reports") / f"report-{meta['a']}-vs-{meta['b']}"
