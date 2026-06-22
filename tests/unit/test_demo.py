"""Unit tests for the --demo one-command quickstart (Phase 5 / B5)."""

import os

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit


def test_locate_demo_data_dir_finds_bundled_system():
    d = c.locate_demo_data_dir()
    assert d is not None
    assert os.path.isfile(os.path.join(d, "ala_dipeptide.parm7"))


def test_setup_demo_workdir_stages_expected_inputs(tmp_path):
    dest = str(tmp_path / "demo")
    c.setup_demo_workdir(dest)
    for name in ("step3_input.parm7", "step3_input.rst7",
                 "step3_input.pdb", "step5_production.mdin"):
        assert os.path.isfile(os.path.join(dest, name)), name


def test_setup_demo_workdir_output_is_detectable(tmp_path):
    dest = str(tmp_path / "demo")
    c.setup_demo_workdir(dest)
    detected = c.detect_files(dest)
    assert detected.get("prmtop", "").endswith("step3_input.parm7")
    assert detected.get("rst7", "").endswith("step3_input.rst7")
    assert detected.get("mdin", "").endswith("step5_production.mdin")
