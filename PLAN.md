# Plan: Growtopia Surgery Advisor

The MVP is done at M4: the advisor beats SurgE's Train-E baseline across the full benchmark grid with zero avoidable deaths. Requirements are in [PRD.md](PRD.md); this file is the order of work.

**Current status:** M0 done except the CI smoke benchmark, which waits for `surg bench` in M1. Package layout, `surg` stubs, SurgE submodule, smoke tests and CI are in place. Next up is M1.

## Milestones

| # | Milestone | Done when | Depends on |
| --- | --- | --- | --- |
| M0 | Repository setup | `uv run pytest` passes on an empty test suite; SurgE vendored at the pinned commit | – |
| M1 | Harness and viewer | `surg play` and `surg web` run a SurgE surgery from screen text alone; Train-E baseline scores the full grid | M0 |
| M2 | Rule engine v1 | Every rule in [docs/decision-engine.md](docs/decision-engine.md) is implemented with memory and the legality check; unit tests pass | M1 |
| M3 | First benchmark | Full grid results for advisor and baseline, plus a ranked list of the rules behind deaths | M2 |
| M4 | Tuned MVP | Rule order and safety margins tuned; every target in PRD section 10 met | M3 |
| M5 | Real game input (later) | Screen reading produces the same screen-state JSON from the real game | M4 |

## M0: Repository setup

- [x] `pyproject.toml` with Python `>=3.12`, managed by `uv`
- [x] Dev tools: `pytest`, `ruff` (lint and format), `mypy` (strict on `src/advisor`)
- [x] Runtime dependencies: `fastapi`, `uvicorn` (viewer only); the advisor itself uses the standard library only
- [x] Add SurgE as a git submodule at `vendor/SurgE`, pinned to commit `f606a003fac9012ba756de5e89c8b736c213b87a`
- [x] Package layout from [AGENTS.md](AGENTS.md#repository-layout), with empty modules
- [x] `surg` console script entry point with stub subcommands
- [ ] CI: lint, type check, unit tests and a gitleaks secret scan on every push (done); a 1-run-per-cell smoke benchmark on the main branch (waits for `surg bench` in M1)
- [x] `.gitignore` covering secrets, `.venv/`, caches, `reports/` and `logs/`
- [x] `.pre-commit-config.yaml` with the gitleaks secret scan, private-key detection and a 500 KB file-size limit
- [x] Add `pre-commit` as a dev dependency and run `uv run pre-commit run --all-files` once on the initial commit

## M1: Harness and viewer

**Observation adapter** (`src/harness/observe.py`)

- [ ] Start a surgery the way SurgE's Discord cog does: plain-text mode, status set to Awake, the "not been diagnosed" scan text, then a UI text update
- [ ] Strip SurgE's markdown formatting and map each on-screen text to the screen-state enums in PRD section 8
- [ ] Compute `usable_tools` with the same conditions as SurgE's tool tray (`ui/surgery_view.py`, which can't be imported because it needs Discord)
- [ ] Never read hidden numbers (exact pulse, sleep level, dirt, sanitation, fever value)
- [ ] Unit tests: one SurgE state per enum value, checked against the expected JSON

**Runner** (`src/harness/runner.py`)

- [ ] Run one surgery to the end with any policy: apply tool, record turn, stop on SurgE's end text or the 80-turn cap
- [ ] Save and restore Python's random state around every SurgE call, so each surgery has its own seed
- [ ] Classify the outcome: success, avoidable death, unlucky death, timeout
- [ ] Write each turn as a JSON line: seed, turn, state, decision, tool text, outcome

**Train-E baseline** (`src/harness/baseline.py`)

- [ ] Generate SurgE's Train-E tips without turning on Train-E mode (it changes the game rules)
- [ ] Map each tip to a tool and take the first one that is usable

**CLI and viewer**

- [ ] `surg play`: print each turn's screen and decision in the terminal
- [ ] `surg web`: FastAPI server on `127.0.0.1:8000` with the endpoints in [docs/testing.md](docs/testing.md#web-viewer)
- [ ] Single HTML page: patient screen, advisor panel, Next, Auto-play with speed control, Pause, Restart, New surgery form, turn log, end card, Train-E toggle
- [ ] Until M2 lands, the viewer runs the Train-E baseline as its policy

**Baseline benchmark**

- [ ] `surg bench --policy baseline` over the full grid; save the report as the number to beat

## M2: Rule engine v1

- [ ] `src/advisor/state.py`: typed screen-state and decision models, with JSON parsing and validation
- [ ] `src/advisor/knowledge.py`: load maladies and special conditions from `vendor/SurgE/data/*.json`
- [ ] `src/advisor/memory.py`: diagnosis, incisions needed, condition, sleep turns left, Lab Kit used, fix done, previous temperature (to tell when the fever has turned negative)
- [ ] `src/advisor/forecast.py`: one-step lookahead for pulse, temperature, dirt and sleep, from [docs/game-model.md](docs/game-model.md#what-happens-every-turn)
- [ ] `src/advisor/rules.py`: one function per rule E1–E7 and P1–P13, in priority order, plus the legality check from [docs/decision-engine.md](docs/decision-engine.md#legality-check)
- [ ] `src/advisor/config.py`: safety margins per skill band, and the `surge` and `wiki` threshold profiles
- [ ] `src/advisor/engine.py`: `decide(state, memory) -> Decision` with the legality check
- [ ] Unit tests: one hand-written state per rule that proves it fires; property test that Scalpel-while-Awake and Anesthetic-while-Unconscious are never returned for any generated state
- [ ] Swap the viewer and `surg play` to the advisor policy

## M3: First benchmark

- [ ] Full grid for advisor and baseline with the same seeds
- [ ] Report: success rate per malady, condition and skill level, side by side
- [ ] For every death, the rules that fired in the last 3 turns; rank rules by how often they appear
- [ ] Separate modifier run: 27 maladies × 4 modifiers × skill 0 and 100 × 50 runs
- [ ] Each death in the report links to the viewer with its settings and seed
- [ ] Update the targets in PRD section 10 from the real numbers

## M4: Tuned MVP

- [ ] Fix the top failing rules from M3, re-running the same seeds after each change
- [ ] Tune safety margins per skill band
- [ ] Confirm zero avoidable deaths across the grid
- [ ] Record final numbers in the README

## M5: Real game input (later, out of MVP scope)

- [ ] Decide on screen capture and text recognition
- [ ] Produce the same screen-state JSON from the real game screen
- [ ] Switch to the `wiki` threshold profile and re-check rules that depend on it

## How to work through the plan

- Do milestones in order. Within a milestone, tasks can go in any order.
- Tick a box only when its code is merged and its tests pass.
- When a task changes a requirement, update [PRD.md](PRD.md) in the same change.
- When a benchmark result changes a rule, note it in [docs/decisions.md](docs/decisions.md).
