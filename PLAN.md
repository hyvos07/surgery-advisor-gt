# Plan: Growtopia Surgery Advisor

The MVP is done at M4: the advisor beats SurgE's Train-E baseline across the full benchmark grid with zero avoidable deaths. Requirements are in [PRD.md](PRD.md); this file is the order of work.

**Current status:** M3 done; M4 (tuning) is next. D14 (minimal Antiseptic), D15 (Fix It last) and D16 (fever treated only above 100.4 F) are applied. The advisor wins 97.2% in the owner's setup (skill 100, Exquisite Bone Saw) and 71.4% over the full grid, using 10.1 tools per success where the baseline uses 12.9 on the same wins, against 28.7% and 22.0% for the Train-E baseline, with zero illegal moves. Targets were reset from these numbers (D17); M4 starts with the top death causes in `reports/m3-*.md`.

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
- [x] CI: lint, type check, unit tests and a gitleaks secret scan on every push; a 1-run-per-cell smoke benchmark on the main branch (blocking since M3)
- [x] `.gitignore` covering secrets, `.venv/`, caches, `reports/` and `logs/`
- [x] `.pre-commit-config.yaml` with the gitleaks secret scan, private-key detection and a 500 KB file-size limit
- [x] Add `pre-commit` as a dev dependency and run `uv run pre-commit run --all-files` once on the initial commit

## M1: Harness and viewer

**Observation adapter** (`src/harness/observe.py`)

- [x] Start a surgery the way SurgE's Discord cog does: plain-text mode, status set to Awake, the "not been diagnosed" scan text, then a UI text update
- [x] Strip SurgE's markdown formatting and map each on-screen text to the screen-state enums in PRD section 8
- [x] Compute `usable_tools` that match SurgE's tool tray (`ui/surgery_view.py`, which can't be imported because it needs Discord), derived from on-screen text ([D10](docs/decisions.md))
- [x] Never read hidden numbers (exact pulse, sleep level, dirt, sanitation, fever value)
- [x] Unit tests: one SurgE state per enum value, checked against the expected JSON

**Runner** (`src/harness/runner.py`)

- [x] Run one surgery to the end with any policy: apply tool, record turn, stop on SurgE's end text or the 80-turn cap
- [x] Save and restore Python's random state around every SurgE call, so each surgery has its own seed
- [x] Classify the outcome: success, avoidable death, unlucky death, timeout
- [x] Write each turn as a JSON line: seed, turn, state, decision, tool text, outcome

**Train-E baseline** (`src/harness/baseline.py`)

- [x] Generate SurgE's Train-E tips without turning on Train-E mode (it changes the game rules)
- [x] Map each tip to a tool and take the first one that is usable

**CLI and viewer**

- [x] `surg play`: print each turn's screen and decision in the terminal
- [x] `surg web`: FastAPI server on `127.0.0.1:8000` with the endpoints in [docs/testing.md](docs/testing.md#web-viewer)
- [x] Single HTML page: patient screen, advisor panel, Next, Auto-play with speed control, Pause, Restart, New surgery form, turn log, end card, Train-E toggle
- [x] Until M2 lands, the viewer runs the Train-E baseline as its policy

**Baseline benchmark**

- [x] `surg bench --policy baseline` over the full grid; save the report as the number to beat

## M2: Rule engine v1

- [x] `src/advisor/state.py`: typed screen-state and decision models, with JSON parsing and validation
- [x] `src/advisor/knowledge.py`: load maladies and special conditions from `vendor/SurgE/data/*.json`
- [x] `src/advisor/memory.py`: diagnosis, incisions needed, condition, sleep turns left, Lab Kit used, fix done, previous temperature (to tell when the fever has turned negative)
- [x] `src/advisor/forecast.py`: one-step lookahead for pulse, temperature, dirt and sleep, from [docs/game-model.md](docs/game-model.md#what-happens-every-turn)
- [x] `src/advisor/rules.py`: one function per rule E1–E7 and P1–P13, in priority order, plus the legality check from [docs/decision-engine.md](docs/decision-engine.md#legality-check)
- [x] `src/advisor/config.py`: safety margins per skill band, and the `surge` and `wiki` threshold profiles
- [x] `src/advisor/engine.py`: `decide(state, memory) -> Decision` with the legality check
- [x] Unit tests: one hand-written state per rule that proves it fires; property test that Scalpel-while-Awake and Anesthetic-while-Unconscious are never returned for any generated state
- [x] Swap the viewer and `surg play` to the advisor policy
- [x] Owner preference to test: use Antiseptic as little as possible, only at the start of long surgeries such as Brain Tumor. Sponge is unaffected (it is forced at `cant_see`). Add it as a `config.py` margin, propose it before editing `rules.py`, and compare with the benchmark (done: `advisor-min-antiseptic`; see D13. The default stays `draft` until the owner decides)

## M3: First benchmark

- [x] Apply D15: close the incisions before Fix It and do Fix It last (memory `fix_unlocked`; P3, P5 and P6 guards as written in D15). Write D15's tests first, then benchmark against the current rules and record the numbers in D15 (done: 96.7% owner's setup, 70.9% full grid)
- [x] Apply D14: make `minimal` the default Antiseptic mode (`Config` default and the `advisor` policy; keep `draft` selectable), update the docs that say `draft` is the default, then re-run the owner's-setup and full-grid benchmarks and re-save the comparison reports (`reports/baseline-5.json` stays as is) (done: 97.1% owner's setup, 71.4% full grid; `draft` is the `advisor-draft-antiseptic` policy)
- [x] Full grid for advisor and baseline with the same seeds (`reports/advisor.json`, `reports/baseline.json`; owner's setup in `reports/main-advisor.json`, `reports/main-baseline.json`)
- [x] Report: success rate per malady, condition and skill level, side by side (done: `surg report`; `reports/m3-main.md`, `m3-full.md`, `m3-mod.md`)
- [x] Tools used: compare the tools per success only on surgeries (same cell and seed) that both advisor and baseline win, and record the fewest tools ever needed per cell as the reference to approach (done: `surg tools`; on paired wins the advisor uses 0.6 fewer tools in both the owner's setup and the full grid, saving about 2 Antiseptic and 0.5 Sponge but spending about 1 Lab Kit and 1 Antibiotics that the baseline skips, all from P2)
- [x] For every death, the rules that fired in the last 3 turns; rank rules by how often they appear (done: E2, E3, E6 and E1 lead; the rule at the mistake turn is ranked too)
- [x] Deeper death classification: look back several turns, not just the fatal one, to find mistakes made earlier (M1 only checks the fatal turn) (done: `--lookback N`; at 3 turns, 20,219 of 45,696 full-grid deaths are avoidable, 316 of 882 in the owner's setup)
- [x] Separate modifier run: 27 maladies × 4 modifiers × skill 0 and 100 × 50 runs (done: advisor 71.3%, baseline 22.0%; Stethoscope 86.1%; Exquisite Bone Saw and Tea are the same modifier type in SurgE and score identically)
- [x] Each death in the report links to the viewer with its settings and seed
- [x] Update the targets in PRD section 10 from the real numbers (done: D17)

## M4: Tuned MVP

- [ ] Fix the top failing rules from M3, re-running the same seeds after each change
- [ ] Tune safety margins per skill band (config only; recorded in decisions.md without asking each time)
- [x] Candidate from M3's tools comparison: P2 broke every positive fever with Lab Kit and Antibiotics, even in short surgeries. Done as D16 (owner: treat a fever only above 100.4 F); paired tools per success 12.3 -> 10.1 against the baseline's 12.9, success flat, but 475 more avoidable deaths on long trauma surgeries to check in the M3 death analysis
- [x] From M3 (owner: M4, not before): Brainworms in the owner's setup, 169 of 316 avoidable deaths, where Antibiotics would have beaten E3's Transfusion; consider letting the fever rules skip the 100.4 F gate (D16) for fevers that keep climbing (done as D22: the cause was E3 transfusing on a merely `weak` pulse, not D16; Brainworms 67% -> 89%)
- [x] From M3 (owner: M4, not before): a Sponge was the better tool in 12,839 of 20,219 full-grid avoidable deaths, mostly instead of E6's fever tool or E1's Defibrillator with the site almost unseeable (D13's revisit condition) (investigated: every Sponge variant lost 7 to 20 points, so D13 stays; the count was mostly the death check's tool-order and fresh-roll bias)
- [x] Fix the lookback death check: a death is avoidable only if the other tool wins and the advisor's own tool replayed with fresh rolls does not (owner-approved; done with common random numbers: lookback-3 avoidable deaths 316 -> 71 in the owner's setup and 20,219 -> 6,823 over the full grid, most of the old count was luck)
- [ ] Meet the D17 targets (PRD section 10), including one-turn avoidable deaths of at most 0.1% in the owner's setup and 1% over the full grid
- [x] Seed offset for `surg bench` (D19); tune on seeds 0-199 and report the final numbers on seeds 1000-1199 (`--seed-offset`)
- [x] Manual-input mode in the web viewer, as an option beside the simulator mode (D21, PRD FR21)
- [ ] Add the AGPL-3.0 `LICENSE` and update the README credits (D20), before the repository goes public
- [ ] Record final numbers in the README (fresh seeds, D19)

## M5: Real game input (later, out of MVP scope)

- [ ] Decide on screen capture and text recognition
- [ ] Produce the same screen-state JSON from the real game screen
- [ ] Switch to the `wiki` threshold profile and re-check rules that depend on it

## How to work through the plan

- Do milestones in order. Within a milestone, tasks can go in any order.
- Tick a box only when its code is merged and its tests pass.
- When a task changes a requirement, update [PRD.md](PRD.md) in the same change.
- When a benchmark result changes a rule, note it in [docs/decisions.md](docs/decisions.md).
