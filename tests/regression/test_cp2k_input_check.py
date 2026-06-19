"""Real-CP2K integration test: generated inputs must pass the CP2K parser (A2.2).

Version gating and golden snapshots prove internal consistency; this test proves
the generated CP2K input is actually accepted by a real CP2K binary's
parser-only ``--check``/``--input-check`` mode. It runs a full generation on the
alanine-dipeptide fixture and asserts every staged input passes.

Marked ``requires_cp2k`` and skips cleanly when no CP2K binary is available
(e.g. on CI), so it never blocks the dependency-free suite.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = [pytest.mark.regression, pytest.mark.requires_cp2k]

_FIX = Path(__file__).resolve().parent.parent / "fixtures"
_SCRIPT = Path(__file__).resolve().parents[2] / "charmmgui2cp2k.py"


@pytest.fixture(scope="module")
def cp2k_info():
    info = c.detect_cp2k_installation(probe_version=False)
    if not info.get("binaries"):
        pytest.skip("no CP2K binary on PATH; skipping real --check integration test")
    return info


def test_generated_stage_inputs_pass_cp2k_parser(tmp_path, cp2k_info):
    work = tmp_path / "work"
    work.mkdir()
    shutil.copy(_FIX / "ala_dipeptide.parm7", work / "step3_input.parm7")
    shutil.copy(_FIX / "ala_dipeptide.rst7", work / "step3_input.rst7")
    shutil.copy(_FIX / "ala_dipeptide.pdb", work / "step3_input.pdb")
    shutil.copy(_FIX / "ala_dipeptide_qmmm.mdin", work / "step5_production.mdin")

    env = os.environ.copy()
    data_dir = c.locate_cp2k_data_dir(cp2k_info=cp2k_info)
    if data_dir:
        env["CP2K_DATA_DIR"] = data_dir

    proc = subprocess.run(
        [
            sys.executable, str(_SCRIPT),
            "--no-tui", "--non-interactive", "--dir", str(work),
            "--cp2k-input-check", "strict", "--no-hardware-aware",
        ],
        cwd=str(work), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        universal_newlines=True, timeout=600,
    )
    tail = (proc.stdout[-3000:] + "\n--STDERR--\n" + proc.stderr[-1500:])
    assert proc.returncode == 0, f"generation failed:\n{tail}"
    assert "cp2k --input-check" in proc.stdout or "input-check OK" in proc.stdout, tail
