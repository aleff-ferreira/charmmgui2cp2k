"""External cross-validation against ParmEd (audit gap A2.1).

charmmgui2cp2k infers elements and reads charges with its own pure-Python
PRMTOP parser. An element misidentification silently propagates into a wrong
electron count and therefore a wrong spin multiplicity, so we cross-check the
tool's interpretation against an independent reference (AmberTools ParmEd).

The test skips cleanly when no AmberTools ParmEd backend is discoverable
(e.g. on a CI runner without AmberTools).
"""

import json
import subprocess
from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit

_FIX = Path(__file__).resolve().parent.parent / "fixtures"
ALA_PARM7 = str(_FIX / "ala_dipeptide.parm7")

_PARMED_DUMP = r"""
import json, sys
import parmed
p = parmed.load_file(sys.argv[1])
print(json.dumps({
    "elements": [a.element_name for a in p.atoms],
    "charges": [a.charge for a in p.atoms],
}))
"""


@pytest.fixture(scope="module")
def parmed_reference():
    backend = c._get_preferred_parmed_backend()
    if backend is None or backend.kind != "amber":
        pytest.skip("AmberTools ParmEd backend not available")
    env = c._amber_python_env(backend.amber_home)
    proc = subprocess.run(
        [backend.python_exe, "-c", _PARMED_DUMP, ALA_PARM7],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, timeout=120,
    )
    if proc.returncode != 0:
        pytest.skip(f"ParmEd reference run failed: {proc.stderr[:200]}")
    return json.loads(proc.stdout)


def test_element_inference_matches_parmed(parmed_reference):
    topo = c.AmberTopology(ALA_PARM7)
    emap, unresolved, atom_types = c.build_element_map(topo)
    assert unresolved == []
    tool_elements = [emap[at] for at in atom_types]
    ref_elements = [e.upper() for e in parmed_reference["elements"]]
    assert len(tool_elements) == len(ref_elements)
    mismatches = [
        (i + 1, t, r)
        for i, (t, r) in enumerate(zip(tool_elements, ref_elements))
        if t != r
    ]
    assert not mismatches, f"element mismatches vs ParmEd (1-based idx): {mismatches}"


def test_charges_match_parmed(parmed_reference):
    topo = c.AmberTopology(ALA_PARM7)
    raw = topo.get_float_array("CHARGE")[: topo.natom]
    tool_charges_e = [q / c.AMBER_CHARGE_SCALE for q in raw]
    ref_charges = parmed_reference["charges"]
    assert len(tool_charges_e) == len(ref_charges)
    for i, (t, r) in enumerate(zip(tool_charges_e, ref_charges)):
        assert t == pytest.approx(r, abs=1e-3), f"charge mismatch at atom {i + 1}"
    # Net charge agreement (alanine dipeptide is neutral).
    assert sum(tool_charges_e) == pytest.approx(sum(ref_charges), abs=1e-3)
