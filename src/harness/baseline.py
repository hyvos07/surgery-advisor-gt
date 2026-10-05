"""Train-E baseline policy."""

import re
from typing import Any

from harness.observe import strip_formatting
from harness.surge import Patient, train_e_tips

# Tip heading -> tool, from docs/testing.md. Headings are matched by prefix,
# because SurgE writes "Losing Blood very quickly" and "Losing Blood" differently.
_HEADING_TOOLS: list[tuple[str, str]] = [
    ("Heart Stopped", "defibrillator"),
    ("Awake", "anesthetic"),
    ("Stitch it Up!", "stitches"),
    ("Fix It!", "fix_it"),
    ("Clean the Area", "antiseptic"),
    ("Prep Patient", "anesthetic"),
    ("Make an Incision!", "scalpel"),
    ("Poor Visibility", "sponge"),
    ("Diagnosis", "ultrasound"),
    ("Losing Blood", "clamp_or_stitches"),
    ("Shattered Bone", "pins"),
    ("Broken Bone", "splint"),
    ("Fever", "lab_kit_or_antibiotics"),
    ("High Fever", "lab_kit_or_antibiotics"),
    ("Antibiotics", "antibiotics"),
    ("Extremely Weak Pulse", "transfusion"),
    ("Coming To", "anesthetic"),
]


# SurgE writes the low-bleeding tip as a bare "Losing Blood" with no newline
# (an operator-precedence slip in `_UpdateTrainEText`), so the next tip is glued on:
# "Losing BloodShattered Bone - ...". Split it back apart.
_BARE_LOSING_BLOOD = re.compile(r"Losing Blood(?! very quickly| - )")


def parse_tips(text: str) -> list[tuple[str, str]]:
    """Split SurgE's tip text into (heading, description) pairs, in SurgE's order."""
    tips = []
    for raw in text.splitlines():
        line = _BARE_LOSING_BLOOD.sub("Losing Blood\n", strip_formatting(raw))
        for part in line.splitlines():
            if part := part.strip():
                heading, _, description = part.partition(" - ")
                tips.append((heading.strip(), description.strip()))
    return tips


def tip_tool(heading: str, description: str, incisions: int) -> str | None:
    """The tool a tip asks for, or None for a heading the baseline doesn't know."""
    # The longest matching heading wins, so "High Fever" isn't taken for "Fever".
    matches = [
        (prefix, tool) for prefix, tool in _HEADING_TOOLS if heading.startswith(prefix)
    ]
    if not matches:
        return None
    _, tool = max(matches, key=lambda match: len(match[0]))
    if tool == "clamp_or_stitches":
        return "clamp" if incisions > 0 else "stitches"
    if tool == "lab_kit_or_antibiotics":
        # The fever tip itself says to do the Lab Kit first until it has been done.
        return "lab_kit" if "Lab Kit" in description else "antibiotics"
    return tool


SUCCESS_TEMP_F = 101  # SurgE: success needs a temperature below this


def _pick(tool: str, rule: str, reason: str) -> dict[str, str]:
    return {"tool": tool, "rule": rule, "reason": reason[:99]}


def baseline_policy(state: dict[str, Any], patient: Patient) -> dict[str, str]:
    """Take SurgE's first Train-E tip whose tool is usable, else the Sponge."""
    for heading, description in parse_tips(train_e_tips(patient)):
        tool = tip_tool(heading, description, state["incisions"])
        if tool is not None and tool in state["usable_tools"]:
            return {
                "tool": tool,
                "rule": "TE",
                "reason": f"Train-E: {heading}"[:99],
            }
    return {
        "tool": "sponge",
        "rule": "TE0",
        "reason": "No usable Train-E tip; using the Sponge"[:99],
    }


def train_e_plus_policy(state: dict[str, Any], patient: Patient) -> dict[str, str]:
    """Train-E, plus fixes for three things its tips get wrong or never say.

    Wherever Train-E has a usable tip this plays it exactly as `baseline` does,
    with one exception (TP3). Otherwise, instead of giving up with the Sponge:
    TP1  Train-E treats only a fever it can see, so patients who start hot with no
         fever stay above the success temperature: Lab Kit, then Antibiotics.
    TP2  Train-E asks for Pins but never says to cut first: open the incision.
    TP3  Train-E's "Stitch it Up!" outranks "Shattered Bone", so it closes the
         incision before Pins can be used, and TP2 then reopens it forever:
         use the Pins first.
    """
    decision = baseline_policy(state, patient)
    usable = state["usable_tools"]
    bones = state["bones"]
    shattered = bones["shattered"] if bones else 0

    if (
        decision["tool"] == "stitches"
        and shattered > 0
        and state["incisions"] > 0
        and "pins" in usable
    ):
        return _pick("pins", "TP3", "Pin the bones before closing the incision")
    if decision["rule"] != "TE0":
        return decision

    if state["temperature"] >= SUCCESS_TEMP_F and state["fever"] is None:
        if "lab_kit" in usable:
            return _pick("lab_kit", "TP1", "Hot, no fever shown: Train-E is silent")
        just_dosed = state["last_tool_text"].startswith("You used antibiotics")
        if "antibiotics" in usable and not just_dosed:
            return _pick("antibiotics", "TP1", "Hot, no fever shown: Train-E is silent")

    if shattered > 0 and state["incisions"] == 0 and state["status"] != "heart_stopped":
        tool = "anesthetic" if state["status"] == "awake" else "scalpel"
        if tool in usable:
            return _pick(tool, "TP2", "Pins need an open incision; Train-E skips it")
    return decision
