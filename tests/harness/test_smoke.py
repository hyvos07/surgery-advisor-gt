"""Smoke test: SurgE's Patient imports through harness.surge on Python 3.12+."""

import sys


def test_surge_patient_imports() -> None:
    assert sys.version_info >= (3, 12)

    from harness.surge import SURGE_DIR, Patient

    assert Patient.__module__ == "core.patient"
    assert Patient.__module__ in sys.modules
    assert str(SURGE_DIR) in sys.path
