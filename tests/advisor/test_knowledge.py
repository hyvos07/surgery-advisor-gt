"""Knowledge loading, tested against hand-written fixtures (no SurgE needed)."""

import json
from pathlib import Path

import pytest

from advisor import knowledge
from advisor.knowledge import Knowledge, Malady, load

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def k() -> Knowledge:
    return load(FIXTURES)


def test_loads_fixture_maladies_and_conditions(k: Knowledge) -> None:
    assert [m.name for m in k.maladies] == ["Heart Attack", "Broken Leg", "Bird Flu"]
    assert [c.id for c in k.conditions] == [
        "none",
        "tough_skin",
        "antibiotic_resistant",
        "filthy",
        "hyperactive",
        "hemophiliac",
    ]


def test_malady_fields(k: Knowledge) -> None:
    heart = k.malady_for_scan("Patient had a heart attack.")
    assert heart == Malady(
        name="Heart Attack",
        scan_text="Patient had a heart attack.",
        fix_text="The heart is now exposed for operating.",
        post_fix_text="You grafted in some nice new arteries!",
        incisions_needed=2,
        needs_fix=True,
        broken=0,
        shattered=0,
        starts_diagnosed=False,
        is_flu=False,
    )
    leg = k.malady_for_scan("Patient broke his leg.")
    assert leg is not None
    assert (leg.incisions_needed, leg.needs_fix) == (1, False)
    assert (leg.broken, leg.shattered) == (1, 1)
    assert leg.fix_text is None
    assert leg.post_fix_text is None
    flu = k.malady_for_scan("Patient is showing signs of the bird flu.")
    assert flu is not None
    assert flu.is_flu
    assert (flu.incisions_needed, flu.needs_fix) == (0, False)


def test_lookup_by_scan_text(k: Knowledge) -> None:
    found = k.malady_for_scan("Patient broke his leg.")
    assert found is not None and found.name == "Broken Leg"


def test_lookup_by_fix_text(k: Knowledge) -> None:
    # After Fix It the scan text becomes the fix text; the malady stays known.
    found = k.malady_for_scan("The heart is now exposed for operating.")
    assert found is not None and found.name == "Heart Attack"


def test_post_fix_text_does_not_identify(k: Knowledge) -> None:
    assert k.malady_for_scan("You grafted in some nice new arteries!") is None


def test_unknown_or_empty_scan_text(k: Knowledge) -> None:
    assert k.malady_for_scan("The patient has not been diagnosed.") is None
    assert k.malady_for_scan("") is None
    assert k.malady_for_scan("​") is None


def test_scan_text_matching_ignores_spacing(k: Knowledge) -> None:
    found = k.malady_for_scan("  Patient   had a heart attack.\n")
    assert found is not None and found.name == "Heart Attack"


def test_condition_fields(k: Knowledge) -> None:
    visible = {c.id: c.visible_at_start for c in k.conditions}
    assert visible == {
        "none": False,
        "tough_skin": True,
        "antibiotic_resistant": False,
        "filthy": True,
        "hyperactive": True,
        "hemophiliac": False,
    }
    assert k.condition("tough_skin").name == "Tough Skin"
    assert k.condition("antibiotic_resistant").name == "Antibiotic-Resistant Infection"


def test_condition_for_text(k: Knowledge) -> None:
    c = k.condition_for_text("The patient is hyperactive.")
    assert c is not None and c.id == knowledge.HYPERACTIVE
    c = k.condition_for_text("The patient is a hemophiliac.")
    assert c is not None and c.id == knowledge.HEMOPHILIAC
    c = k.condition_for_text(
        "The patient exhibits very tough skin. Possibly a superhero."
    )
    assert c is not None and c.id == knowledge.TOUGH_SKIN


def test_none_condition_has_no_visible_text(k: Knowledge) -> None:
    assert k.condition_for_text("") is None
    assert k.condition_for_text("​") is None
    assert k.condition_for_text("The patient is cheerful.") is None
    assert k.condition("none").visible_at_start is False


def test_unknown_condition_id(k: Knowledge) -> None:
    with pytest.raises(KeyError):
        k.condition("grumpy")


def test_load_is_cached_per_directory(tmp_path: Path) -> None:
    assert load(FIXTURES) is load(FIXTURES)
    assert load(FIXTURES) is load(FIXTURES / ".." / "fixtures")
    other = tmp_path / "data"
    other.mkdir()
    (other / "maladies.json").write_text("[]", encoding="utf-8")
    (other / "special_conditions.json").write_text("[]", encoding="utf-8")
    empty = load(other)
    assert empty is not load(FIXTURES)
    assert empty.maladies == ()


def test_default_data_dir_points_at_surge_data() -> None:
    d = knowledge.default_data_dir()
    assert d.parts[-3:] == ("vendor", "SurgE", "data")
    assert d.is_absolute()


def _write(directory: Path, maladies: list[dict[str, object]]) -> Path:
    directory.mkdir()
    (directory / "maladies.json").write_text(json.dumps(maladies), encoding="utf-8")
    (directory / "special_conditions.json").write_text(
        (FIXTURES / "special_conditions.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return directory


def test_starts_diagnosed_from_ultrasound_used(tmp_path: Path) -> None:
    d = _write(
        tmp_path / "nose",
        [
            {
                "diagnostic": "Nose Job",
                "ultrasound_used": True,
                "scan_text": "Patient wants a nose job.",
                "post_fix_text": "You have cut into nasal area.",
                "fix_text": "You rearranged their face!",
                "incisions_needed": 1,
            }
        ],
    )
    nose = load(d).maladies[0]
    assert nose.starts_diagnosed
    assert nose.needs_fix


def test_duplicate_post_fix_text_is_allowed_but_not_matched(tmp_path: Path) -> None:
    d = _write(
        tmp_path / "dup",
        [
            {"diagnostic": "A", "scan_text": "a scan", "post_fix_text": "Same."},
            {"diagnostic": "B", "scan_text": "b scan", "post_fix_text": "Same."},
        ],
    )
    k = load(d)
    assert k.malady_for_scan("Same.") is None
    assert k.malady_for_scan("b scan") == k.maladies[1]


def test_ambiguous_scan_text_is_rejected(tmp_path: Path) -> None:
    d = _write(
        tmp_path / "ambiguous",
        [
            {"diagnostic": "A", "scan_text": "same scan"},
            {"diagnostic": "B", "scan_text": "other", "fix_text": "same scan"},
        ],
    )
    with pytest.raises(ValueError, match="identifies both"):
        load(d)


def test_bad_data_files(tmp_path: Path) -> None:
    d = _write(tmp_path / "nokey", [{"diagnostic": "A"}])
    with pytest.raises(ValueError, match="scan_text"):
        load(d)
    missing = tmp_path / "missing"
    missing.mkdir()
    with pytest.raises(FileNotFoundError):
        load(missing)
