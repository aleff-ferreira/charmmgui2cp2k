"""Unit tests for QM/MM link-bond geometry sanity checks (audit gap A3.2).

detect_link_bonds() finds boundary bonds from connectivity alone; these checks
verify the two atoms are at a physically sensible covalent distance, catching
clashes and non-bonds (stale topology) before they surface as SCF divergence.
"""

from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit

_FIX = Path(__file__).resolve().parent.parent / "fixtures"


def test_expected_covalent_bond_length():
    assert c.expected_covalent_bond_length("C", "C") == pytest.approx(1.52)
    assert c.expected_covalent_bond_length("C", "H") == pytest.approx(1.07)
    assert c.expected_covalent_bond_length("Xx", "C") is None  # unknown element


def test_link_geometry_ok_for_normal_cc_cut():
    links = [{"QM_INDEX": 1, "MM_INDEX": 2, "QM_ELEM": "C", "MM_ELEM": "C"}]
    coords = [(0.0, 0.0, 0.0), (1.52, 0.0, 0.0)]
    audit = c.verify_link_geometry(links, coords)
    assert audit["ok"] is True
    assert audit["links"][0]["status"] == "ok"
    # Mutates the link in place with measured/derived geometry.
    assert links[0]["R_QM_MM"] == pytest.approx(1.52)
    assert links[0]["R_QM_H"] == pytest.approx(1.07)


def test_link_geometry_flags_clash():
    links = [{"QM_INDEX": 1, "MM_INDEX": 2, "QM_ELEM": "C", "MM_ELEM": "C"}]
    audit = c.verify_link_geometry(links, [(0.0, 0.0, 0.0), (0.3, 0.0, 0.0)])
    assert audit["ok"] is False
    assert audit["links"][0]["status"] == "short"
    assert "short" in audit["issues"][0]


def test_link_geometry_flags_nonbond():
    links = [{"QM_INDEX": 1, "MM_INDEX": 2, "QM_ELEM": "C", "MM_ELEM": "C"}]
    audit = c.verify_link_geometry(links, [(0.0, 0.0, 0.0), (5.0, 0.0, 0.0)])
    assert audit["ok"] is False
    assert audit["links"][0]["status"] == "long"


def test_link_geometry_unknown_without_coords():
    links = [{"QM_INDEX": 1, "MM_INDEX": 2, "QM_ELEM": "C", "MM_ELEM": "C"}]
    audit = c.verify_link_geometry(links, [])
    assert audit["ok"] is True  # cannot fail without coordinates
    assert audit["links"][0]["status"] == "unknown"


def test_link_geometry_unknown_element_radius():
    links = [{"QM_INDEX": 1, "MM_INDEX": 2, "QM_ELEM": "XX", "MM_ELEM": "C"}]
    audit = c.verify_link_geometry(links, [(0.0, 0.0, 0.0), (1.5, 0.0, 0.0)])
    assert audit["links"][0]["status"] == "unknown"
    assert audit["ok"] is True


def test_link_geometry_on_real_fixture():
    topo, coords, _box, emap, _u, _alias = c._step2_parse_topology(
        str(_FIX / "ala_dipeptide.parm7"), str(_FIX / "ala_dipeptide.rst7")
    )
    links, _adj = c._step4_detect_links(topo, [11, 12, 13, 14], emap)
    audit = c.verify_link_geometry(links, coords)
    assert audit["ok"] is True
    assert audit["links"][0]["status"] == "ok"
    # The CA-CB bond is a normal ~1.5 Å single bond.
    assert audit["links"][0]["distance_A"] == pytest.approx(1.52, abs=0.1)


def test_format_link_geometry_renders_header_and_rows():
    links = [{"QM_INDEX": 11, "MM_INDEX": 9, "QM_ELEM": "C", "MM_ELEM": "C"}]
    audit = c.verify_link_geometry(links, [(0.0, 0.0, 0.0), (1.52, 0.0, 0.0)])
    text = "\n".join(c.format_link_geometry(audit))
    assert "Link geometry: OK" in text
    assert "qm_index" in text
