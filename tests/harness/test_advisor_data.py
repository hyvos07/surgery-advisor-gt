"""The advisor's knowledge and fail rates agree with the real SurgE."""

import pytest

from advisor import config, knowledge
from advisor.state import Modifier
from harness import surge

MODIFIERS: list[str | None] = [None, *(m.value for m in Modifier)]


@pytest.fixture(scope="module")
def k() -> knowledge.Knowledge:
    return knowledge.load()


def test_real_data_counts(k: knowledge.Knowledge) -> None:
    assert len(k.maladies) == 27
    assert len(k.conditions) == 6


def test_real_data_names_match_surge(k: knowledge.Knowledge) -> None:
    assert sorted(m.name for m in k.maladies) == sorted(surge.MALADY_NAMES)
    assert {c.name for c in k.conditions} == set(surge.CONDITION_NAMES.values())
    assert {c.id for c in k.conditions} == set(surge.CONDITION_NAMES)


def test_scan_and_fix_texts_are_unique(k: knowledge.Knowledge) -> None:
    texts = [t for m in k.maladies for t in (m.scan_text, m.fix_text) if t is not None]
    assert len(texts) == len(set(texts))
    for m in k.maladies:
        assert k.malady_for_scan(m.scan_text) is m
        if m.fix_text is not None:
            assert k.malady_for_scan(m.fix_text) is m


def test_needs_fix_agrees_with_fix_text(k: knowledge.Knowledge) -> None:
    for m in k.maladies:
        assert m.needs_fix == (m.fix_text is not None), m.name


def test_nose_job_is_the_only_malady_that_starts_diagnosed(
    k: knowledge.Knowledge,
) -> None:
    assert [m.name for m in k.maladies if m.starts_diagnosed] == ["Nose Job"]


def test_hidden_conditions(k: knowledge.Knowledge) -> None:
    hidden = {c.id for c in k.conditions if not c.visible_at_start}
    assert hidden == {"none", "antibiotic_resistant", "hemophiliac"}


@pytest.mark.parametrize("modifier", MODIFIERS)
def test_fail_rate_agrees_with_surge(modifier: str | None) -> None:
    for skill in range(101):
        patient = surge.start_surgery("Heart Attack", skill=skill, modifier=modifier)
        assert config.fail_rate(skill, modifier) == patient._CalculateSkillFailRate(), (
            skill,
            modifier,
        )
