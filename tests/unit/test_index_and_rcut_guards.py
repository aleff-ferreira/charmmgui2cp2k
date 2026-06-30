"""Unit tests for QM-index bounds checks and the hard QM/MM RCUT floor
(audit fixes C5, H9, M1).

These three were "knows-but-proceeds" gaps: out-of-range QM atom indices and a
physically meaningless QM/MM coupling range were silently tolerated, producing
wrong-but-clean output. The guards below turn each into an explicit failure.
"""

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit


class _Topo:
    """Minimal stand-in exposing only the .natom attribute the code reads."""
    def __init__(self, natom):
        self.natom = natom


def _pdb_line(serial, name, resn, segid, elem):
    """Build a fixed-column PDB ATOM record (>=80 chars) the parser can read."""
    s = list(" " * 80)
    s[0:6] = list("ATOM  ")
    s[6:11] = list(str(serial).rjust(5))
    s[12:16] = list(name.ljust(4)[:4])
    s[17:20] = list(resn.ljust(3)[:3])
    s[30:38] = list("   8.000")
    s[38:46] = list("   8.000")
    s[46:54] = list("   8.000")
    s[54:60] = list("  1.00")
    s[60:66] = list("  0.00")
    s[72:76] = list(segid.ljust(4)[:4])
    s[76:78] = list(elem.rjust(2))
    return "".join(s) + "\n"


def _write_pdb(tmp_path, serials):
    p = tmp_path / "qm.pdb"
    with open(p, "w") as fh:
        for ser in serials:
            fh.write(_pdb_line(ser, "C", "QM", "QM", "C"))
    return str(p)


# ---------------- C5: extract_qm_from_pdb bounds check ----------------

def test_pdb_no_topo_is_backward_compatible(tmp_path):
    """Without topo, behaviour is unchanged: every marked serial returned."""
    pdb = _write_pdb(tmp_path, [1, 2, 100])
    elems, idx = c.extract_qm_from_pdb(pdb)
    assert sorted(idx) == [1, 2, 100]


def test_pdb_out_of_range_serials_dropped_with_warning(tmp_path, capsys):
    """Serial beyond NATOM is dropped (it signals a PDB/topology mismatch)."""
    pdb = _write_pdb(tmp_path, [1, 2, 100])
    elems, idx = c.extract_qm_from_pdb(pdb, topo=_Topo(5))
    assert sorted(idx) == [1, 2]
    # element dict pruned to surviving serials
    assert all(int(s) <= 5 for serials in elems.values() for s in serials)
    out = capsys.readouterr().out
    assert "outside the topology range" in out


def test_pdb_in_range_serials_kept_silently(tmp_path, capsys):
    pdb = _write_pdb(tmp_path, [1, 2, 100])
    elems, idx = c.extract_qm_from_pdb(pdb, topo=_Topo(200))
    assert sorted(idx) == [1, 2, 100]
    assert "outside the topology range" not in capsys.readouterr().out


# ---------------- H9: compute_qm_cell index validation ----------------

_COORDS = [[0.0, 0.0, 0.0], [1.5, 0.0, 0.0], [0.0, 1.5, 0.0]]


def test_compute_qm_cell_valid_indices_ok():
    abc, meta = c.compute_qm_cell([1, 2, 3], _COORDS)
    assert isinstance(abc, str) and len(abc.split()) == 3
    assert meta["used_qm_atoms"] == 3


def test_compute_qm_cell_out_of_range_raises():
    with pytest.raises(ValueError, match=r"out of range"):
        c.compute_qm_cell([1, 2, 99], _COORDS)


def test_compute_qm_cell_zero_index_raises():
    with pytest.raises(ValueError, match=r"out of range"):
        c.compute_qm_cell([0, 1], _COORDS)


def test_compute_qm_cell_empty_selection_falls_back():
    """Genuinely empty selection still returns the documented fallback cell."""
    abc, meta = c.compute_qm_cell([], _COORDS)
    assert meta.get("fallback") is True


# ---------------- M1: hard physical RCUT floor ----------------

def test_rcut_floor_rejects_tiny_cell():
    policy = c.make_qmmm_periodic_policy()
    with pytest.raises(ValueError, match=r"physical floor"):
        c.evaluate_qmmm_periodic_electrostatics("1.0 1.0 1.0", policy)


def test_rcut_ok_for_reasonable_cell():
    policy = c.make_qmmm_periodic_policy()
    meta = c.evaluate_qmmm_periodic_electrostatics("30.0 30.0 30.0", policy)
    assert meta["effective_rcut"] >= c.MIN_PHYSICAL_QMMM_RCUT


def test_rcut_floor_constant_is_one_angstrom():
    assert c.MIN_PHYSICAL_QMMM_RCUT == 1.0
