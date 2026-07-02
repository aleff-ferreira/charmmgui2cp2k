"""Unit tests for refined IMOMM alpha on non-single cuts and the forbidden-metal
covalent-length guard (audit fixes H3, H4, M5).

H3/H4: capping a severed peptide/aromatic bond with the single-bond table ALPHA
mis-places the link hydrogen (~7-11% off). ALPHA is now recomputed from the
force-field equilibrium length for non-single cuts. M5: a forbidden (Kr-proxy)
metal must not receive a plausible covalent length that would let its cut pass
the geometry check as 'ok'.
"""

from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit

_FIX = Path(__file__).resolve().parent.parent / "fixtures"


# ---------------- H3/H4: refined ALPHA ----------------

def test_refined_alpha_peptide():
    # peptide C-N ~1.33 Å, QM=C (r(C-H)=1.09) -> ~1.22
    assert c.refined_alpha_imomm_for_cut("C", 1.335, 1.35) == pytest.approx(1.22, abs=0.01)


def test_refined_alpha_aromatic():
    # aromatic C-C ~1.40 Å -> ~1.28
    assert c.refined_alpha_imomm_for_cut("C", 1.40, 1.38) == pytest.approx(1.28, abs=0.01)


def test_refined_alpha_falls_back_without_ff_length():
    assert c.refined_alpha_imomm_for_cut("C", None, 1.38) == 1.38


def test_refined_alpha_falls_back_unknown_qm_element():
    assert c.refined_alpha_imomm_for_cut("ZZ", 1.40, 1.38) == 1.38


def test_single_bond_cut_keeps_table_alpha_on_fixture():
    """The demo CA-CB single-bond cut must keep the curated table ALPHA (1.38),
    i.e. the refinement only touches non-single cuts (keeps golden stable)."""
    topo, coords, _b, emap, _u, _a = c._step2_parse_topology(
        str(_FIX / "ala_dipeptide.parm7"), str(_FIX / "ala_dipeptide.rst7")
    )
    links, _adj = c._step4_detect_links(topo, [11, 12, 13, 14], emap)
    assert links[0]["BOND_ORDER_CLASS"] == "single"
    assert links[0]["ALPHA_IMOMM"] == pytest.approx(1.38, abs=1e-6)


# ---------------- M5: forbidden-metal guard ----------------

@pytest.mark.parametrize("pair", [("FE", "C"), ("ZN", "N"), ("C", "CU"), ("MN", "O")])
def test_forbidden_metal_has_no_covalent_length(pair):
    assert c.expected_covalent_bond_length(*pair) is None


def test_legitimate_ion_still_has_length():
    """Na/Mg/K/Ca are AMBER-parameterised ions, not Kr-proxied — still valid."""
    assert c.expected_covalent_bond_length("CA", "O") is not None
    assert c.expected_covalent_bond_length("C", "C") == pytest.approx(1.52)


def test_metal_cut_geometry_is_unknown_not_ok():
    """A forbidden-metal cut must not be reported 'ok' by the geometry check."""
    links = [{"QM_INDEX": 1, "MM_INDEX": 2, "QM_ELEM": "FE", "MM_ELEM": "C"}]
    audit = c.verify_link_geometry(links, [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0)])
    assert audit["links"][0]["status"] == "unknown"
