# CLAUDE.md

The shared instructions for all coding agents live in AGENTS.md and are imported here, so there is one source of truth. Put project rules there, not here.

@AGENTS.md

## Claude Code specifics

- **Start of a session:** read the status line and open tasks in [PLAN.md](PLAN.md) before proposing work. Say which milestone task you're picking up.
- **Plan first for rule changes.** Adding, removing or reordering rules in `src/advisor/rules.py` changes benchmark results across the grid. Propose the change and the test you'll add before editing.
- **Ask before you:**
  - change a target, requirement or open question in [PRD.md](PRD.md)
  - change the screen-state schema (PRD section 8), since the web viewer and future screen reader depend on it
  - add a runtime dependency to `src/advisor/` (it is standard library only)
  - touch anything listed in [docs/decisions.md](docs/decisions.md)
- **Before you say a task is done:** run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/advisor` and `uv run pytest`. For changes under `src/advisor/`, also run `uv run surg bench --runs 5 --compare reports/baseline-5.json` and report the numbers.
- **Long runs:** the full benchmark takes minutes. Run it in the background and keep working, rather than waiting on it.
- **Never edit `vendor/SurgE`**, even for a one-line fix. Work around it in `src/harness/` and add the quirk to the gotchas table in AGENTS.md.
- **Keep this file short.** Anything that applies to every agent belongs in AGENTS.md.
