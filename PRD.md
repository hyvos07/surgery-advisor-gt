# PRD: Growtopia Surgery Advisor

| | |
| --- | --- |
| Status | Draft; implementation at M3 (see [PLAN.md](PLAN.md)) |
| Owner | Daniel Liman |
| Last updated | 2026-10-06 |
| Living version | [Plan & PRD doc](https://claude.ai/code/artifact/e9963b51-b5a3-4769-8b3a-5f630bce91c1) |

## 1. Summary

The Surgery Advisor is a Python program that reads the current state of a Growtopia surgery and returns the next tool to use, with the rule that chose it and a one-line reason. The MVP only advises. It does not tap, capture the screen or connect to the live game.

The advisor is a **hand-written rule engine**, not a trained model. SurgE's open-source simulator ([CantFindDev/SurgE](https://github.com/CantFindDev/SurgE)) contains the complete surgery rules, so there is nothing a model would need to learn that cannot be written down directly, and there is no labelled dataset to train on. An ordered rule list is already a decision tree, written by hand and debuggable line by line. See [docs/decisions.md](docs/decisions.md), decision D1.

All testing runs against SurgE's unmodified `Patient` class, both as a large batch benchmark and in a step-by-step web viewer.

## 2. Problem

A Growtopia surgery is a sequence of tool choices under uncertainty. Every tool can skill-fail (5% at skill 100, 30% at skill 0), the heart can stop at random while the patient is asleep, and six special conditions change how the patient reacts. A fixed recipe per malady breaks as soon as one of those events happens. The advisor has to decide from whatever state the surgery is in right now.

## 3. Goals

- G1. Return one legal next tool for any visible surgery state, with its rule ID and a reason.
- G2. Cover all 27 maladies, all 6 special conditions and all 4 modifiers in SurgE's data files.
- G3. Work at any skill level from 0 to 100, including the 30% fail rate at skill 0.
- G4. Decide only from information a player can see on screen, so the same logic can run on the real game later.
- G5. Never cause an avoidable death.

## 4. Non-goals (MVP)

- Tapping, screen capture or OCR.
- Connecting to or automating the live game.
- Machine learning of any kind.
- The real 2-minute timer. The advisor answers instantly, so the tests use an 80-turn cap instead.
- Hosting anything publicly.

## 5. Approach

Each turn the advisor runs three layers:

1. **Observation:** the screen-state JSON in section 8, containing only what a player can see.
2. **Memory:** facts learned earlier in the same surgery that the screen no longer shows, such as the diagnosis, incisions needed, the special condition, sleep turns left and whether the Lab Kit was used.
3. **Rules with one-step lookahead:** an ordered list of emergency rules, then rules for the current phase of the surgery. Each rule predicts the next turn with SurgE's own formulas, so the advisor acts before a crisis rather than after it. The first rule whose tool is usable wins.

The key strategy is to **keep the patient awake as long as possible**. The heart can only stop while the patient is asleep (10% per tool), so every tool that works on an awake patient is used before the Anesthetic. Once the first incision is open, the patient stays asleep until the last incision is closed.

Full rule list, memory and special-condition handling: [docs/decision-engine.md](docs/decision-engine.md). Game mechanics the rules rely on: [docs/game-model.md](docs/game-model.md).

## 6. Users

One user: the project owner, testing the advisor against SurgE for fun and learning. Coding agents (Claude Code and others) also work in the repository and follow [AGENTS.md](AGENTS.md).

## 7. Functional requirements

### Advisor

| ID | Requirement |
| --- | --- |
| FR1 | Accept a screen state as JSON containing only on-screen fields (section 8). |
| FR2 | Return one tool from `usable_tools`, plus the rule ID and a one-line reason. |
| FR3 | Never return Scalpel while the status is Awake, or Anesthetic while the status is Unconscious. These are the two decisions that kill the patient instantly. Also never return Clamp, Splint or Pins when there is nothing to treat, which makes the surgery impossible to finish. Full list: [docs/decision-engine.md](docs/decision-engine.md#legality-check). |
| FR4 | Keep memory across turns within one surgery and reset it for each new patient. |
| FR5 | Update memory only on a confirmed success. Detect `[Skill Fail` in `last_tool_text` and assume the tool had no effect. |
| FR6 | Accept skill level 0–100 and an optional modifier, compute the fail rate, and widen safety margins as the fail rate rises. |
| FR7 | Handle all 6 special conditions, including Nose Job, where Ultrasound never runs and hidden conditions must be assumed. |
| FR8 | Load maladies and special conditions from SurgE's JSON files, not from a hand-copied list. |
| FR9 | Log every decision (turn, state, rule, tool, reason) as JSON lines. |
| FR10 | Read thresholds that differ between SurgE and the real game from a selectable profile (`surge` or `wiki`). |

### Test harness

| ID | Requirement |
| --- | --- |
| FR11 | Drive an unmodified SurgE `Patient` turn by turn, translating it into the screen-state JSON from on-screen text only. |
| FR12 | Compute `usable_tools` with the same rules as SurgE's tool tray, and reject any decision whose tool is not usable. |
| FR13 | Isolate SurgE's random state per surgery, so a seed always replays the same surgery. |
| FR14 | Provide a Train-E baseline policy that always takes SurgE's first usable Train-E tip. |
| FR15 | Run the benchmark grid (section 10) and report success rates, outcomes and the rules behind each death. |

### Web viewer

| ID | Requirement |
| --- | --- |
| FR16 | Serve a local page that plays one SurgE surgery in slow motion: show the patient screen and the advisor's next tool; each press of Next applies it and advances one turn. |
| FR17 | Start a surgery from malady, special condition, skill level, modifier and seed (blank means random), and restart it with the same seed. |
| FR18 | Offer Auto-play with a speed control (0.5–3 seconds per turn) and Pause. |
| FR19 | Show a turn log (tool, skill fail, rule, what changed) and an end card with SurgE's result message. |
| FR20 | Let the benchmark report link any run to the viewer by its settings and seed. |

Viewer design and endpoints: [docs/testing.md](docs/testing.md#web-viewer).

## 8. Interfaces

### Input: screen state

All enum values are lowercase snake case. A field is `null` when the screen does not show it.

```json
{
  "skill_level": 40,
  "modifier": null,
  "special_condition_text": "The patient is hyperactive.",
  "scan_text": "Patient had a heart attack.",
  "pulse": "steady",
  "status": "unconscious",
  "temperature": 99.1,
  "site": "not_sanitized",
  "visibility": "hard_to_see",
  "incisions": 1,
  "bones": {"broken": 0, "shattered": 0},
  "bleeding": "slowly",
  "fever": null,
  "last_tool_text": "You've made a neat incision.",
  "usable_tools": ["sponge", "anesthetic", "stitches", "scalpel", "antiseptic",
                   "lab_kit", "transfusion", "splint", "pins", "clamp"]
}
```

| Field | Type and values |
| --- | --- |
| `skill_level` | Integer 0–100 |
| `modifier` | `null`, `stethoscope`, `tea`, `exquisite_bone_saw`, `nano_nurse_bot` |
| `special_condition_text` | String, or `null` while hidden |
| `scan_text` | String, or `null` before diagnosis |
| `pulse` | `strong`, `steady`, `weak`, `extremely_weak` |
| `status` | `awake`, `coming_to`, `unconscious`, `heart_stopped` |
| `temperature` | Number, °F |
| `site` | `clean`, `not_sanitized`, `unclean`, `unsanitary` |
| `visibility` | `clear`, `hard_to_see`, `cant_see` |
| `incisions` | Integer |
| `bones` | `{"broken": int, "shattered": int}`, or `null` before diagnosis |
| `bleeding` | `null`, `slowly`, `losing`, `very_quickly` |
| `fever` | `null`, `slowly_rising`, `climbing`, `climbing_fast` |
| `last_tool_text` | String |
| `usable_tools` | Array of tool IDs: `defibrillator`, `sponge`, `anesthetic`, `stitches`, `scalpel`, `ultrasound`, `antiseptic`, `fix_it`, `lab_kit`, `antibiotics`, `transfusion`, `splint`, `pins`, `clamp` |

### Output: decision

```json
{
  "tool": "scalpel",
  "rule": "P5",
  "reason": "Heart Attack needs 2 incisions, 1 open; 3 sleep turns left is enough."
}
```

### Command line

| Command | What it does |
| --- | --- |
| `surg next state.json` | Prints the decision for one state as JSON (memory starts empty); an unreadable file, invalid JSON or a schema error prints a message on stderr and exits 1 |
| `surg play --skill 40 --condition hyperactive --seed 7` | Runs one SurgE surgery in the terminal, turn by turn |
| `surg bench --runs 200` | Runs the full benchmark grid and writes a report |
| `surg web` | Starts the web viewer on `http://127.0.0.1:8000` (`--port` changes the port; the host is fixed) |

`surg play` also takes `--malady`, `--modifier`, `--policy` and `--log FILE.jsonl`; blank settings are chosen at random from the seed. `surg bench` also takes `--policy`, `--skills` (comma list, default `0,25,50,75,100`), `--modifiers` (comma list of ids or `none`, default `none`), `--out BASE`, `--compare REPORT.json` and `--workers`. `--policy` is `advisor` (the default), `advisor-min-antiseptic`, `baseline` or `train-e-plus`.

## 9. Non-functional requirements

| ID | Requirement |
| --- | --- |
| NFR1 | Python 3.12 or newer (SurgE uses 3.12 f-string syntax). |
| NFR2 | A decision takes under 10 ms. |
| NFR3 | The full benchmark grid (162,000 surgeries) finishes in under 15 minutes on a laptop. |
| NFR4 | The same seed and settings always produce the same surgery and the same decisions. |
| NFR5 | No network access at runtime. The web viewer binds to `127.0.0.1` only. |
| NFR6 | SurgE stays unmodified under `vendor/SurgE`, pinned to a fixed commit. |

## 10. Success metrics

Targets are first guesses. The first benchmark run (milestone M3) will reset them.

| Metric | Target |
| --- | --- |
| Avoidable deaths (scalpel while awake, anesthetic while unconscious, illegal tool, or a death another legal tool would have prevented) | 0 |
| Success rate at skill 100, all maladies and conditions | ≥ 95% |
| Success rate at skill 0 | Beats the Train-E baseline by ≥ 10 points |
| Average tools per successful surgery | Lower than the Train-E baseline |
| Decision time | < 10 ms |

The benchmark grid is 27 maladies × 6 special conditions × 5 skill levels (0, 25, 50, 75, 100) × 200 seeded runs. Details: [docs/testing.md](docs/testing.md).

## 11. Scope by milestone

| Milestone | In scope |
| --- | --- |
| M0–M4 (MVP) | Advisor, harness, benchmark, web viewer, tuning |
| M5 (later) | Reading the real game screen and tapping, producing the same screen-state JSON |

Plan and task lists: [PLAN.md](PLAN.md).

## 12. Risks

| Risk | Mitigation |
| --- | --- |
| SurgE differs from the real game: success needs below 101°F (the wiki says 100.4°F) and Hyperactive sleep lasts 5 turns (the wiki says 4) | Keep these in the `surge` and `wiki` threshold profiles; switch profile before M5 |
| Luck caps low-skill results: at a 30% fail rate, two Defibrillator fails in a row (9%) kill no matter what | Score these as unlucky deaths, separate from avoidable ones |
| SurgE needs Python 3.12+ | Pin Python 3.12 in `pyproject.toml` |
| SurgE is AGPL-3.0 | Keep it unmodified in `vendor/`, used only by the test harness; run the viewer locally only. See D4 in [docs/decisions.md](docs/decisions.md) |
| SurgE's own quirks (random special condition always "None", Train-E mode changes game rules) skew tests | Harness works around each one; listed in [AGENTS.md](AGENTS.md#surge-gotchas) |

## 13. Open questions

- Q1. Should the default threshold profile be `surge` or `wiki`? Until decided, the default is `surge`, because all testing runs on SurgE.
- Q2. Should modifiers be in the benchmark grid, or only no-modifier runs for the MVP? Until decided, the grid has no modifiers and a separate smaller modifier run. The owner plays at skill 100 with the Exquisite Bone Saw (2% skill fails), so that setup is the headline benchmark alongside the full grid (D12).
- Q3. Which license should this repository use? Until decided, there is no license file.

## 14. References

- [CantFindDev/SurgE](https://github.com/CantFindDev/SurgE), Release branch, commit `f606a00`: `core/patient.py`, `ui/surgery_view.py`, `cogs/surgery_cog.py`, `data/*.json`
- [Guide:Surgery, Growtopia Wiki (Fandom)](https://growtopia.fandom.com/wiki/Guide:Surgery)
- [Guide:Surgery, growtopiawiki.com](https://growtopiawiki.com/w/Guide:Surgery)
