"""Unit tests for the strict-mode generation gate (audit gap A3.3).

By default the scientific checks only warn; --strict turns unresolved concerns
into a non-zero exit so a bad QM/MM setup never silently reaches a batch queue.
"""

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit


def test_collect_concerns_empty_when_all_ok():
    concerns = c.collect_generation_scientific_concerns(
        charge_conservation={"ok": True, "issues": []},
        link_geometry={"ok": True, "issues": []},
        data_availability={"ok": True, "issues": []},
    )
    assert concerns == []


def test_collect_concerns_aggregates_by_category():
    concerns = c.collect_generation_scientific_concerns(
        charge_conservation={"ok": False, "issues": ["q drift"]},
        link_geometry={"ok": False, "issues": ["too short"]},
        data_availability={"ok": False, "issues": ["GTH missing", "dftd3 missing"]},
    )
    categories = [cat for cat, _ in concerns]
    assert categories.count("charge_conservation") == 1
    assert categories.count("link_geometry") == 1
    assert categories.count("data_availability") == 2


def test_collect_concerns_ignores_unrun_checks():
    concerns = c.collect_generation_scientific_concerns(
        charge_conservation=None, link_geometry=None, data_availability=None
    )
    assert concerns == []


def test_gate_passes_when_no_concerns_even_if_strict():
    passed, code = c.enforce_strict_generation_gate([], strict=True)
    assert passed is True
    assert code == 0


def test_gate_passes_non_strict_with_concerns():
    passed, code = c.enforce_strict_generation_gate(
        [("link_geometry", "too short")], strict=False
    )
    assert passed is True  # concerns only warned, not fatal
    assert code == 0


def test_gate_fails_strict_with_concerns():
    passed, code = c.enforce_strict_generation_gate(
        [("charge_conservation", "q drift")], strict=True
    )
    assert passed is False
    assert code == c.STRICT_GATE_EXIT_CODE
    assert code != 0
