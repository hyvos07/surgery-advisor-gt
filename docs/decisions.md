# Decisions

Choices someone might later question, with the reason and what would reopen them. Newest at the bottom. Add an entry when a benchmark result changes a rule, a target changes, or an open question in [PRD.md](../PRD.md#13-open-questions) is settled.

| ID | Date | Decision | Status |
| --- | --- | --- | --- |
| D1 | 2026-09-23 | Hand-written rule engine, not a trained model | Accepted |
| D2 | 2026-09-23 | Not using Jev or another hosted model | Accepted |
| D3 | 2026-09-23 | SurgE as the test bed, unmodified and pinned | Accepted |
| D4 | 2026-09-23 | Keep the advisor separate from SurgE's AGPL code; local viewer only | Accepted |
| D5 | 2026-09-23 | Decide only from what a player can see | Accepted |
| D6 | 2026-09-23 | Keep the patient awake as long as possible | Accepted, to be checked at M3 |
| D7 | 2026-09-23 | Step-by-step web viewer as a test tool | Accepted |
| D8 | 2026-10-05 | `surge` threshold profile as the default | Provisional (PRD Q1) |
| D9 | 2026-10-05 | Python 3.12, uv, pytest, ruff, mypy, FastAPI | Accepted |
| D10 | 2026-10-05 | `usable_tools` derived from on-screen text, plus three tray flags | Accepted |
| D11 | 2026-10-05 | `train-e-plus` as a second reference; pure Train-E stays the target | Accepted |
| D12 | 2026-10-05 | Owner's setup (skill 100, Exquisite Bone Saw) is the headline benchmark | Accepted |

## D1. Hand-written rule engine, not a trained model

- **Context:** the advisor could be a hand-written rule list, a trained decision tree, or some other learned model.
- **Decision:** an ordered list of hand-written rules with a legality check.
- **Why:** SurgE's source contains the complete rules, so nothing needs to be learned. There is no labelled dataset. A rule list is already a decision tree, and it is easier to debug and explain one rule at a time.
- **Revisit if:** the benchmark plateaus well below target and the failing cases can't be expressed as rules. Even then, the first step would be a search over rule order and margins, not a model.

## D2. Not using Jev or another hosted model

- **Context:** TypeSafe's Jev returns typed decisions with probabilities and was considered early on.
- **Decision:** no hosted model in the decision loop.
- **Why:** surgery decisions follow known rules exactly, which Jev's own documentation says not to hand to a model. Rules are also free, instant, deterministic and work offline. Jev was waitlisted, has no fine-tuning, and each call is a network round trip of 70–500 ms.
- **Revisit if:** M5 needs to interpret messy screen text that simple parsing can't handle.

## D3. SurgE as the test bed, unmodified and pinned

- **Context:** the advisor needs a simulator to run thousands of surgeries.
- **Decision:** use [CantFindDev/SurgE](https://github.com/CantFindDev/SurgE) as a git submodule at `vendor/SurgE`, pinned to commit `f606a00`, never edited.
- **Why:** it is open source, implements every malady, condition and modifier, and its `Patient` class runs without Discord. Not editing it means test results always reflect SurgE as published, and upgrades are a submodule bump.
- **Revisit if:** SurgE changes its game logic upstream. Bump the pin deliberately and re-run the full benchmark.

## D4. Keep the advisor separate from SurgE's AGPL code; local viewer only

- **Context:** SurgE is licensed AGPL-3.0, which requires sharing source when the software is distributed or offered as a network service.
- **Decision:** `src/advisor/` never imports SurgE code; it only reads SurgE's JSON data files. Only `src/harness/` imports SurgE. The web viewer binds to `127.0.0.1`.
- **Why:** the advisor stays independent of SurgE and reusable on the real game, and running everything locally avoids the network-service clause.
- **Revisit if:** the project is published or the viewer is hosted. Check the licensing then; this is not legal advice.

## D5. Decide only from what a player can see

- **Context:** SurgE exposes exact hidden values (pulse number, sleep level, dirt) that the real game never shows.
- **Decision:** the screen-state JSON contains only on-screen information. Memory may count turns, never read hidden values.
- **Why:** the same advisor must work on the real game screen later (M5). Peeking would make benchmark results meaningless for the real game.
- **Revisit if:** never, for the advisor. Debug tooling in the harness may show hidden values, clearly labelled.

## D6. Keep the patient awake as long as possible

- **Context:** SurgE stops the heart with 10% chance per tool, but only while the patient is asleep.
- **Decision:** do all awake-safe work before the Anesthetic; once cut open, stay asleep until closed. Maladies with no incisions never get Anesthetic.
- **Why:** fewer turns asleep means fewer heart stops, which matters most at low skill where each Defibrillator try fails 30% of the time.
- **Revisit if:** M3 shows that prep turns cost more (in pulse or temperature) than the heart-stop risk they save.

## D7. Step-by-step web viewer as a test tool

- **Context:** reading JSON logs is a slow way to understand why a surgery failed.
- **Decision:** a local web page that plays a SurgE surgery one Next press at a time, showing the advisor's pick, rule and reason, and that benchmark reports link into by seed.
- **Why:** seeing a failing surgery turn by turn is the fastest way to find the rule that went wrong.
- **Revisit if:** –

## D8. `surge` threshold profile as the default

- **Context:** SurgE and the real game disagree on a few thresholds (success below 101°F vs 100.4°F; Hyperactive sleep 5 vs 4).
- **Decision:** default to the `surge` profile; keep a `wiki` profile alongside.
- **Why:** every test in the MVP runs on SurgE, so its thresholds are the ones that decide pass or fail.
- **Revisit if:** the owner answers PRD open question Q1, or work on M5 starts.

## D9. Python 3.12, uv, pytest, ruff, mypy, FastAPI

- **Context:** SurgE is Python 3.12; the harness imports it directly.
- **Decision:** Python 3.12+ managed with uv; pytest for tests; ruff for lint and format; mypy strict on the advisor; FastAPI and uvicorn for the viewer only. The advisor itself uses only the standard library.
- **Why:** one language end to end, with no glue between the advisor and SurgE. Keeping the advisor dependency-free keeps it easy to reuse.
- **Revisit if:** –

## D10. `usable_tools` derived from on-screen text, plus three tray flags

- **Context:** SurgE's tool tray decides which buttons are enabled from hidden values: `HeartDamage > 0` for the Defibrillator and `SiteDirtyness < 10` for "site workable". The real game will not give the advisor either number (D5), and AGENTS hard rule 2 forbids reading them.
- **Decision:** `observe.py` derives `usable_tools` from the screen. Defibrillator is the "Heart Stopped!" status, a workable site is the absence of "You can't see what you are doing!", Pins and Clamp need an open incision, Ultrasound needs no diagnosis. Fix It, Lab Kit and Antibiotics have no text, so `observe.py` reads SurgE's `IsFixable`, `IsLabKitUsed` and `LabWorked` flags, which are the tray's button state.
- **Why:** the advisor sees the same things on the real game, where the tray itself is on screen. `tests/harness/test_observe.py` checks the derived list against a copy of SurgE's tray conditions on 300 random surgeries, and scans `observe.py` for the hidden names.
- **Revisit if:** SurgE changes its tray (a bump of the pin), or M5 shows the real tray can't be read reliably.

## D11. `train-e-plus` as a second reference; pure Train-E stays the target

- **Context:** the pure Train-E baseline stalls on patients its tips don't cover (Pins with no incision, Stitches before Pins, a high temperature with no fever), so a large share of its failures say little about how good a real strategy is.
- **Decision:** add `train-e-plus`, which plays identically to `baseline` wherever Train-E has a usable tip and patches only the three known gaps (TP1 to TP3 in [testing.md](testing.md#second-reference-policy-train-e-plus)); the one place it overrides a usable tip is TP3. The PRD section 10 targets keep comparing against `baseline`.
- **Why:** it separates "the advisor beats SurgE's own hints" from "the advisor only fixed two holes", without moving the target. It can't make `baseline` look worse or better, because `baseline` is untouched.
- **Revisit if:** more gaps are found. Add them to `train-e-plus` only, and record the change here.

## D12. Owner's setup (skill 100, Exquisite Bone Saw) is the headline benchmark

- **Context:** the owner plays at skill 100 with the Exquisite Bone Saw. In SurgE every modifier except the Stethoscope sets the fail rate to round(35 − skill ÷ 3), so this setup fails 2% of the time, against 5% at skill 100 with no modifier (at skill 0 the Bone Saw is worse: 35% against 30%). The Bone Saw has no other effect in SurgE.
- **Decision:** report a benchmark of all 27 maladies × 6 conditions at skill 100 with the Exquisite Bone Saw first, then the full grid. The full grid and the PRD section 10 targets are unchanged, and the advisor must still handle every skill level and modifier (FR6).
- **Why:** it measures the advisor where it will be used, without dropping the coverage that keeps it general.
- **Revisit if:** the owner's setup changes, or PRD open question Q2 is settled.
