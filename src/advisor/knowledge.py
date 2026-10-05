"""Loads maladies and special conditions from SurgE's JSON data files.

Reads the JSON with the standard library only and never imports SurgE. The
data directory defaults to `vendor/SurgE/data`; tests point it at fixtures.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

MALADIES_FILE = "maladies.json"
CONDITIONS_FILE = "special_conditions.json"

# PRD condition ids. Constants so rules and memory never spell them as literals.
NONE = "none"
TOUGH_SKIN = "tough_skin"
ANTIBIOTIC_RESISTANT = "antibiotic_resistant"
FILTHY = "filthy"
HYPERACTIVE = "hyperactive"
HEMOPHILIAC = "hemophiliac"

# SurgE's condition names -> PRD ids. Only the names are mapped here; the text
# and visibility are read from the data file.
CONDITION_IDS: dict[str, str] = {
    "None": NONE,
    "Tough Skin": TOUGH_SKIN,
    "Antibiotic-Resistant Infection": ANTIBIOTIC_RESISTANT,
    "Filthy": FILTHY,
    "Hyperactive": HYPERACTIVE,
    "Hemophiliac": HEMOPHILIAC,
}


def _normalize(text: str) -> str:
    """Drop zero-width characters and collapse whitespace, as the observer does."""
    for ch in ("​", "‌", "‍", "﻿"):
        text = text.replace(ch, "")
    return " ".join(text.split())


@dataclass(frozen=True)
class Malady:
    name: str
    scan_text: str
    fix_text: str | None
    post_fix_text: str | None
    incisions_needed: int  # without Tough Skin
    needs_fix: bool
    broken: int
    shattered: int
    starts_diagnosed: bool  # Nose Job: Ultrasound is never usable
    is_flu: bool


@dataclass(frozen=True)
class Condition:
    id: str
    name: str
    text: str
    visible_at_start: bool


@dataclass(frozen=True)
class Knowledge:
    maladies: tuple[Malady, ...]
    conditions: tuple[Condition, ...]

    def malady_for_scan(self, text: str) -> Malady | None:
        """The malady whose `scan_text` or `fix_text` is `text`, else None.

        `post_fix_text` is deliberately not matched: it is not unique across
        maladies ("You excised the tumor!", "You cauterized it.").
        """
        wanted = _normalize(text)
        if not wanted:
            return None
        for malady in self.maladies:
            if wanted == _normalize(malady.scan_text):
                return malady
            if malady.fix_text is not None and wanted == _normalize(malady.fix_text):
                return malady
        return None

    def condition_for_text(self, text: str) -> Condition | None:
        """The condition shown by `text`, else None.

        The `none` condition has no visible text, so it is never returned.
        """
        wanted = _normalize(text)
        if not wanted:
            return None
        for condition in self.conditions:
            if wanted == _normalize(condition.text):
                return condition
        return None

    def condition(self, id: str) -> Condition:
        for condition in self.conditions:
            if condition.id == id:
                return condition
        raise KeyError(f"unknown condition id {id!r}")


def default_data_dir() -> Path:
    """`<repo>/vendor/SurgE/data`, found relative to this file."""
    return Path(__file__).resolve().parents[2] / "vendor" / "SurgE" / "data"


def _read_list(path: Path) -> list[dict[str, Any]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise FileNotFoundError(f"data file not found: {path}") from None
    if not isinstance(raw, list) or not all(isinstance(e, dict) for e in raw):
        raise ValueError(f"{path} must contain a JSON list of objects")
    return raw


def _malady(entry: dict[str, Any], path: Path) -> Malady:
    try:
        name = entry["diagnostic"]
        scan_text = entry["scan_text"]
    except KeyError as e:
        raise ValueError(f"{path}: malady entry is missing {e.args[0]!r}") from None
    return Malady(
        name=name,
        scan_text=scan_text,
        fix_text=entry.get("fix_text"),
        post_fix_text=entry.get("post_fix_text"),
        incisions_needed=int(entry.get("incisions_needed", 0)),
        needs_fix=not entry.get("patient_fixed", False),
        broken=int(entry.get("broken", 0)),
        shattered=int(entry.get("shattered", 0)),
        starts_diagnosed=bool(entry.get("ultrasound_used", False)),
        is_flu=bool(entry.get("flu", False)),
    )


def _condition(entry: dict[str, Any], path: Path) -> Condition:
    try:
        name = entry["condition_name"]
        text = entry["condition_text"]
        visible = entry["condition_visibility"]
    except KeyError as e:
        raise ValueError(f"{path}: condition entry is missing {e.args[0]!r}") from None
    if name not in CONDITION_IDS:
        raise ValueError(f"{path}: unknown condition name {name!r}")
    return Condition(
        id=CONDITION_IDS[name], name=name, text=text, visible_at_start=bool(visible)
    )


def _check_unique_scan_texts(maladies: tuple[Malady, ...], path: Path) -> None:
    """Fail loudly if two maladies could be confused when read from a scan."""
    seen: dict[str, str] = {}
    names: set[str] = set()
    for malady in maladies:
        if malady.name in names:
            raise ValueError(f"{path}: duplicate malady name {malady.name!r}")
        names.add(malady.name)
        for text in (malady.scan_text, malady.fix_text):
            if text is None:
                continue
            key = _normalize(text)
            if key in seen and seen[key] != malady.name:
                raise ValueError(
                    f"{path}: text {text!r} identifies both "
                    f"{seen[key]!r} and {malady.name!r}"
                )
            seen[key] = malady.name


@cache
def _load(directory: Path) -> Knowledge:
    maladies_path = directory / MALADIES_FILE
    conditions_path = directory / CONDITIONS_FILE
    maladies = tuple(_malady(e, maladies_path) for e in _read_list(maladies_path))
    conditions = tuple(
        _condition(e, conditions_path) for e in _read_list(conditions_path)
    )
    _check_unique_scan_texts(maladies, maladies_path)
    return Knowledge(maladies=maladies, conditions=conditions)


def load(data_dir: Path | None = None) -> Knowledge:
    """Load the data in `data_dir` (default: SurgE's), cached per directory."""
    directory = (data_dir if data_dir is not None else default_data_dir()).resolve()
    return _load(directory)
