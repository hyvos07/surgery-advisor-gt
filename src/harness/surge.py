"""The only module that imports SurgE (adds vendor/SurgE to sys.path)."""

import sys
from pathlib import Path

SURGE_DIR = Path(__file__).resolve().parents[2] / "vendor" / "SurgE"

if not (SURGE_DIR / "core" / "patient.py").is_file():
    raise ImportError(
        f"SurgE not found at {SURGE_DIR}; run `git submodule update --init`"
    )

if str(SURGE_DIR) not in sys.path:
    sys.path.insert(0, str(SURGE_DIR))

from core.data_loaders import Maladies  # noqa: E402
from core.enums import PatientState, ToolType  # noqa: E402
from core.patient import Patient  # noqa: E402
from core.text import PatientStatus, TextManager  # noqa: E402

# Plain-text mode, set once at import and never changed: SurgE compares status
# strings in their formatted form, so switching modes mid-run would break it.
TextManager.setTextManager(False)

NOT_DIAGNOSED = "The patient has not been diagnosed."

# Tool IDs from PRD section 8, in the order of SurgE's tool tray.
TOOL_TYPES: dict[str, ToolType] = {
    "defibrillator": ToolType.SurgicalDefib,
    "sponge": ToolType.SurgicalSponge,
    "anesthetic": ToolType.SurgicalAnesthetic,
    "stitches": ToolType.SurgicalStitches,
    "scalpel": ToolType.SurgicalScalpel,
    "ultrasound": ToolType.SurgicalUltrasound,
    "antiseptic": ToolType.SurgicalAntiseptic,
    "fix_it": ToolType.FixIt,
    "lab_kit": ToolType.SurgicalLabKit,
    "antibiotics": ToolType.SurgicalAntibiotics,
    "transfusion": ToolType.SurgicalTransfusion,
    "splint": ToolType.SurgicalSplint,
    "pins": ToolType.SurgicalPins,
    "clamp": ToolType.SurgicalClamp,
}
TOOL_IDS: tuple[str, ...] = tuple(TOOL_TYPES)

# PRD IDs -> SurgE names. SurgE silently ignores a name it doesn't know, so
# start_surgery() validates against these instead of passing text through.
CONDITION_NAMES: dict[str, str] = {
    "none": "None",
    "tough_skin": "Tough Skin",
    "antibiotic_resistant": "Antibiotic-Resistant Infection",
    "filthy": "Filthy",
    "hyperactive": "Hyperactive",
    "hemophiliac": "Hemophiliac",
}
MODIFIER_NAMES: dict[str, str] = {
    "stethoscope": "Stethoscope",
    "tea": "Tea",
    "exquisite_bone_saw": "Exquisite Bone Saw",
    "nano_nurse_bot": "Nano Nurse Bot",
}
# SurgE's own spelling, e.g. "Herinated Disc".
MALADY_NAMES: tuple[str, ...] = tuple(Maladies.GetAllMaladieNames())


def start_surgery(
    malady: str,
    condition: str = "none",
    skill: int = 100,
    modifier: str | None = None,
) -> Patient:
    """Start a surgery the way SurgE's Discord cog does (see docs/testing.md).

    The condition is always passed explicitly, because SurgE's random roll always
    returns "None". Train-E mode stays off: it changes the game's rules.
    """
    by_lower = {name.lower(): name for name in MALADY_NAMES}
    if malady.lower() not in by_lower:
        raise ValueError(f"unknown malady {malady!r}; choose from {MALADY_NAMES}")
    if condition not in CONDITION_NAMES:
        raise ValueError(
            f"unknown condition {condition!r}; choose from {list(CONDITION_NAMES)}"
        )
    if modifier is not None and modifier not in MODIFIER_NAMES:
        raise ValueError(
            f"unknown modifier {modifier!r}; choose from {list(MODIFIER_NAMES)}"
        )
    if not 0 <= skill <= 100:
        raise ValueError(f"skill must be 0-100, got {skill}")

    patient = Patient(
        SkillLevel=skill,
        malady=by_lower[malady.lower()],
        specialcondition=CONDITION_NAMES[condition],
        modifier=MODIFIER_NAMES[modifier] if modifier else None,
        TrainEMode=False,
    )
    # A new Patient has an empty status, and Scalpel on turn 0 wouldn't kill.
    patient.PatientStatus = PatientStatus.GetPatientState(PatientState.Awake)
    if not patient.ScanText:
        patient.ScanText = TextManager.ErrorText(NOT_DIAGNOSED)
    patient.UpdatePatientUITexts()
    return patient


__all__ = [
    "CONDITION_NAMES",
    "MALADY_NAMES",
    "MODIFIER_NAMES",
    "NOT_DIAGNOSED",
    "SURGE_DIR",
    "TOOL_IDS",
    "TOOL_TYPES",
    "Patient",
    "TextManager",
    "start_surgery",
]
