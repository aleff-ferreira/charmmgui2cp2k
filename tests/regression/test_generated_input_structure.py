"""End-to-end structural validation of the generated CP2K QM/MM input (P3).

The scientific-rigor audit noted its `generated_output` dimension produced no
findings — i.e. the final `.inp` was never validated as an integrated whole.
This test closes that blind spot *without* needing a CP2K binary: it runs a full
`--demo` generation and asserts the emitted QM/MM input is internally consistent
(QM_KIND per element, well-formed &LINK blocks, a physical &CELL, and a
parity-consistent multiplicity that matches electronic_state.dat).

Complements ``test_cp2k_input_check.py`` (the ``requires_cp2k`` parser check):
this one runs everywhere, that one proves real-CP2K acceptance when available.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.regression

_SCRIPT = Path(__file__).resolve().parents[2] / "charmmgui2cp2k.py"


@pytest.fixture(scope="module")
def demo_output(tmp_path_factory):
    work = tmp_path_factory.mktemp("gen_struct")
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT), "--no-tui", "--demo", "--dir", str(work)],
        capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, f"demo generation failed:\n{proc.stdout[-2000:]}"
    inp = next(work.glob("**/40_qmmm_md.inp"), None)
    assert inp is not None, "40_qmmm_md.inp was not generated"
    return inp.parent


def _read(out_dir, name):
    return (out_dir / name).read_text()


def test_force_eval_and_qmmm_blocks_present(demo_output):
    text = _read(demo_output, "40_qmmm_md.inp")
    assert "&FORCE_EVAL" in text and "&QMMM" in text and "&END QMMM" in text
    assert "ECOUPL" in text  # QM/MM electrostatic coupling scheme


def test_every_qm_element_has_a_qm_kind_with_mm_index(demo_output):
    text = _read(demo_output, "40_qmmm_md.inp")
    kinds = re.findall(r"&QM_KIND\s+(\S+)\s*\n\s*MM_INDEX\s+([0-9 ]+)", text)
    assert kinds, "no &QM_KIND blocks found"
    all_idx = []
    for _elem, idx_str in kinds:
        idxs = [int(i) for i in idx_str.split()]
        assert idxs, "empty MM_INDEX"
        all_idx += idxs
    # QM atom indices are 1-based and unique across kinds.
    assert all(i >= 1 for i in all_idx)
    assert len(all_idx) == len(set(all_idx)), "duplicate QM atom index across QM_KIND blocks"


def test_link_blocks_are_well_formed(demo_output):
    text = _read(demo_output, "40_qmmm_md.inp")
    links = re.findall(r"&LINK\b(.*?)&END LINK", text, re.DOTALL)
    assert links, "no &LINK blocks (demo has a CA-CB cut)"
    for block in links:
        assert re.search(r"QM_INDEX\s+\d+", block)
        assert re.search(r"MM_INDEX\s+\d+", block)
        assert "LINK_TYPE IMOMM" in block
        alpha = re.search(r"ALPHA_IMOMM\s+([0-9.]+)", block)
        assert alpha and float(alpha.group(1)) > 0.0


def test_qm_cell_is_physical(demo_output):
    text = _read(demo_output, "40_qmmm_md.inp")
    # The &QMMM/&CELL ABC (QM cell) must be three positive lengths.
    abc = re.search(r"&QMMM.*?&CELL.*?ABC \[angstrom\]\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)",
                    text, re.DOTALL)
    assert abc, "no QM &CELL ABC found"
    lengths = [float(abc.group(i)) for i in (1, 2, 3)]
    assert all(l > 1.0 for l in lengths), f"non-physical QM cell {lengths}"


def test_multiplicity_parity_matches_electron_accounting(demo_output):
    text = _read(demo_output, "40_qmmm_md.inp")
    charge = int(re.search(r"\bCHARGE\s+(-?\d+)", text).group(1))
    mult = int(re.search(r"\bMULTIPLICITY\s+(\d+)", text).group(1))
    state = _read(demo_output, "electronic_state.dat")
    n_elec = int(re.search(r"FINAL_ELECTRON_COUNT:\s+(\d+)", state).group(1))
    # M = 2S+1 parity must match the electron-count parity (necessary physics).
    assert (n_elec % 2) == ((mult - 1) % 2), (
        f"multiplicity {mult} parity-inconsistent with {n_elec} electrons"
    )
    # electronic_state.dat and the emitted input must agree.
    assert int(re.search(r"CP2K_DFT_MULTIPLICITY:\s+(\d+)", state).group(1)) == mult
    assert int(re.search(r"CP2K_DFT_CHARGE:\s+(-?\d+)", state).group(1)) == charge


def test_boundary_charges_json_consistent_with_links(demo_output):
    text = _read(demo_output, "40_qmmm_md.inp")
    n_link_blocks = len(re.findall(r"&END LINK", text))
    bc = json.loads(_read(demo_output, "boundary_charges.json"))
    assert bc["n_links"] == n_link_blocks
    # A conserving audit for the clean demo system.
    assert bc["charge_conservation"]["ok"] is True
