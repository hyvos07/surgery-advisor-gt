"""Train-E baseline policy."""

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


def parse_tips(text: str) -> list[tuple[str, str]]:
    """Split SurgE's tip text into (heading, description) pairs, in SurgE's order."""
    tips = []
    for raw in text.splitlines():
        if line := strip_formatting(raw):
            heading, _, description = line.partition(" - ")
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
