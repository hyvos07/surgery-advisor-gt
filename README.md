# Growtopia Surgery Advisor

A rule-based advisor that reads the current state of a Growtopia surgery and tells you the next tool to use, with the rule that chose it and why. It is tested against [SurgE](https://github.com/CantFindDev/SurgE), an open-source surgery simulator.

> **Status:** M4 (tuning, the last MVP milestone) in progress. The advisor runs in the simulator and wins 98.3% of surgeries at skill 100 with the Exquisite Bone Saw, against 28.7% for SurgE's Train-E tips. See [PLAN.md](PLAN.md) for the latest numbers.

```json
{"tool": "scalpel", "rule": "P5", "reason": "Heart Attack needs 2 incisions, 1 open; patient is unconscious."}
```

## How it works

- **Sees what a player sees.** The input is the surgery screen as words and numbers (pulse "weak", status "unconscious", 104.6°F), never SurgE's hidden values.
- **Remembers what the screen forgets,** such as the diagnosis, incisions still needed and turns of sleep left.
- **Decides from the current state.** Emergency rules come first (heart stopped, pulse about to drop out, fever spiking), then the rules for the stage of the surgery. A skill fail or a sudden heart stop is just another state.
- **Never makes a fatal move.** A legality check blocks Scalpel on an awake patient, Anesthetic on an unconscious one, and tools that would make the surgery impossible to finish.
- **Handles all 27 maladies, 6 special conditions, 4 modifiers and skill levels 0–100.**

Why rules and not a model: [docs/decisions.md](docs/decisions.md#d1-hand-written-rule-engine-not-a-trained-model).

## Quick start

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone --recurse-submodules <this repo>
cd <this repo>
uv sync

uv run surg web                     # step-by-step viewer at http://127.0.0.1:8000
                                    # Manual tab: get advice while playing the real game
uv run surg play --skill 40 --seed 7  # one surgery in the terminal
uv run surg bench --runs 5          # quick benchmark
```

## Documentation

| File | What's in it |
| --- | --- |
| [PRD.md](PRD.md) | Requirements, screen-state schema, success metrics, open questions |
| [PLAN.md](PLAN.md) | Milestones and task checklists |
| [docs/game-model.md](docs/game-model.md) | How SurgE's surgery works: tools, per-turn updates, maladies, conditions |
| [docs/decision-engine.md](docs/decision-engine.md) | Rules, memory, forecast, legality check, safety margins |
| [docs/testing.md](docs/testing.md) | Unit tests, benchmark grid, Train-E baseline, web viewer |
| [docs/decisions.md](docs/decisions.md) | Why things are the way they are |
| [AGENTS.md](AGENTS.md) | Instructions for coding agents (and a good contributor guide) |
| [CLAUDE.md](CLAUDE.md) | Claude Code entry point; imports AGENTS.md |

## Scope

This project runs only against the SurgE simulator. It does not connect to, read from or send input to the Growtopia game. Growtopia's rules permanently suspend accounts that use bots or macros, so pointing this at the live game would put your account at risk.

## Credits and license

- Surgery mechanics and data come from [SurgE](https://github.com/CantFindDev/SurgE) by CantFind, AGPL-3.0, included unmodified as a git submodule under `vendor/SurgE`.
- Growtopia is a trademark of its owners. This project is not affiliated with or endorsed by them.
- This repository is licensed under the [GNU Affero General Public License v3.0 or later](LICENSE), the same license family as SurgE ([D20](docs/decisions.md)). If you host a modified version for others to use over a network, you must offer them its source.
