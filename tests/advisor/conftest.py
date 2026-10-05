"""Shared fixtures for the advisor tests (no SurgE needed)."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from advisor.knowledge import Knowledge, load
from advisor.state import ScreenState

FIXTURES = Path(__file__).parent / "fixtures"

_DEFAULT_STATE: dict[str, Any] = {
    "skill_level": 50,
    "modifier": None,
    "special_condition_text": None,
    "scan_text": None,
    "pulse": "strong",
    "status": "awake",
    "temperature": 98.6,
    "site": "clean",
    "visibility": "clear",
    "incisions": 0,
    "bones": None,
    "bleeding": None,
    "fever": None,
    "last_tool_text": "",
    "usable_tools": ["sponge"],
}


@pytest.fixture(scope="session")
def know() -> Knowledge:
    """The hand-written fixture data: 3 maladies and all 6 conditions."""
    return load(FIXTURES)


@pytest.fixture
def make_state() -> Callable[..., ScreenState]:
    """Build a valid ScreenState from defaults plus keyword overrides."""

    def make(**overrides: Any) -> ScreenState:
        return ScreenState.from_dict({**_DEFAULT_STATE, **overrides})

    return make
