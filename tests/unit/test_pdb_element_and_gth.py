"""Unit tests for authoritative PDB element resolution (M2) and unresolved-GTH
detection (H2).

M2: PDB atom-name parsing is ambiguous (Cα "CA" vs calcium; "HB"); the topology
ATOMIC_NUMBER is the ground truth and must win. H2: an element without a GTH
pseudopotential mapping yields 'POTENTIAL …-qX' that crashes CP2K, so it must be
detected (the CLI/TUI then hard-stop rather than write broken input).
"""

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit


def _pdbline(serial, name, elem_col="", segid="QM"):
    s = list(" " * 80)
    s[0:6] = list("ATOM  ")
    s[6:11] = list(str(serial).rjust(5))
    s[12:16] = list(name.ljust(4)[:4])
    s[17:20] = list("LIG")
    s[30:54] = list("   1.000   1.000   1.000")
    s[72:76] = list(segid.ljust(4)[:4])
    if elem_col:
        s[76:78] = list(elem_col.rjust(2))
    return "".join(s) + "\n"


class _Topo:
    def __init__(self, atomic_numbers, natom=None):
        self._a = list(atomic_numbers)
        self.natom = natom if natom is not None else len(self._a)

    def get_int_array(self, flag):
        return self._a if flag == "ATOMIC_NUMBER" else []


# ---------------- M2: element resolution ----------------

def test_topo_atomic_number_disambiguates_calpha():
    """Atom name 'CA' with topo Z=6 is carbon, not calcium."""
    assert c._resolve_pdb_element(_pdbline(1, "CA"), 1, [6]) == "C"


def test_topo_atomic_number_resolves_metal():
    assert c._resolve_pdb_element(_pdbline(1, "FE1"), 1, [26]) == "FE"


def test_element_column_used_when_no_topo():
    assert c._resolve_pdb_element(_pdbline(1, "FE1", elem_col="FE"), 1, None) == "FE"


def test_name_fallback_is_validated():
    """Without topo or element column, a valid single-char element resolves."""
    assert c._resolve_pdb_element(_pdbline(1, "C"), 1, None) == "C"


def test_extract_qm_from_pdb_uses_topo_element(tmp_path):
    """End to end: a Cα named 'CA' resolves to carbon via the topology."""
    p = tmp_path / "qm.pdb"
    p.write_text(_pdbline(1, "CA") + _pdbline(2, "N"))
    topo = _Topo([6, 7])  # carbon, nitrogen
    elems, idx = c.extract_qm_from_pdb(str(p), topo=topo)
    assert sorted(idx) == [1, 2]
    assert "C" in elems and "N" in elems
    assert "CA" not in elems  # NOT mis-read as calcium


# ---------------- H2: unresolved GTH detection ----------------

def test_common_elements_all_resolve():
    _lines, unresolved = c.generate_qm_kinds({"C": ["1"], "H": ["2"],
                                              "N": ["3"], "O": ["4"]})
    assert unresolved == []


def test_unknown_element_is_flagged_unresolved():
    _lines, unresolved = c.generate_qm_kinds({"XX": ["1"]})
    assert "XX" in unresolved


def test_gth_hardstop_uses_rigor_exit_code():
    """The CLI/TUI hard-stop on unresolved GTH is a rigor failure (exit 3)."""
    assert c.STRICT_GATE_EXIT_CODE == 3
