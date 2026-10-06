# AGENTS.md

Instructions for coding agents working in this repository. Humans can read it too.

## Project in one paragraph

The Surgery Advisor reads the current state of a Growtopia surgery and returns the next tool to use, with a rule ID and a reason. It is a hand-written rule engine, not a machine learning model. It is tested against [SurgE](https://github.com/CantFindDev/SurgE), an open-source surgery simulator, kept unmodified under `vendor/SurgE`. The MVP only advises: no tapping, no screen capture, no connection to the live game.

**Status:** M2 done; M3 (first benchmark) in progress. Every command and module below exists. The status line at the top of [PLAN.md](PLAN.md) has the latest numbers.

## Read before you start

| File | Read it when |
| --- | --- |
| [PLAN.md](PLAN.md) | Always. It says which milestone is current and which tasks are open |
| [PRD.md](PRD.md) | You change behaviour, the screen-state schema or the CLI |
| [docs/game-model.md](docs/game-model.md) | You touch rules, the forecast or the observation adapter |
| [docs/decision-engine.md](docs/decision-engine.md) | You add, change or reorder a rule |
| [docs/testing.md](docs/testing.md) | You touch the harness, benchmark or web viewer |
| [docs/decisions.md](docs/decisions.md) | You're about to change something listed there |

## Setup

```bash
git submodule update --init      # fetches vendor/SurgE at the pinned commit
uv sync                          # creates .venv with Python 3.12 and all dependencies
```

Python 3.12 or newer is required. SurgE uses 3.12 f-string syntax and fails to import on 3.11.

## Commands

| Task | Command |
| --- | --- |
| Unit tests | `uv run pytest` |
| Lint | `uv run ruff check .` |
| Format check | `uv run ruff format --check .` |
| Type check | `uv run mypy src/advisor` |
| One decision | `uv run surg next state.json` |
| Play one surgery in the terminal | `uv run surg play --malady "Heart Attack" --condition tough_skin --skill 50 --seed 7` |
| Quick benchmark (about 1 minute) | `uv run surg bench --runs 5` |
| Full benchmark | `uv run surg bench --runs 200` |
| Save a report as the number to beat | `uv run surg bench --runs 200 --out reports/baseline` |
| Compare with a saved report | `uv run surg bench --runs 5 --compare reports/baseline-5.json` (a report is only comparable with one made with the same `--runs` and grid: `reports/baseline-5.json` for 5 runs, `reports/baseline.json` for 200) |
| Compare tools with another policy | `uv run surg tools reports/advisor.json reports/baseline.json` (both made with the same `--runs` and grid) |
| Web viewer | `uv run surg web`, then open `http://127.0.0.1:8000` |

Before you finish any change, run lint, format check, type check and unit tests. If you changed anything under `src/advisor/`, also run the quick benchmark and compare it with the last saved report.

## Repository layout

```text
src/
  advisor/           the rule engine; standard library only
    state.py         screen-state and decision models, JSON parsing
    knowledge.py     loads maladies and conditions from vendor/SurgE/data/*.json
    memory.py        what the advisor remembers between turns
    forecast.py      one-step lookahead using the game's formulas
    rules.py         one function per rule, and the RULES priority list
    config.py        safety margins per skill band; surge and wiki profiles
    engine.py        decide(state, memory) -> Decision, plus the legality check
  harness/           everything that touches SurgE
    surge.py         the only module that imports SurgE (adds vendor/SurgE to sys.path)
    observe.py       SurgE Patient -> screen-state JSON, from on-screen text only
    runner.py        runs one surgery with any policy; seeds and outcomes
    baseline.py      Train-E baseline policy
    bench.py         benchmark grid and reports
  web/
    app.py           FastAPI server for the step-by-step viewer
    static/index.html
  cli.py             the `surg` command
tests/
  advisor/           rule, memory, forecast and engine tests (no SurgE needed)
  harness/           adapter and runner tests against real SurgE patients
docs/                reference docs (see the table above)
vendor/SurgE/        git submodule, unmodified, pinned
reports/             benchmark output (git-ignored)
logs/                decision logs (git-ignored)
```

## Architecture boundaries

- `src/advisor/` must never import `harness`, `web` or anything from `vendor/SurgE`. It may read SurgE's JSON data files through `knowledge.py`, and nothing else. This keeps the advisor reusable on the real game later, and keeps it separate from SurgE's AGPL code.
- `src/harness/surge.py` is the only place that puts `vendor/SurgE` on `sys.path` and imports from it. Everything else in the harness goes through it.
- The web viewer and CLI call the same `engine.decide()` and the same runner. No decision logic lives in `web/` or `cli.py`.

## Hard rules

These protect the core guarantees in [PRD.md](PRD.md). Don't break them, even temporarily.

1. **Never modify `vendor/SurgE`.** If SurgE behaves oddly, work around it in `src/harness/` and add it to [SurgE gotchas](#surge-gotchas).
2. **The advisor sees only what a player can see.** `observe.py` builds the screen state from SurgE's display text. It must never read hidden values such as `Pulse`, `SleepLevel`, `SiteDirtyness`, `SiteSanitation`, `Fever`, `HeartDamage` or `IncisionsNeeded`. Memory may track these by counting turns, never by peeking.
3. **The legality check is never bypassed.** `engine.decide()` must never return a tool missing from `usable_tools`, Scalpel while `status` is `awake`, or Anesthetic while `status` is `unconscious`. The property test for this must always pass.
4. **Memory changes only on a confirmed success.** If `last_tool_text` contains `[Skill Fail`, treat the tool as having done nothing.
5. **Rule IDs are permanent.** Never renumber E1–E7 or P1–P13. A new rule gets the next free ID; a removed rule's ID is retired. Benchmark reports and logs refer to these IDs.
6. **Benchmarks use fixed seeds.** Never compare two benchmark runs with different seeds or grid settings.
7. **Never lower a target to make it pass.** Targets in PRD section 10 change only with the owner's agreement, recorded in [docs/decisions.md](docs/decisions.md).
8. **Stay inside the simulator.** Don't add code that talks to the live Growtopia client, injects input, reads game memory or network traffic, or tries to avoid anti-cheat detection. M5 is a separate decision for the owner.
9. **The web viewer binds to `127.0.0.1` only.** SurgE is AGPL-3.0, and hosting it publicly would require publishing source.

## Coding conventions

- Type hints everywhere. `mypy --strict` must pass on `src/advisor`.
- Screen state, decisions and config are frozen dataclasses. Memory is the only mutable object, and only `memory.update()` mutates it.
- Enum values match PRD section 8 exactly: lowercase snake case (`coming_to`, `extremely_weak`, `fix_it`).
- A rule is a pure function with this shape:

  ```python
  def rule_e5_stop_heavy_bleeding(s: ScreenState, m: Memory, f: Forecast, c: Config) -> Decision | None:
      ...
  ```

  It returns a `Decision` when it fires and `None` otherwise. It never has side effects.
- Reasons are plain English, under 100 characters, and name the fact that triggered the rule ("Pulse will drop to extremely weak next turn").
- No `print()` in library code. Decisions are logged as JSON lines through `logging`.
- Thresholds and margins live in `config.py`, never as literals inside rules.

## Changing the rules

1. Read the rule's section in [docs/decision-engine.md](docs/decision-engine.md) and the mechanics it depends on in [docs/game-model.md](docs/game-model.md).
2. Write or update the unit test first: a hand-built state where the rule should fire, and one where it shouldn't.
3. Make the change in `rules.py` (and `config.py` for margins).
4. Run the quick benchmark with `--compare` against the last saved report. Include the before-and-after success rates in your summary.
5. Update [docs/decision-engine.md](docs/decision-engine.md) in the same change. If the change came from benchmark evidence, add an entry to [docs/decisions.md](docs/decisions.md).

## SurgE gotchas

Things in SurgE that will bite you. The harness handles each one; keep it that way.

| Gotcha | What to do |
| --- | --- |
| `ui/` and `cogs/` import `discord` | Never import them. `observe.py` derives the tool-tray conditions from `ui/surgery_view.py` (`_TOOL_LAYOUT`) using on-screen text ([D10](docs/decisions.md#d10-usable_tools-derived-from-on-screen-text-plus-three-tray-flags)); `tests/harness/test_observe.py` holds a copy of `_TOOL_LAYOUT` and fails if the two drift apart. `IsBrainWorms` is never set in SurgE, so that clause of the Fix It condition is dead |
| SurgE imports `core.*` as top-level packages | `harness/surge.py` adds `vendor/SurgE` to `sys.path` before importing |
| A new `Patient` has an empty status, so Scalpel on turn 0 wouldn't kill | Start every surgery like `cogs/surgery_cog.py` does: `TextManager.setTextManager(False)`, set `PatientStatus` to the Awake text, set the "not been diagnosed" scan text if empty, then call `UpdatePatientUITexts()` |
| `TextManager` mode is global, and status comparisons use the formatted text | Set plain-text mode once at start-up and never change it mid-run |
| Plain-text mode wraps words in markdown, e.g. `**[Awake](https://github.com/...)**` | Strip formatting in `observe.py` before matching |
| The fastest bleeding text is spelled "loosing blood" | Match both spellings |
| The random special condition always returns "None" (the "None" entry matches every roll first) | Always pass the special condition explicitly |
| `TrainEMode=True` changes the game: Anesthetic on an unconscious patient gives Near Coma instead of death | Run every surgery with `TrainEMode=False`. To get Train-E tips, set `TrainE = True`, call `_UpdateTrainEText()`, then set it back |
| SurgE uses Python's global `random` | Save and restore the random state around every SurgE call, per surgery |
| `Patient.timer()` sleeps for real minutes; `SetCurrentPatientEmbed()` rolls a reward drop | Never call either. Use the 80-turn cap and read texts directly |
| Nose Job starts already diagnosed, so Ultrasound is never usable and hidden conditions stay hidden | The advisor assumes both hidden conditions (see [docs/decision-engine.md](docs/decision-engine.md#special-conditions)) |
| The low-bleeding Train-E tip has no newline, so the next tip is glued on ("Losing BloodShattered Bone") | `harness/baseline.py` splits the text back apart; keep the regression test |
| The disc malady is spelled "Herinated Disc" | Use SurgE's spelling when passing malady names |

## Keeping docs in sync

- Behaviour, schema or CLI change: update [PRD.md](PRD.md).
- Task finished: tick it in [PLAN.md](PLAN.md) and update the status line at the top.
- New SurgE quirk: add it to the table above.
- A choice someone might later question: add it to [docs/decisions.md](docs/decisions.md).

## Commits and pull requests

- One logical change per commit. Message in the imperative, prefixed with the milestone: `M2: add heavy-bleeding clamp rule (E5)`.
- A pull request description says what changed, why, which checks you ran, and for rule changes the before-and-after benchmark numbers.
- Don't commit `reports/`, `logs/` or `.venv/`.
