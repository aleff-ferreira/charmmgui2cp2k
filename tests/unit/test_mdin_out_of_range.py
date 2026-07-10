"""Unit test for mdin/topology mismatch handling (audit fix M3).

Out-of-range iqmatoms mean the mdin does not correspond to the topology, so the
whole QM selection is untrustworthy. In non-interactive mode the generator now
fails loudly (exit STRICT_GATE_EXIT_CODE) instead of silently dropping the
user's intended atoms; interactive mode still warns and drops.
"""

from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit

_FIX = Path(__file__).resolve().parent.parent / "fixtures"


def _load_fixture():
    topo, _coords, _box, emap, _u, _alias = c._step2_parse_topology(
        str(_FIX / "ala_dipeptide.parm7"), str(_FIX / "ala_dipeptide.rst7")
    )
    atom_types = list(topo.get_string_array("AMBER_ATOM_TYPE") or [])
    return topo, emap, atom_types


def _write_mdin(tmp_path, iqmatoms):
    p = tmp_path / "qmmm.mdin"
    p.write_text(
        "test\n &cntrl\n  ifqnt=1,\n /\n &qmmm\n"
        f"  iqmatoms={iqmatoms},\n  qmcharge=0,\n /\n"
    )
    return str(p)


def test_in_range_mdin_parses(tmp_path):
    topo, emap, atom_types = _load_fixture()
    mdin = _write_mdin(tmp_path, "11, 12, 13, 14")
    elems, indices, _meta = c.extract_qm_from_mdin(
        mdin, topo, emap, atom_types, interactive=False
    )
    assert sorted(indices) == [11, 12, 13, 14]


def test_out_of_range_mdin_hard_fails_non_interactive(tmp_path):
    topo, emap, atom_types = _load_fixture()
    mdin = _write_mdin(tmp_path, "11, 99999")  # 99999 >> NATOM
    with pytest.raises(SystemExit) as exc:
        c.extract_qm_from_mdin(mdin, topo, emap, atom_types, interactive=False)
    assert exc.value.code == c.STRICT_GATE_EXIT_CODE


def test_out_of_range_mdin_warns_and_drops_interactive(tmp_path):
    topo, emap, atom_types = _load_fixture()
    mdin = _write_mdin(tmp_path, "11, 12, 99999")
    elems, indices, _meta = c.extract_qm_from_mdin(
        mdin, topo, emap, atom_types, interactive=True
    )
    # Interactive path keeps the valid atoms, drops the out-of-range one.
    assert 99999 not in indices
    assert 11 in indices and 12 in indices
