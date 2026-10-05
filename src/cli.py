"""The `surg` command: next, play, bench and web."""

import argparse
import sys

# Subcommand -> milestone that implements it.
_STUBS = {
    "next": ("Print the decision for one screen-state JSON file", "M2"),
    "play": ("Run one SurgE surgery in the terminal, turn by turn", "M1"),
    "bench": ("Run the benchmark grid and write a report", "M1"),
    "web": ("Start the web viewer on http://127.0.0.1:8000", "M1"),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="surg", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, (help_text, _) in _STUBS.items():
        sub.add_parser(name, help=help_text)
    # Ignore unknown options so the documented commands parse until implemented.
    ns, _ = parser.parse_known_args(argv)
    milestone = _STUBS[ns.command][1]
    print(f"surg {ns.command}: not implemented yet ({milestone})", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
