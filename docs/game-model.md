# Game model

How a SurgE surgery works, read from the source at commit `f606a00` (`core/patient.py`, `ui/surgery_view.py`, `cogs/surgery_cog.py`, `data/*.json`). The advisor's rules and forecast are built on these exact mechanics. When this file and SurgE disagree, SurgE wins: fix this file.

Every tool takes one turn. After the tool's own effect, SurgE runs a fixed per-turn update (see [What happens every turn](#what-happens-every-turn)).

## Skill fails

Every tool, including Fix It, rolls for a skill fail before it takes effect.

| Modifier | Fail rate | Skill 0 | Skill 50 | Skill 100 |
| --- | --- | --- | --- | --- |
| None | round(30 − skill ÷ 4) | 30% | 18% | 5% |
| Stethoscope | round((30 − skill ÷ 4) ÷ 2) | 15% | 9% | 2% |
| Tea, Exquisite Bone Saw, Nano Nurse Bot | round(35 − skill ÷ 3) | 35% | 18% | 2% |

- Dirt does not change the fail rate in SurgE, even though Train-E's "Poor visibility" tip says it does.
- Nano Nurse Bot also has a 2% chance per tool to not use up the tool. That only affects the tools-used count, not the surgery.

## What the screen shows

Most vitals are shown as words, not numbers. The advisor sees only the words.

| Readout | Screen-state value | Hidden value behind it |
| --- | --- | --- |
| Pulse (max 40) | `strong` / `steady` / `weak` / `extremely_weak` | 31+ / 21–30 / 11–20 / 10 or less |
| Status | `awake` / `coming_to` / `unconscious` / `heart_stopped` | sleep 0 / sleep 1–2 / sleep 3+ / heart damage above 0 |
| Operation site | `clean` / `not_sanitized` / `unclean` / `unsanitary` | sanitation 1+ / −1 to 0 / −3 to −2 / below −3 |
| Visibility | `clear` / `hard_to_see` / `cant_see` | dirt 0–3 / 4–9 / 10+ |
| Bleeding | `null` / `slowly` / `losing` / `very_quickly` | 0 or less / 1 / 2–3 / 4+ |
| Fever (shown only when fever > 0 and temperature > 100°F) | `null` / `slowly_rising` / `climbing` / `climbing_fast` | – / under 0.5 per turn / 0.5–2 / over 2 |
| Temperature | Number | Exact |
| Incisions | Number | Exact (the count turns green at the needed number) |
| Bones | Broken and shattered counts | Hidden until Ultrasound |
| Diagnosis | Scan text | Hidden until Ultrasound ("The patient has not been diagnosed.") |

## Tools

"Site visible" means visibility is not `cant_see`. At `cant_see`, the Sponge is the only usable tool, **including when the heart has stopped**.

| Tool | Usable when | On success | On skill fail |
| --- | --- | --- | --- |
| Defibrillator | Heart stopped and site visible | Restarts the heart | Dirt +1; heart stays stopped |
| Sponge | Always | Dirt to 0 | Nothing |
| Anesthetic | Site visible | From Awake or Coming to: asleep, sleep 10 (5 if Hyperactive). **From Unconscious: kills the patient** | Dirt +1 |
| Scalpel | Site visible | Incision +1. **While Awake: kills the patient.** At or past the needed count: no cut, bleeding +1 | Still cuts, bleeding +1 (except on the final needed cut) |
| Stitches | Site visible | Closes 1 incision; if none are open, stops 1 bleeding | Nothing |
| Ultrasound | Not yet used and site visible | Shows diagnosis and bones, reveals a hidden condition | Nothing; stays usable |
| Antiseptic | Site visible | Sanitation to 20 | Nothing |
| Fix It | After Ultrasound, incisions at the needed count, not yet fixed. **Once unlocked it stays usable, even after every incision is stitched closed again** (SurgE never revokes it; its code comment says the real game behaves the same) | Fixes the malady | Nothing; try again |
| Lab Kit | Not yet used and site visible | Unlocks Antibiotics | Nothing; stays usable |
| Antibiotics | After a successful Lab Kit, site visible | Fever −3 (−1.5 if antibiotic-resistant), only if temperature > 98.6°F | Fever +1 |
| Transfusion | Site visible | Pulse +15 (max 40) | Dirt +1 |
| Splint | Site visible | Broken bones −1 | Bleeding +1 |
| Pins | Incision open and site visible | Shattered −1, broken +1 | Bleeding +1 |
| Clamp | Incision open and site visible | Bleeding −1 | Nothing |

### Traps: tools with nothing to treat

SurgE doesn't check that there is something to treat for three tools. Each one pushes a count below zero, and the surgery can then never succeed, because success needs those counts to be exactly 0. The screen shows nothing wrong.

| Tool | Used when | Result |
| --- | --- | --- |
| Clamp | No bleeding | Bleeding goes negative |
| Splint | No broken bones | Broken bones go negative |
| Pins | No shattered bones | Shattered goes negative, broken goes up |

Bones are hidden until Ultrasound, so Splint and Pins must never be used before diagnosis. The advisor's legality check blocks all three cases (see [decision-engine.md](decision-engine.md#legality-check)).

## What happens every turn

After the tool's effect, SurgE runs these steps in this order (`UpdatePatientValues`):

1. **Fix It unlock:** once Ultrasound has run and incisions reach the needed count, Fix It becomes usable.
2. **Dirt** rises by bleeding + open incisions.
3. **Pulse** falls by bleeding, plus 1 if any incision is open. Pulse below 1: the patient bled out.
4. **Fever:** capped at 4 per turn. If fever is at or above 0 and the site is dirty while bleeding (sanitation ≤ 2) or cut open (sanitation ≤ 4), fever rises 0.06. Then temperature rises by the fever (minimum 98.6°F).
5. **Heart:** while asleep, each tool except the Defibrillator has a **10% chance to stop the heart**. While stopped, heart damage rises every turn; at 3 the patient dies. If the heart is beating, sleep falls by 1.
6. **Awake bleeding:** if the patient is Awake with an incision open, bleeding rises by 1 (2 if Hemophiliac) and the patient "screams and flails".
7. **Sanitation** falls by dirt ÷ 3 (rounded down), plus 10 if Filthy. Minimum −25.
8. **Infection:** temperature 111°F or higher kills.
9. **Success:** the surgery ends successfully once the malady is fixed, bleeding is 0, incisions are 0, temperature is below 101°F, no bones are broken or shattered and the heart is beating. The patient may still be asleep.

### Consequences the rules rely on

- **Heart stop timing:** the heart stops on turn *t*. A Defibrillator fail on *t*+1 and another on *t*+2 kill the patient. The Defibrillator has two tries, and if the site is `cant_see`, one of those goes to the Sponge.
- **Sleep length:** Anesthetic sets sleep to 10, and the same turn's update takes it to 9. The patient then shows Unconscious for 7 turns (sleep 9 to 3) and Coming to for 2 (sleep 2 and 1). Hyperactive: Unconscious for 2 turns, Coming to for 2.
- **Coming to is not Awake:** Scalpel is safe and Anesthetic is safe while Coming to.
- **Negative fever sticks:** fever only rises while it is 0 or more. One Antibiotics dose that takes fever below zero makes the temperature fall every turn from then on, until 98.6°F. For example, Bird Flu at fever 2.5: one dose leaves fever at −1.75 per turn. Turtle Flu (fever 3.6) needs two doses; antibiotic-resistant patients need roughly twice as many.
- **Fever is invisible once negative:** the fever text disappears. A falling temperature is the only sign it worked.

## Special conditions

| Condition | ID | Visible at start | Effect |
| --- | --- | --- | --- |
| None | `none` | – | – |
| Tough Skin | `tough_skin` | Yes | +1 incision needed |
| Filthy | `filthy` | Yes | Sanitation falls 10 extra per turn |
| Hyperactive | `hyperactive` | Yes | Anesthetic sleep 5 instead of 10 |
| Antibiotic-Resistant Infection | `antibiotic_resistant` | No; Ultrasound reveals it | Antibiotics −1.5 fever instead of −3 |
| Hemophiliac | `hemophiliac` | No; Ultrasound reveals it | Scalpel stabs, Scalpel/Splint/Pins skill fails and awake flailing add 2 bleeding instead of 1 |

SurgE's random condition roll always returns None (the "None" entry matches every roll first). Tests always set the condition explicitly.

## Maladies

The advisor's lookup once Ultrasound reveals the diagnosis. Add 1 incision for Tough Skin. Names use SurgE's spelling. "Needs Fix It: No" means the malady counts as fixed from the start.

| Malady | Incisions needed | Needs Fix It | Broken / shattered bones | Starts with |
| --- | --- | --- | --- | --- |
| Bird Flu | 0 | No | – | 104.6°F, fever +2.5/turn, dirt 6 |
| Broken Arm | 0 | No | 1 / 0 | bleeding 1 |
| Monkey Flu | 0 | No | – | 107.6°F, fever +2.4/turn |
| Turtle Flu | 0 | No | – | 101.6°F, fever +3.6/turn, dirt 6 |
| Broken Heart | 1 | Yes | 0 / 2 | 107.6°F, fever +1.2/turn, dirt 2 |
| Broken Leg | 1 | No | 1 / 1 | bleeding 1 |
| Grumbleteeth | 1 | Yes | 0 / 1 | 104.6°F, pulse 20, dirt 5 |
| Lung Tumor | 1 | Yes | – | – |
| Nose Job | 1 | Yes | – | already diagnosed |
| Serious Head Injury | 1 | Yes | – | bleeding 4, pulse 20, dirt 6 |
| Brainworms | 2 | Yes | 0 / 1 | 100.58°F, fever +0.8/turn, bleeding 5, dirt 10 |
| Broken Everything | 2 | Yes | 0 / 4 | 100.58°F, bleeding 1, dirt 6 |
| Chicken Feet | 2 | Yes | 0 / 2 | fever +1.56/turn, dirt 10 |
| Gem Cuts | 2 | Yes | – | bleeding 1 |
| Heart Attack | 2 | Yes | – | – |
| Kidney Failure | 2 | Yes | – | 101.6°F, fever +1.2/turn |
| Liver Infection | 2 | Yes | – | 104.6°F |
| Moldy Guts | 2 | Yes | 0 / 1 | 104.6°F, fever +1.98/turn, pulse 20 |
| Serious Trauma | 2 | Yes | 2 / 1 | bleeding 3, pulse 30, dirt 10 |
| Swallowed a World Lock | 2 | Yes | – | 101.6°F, bleeding 1, dirt 6 |
| Appendicitis | 3 | Yes | – | 104.6°F, fever +1.2/turn, pulse 30 |
| Chaos Infection | 3 | Yes | 2 / 0 | 105.6°F, fever +2.6/turn, bleeding 3, dirt 10 |
| Fatty Liver | 3 | Yes | – | 101.6°F, fever +2.0/turn, bleeding 3, dirt 10 |
| Herinated Disc | 3 | Yes | – | 100.4°F |
| Massive Trauma | 3 | Yes | 2 / 2 | bleeding 4, pulse 30, dirt 10 |
| Torn Punching Muscle | 3 | Yes | – | dirt 15 |
| Brain Tumor | 5 | Yes | – | – |

Every patient starts at pulse 40, 98.6°F, no fever, bleeding 0 and dirt 0 unless the table says otherwise. Starting fever is the per-turn rise; it applies from the first turn.

## Where SurgE and the real game differ

| Item | SurgE | Real game (wiki) | Profile |
| --- | --- | --- | --- |
| Temperature needed for success | Below 101°F | Below 100.4°F | `success_temp_f` |
| Hyperactive anesthetic | Sleep 5 | 4 turns asleep | `hyperactive_sleep` |
| Effect of dirt on skill fails | None | Train-E text says it raises them | `dirt_raises_fails` |

These live in the `surge` and `wiki` profiles in `src/advisor/config.py`. The default is `surge` until PRD open question Q1 is decided.

## Sources

- [CantFindDev/SurgE](https://github.com/CantFindDev/SurgE), Release branch, commit `f606a00`
- [Guide:Surgery, Growtopia Wiki (Fandom)](https://growtopia.fandom.com/wiki/Guide:Surgery)
- [Guide:Surgery, growtopiawiki.com](https://growtopiawiki.com/w/Guide:Surgery)
