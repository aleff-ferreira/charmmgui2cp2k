"""Fixture-based tests over the small alanine-dipeptide reference system.

The fixture (ACE-ALA-NME, 22 atoms, gas phase) is built reproducibly with
AmberTools tleap; see tests/fixtures/make_ala_dipeptide.tleap. The QM region
(tests/fixtures/ala_dipeptide_qmmm.mdin) is the ALA side-chain methyl
(atoms 11-14), giving a single non-polar C-C boundary cut (CA9-CB11) -- the
best-practice link-atom case.
"""

from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit

_FIX = Path(__file__).resolve().parent.parent / "fixtures"
ALA_PARM7 = str(_FIX / "ala_dipeptide.parm7")
ALA_RST7 = str(_FIX / "ala_dipeptide.rst7")
ALA_MDIN = str(_FIX / "ala_dipeptide_qmmm.mdin")


@pytest.fixture(scope="module")
def topo():
    return c.AmberTopology(ALA_PARM7)


def test_fixture_parses_to_expected_shape(topo):
    assert topo.natom == 22
    assert topo.get_string_array("RESIDUE_LABEL") == ["ACE", "ALA", "NME"]
    assert topo.get_int_array("RESIDUE_POINTER") == [1, 7, 17]
    assert not topo.is_chamber


def test_element_map_resolves_all_types(topo):
    emap, unresolved, atom_types = c.build_element_map(topo)
    assert unresolved == []
    # Spot-check the chemically critical type codes.
    assert emap["CT"] == "C"
    assert emap["CX"] == "C"
    assert emap["N"] == "N"
    assert emap["O"] == "O"
    assert emap["H"] == "H"
    # Every atom maps to a known element.
    assert all(at in emap for at in atom_types)


def test_link_detection_finds_single_cc_cut(topo):
    emap, _unresolved, _types = c.build_element_map(topo)
    links, _adj = c._step4_detect_links(topo, [11, 12, 13, 14], emap)
    assert len(links) == 1
    link = links[0]
    assert link["QM_INDEX"] == 11  # CB (in QM)
    assert link["MM_INDEX"] == 9   # CA (in MM)
    assert (link["QM_ELEM"], link["MM_ELEM"]) == ("C", "C")


def test_mdin_extraction_matches_fixture_region():
    detected = {"prmtop": ALA_PARM7, "rst7": ALA_RST7, "mdin": ALA_MDIN}
    topo, _coords, _box, emap, _unresolved, alias = c._step2_parse_topology(
        detected["prmtop"], detected["rst7"]
    )
    result = c._step3_extract_qm_from_mdin(
        detected["mdin"], topo, emap, list(alias.atom_aliases),
        prmtop_path=detected["prmtop"], crd_path=detected["rst7"],
    )
    assert result is not None
    qm_elements, qm_indices, mdin_meta, label = result
    assert qm_indices == [11, 12, 13, 14]
    assert {k: len(v) for k, v in qm_elements.items()} == {"C": 1, "H": 3}
    assert mdin_meta["qmcharge"] == 0
    assert label == "iqmatoms"


def test_electron_count_and_parity_are_consistent(topo):
    emap, _unresolved, _types = c.build_element_map(topo)
    links, _adj = c._step4_detect_links(topo, [11, 12, 13, 14], emap)
    qm_elements = {"C": [11], "H": [12, 13, 14]}
    ec, _meta = c.estimate_qm_electrons_for_spin(qm_elements, 0, links)
    assert ec == 8  # CB(4) + 3H(3) + 1 link-H = 8
    consistent, _ = c.validate_multiplicity_parity(1, ec)  # closed-shell singlet
    assert consistent is True


def test_residual_charge_plan_on_real_residue_conserves_charge(topo):
    # QM = methyl (11-14); frontier M1 = CA (9). Redistribute over the rest
    # of the ALA residue and verify exact charge conservation.
    plan = c.build_residual_charge_plan([11, 12, 13, 14], topo, m1_set={9})
    # Only the ALA residue is split, so at most one plan entry.
    for entry in plan:
        redistributed = sum(
            u["new_charge_e"] - u["old_charge_e"] for u in entry["updates"]
        )
        assert redistributed == pytest.approx(entry["removed_charge_e"], abs=1e-8)
        assert 9 not in entry["target_atoms"]  # frontier atom never a target
