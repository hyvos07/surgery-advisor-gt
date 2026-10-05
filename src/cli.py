"""The `surg` command: next, play, bench and web."""

import argparse
import json
import sys
from pathlib import Path

POLICY_CHOICES = ["advisor", "advisor-min-antiseptic", "baseline", "train-e-plus"]


def _next(args: argparse.Namespace) -> int:
    # Only the advisor is needed here, so SurgE is never loaded.
    from advisor import knowledge
    from advisor.config import Config
    from advisor.engine import decide
    from advisor.memory import Memory
    from advisor.state import ScreenState

    try:
        text = Path(args.state).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        print(f"surg next: cannot read {args.state}: {error}", file=sys.stderr)
        return 1
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as error:
        print(f"surg next: {args.state} is not valid JSON: {error}", file=sys.stderr)
        return 1
    try:
        state = ScreenState.from_dict(raw)
        config = Config.for_patient(
            state.skill_level, state.modifier.value if state.modifier else None
        )
    except ValueError as error:
        print(f"surg next: invalid screen state: {error}", file=sys.stderr)
        return 1

    # One state has no history, so memory starts empty.
    decision = decide(state, Memory.new(knowledge.load()), config)
    print(json.dumps(decision.to_dict(), indent=2))
    return 0


def _bench(args: argparse.Namespace) -> int:
    # Imported here so `surg --help` and `surg next` don't load SurgE.
    from harness import bench

    try:
        grid = bench.grid_from_options(args.skills, args.modifiers)
    except ValueError as error:
        print(f"surg bench: {error}", file=sys.stderr)
        return 1
    saved = None
    if args.compare:
        saved = json.loads(Path(args.compare).read_text(encoding="utf-8"))

    def progress(done: int, total: int) -> None:
        if done == total or done % max(1, total // 20) == 0:
            print(f"  {done}/{total} cells", file=sys.stderr, flush=True)

    try:
        report = bench.run_grid(
            args.policy, args.runs, grid, workers=args.workers, progress=progress
        )
        comparison = bench.compare_reports(report, saved) if saved else None
    except ValueError as error:
        print(f"surg bench: {error}", file=sys.stderr)
        return 1

    base = Path(args.out) if args.out else bench.default_base()
    json_path, md_path = bench.write_report(report, base, comparison)
    print(bench.render_markdown(report, comparison))
    print(f"Wrote {json_path} and {md_path}")
    return 0


def _dash(value: object) -> str:
    return "-" if value is None else str(value)


def _screen(state: dict[str, object]) -> str:
    """The patient screen as a few plain lines."""
    bones = state["bones"]
    bone_text = (
        "unknown"
        if bones is None
        else f"{bones['broken']} broken, {bones['shattered']} shattered"  # type: ignore[index]
    )
    return "\n".join(
        [
            f"  Pulse {state['pulse']} | Status {state['status']} | "
            f"Temp {state['temperature']} | Site {state['site']} | "
            f"Visibility {state['visibility']}",
            f"  Incisions {state['incisions']} | Bones {bone_text} | "
            f"Bleeding {_dash(state['bleeding'])} | Fever {_dash(state['fever'])}",
            f"  Scan: {_dash(state['scan_text'])}",
            f"  Condition: {_dash(state['special_condition_text'])}",
            f"  Last tool: {state['last_tool_text']}",
            f"  Usable: {', '.join(state['usable_tools'])}",  # type: ignore[arg-type]
        ]
    )


def _play(args: argparse.Namespace) -> int:
    from harness.runner import Surgery, policy_by_name, resolve_settings

    try:
        settings = resolve_settings(
            args.malady, args.condition, args.skill, args.modifier, args.seed
        )
        surgery = Surgery(settings, policy_by_name(args.policy), args.policy)
    except ValueError as error:
        print(f"surg play: {error}", file=sys.stderr)
        return 1

    print(
        f"{settings.malady} | {settings.condition} | skill {settings.skill} | "
        f"modifier {_dash(settings.modifier)} | seed {settings.seed} | "
        f"policy {args.policy}"
    )
    log = open(args.log, "w", encoding="utf-8") if args.log else None  # noqa: SIM115
    try:
        while not surgery.ended:
            decision = surgery.decision or {}
            print(f"\nTurn {surgery.turn}\n{_screen(surgery.state)}")
            print(f"  -> {decision['tool']}  [{decision['rule']}] {decision['reason']}")
            record = surgery.step()
            if log:
                log.write(json.dumps(record) + "\n")
    finally:
        if log:
            log.close()

    result = surgery.result()
    print(f"\n{record['tool_text']}")
    print(
        f"Result: {result.outcome} | {result.end_text or 'turn cap reached'} | "
        f"{result.turns} turns, {result.skill_fails} skill fails, "
        f"{result.illegal_moves} illegal moves"
    )
    return 0


def _web(args: argparse.Namespace) -> int:
    import uvicorn

    from web.app import app

    # Local only: SurgE is AGPL-3.0, and hosting the viewer publicly would mean
    # publishing source (AGENTS.md hard rule 9). There is deliberately no --host.
    print(f"Viewer at http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="surg", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    nxt = sub.add_parser("next", help="Print the decision for one screen-state file")
    nxt.add_argument("state", metavar="STATE.json", help="screen state (PRD section 8)")

    bench = sub.add_parser("bench", help="Run the benchmark grid and write a report")
    bench.add_argument("--runs", type=int, default=200, help="seeded runs per cell")
    bench.add_argument("--policy", choices=POLICY_CHOICES, default="advisor")
    bench.add_argument(
        "--skills",
        default="0,25,50,75,100",
        help="comma list of skill levels, 0 to 100 (default: %(default)s)",
    )
    bench.add_argument(
        "--modifiers",
        default="none",
        help="comma list of modifier ids, or none (default: %(default)s)",
    )
    bench.add_argument("--compare", metavar="REPORT.json", help="saved report")
    bench.add_argument("--out", metavar="BASE", help="write BASE.json and BASE.md")
    bench.add_argument("--workers", type=int, help="processes (default: CPU count)")

    play = sub.add_parser("play", help="Run one SurgE surgery in the terminal")
    play.add_argument("--malady", help="SurgE's spelling, e.g. 'Heart Attack'")
    play.add_argument("--condition", help="none, tough_skin, filthy, ...")
    play.add_argument("--skill", type=int, help="0 to 100")
    play.add_argument("--modifier", help="stethoscope, tea, ...")
    play.add_argument("--seed", type=int, help="same seed, same surgery")
    play.add_argument("--policy", choices=POLICY_CHOICES, default="advisor")
    play.add_argument("--log", metavar="FILE.jsonl", help="write each turn as JSON")

    web = sub.add_parser("web", help="Start the web viewer on http://127.0.0.1:8000")
    web.add_argument("--port", type=int, default=8000)

    return parser


def main(argv: list[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    handlers = {"next": _next, "play": _play, "bench": _bench, "web": _web}
    return handlers[ns.command](ns)


if __name__ == "__main__":
    sys.exit(main())
