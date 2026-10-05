"""Screen-state and decision models, and JSON parsing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Enum values match PRD section 8 exactly: lowercase snake case.


class Pulse(StrEnum):
    STRONG = "strong"
    STEADY = "steady"
    WEAK = "weak"
    EXTREMELY_WEAK = "extremely_weak"


class Status(StrEnum):
    AWAKE = "awake"
    COMING_TO = "coming_to"
    UNCONSCIOUS = "unconscious"
    HEART_STOPPED = "heart_stopped"


class Site(StrEnum):
    CLEAN = "clean"
    NOT_SANITIZED = "not_sanitized"
    UNCLEAN = "unclean"
    UNSANITARY = "unsanitary"


class Visibility(StrEnum):
    CLEAR = "clear"
    HARD_TO_SEE = "hard_to_see"
    CANT_SEE = "cant_see"


class Bleeding(StrEnum):
    """Bleeding words; no bleeding is `None` in the screen state."""

    SLOWLY = "slowly"
    LOSING = "losing"
    VERY_QUICKLY = "very_quickly"


class Fever(StrEnum):
    """Fever words; no fever text is `None` in the screen state."""

    SLOWLY_RISING = "slowly_rising"
    CLIMBING = "climbing"
    CLIMBING_FAST = "climbing_fast"


class Tool(StrEnum):
    DEFIBRILLATOR = "defibrillator"
    SPONGE = "sponge"
    ANESTHETIC = "anesthetic"
    STITCHES = "stitches"
    SCALPEL = "scalpel"
    ULTRASOUND = "ultrasound"
    ANTISEPTIC = "antiseptic"
    FIX_IT = "fix_it"
    LAB_KIT = "lab_kit"
    ANTIBIOTICS = "antibiotics"
    TRANSFUSION = "transfusion"
    SPLINT = "splint"
    PINS = "pins"
    CLAMP = "clamp"


class Modifier(StrEnum):
    STETHOSCOPE = "stethoscope"
    TEA = "tea"
    EXQUISITE_BONE_SAW = "exquisite_bone_saw"
    NANO_NURSE_BOT = "nano_nurse_bot"


SKILL_MIN = 0
SKILL_MAX = 100


@dataclass(frozen=True)
class Bones:
    broken: int
    shattered: int


@dataclass(frozen=True)
class Decision:
    tool: Tool
    rule: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {"tool": self.tool.value, "rule": self.rule, "reason": self.reason}


# Field order follows PRD section 8, and to_dict() emits keys in this order.
_KEYS = (
    "skill_level",
    "modifier",
    "special_condition_text",
    "scan_text",
    "pulse",
    "status",
    "temperature",
    "site",
    "visibility",
    "incisions",
    "bones",
    "bleeding",
    "fever",
    "last_tool_text",
    "usable_tools",
)


def _int(value: object, name: str) -> int:
    # bool is a subclass of int, but `true` is not a valid count.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {value!r}")
    return value


def _str(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {value!r}")
    return value


def _opt_str(value: object, name: str) -> str | None:
    return None if value is None else _str(value, name)


def _enum[E: StrEnum](cls: type[E], value: object, name: str) -> E:
    # Strict: a plain string only. An enum member of another class is rejected.
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string, got {value!r}")
    try:
        return cls(value)
    except ValueError:
        allowed = ", ".join(m.value for m in cls)
        raise ValueError(f"{name} must be one of {allowed}; got {value!r}") from None


def _opt_enum[E: StrEnum](cls: type[E], value: object, name: str) -> E | None:
    return None if value is None else _enum(cls, value, name)


@dataclass(frozen=True)
class ScreenState:
    """What a player can see on the surgery screen (PRD section 8)."""

    skill_level: int
    modifier: Modifier | None
    special_condition_text: str | None
    scan_text: str | None
    pulse: Pulse
    status: Status
    temperature: float
    site: Site
    visibility: Visibility
    incisions: int
    bones: Bones | None
    bleeding: Bleeding | None
    fever: Fever | None
    last_tool_text: str
    usable_tools: tuple[Tool, ...]

    @property
    def incision_open(self) -> bool:
        return self.incisions > 0

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> ScreenState:
        """Parse and validate a screen-state dict; raise ValueError if it is bad."""
        if not isinstance(d, Mapping):
            raise ValueError(f"screen state must be an object, got {type(d).__name__}")
        missing = [k for k in _KEYS if k not in d]
        if missing:
            raise ValueError(f"screen state is missing keys: {', '.join(missing)}")
        extra = sorted(str(k) for k in d if k not in _KEYS)
        if extra:
            raise ValueError(f"screen state has unknown keys: {', '.join(extra)}")

        skill = _int(d["skill_level"], "skill_level")
        if not SKILL_MIN <= skill <= SKILL_MAX:
            raise ValueError(
                f"skill_level must be {SKILL_MIN}-{SKILL_MAX}, got {skill}"
            )

        temperature = d["temperature"]
        if isinstance(temperature, bool) or not isinstance(temperature, int | float):
            raise ValueError(f"temperature must be a number, got {temperature!r}")

        incisions = _int(d["incisions"], "incisions")
        if incisions < 0:
            raise ValueError(f"incisions must not be negative, got {incisions}")

        bones: Bones | None = None
        raw_bones = d["bones"]
        if raw_bones is not None:
            if not isinstance(raw_bones, Mapping):
                raise ValueError(f"bones must be an object or null, got {raw_bones!r}")
            if set(raw_bones) != {"broken", "shattered"}:
                raise ValueError(
                    "bones must have exactly the keys broken and shattered, "
                    f"got {sorted(str(k) for k in raw_bones)}"
                )
            bones = Bones(
                broken=_int(raw_bones["broken"], "bones.broken"),
                shattered=_int(raw_bones["shattered"], "bones.shattered"),
            )

        raw_tools = d["usable_tools"]
        if isinstance(raw_tools, str) or not isinstance(raw_tools, list | tuple):
            raise ValueError(f"usable_tools must be an array, got {raw_tools!r}")
        tools = tuple(_enum(Tool, t, "usable_tools item") for t in raw_tools)
        if len(set(tools)) != len(tools):
            raise ValueError("usable_tools must not repeat a tool")

        return cls(
            skill_level=skill,
            modifier=_opt_enum(Modifier, d["modifier"], "modifier"),
            special_condition_text=_opt_str(
                d["special_condition_text"], "special_condition_text"
            ),
            scan_text=_opt_str(d["scan_text"], "scan_text"),
            pulse=_enum(Pulse, d["pulse"], "pulse"),
            status=_enum(Status, d["status"], "status"),
            temperature=float(temperature),
            site=_enum(Site, d["site"], "site"),
            visibility=_enum(Visibility, d["visibility"], "visibility"),
            incisions=incisions,
            bones=bones,
            bleeding=_opt_enum(Bleeding, d["bleeding"], "bleeding"),
            fever=_opt_enum(Fever, d["fever"], "fever"),
            last_tool_text=_str(d["last_tool_text"], "last_tool_text"),
            usable_tools=tools,
        )

    def to_dict(self) -> dict[str, Any]:
        """The PRD section 8 JSON form; `from_dict(s.to_dict()) == s`."""
        return {
            "skill_level": self.skill_level,
            "modifier": self.modifier.value if self.modifier else None,
            "special_condition_text": self.special_condition_text,
            "scan_text": self.scan_text,
            "pulse": self.pulse.value,
            "status": self.status.value,
            "temperature": self.temperature,
            "site": self.site.value,
            "visibility": self.visibility.value,
            "incisions": self.incisions,
            "bones": (
                None
                if self.bones is None
                else {"broken": self.bones.broken, "shattered": self.bones.shattered}
            ),
            "bleeding": self.bleeding.value if self.bleeding else None,
            "fever": self.fever.value if self.fever else None,
            "last_tool_text": self.last_tool_text,
            "usable_tools": [t.value for t in self.usable_tools],
        }
