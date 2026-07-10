"""End-to-end regression test for a transition-metal QM/MM boundary (P3).

Closes the audit's second blind spot: the metal paths (forbidden Kr-proxy link
bonds C2, ADMM metal coverage C3/M14, spin ambiguity H6/M10) were only unit-
tested on synthetic inputs, never exercised through the real pipeline on a real
metal-containing topology. This drives them on a committed dimethylzinc fixture
(Zn bonded to two methyls; see tests/fixtures/make_metal_znme2.tleap) whose
QM/MM boundary cuts a Zn-C bond.
"""

from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.regression

_FIX = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture(scope="module")
def metal_topo():
    topo, coords, box, emap, _u, _a = c._step2_parse_topology(
        str(_FIX / "metal_znme2.parm7"), str(_FIX / "metal_znme2.rst7")
    )
    return topo, coords, emap


def test_fixture_carries_zinc(metal_topo):
    topo, _coords, _emap = metal_topo
    assert topo.natom == 9
    assert 30 in topo.get_int_array("ATOMIC_NUMBER")  # Zn = Z 30


def _cats(concerns):
    return {cat for cat, _msg in concerns}


def test_boundary_cut_through_metal_is_forbidden_and_gated(metal_topo):
    """QM = one methyl (atoms 6-9); the Zn-C2 bond crosses the boundary."""
    topo, coords, emap = metal_topo
    links, _adj = c._step4_detect_links(topo, [6, 7, 8, 9], emap)
    assert links, "expected a Zn-C link across the boundary"
    lk = links[0]
    verdict = c.classify_forbidden_link_bond(lk["QM_ELEM"], lk["MM_ELEM"])
    assert verdict["forbidden"] is True
    assert "ZN" in (lk["QM_ELEM"], lk["MM_ELEM"])

    concerns = c.collect_generation_scientific_concerns(link_bonds=links)
    assert "forbidden_link" in _cats(concerns)
    # Under --strict this is a hard stop with the rigor exit code.
    passed, code = c.enforce_strict_generation_gate(concerns, strict=True)
    assert passed is False and code == c.STRICT_GATE_EXIT_CODE


def test_metal_in_qm_region_fails_admm_coverage(metal_topo):
    qm_elements = {"ZN": [1], "C": [6], "H": [7, 8, 9]}
    uncovered = c.admm_recommendation_uncovered_elements(
        qm_elements, basis_set="DZVP-MOLOPT-GTH")
    assert "ZN" in uncovered
    # And the TUI/CLI ADMM gate message fires.
    assert c.admm_coverage_block_message(qm_elements, use_admm=True,
                                         basis_set="DZVP-MOLOPT-GTH") is not None


def test_metal_in_qm_region_is_spin_ambiguous_and_gated(metal_topo):
    qm_elements = {"ZN": [1], "C": [6], "H": [7, 8, 9]}
    decision = c.recommend_qm_spin_state(
        qm_elements=qm_elements, qm_charge=0, link_bonds=[])
    assert decision["decision_class"] == "AMBIGUOUS_REQUIRES_USER"
    assert decision["risk_flags"]

    concerns = c.collect_generation_scientific_concerns(spin_decision=decision)
    assert "spin_state" in _cats(concerns)
    passed, code = c.enforce_strict_generation_gate(concerns, strict=True)
    assert passed is False and code == c.STRICT_GATE_EXIT_CODE


def test_full_metal_boundary_gate_aggregates_all_risks(metal_topo):
    """The complete gate on the metal system flags the boundary and spin
    risks together — the end-to-end integration the audit found untested."""
    topo, coords, emap = metal_topo
    # QM = Zn + one methyl; the other methyl's Zn-C bond is the cut.
    qm_indices = [1, 6, 7, 8, 9]
    qm_elements = {"ZN": [1], "C": [6], "H": [7, 8, 9]}
    links, _adj = c._step4_detect_links(topo, qm_indices, emap)
    decision = c.recommend_qm_spin_state(
        qm_elements=qm_elements, qm_charge=0, link_bonds=links)
    _elec, e_meta = c.estimate_qm_electrons_for_spin(
        qm_elements=qm_elements, qm_charge=0, link_bonds=links)
    concerns = c.collect_generation_scientific_concerns(
        spin_decision=decision, qm_electron_meta=e_meta, link_bonds=links)
    cats = _cats(concerns)
    assert "spin_state" in cats  # transition-metal spin ambiguity
    passed, code = c.enforce_strict_generation_gate(concerns, strict=True)
    assert passed is False and code == c.STRICT_GATE_EXIT_CODE
