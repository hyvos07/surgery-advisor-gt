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

from core.patient import Patient  # noqa: E402

__all__ = ["SURGE_DIR", "Patient"]
