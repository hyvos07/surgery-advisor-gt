"""The `surg` command: next, play, bench and web."""

import argparse
import json
import sys
from pathlib import Path

# Subcommands not built yet -> (help text, milestone that implements it).
_STUBS = {
    "next": ("Print the decision for one screen-state JSON file", "M2"),
    "play": ("Run one SurgE surgery in the terminal, turn by turn", "M1"),
    "web": ("Start the web viewer on http://127.0.0.1:8000", "M1"),
}


def _bench(args: argparse.Namespace) -> int:
    # Imported here so `surg --help` and the stubs don't load SurgE.
    from harness import bench

    saved = None
    if args.compare:
        saved = json.loads(Path(args.compare).read_text(encoding="utf-8"))

    def progress(done: int, total: int) -> None:
        if done == total or done % max(1, total // 20) == 0:
            print(f"  {done}/{total} cells", file=sys.stderr, flush=True)

    try:
        report = bench.run_grid(
            args.policy, args.runs, workers=args.workers, progress=progress
        )
        comparison = bench.compare_reports(report, saved) if saved else None
    except (NotImplementedError, ValueError) as error:
        print(f"surg bench: {error}", file=sys.stderr)
        return 1

    base = Path(args.out) if args.out else bench.default_base()
    json_path, md_path = bench.write_report(report, base, comparison)
    print(bench.render_markdown(report, comparison))
    print(f"Wrote {json_path} and {md_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="surg", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (help_text, _) in _STUBS.items():
        sub.add_parser(name, help=help_text)

    bench = sub.add_parser("bench", help="Run the benchmark grid and write a report")
    bench.add_argument("--runs", type=int, default=200, help="seeded runs per cell")
    bench.add_argument(
        "--policy",
        choices=["baseline", "advisor"],
        default="baseline",
        help="policy to score (advisor arrives in M2)",
    )
    bench.add_argument("--compare", metavar="REPORT.json", help="saved report")
    bench.add_argument("--out", metavar="BASE", help="write BASE.json and BASE.md")
    bench.add_argument("--workers", type=int, help="processes (default: CPU count)")

    # The stubs accept any options, so the documented commands parse until built.
    ns, extra = parser.parse_known_args(argv)
    if ns.command in _STUBS:
        print(
            f"surg {ns.command}: not implemented yet ({_STUBS[ns.command][1]})",
            file=sys.stderr,
        )
        return 1
    if extra:
        parser.error(f"unrecognized arguments: {' '.join(extra)}")
    return _bench(ns)


if __name__ == "__main__":
    sys.exit(main())
