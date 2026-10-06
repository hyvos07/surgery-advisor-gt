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
| D13 | 2026-10-05 | Fix P5 re-cutting after Fix It; Sponge only at `cant_see` | Accepted |
| D14 | 2026-10-05 | `minimal` Antiseptic becomes the default mode | Accepted, applied in M3 |
| D15 | 2026-10-05 | Close the incisions before Fix It, and do Fix It last | Accepted, applied in M3 |
| D16 | 2026-10-06 | Treat a fever only above 100.4 F | Accepted, applied in M3 |
| D17 | 2026-10-06 | Reset the PRD section 10 targets from the M3 benchmark | Accepted |
| D18 | 2026-10-06 | In M4, success comes before tools | Accepted |
| D19 | 2026-10-06 | Tune on seeds 0-199, report the final numbers on fresh seeds | Accepted |
| D20 | 2026-10-06 | License the repository under AGPL-3.0 | Accepted, not yet applied |
| D21 | 2026-10-06 | Optional manual-input mode in the web viewer | Accepted, applied in M4 |
| D22 | 2026-10-06 | Transfuse only when the pulse could bleed out | Accepted, applied in M4 |
| D23 | 2026-10-06 | One-turn avoidable deaths use the shared-roll test | Accepted, not yet applied |

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

## D13. Fix P5 re-cutting after Fix It; Sponge only at `cant_see`

- **Context:** the first build of the draft rules won 20.9% in the owner's setup and 17.8% over the full grid, below the Train-E baseline. Two loops caused most of it. P5 cut again after every Stitches once the malady was fixed, so P5 and P6 alternated until the turn cap. E2's "hard to see" branch sponged every turn while bleeding and open incisions kept adding dirt, holding back the Anesthetic, the Clamp and the Transfusion (E2 was the last rule in 357 of 538 deaths in a 648-surgery sample).
- **Decision:** a cut is needed only while a Fix It malady is unfixed and below its incision count, or to reach shattered bones with no incision open. E2 fires only at `cant_see`; the dirt guard margin is removed. The owner chose "sponge only when the site can't be seen" over a capped pre-emptive Sponge, accepting that a heart that stops while the site can't be seen gets one Defibrillator try instead of two.
- **Why (benchmark, 200 runs per cell, draft Antiseptic mode):**

  | | Owner's setup, before | after | Full grid, before | after |
  | --- | ---: | ---: | ---: | ---: |
  | Success | 20.9% | 96.2% | 17.8% | 67.7% |
  | Avoidable deaths | 5,232 | 82 | 47,847 | 3,583 |
  | Timeouts | 17,334 | 63 | 24,739 | 994 |
  | Tools per success | 6.7 | 17.2 | 7.9 | 18.7 |

  Tools per success rose because the advisor now wins the long surgeries it used to lose; on the same cells it uses about 1.2 more tools per success than the Train-E baseline (0.6 more in `minimal` Antiseptic mode). `minimal` Antiseptic mode scored slightly better (96.6% owner's setup, 68.7% full grid, fewer tools); the default stays `draft` until the owner decides. Zero illegal moves in every run.
- **Revisit if:** M3's death analysis shows deaths from a stopped heart behind a `cant_see` site, especially at low skill.

## D14. `minimal` Antiseptic becomes the default mode

- **Context:** D13's benchmark ran both Antiseptic modes. `minimal` scored slightly better everywhere: 96.6% against 96.2% in the owner's setup, 68.7% against 67.7% over the full grid, and about 0.45 fewer tools per success.
- **Decision:** the owner chose `minimal` as the default.
- **Result (benchmark, 200 runs per cell, with D15 applied, `draft` before and `minimal` after):**

  | | Owner's setup, draft | minimal | Full grid, draft | minimal |
  | --- | ---: | ---: | ---: | ---: |
  | Success | 96.7% | 97.1% | 70.9% | 71.4% |
  | Avoidable deaths | 76 | 59 | 3,414 | 3,352 |
  | Timeouts | 40 | 33 | 932 | 911 |
  | Tools per success | 16.3 | 16.0 | 18.0 | 17.7 |

  Zero illegal moves. The 5-run quick benchmark showed the opposite (72.8% against 74.0%); at 5 runs per cell that gap is noise, and the 200-run results decide.
- **Status:** applied in M3. The `advisor` policy uses `minimal`; `draft` stays selectable as the `advisor-draft-antiseptic` policy, which replaces `advisor-min-antiseptic` (older reports and the D13 text use that name).
- **Revisit if:** M3's death analysis ties deaths to an unclean site or infection.

## D15. Close the incisions before Fix It, and do Fix It last

- **Context:** the owner noticed that Fix It stays usable after the incisions are stitched closed again. Checked in SurgE: `_UpdateFixability` sets "fixable" once the needed incisions are reached and never clears it until Fix It succeeds. In 19 of 20 seeded Heart Attack surgeries, cut, close, then Fix It as the very last tool ended in success.
- **Decision:** once Fix It is unlocked, close every incision first (Pins on shattered bones still come before closing), then use Fix It with no incision open.
- **Why:** each turn with an incision open costs pulse, adds dirt and raises the fever risk, and an awake patient with one open bleeds more every turn. A Fix It skill fail then costs a turn with the site closed instead of open, and the patient may already be awake, with no heart-stop risk and no need to re-dose the Anesthetic.
- **Planned rule change (rule IDs unchanged):**
  - Memory gains `fix_unlocked`: true once Fix It appears in `usable_tools` or the scan text shows the malady's fix text, until Fix It succeeds.
  - P5 (Cut): no cut for Fix It once it is unlocked.
  - P6 (Close): also fires when Fix It is unlocked but not done yet.
  - P3 (Fix): fires only when no incision is open.
- **Tests to write first:** a Heart Attack at its needed incisions with Fix It unlocked and the patient asleep gets Stitches (P6), not Fix It; the same patient with 0 incisions gets Fix It (P3) and P5 stays silent; a Broken Heart with a shattered bone gets Pins before any closing.
- **Result (benchmark, 200 runs per cell, draft Antiseptic mode, against the D13 rules):**

  | | Owner's setup, before | after | Full grid, before | after |
  | --- | ---: | ---: | ---: | ---: |
  | Success | 96.2% | 96.7% | 67.7% | 70.9% |
  | Avoidable deaths | 82 | 76 | 3,583 | 3,414 |
  | Unlucky deaths | 1,073 | 939 | 47,764 | 42,752 |
  | Timeouts | 63 | 40 | 994 | 932 |
  | Tools per success | 17.2 | 16.3 | 18.7 | 18.0 |

  The gain grows as skill falls (+1.1 points at skill 100, +5.0 at skill 0), where fewer turns with an incision open matter most. Zero illegal moves.
- **Status:** applied in M3.

## D16. Treat a fever only above 100.4 F

- **Context:** the paired `surg tools` comparison showed P2 spending about 1 Lab Kit and 1 Antibiotics per success on short surgeries (Broken Arm, Heart Attack, Lung Tumor, Nose Job) that the Train-E baseline finishes below 101 F without treating the fever.
- **Decision:** the owner chose "only use Antibiotics when the temperature is above 100.4 F". 100.4 F is the real game's finish threshold (the `wiki` profile's `success_temp_f`; SurgE's is 101).
- **Why:** a fever below the finish threshold costs two tools and does nothing for the result unless the surgery runs long enough to push the temperature over it.
- **Rule change (rule IDs unchanged):** P2 also requires the temperature to be strictly above `FEVER_TREAT_F` (100.4 F, in `config.py`, the same under the `surge` and `wiki` profiles). This gates Lab Kit and Antibiotics alike, since P2 chooses between them. E6 (fever climbing fast, or a forecast reaching the crisis temperature) and P11 (temperature at or above the finish threshold) are unchanged.
- **Result (benchmark, 200 runs per cell, before and after; paired tools are the advisor and the Train-E baseline on surgeries both win):**

  | | Owner's setup, before | after | Full grid, before | after |
  | --- | ---: | ---: | ---: | ---: |
  | Success | 97.1% | 97.2% | 71.43% | 71.36% |
  | Avoidable deaths | 59 | 61 | 3,352 | 3,827 |
  | Timeouts | 33 | 15 | 911 | 700 |
  | Tools per success | 16.0 | 15.2 | 17.7 | 16.6 |
  | Paired tools per success, advisor vs baseline | 12.0 vs 12.6 | 10.1 vs 12.6 | 12.3 vs 12.9 | 10.1 vs 12.9 |

  Zero illegal moves. Over the full grid the Lab Kit and Antibiotics gap on paired wins fell from about +1 each to +0.17 and +0.18. Success moved by +0.1 points in the owner's setup and -0.07 over the full grid, but the avoidable deaths rose by 475 there, and the short and long surgeries moved in opposite directions: Heart Attack +4.4 points, Nose Job +4.1, Lung Tumor +2.7, Serious Head Injury +1.5, against Serious Trauma -4.1, Broken Leg -2.9, Massive Trauma -2.9, Torn Punching Muscle -2.7 and Gem Cuts -2.1.
- **Status:** applied in M3.
- **Revisit if:** deaths from fever or infection rise in the M3 death analysis, or the `antibiotic_resistant` condition loses success.

## D17. Reset the PRD section 10 targets from the M3 benchmark

- **Context:** the first targets were guesses. M3 measured the advisor (D14, D15 and D16 applied) at 97.2% in the owner's setup, 93.7% at skill 100 and 47.3% at skill 0 with no modifier, 71.4% over the full grid, zero illegal moves, one-turn avoidable deaths of 0.19% (owner's setup) and 2.4% (full grid), 10.1 tools per success against the Train-E baseline's 12.9 on surgeries both won, and 0.02 ms per decision. "Zero avoidable deaths" mixed two things: illegal moves, which must never happen, and deaths another tool might have prevented, which a 3-turn lookback finds in 316 of 882 deaths in the owner's setup and partly reflect luck.
- **Decision (owner):** zero illegal moves; one-turn avoidable deaths at most 0.1% of surgeries in the owner's setup and 1% over the full grid; success at least 98% in the owner's setup, 95% at skill 100 and 50% at skill 0; at least 20% fewer tools per success than the baseline on paired wins, and never more than 1 tool worse for any malady; decisions under 10 ms. The 3-turn lookback count is tracked without a target.
- **Why:** each target is measurable with `surg bench`, `surg tools` and `surg report`, sits just beyond the M3 result, and keeps the owner's priority of using as few tools as possible.
- **Revisit if:** M4 meets every target early, or one proves unreachable without hurting another.

## D18. In M4, success comes before tools

- **Context:** some fixes raise success at the cost of tools (Antibiotics for Brainworms, M3), and some save tools at the cost of success (D16 on long trauma surgeries).
- **Decision (owner):** accept a rule or margin change when success rises and the D17 tools target still holds: at least 20% fewer tools per success than the Train-E baseline on paired wins, and no malady more than 1 tool worse.
- **Why:** a dead patient costs more than a spare tool, and the tools target already keeps the advisor lean.
- **Revisit if:** the tools target stops holding.

## D19. Tune on seeds 0-199, report the final numbers on fresh seeds

- **Context:** M4 tunes rules and margins against the same 200 seeds per cell, so the rules may fit those exact surgeries.
- **Decision (owner):** `surg bench` gains a seed offset. Tuning and every before/after comparison use seeds 0-199; the final MVP numbers in the README come from seeds 1000-1199, which tuning never saw.
- **Why:** a gap between the two shows overfitting; no gap means the numbers can be trusted.
- **Revisit if:** the fresh-seed results fall well below the tuning seeds.

## D20. License the repository under AGPL-3.0

- **Context:** the owner will make the repository public at MVP (PRD Q3). The harness and viewer run SurgE's AGPL-3.0 code; the advisor itself never imports it.
- **Decision (owner):** AGPL-3.0 for the whole repository, the same as SurgE.
- **Why:** no grey area about combining with SurgE; the advisor stays free to use, and anyone hosting a modified version must publish its source.
- **Status:** accepted, not yet applied. Adding `LICENSE` and updating the README credits is an M4 task, before the repository goes public. D4's "revisit if published" is answered by this.

## D21. Optional manual-input mode in the web viewer

- **Context:** the advisor only played SurgE surgeries. To use it beside the real game, the player has to tell it what the screen shows.
- **Decision (owner):** add a manual mode to `surg web` as an option next to the simulator mode, which stays unchanged. The player enters the screen-state fields (PRD section 8), presses Advise and gets the tool, rule and reason; memory carries across turns until a new patient is started.
- **Why:** it makes the MVP usable while playing without any connection to the game, so hard rule 8 is untouched.
- **Status:** applied in M4: a Manual tab in `surg web`, with the tool tray pre-ticked from the game's tray rules (the same as `harness/observe.py`), which the player can override.

## D22. Transfuse only when the pulse could bleed out

- **Context:** Brainworms in the owner's setup (skill 100, Exquisite Bone Saw) died of infection at 111 F on turn 10. E2 forced a Sponge every other turn (`cant_see`), and on the free turns E3 saw a `weak` pulse, forecast `extremely_weak` (the word's floor, 11, minus the `very_quickly` bleed cap, 6, gives 5) and transfused, so E6's Antibiotics never got a turn. In SurgE the patient bleeds out only when the pulse falls below 1 ([game-model.md](game-model.md)); "extremely weak" is just a word.
- **Decision (owner approved):** E3 fires when the worst-case `pulse_floor` is below `PULSE_BLED_OUT` (1, in `config.py`), instead of when its pulse word would be `extremely_weak`. The reason names the turns ahead from the margin ("Pulse could fall below 1 next turn and bleed out", or "within 2 turns").
- **Why:** a transfusion that cannot change the outcome costs the turn that Antibiotics, Clamp or Stitches needed. The forecast keeps its pessimism (upper bound of each hidden bleed); only the danger line moves from a word to the real death point.
- **Rule change (rule IDs unchanged):** E3's guard only. `Forecast.pulse_word_next` is still computed (the forecast tests and schema check cover it) but no rule uses it now.
- **Result (benchmark, 200 runs per cell, before and after; avoidable is the one-turn lookback; paired tools are the advisor and the Train-E baseline on surgeries both win):**

  | | Owner's setup, seeds 0-199, before | after | Owner's setup, fresh seeds 1000-1199, before | after | Full grid, before | after |
  | --- | ---: | ---: | ---: | ---: | ---: | ---: |
  | Success | 97.2% | 98.1% | 96.9% | 97.7% | 71.4% | 72.9% |
  | Avoidable deaths | 61 | 51 | 45 | 45 | 3,827 | 3,620 |
  | Timeouts | 15 | 1 | 10 | 1 | 700 | 129 |
  | Tools per success | 15.2 | 14.7 | 15.1 | 14.6 | 16.6 | 16.1 |
  | Paired tools per success, advisor vs baseline | 10.1 vs 12.6 | 10.1 vs 12.6 | 10.0 vs 12.4 | 9.9 vs 12.4 | 10.1 vs 12.9 | 10.1 vs 12.9 |

  Zero illegal moves in every report. Brainworms in the owner's setup rose from 67.2% to 89.2% on seeds 0-199 and from 69.8% to 88.6% on fresh seeds. Over the full grid the gain was +2.8 points at skill 0 (47.3% to 50.0%), +0.8 at skill 100 (93.7% to 94.5%) and +3.0 at skill 25. The quick benchmark (5 runs per cell) went from 72.2% to 74.4%. The worst malady on paired tools over the full grid is Torn Punching Muscle at +0.5 tools against the baseline, inside the D17 limit of 1.
- **Risk:** bleed-outs rise: a pulse that stays above 1 in the worst case can still fall below it after a Sponge skill fail (a 2% chance in the owner's setup) on a `cant_see` turn at a low pulse. Massive Trauma went slightly down: 97.5% to 96.4% in the owner's setup, 96.9% to 96.4% on fresh seeds, and -0.8 points over the full grid, with its avoidable deaths up from 0 to 5 (seeds 0-199) and 4 (fresh).
- **Status:** applied in M4.
- **Revisit if:** bleed-out deaths become a top cause of death in M4 reports.

## D23. One-turn avoidable deaths use the shared-roll test

- **Context:** the D17 target for one-turn avoidable deaths counts a death as avoidable when another tool merely survives the fatal turn. A skill-failed Antibiotics dose adds fever, so on such a turn almost any other tool "survives" it, even though the patient dies the next turn anyway. The deeper lookback had the same kind of bias and was fixed with shared rolls and an original-tool control (M4).
- **Decision (owner):** at the fatal turn, use the same test as the deeper check: another tool must win 2 of 3 rollouts with shared random draws while the advisor's own tool does not. The D17 limits stay: at most 0.1% of surgeries in the owner's setup and 1% over the full grid. Illegal moves still count as avoidable.
- **Why:** the target should measure decisions, not skill-fail luck.
- **Status:** accepted, not yet applied. Note that `--lookback 1` will no longer reproduce the M1-M3 one-turn numbers; earlier reports stay comparable only with each other.
