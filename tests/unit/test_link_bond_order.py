"""Unit tests for bond-order-aware link chemistry (audit fixes C4, H1, L2).

AMBER prmtops store no chemical bond order, so the old code capped any QM/MM
cut with a single-bond IMOMM hydrogen and only sanity-checked geometry with a
permissive ±40% tolerance — silently accepting cuts through double, aromatic,
peptide and triple bonds. These tests pin: (H1) the force-field equilibrium
length is now read and recorded per link; (C4) bond order is classified from it
and non-single cuts are surfaced; (L2/C4) the geometry tolerance is tightened.
"""

from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit

_FIX = Path(__file__).resolve().parent.parent / "fixtures"


# ---------------- C4/L2: tightened geometry tolerance ----------------

def test_geometry_tolerance_tightened():
    assert c.LINK_GEOMETRY_TOLERANCE_FRAC == pytest.approx(0.15)


# ---------------- C4/H1: bond-order classifier ----------------

@pytest.mark.parametrize("req,expected_single", [
    (1.526, True),   # C-C single (ff14SB CT-CT)
    (1.45, True),    # still single-ish (ratio ~0.95)
])
def test_single_bond_lengths_classified_single(req, expected_single):
    r = c.classify_link_bond_order("C", "C", req)
    assert r["is_single"] is expected_single
    assert r["class"] == "single"


@pytest.mark.parametrize("req", [1.40, 1.34])  # aromatic, double
def test_aromatic_and_double_flagged_nonsingle(req):
    r = c.classify_link_bond_order("C", "C", req)
    assert r["is_single"] is False
    assert r["class"] in ("elevated", "multiple")


def test_triple_bond_is_multiple():
    r = c.classify_link_bond_order("C", "C", 1.20)
    assert r["class"] == "multiple"
    assert r["is_single"] is False


def test_peptide_cn_flagged_nonsingle():
    """Peptide C-N (~1.33 Å) has partial double-bond character (audit H3)."""
    r = c.classify_link_bond_order("C", "N", 1.335)
    assert r["is_single"] is False


def test_unknown_equil_length_is_conservative_single():
    """No FF length available -> treated as single (no false alarm)."""
    r = c.classify_link_bond_order("C", "C", None)
    assert r["class"] == "unknown"
    assert r["is_single"] is True


def test_unknown_element_radius_is_conservative():
    r = c.classify_link_bond_order("XX", "C", 1.30)
    assert r["class"] == "unknown"
    assert r["is_single"] is True


# ---------------- C4/H1: non-single cut messaging ----------------

def test_nonsingle_messages_for_flagged_links():
    links = [
        {"QM_ELEM": "C", "MM_ELEM": "C", "QM_INDEX": 1, "MM_INDEX": 2,
         "BOND_ORDER_CLASS": "multiple", "FF_EQUIL_LENGTH": 1.20},
        {"QM_ELEM": "C", "MM_ELEM": "N", "QM_INDEX": 3, "MM_INDEX": 4,
         "BOND_ORDER_CLASS": "elevated", "FF_EQUIL_LENGTH": 1.33},
    ]
    msgs = c.nonsingle_link_cut_messages(links)
    assert len(msgs) == 2
    assert all("Non-single QM/MM cut" in m for m in msgs)


def test_no_messages_for_single_or_unknown_cuts():
    links = [
        {"QM_ELEM": "C", "MM_ELEM": "C", "BOND_ORDER_CLASS": "single"},
        {"QM_ELEM": "C", "MM_ELEM": "C", "BOND_ORDER_CLASS": "unknown"},
    ]
    assert c.nonsingle_link_cut_messages(links) == []


# ---------------- H1: detect_link_bonds records FF length + order ----------------

def test_detect_records_ff_length_and_order_on_fixture():
    topo, coords, _box, emap, _u, _alias = c._step2_parse_topology(
        str(_FIX / "ala_dipeptide.parm7"), str(_FIX / "ala_dipeptide.rst7")
    )
    links, _adj = c._step4_detect_links(topo, [11, 12, 13, 14], emap)
    assert links, "expected at least one QM/MM link (CA-CB)"
    lk = links[0]
    # H1: bond-type index + force-field equilibrium length are captured.
    assert lk["FF_BOND_TYPE_INDEX"] >= 1
    assert lk["FF_EQUIL_LENGTH"] == pytest.approx(1.526, abs=0.05)
    # C4: the CA-CB single bond is correctly classified single (no false alarm).
    assert lk["BOND_ORDER_CLASS"] == "single"
