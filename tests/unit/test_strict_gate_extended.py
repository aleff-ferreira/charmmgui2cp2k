"""Unit tests for the extended strict generation gate (audit fixes H6, H7, M9,
M10, and gate-wiring of C2/C4).

Previously the gate only saw charge/geometry/data-availability checks, so
--strict was blind to spin ambiguity, parity violations, unresolved elements,
duplicate M1 frontier atoms, forbidden link bonds, and non-single cuts — the
code detected these but only warned. They are now first-class gate concerns.
"""

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit


def _categories(concerns):
    return {cat for cat, _msg in concerns}


def test_clean_inputs_produce_no_concerns():
    assert c.collect_generation_scientific_concerns() == []


def test_spin_ambiguous_is_a_concern():
    sd = {"decision_class": "AMBIGUOUS_REQUIRES_USER", "risk_flags": [],
          "parity_consistent": True}
    assert "spin_state" in _categories(
        c.collect_generation_scientific_concerns(spin_decision=sd))


def test_spin_risk_flags_are_concerns():
    sd = {"decision_class": "LOW_RISK_INFERRED",
          "risk_flags": ["transition metal Fe present"],
          "parity_consistent": True}
    cats = _categories(c.collect_generation_scientific_concerns(spin_decision=sd))
    assert "spin_risk" in cats


def test_parity_inconsistent_is_a_concern():
    sd = {"decision_class": "AUTHORITATIVE", "risk_flags": [],
          "parity_consistent": False}
    assert "spin_parity" in _categories(
        c.collect_generation_scientific_concerns(spin_decision=sd))


def test_parity_none_is_not_a_concern():
    """Unverifiable parity (None) is handled elsewhere; only a definite
    inconsistency (False) is a gate concern."""
    sd = {"decision_class": "AUTHORITATIVE", "risk_flags": [],
          "parity_consistent": None}
    assert "spin_parity" not in _categories(
        c.collect_generation_scientific_concerns(spin_decision=sd))


def test_unresolved_elements_is_a_concern():
    meta = {"unresolved_elements": ["XX"]}
    assert "unresolved_elements" in _categories(
        c.collect_generation_scientific_concerns(qm_electron_meta=meta))


def test_duplicate_m1_is_a_concern():
    links = [
        {"M1_INDEX": 9, "QM_INDEX": 1, "MM_INDEX": 9, "QM_ELEM": "C", "MM_ELEM": "C"},
        {"M1_INDEX": 9, "QM_INDEX": 2, "MM_INDEX": 9, "QM_ELEM": "C", "MM_ELEM": "C"},
    ]
    assert "duplicate_m1" in _categories(
        c.collect_generation_scientific_concerns(link_bonds=links))


def test_forbidden_link_is_a_concern():
    links = [{"QM_ELEM": "FE", "MM_ELEM": "C", "QM_INDEX": 1, "MM_INDEX": 2,
              "M1_INDEX": 2}]
    assert "forbidden_link" in _categories(
        c.collect_generation_scientific_concerns(link_bonds=links))


def test_nonsingle_cut_is_a_concern():
    links = [{"QM_ELEM": "C", "MM_ELEM": "C", "QM_INDEX": 1, "MM_INDEX": 2,
              "M1_INDEX": 2, "BOND_ORDER_CLASS": "multiple", "FF_EQUIL_LENGTH": 1.20}]
    assert "link_bond_order" in _categories(
        c.collect_generation_scientific_concerns(link_bonds=links))


def test_clean_links_no_boundary_concerns():
    links = [{"QM_ELEM": "C", "MM_ELEM": "C", "QM_INDEX": 1, "MM_INDEX": 2,
              "M1_INDEX": 2, "BOND_ORDER_CLASS": "single"}]
    cats = _categories(c.collect_generation_scientific_concerns(link_bonds=links))
    assert cats.isdisjoint({"duplicate_m1", "forbidden_link", "link_bond_order"})


def test_strict_gate_fails_on_any_concern():
    concerns = [("spin_parity", "bad")]
    passed, code = c.enforce_strict_generation_gate(concerns, strict=True)
    assert passed is False and code == c.STRICT_GATE_EXIT_CODE


def test_nonstrict_gate_passes_despite_concerns():
    concerns = [("spin_parity", "bad")]
    passed, code = c.enforce_strict_generation_gate(concerns, strict=False)
    assert passed is True and code == 0
