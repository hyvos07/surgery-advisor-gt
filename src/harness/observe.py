"""Builds screen-state JSON from a SurgE Patient's on-screen text only."""

import re
from typing import Any

from harness.surge import NOT_DIAGNOSED, TOOL_IDS, Patient

# Every field below comes from a text SurgE shows the player. Never read the
# hidden numbers (pulse, sleep level, dirt, sanitation, fever, heart damage,
# incisions needed): tests/harness/test_observe.py scans this file for them.
#
# The incision count is drawn green when it equals the number needed. Stripping
# the formatting removes that hint, so don't use styling as a signal.

_LINK = re.compile(r"\[(.*?)\]\(https://github\.com/CantFindDev/SurgE\)")
_EDGE_UNDERSCORE = re.compile(r"(?<![A-Za-z0-9])_|_(?![A-Za-z0-9])")

_PULSE = {
    "Extremely Weak": "extremely_weak",
    "Weak": "weak",
    "Steady": "steady",
    "Strong": "strong",
}
_STATUS = {
    "Heart Stopped!": "heart_stopped",
    "Awake": "awake",
    "Coming To": "coming_to",
    "Unconscious": "unconscious",
}
_SITE = {
    "Unsanitary": "unsanitary",
    "Unclean": "unclean",
    "Not sanitized": "not_sanitized",
    "Clean": "clean",
}
_VISIBILITY = {
    "": "clear",
    "It is becoming hard to see your work.": "hard_to_see",
    "You can't see what you are doing!": "cant_see",
}


def strip_formatting(text: object) -> str:
    """Remove SurgE's plain-text markdown (links, bold, italics) and tidy spaces."""
    s = _LINK.sub(r"\1", str(text))
    s = s.replace("*", "").replace("‍", "")
    s = _EDGE_UNDERSCORE.sub("", s)
    return " ".join(s.split())


def _lookup(table: dict[str, str], text: str, what: str) -> str:
    try:
        return table[text]
    except KeyError:
        raise ValueError(f"unrecognised {what} text: {text!r}") from None


def _bleeding(text: str) -> str | None:
    if not text:
        return None
    if "very quickly" in text:
        return "very_quickly"
    if "slowly" in text:
        return "slowly"
    return "losing"


def _fever(text: str) -> str | None:
    if not text:
        return None
    if "climbing fast" in text:
        return "climbing_fast"
    if "slowly rising" in text:
        return "slowly_rising"
    return "climbing"


def _bones(text: str) -> dict[str, int]:
    broken = re.search(r"(\d+) broken", text)
    shattered = re.search(r"(\d+) shattered", text)
    return {
        "broken": int(broken.group(1)) if broken else 0,
        "shattered": int(shattered.group(1)) if shattered else 0,
    }


def usable_tools(
    patient: Patient, *, status: str, visibility: str, diagnosed: bool, incisions: int
) -> list[str]:
    """The tools the tray enables, in tray order (`_TOOL_LAYOUT` in ui/surgery_view.py).

    Almost every condition follows from what is on screen: Defibrillator is
    "Heart Stopped!", the site is workable unless "You can't see what you are
    doing!", Pins and Clamp need an open incision, Ultrasound needs no diagnosis.
    Only three conditions have no text: Fix It, Lab Kit and Antibiotics are
    enabled by flags SurgE keeps, so those are read as the tray's button state.
    """
    visible = visibility != "cant_see"
    enabled = {
        "defibrillator": visible and status == "heart_stopped",
        "sponge": True,
        "anesthetic": visible,
        "stitches": visible,
        "scalpel": visible,
        "ultrasound": visible and not diagnosed,
        "antiseptic": visible,
        "fix_it": visible and bool(patient.IsFixable),
        "lab_kit": visible and not patient.IsLabKitUsed,
        "antibiotics": visible and bool(patient.LabWorked),
        "transfusion": visible,
        "splint": visible,
        "pins": visible and incisions > 0,
        "clamp": visible and incisions > 0,
    }
    return [tool for tool in TOOL_IDS if enabled[tool]]


def observe(patient: Patient) -> dict[str, Any]:
    """The screen state (PRD section 8) for the patient's current screen."""
    scan = strip_formatting(patient.ScanText)
    diagnosed = bool(scan) and scan != NOT_DIAGNOSED
    status = _lookup(_STATUS, strip_formatting(patient.PatientStatus), "status")
    visibility = _lookup(
        _VISIBILITY, strip_formatting(patient.DirtynessText), "visibility"
    )
    incisions = int(strip_formatting(patient.IncisionText))

    # SurgE shows a condition's text only once it is visible; "None" has no text.
    condition_text = None
    if patient.SpecialConditionVisibility and patient.SpecialCondition != "None":
        condition_text = strip_formatting(patient.SpecialConditionText)

    modifier = patient.ModifierItem
    return {
        "skill_level": int(patient.SkillLevel),
        "modifier": modifier.lower().replace(" ", "_") if modifier else None,
        "special_condition_text": condition_text,
        "scan_text": scan if diagnosed else None,
        "pulse": _lookup(_PULSE, strip_formatting(patient.PulseText), "pulse"),
        "status": status,
        "temperature": float(strip_formatting(patient.TempText)),
        "site": _lookup(_SITE, strip_formatting(patient.SiteText), "site"),
        "visibility": visibility,
        "incisions": incisions,
        "bones": _bones(strip_formatting(patient.BoneText)) if diagnosed else None,
        "bleeding": _bleeding(strip_formatting(patient.BleedingText)),
        "fever": _fever(strip_formatting(patient.FeverText)),
        "last_tool_text": strip_formatting(patient.ToolText),
        "usable_tools": usable_tools(
            patient,
            status=status,
            visibility=visibility,
            diagnosed=diagnosed,
            incisions=incisions,
        ),
    }
