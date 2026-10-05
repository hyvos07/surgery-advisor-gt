"""Smoke test: the advisor package imports without SurgE."""

import importlib

MODULES = ["config", "engine", "forecast", "knowledge", "memory", "rules", "state"]


def test_advisor_modules_import() -> None:
    for name in MODULES:
        importlib.import_module(f"advisor.{name}")
