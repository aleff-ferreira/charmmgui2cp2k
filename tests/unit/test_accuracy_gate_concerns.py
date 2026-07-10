"""Unit tests for accuracy-degradation gate concerns (audit fixes H10, H13,
M15, M13).

RCUT relaxed below target, an unsafe QM/MM production timestep, and an
under-converged MGRID cutoff were all detected-but-only-warned. They are now
strict-gate concerns: warned in normal mode, refused under --strict.
"""

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit


def _cats(concerns):
    return {cat for cat, _msg in concerns}


# ---------------- H10/M13: relaxed RCUT ----------------

def test_relaxed_rcut_is_a_concern():
    meta = {"rcut_relaxed": True, "effective_rcut": 6.5, "target_rcut": 8.0}
    assert "rcut_reduced" in _cats(
        c.collect_generation_scientific_concerns(qmmm_periodic_meta=meta))


def test_unrelaxed_rcut_is_not_a_concern():
    meta = {"rcut_relaxed": False, "effective_rcut": 8.0, "target_rcut": 8.0}
    assert "rcut_reduced" not in _cats(
        c.collect_generation_scientific_concerns(qmmm_periodic_meta=meta))


# ---------------- H13: unsafe timestep ----------------

def test_timestep_above_floor_is_a_concern():
    assert "md_timestep" in _cats(
        c.collect_generation_scientific_concerns(md_timestep=1.0))


def test_timestep_at_floor_is_ok():
    assert "md_timestep" not in _cats(
        c.collect_generation_scientific_concerns(
            md_timestep=c.MAX_SAFE_QMMM_TIMESTEP_FS))


def test_timestep_floor_is_half_fs():
    assert c.MAX_SAFE_QMMM_TIMESTEP_FS == 0.5


# ---------------- M15: under-converged MGRID ----------------

def test_low_cutoff_is_a_concern():
    assert "mgrid_cutoff" in _cats(
        c.collect_generation_scientific_concerns(mgrid_cutoff=200.0))


def test_adequate_cutoff_is_ok():
    assert "mgrid_cutoff" not in _cats(
        c.collect_generation_scientific_concerns(mgrid_cutoff=500.0))


# ---------------- Strict gate wiring ----------------

def test_accuracy_concerns_fail_strict_gate():
    concerns = c.collect_generation_scientific_concerns(
        md_timestep=1.0, mgrid_cutoff=100.0,
        qmmm_periodic_meta={"rcut_relaxed": True, "effective_rcut": 5.0,
                            "target_rcut": 8.0},
    )
    passed, code = c.enforce_strict_generation_gate(concerns, strict=True)
    assert passed is False and code == c.STRICT_GATE_EXIT_CODE
    # non-strict: warned, not blocked
    assert c.enforce_strict_generation_gate(concerns, strict=False) == (True, 0)
