"""Unit tests for global and cross-channel charge conservation (audit H5, M6).

H5: the per-atom charge verifier could pass while per-atom deviations accumulate
into a net system-charge gain/loss; a global net-charge check now guards that on
the emitted topology. M6: the QM/MM charge audit now exposes a combined
cross-channel total/drift so a boundary-channel imbalance is visible in one place.
"""

from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit

_FIX = Path(__file__).resolve().parent.parent / "fixtures"


# ---------------- H5: global net-charge check ----------------

def test_net_charge_tolerances_ordered():
    assert (c.CHARGE_CONSERVATION_NET_WARN_TOL_E
            < c.CHARGE_CONSERVATION_NET_HARD_TOL_E)


def test_manifest_verifier_passes_on_identity():
    """Verifying a prmtop against itself (no residual plan) conserves charge
    exactly — the new net-charge check must not raise on the happy path."""
    topo = c.AmberTopology(str(_FIX / "ala_dipeptide.parm7"))
    src = topo.get_float_array("CHARGE")
    # Should not raise (per-atom + net both zero drift).
    c.verify_prmtop_charges_match_manifest(
        emitted_prmtop_path=str(_FIX / "ala_dipeptide.parm7"),
        source_charges_amber_units=src,
        residual_charge_plan=None,
        label="identity",
    )


# ---------------- M6: cross-channel combined aggregate ----------------

def test_combined_block_present_and_consistent():
    audit = c.verify_qmmm_charge_conservation(
        residual_charge_plan=[{
            "residue_label": "ALA", "residue_index": 1,
            "removed_charge_e": 0.1,
            "updates": [{"old_charge_e": 0.0, "new_charge_e": 0.1}],
        }],
        link_bonds=[{"QM_INDEX": 11, "M1_INDEX": 9, "M1_CHARGE_E": 0.2,
                     "M2_INDICES": [7, 8]}],
    )
    assert audit["ok"] is True
    assert "combined" in audit
    assert audit["combined"]["total_moved_e"] == pytest.approx(0.3)
    assert audit["combined"]["consistent"] is True
    assert audit["combined"]["max_drift_e"] == pytest.approx(0.0, abs=1e-9)


def test_combined_reports_inconsistent_channel():
    """A residual entry whose updates don't sum to the removed charge is an
    internal imbalance; the combined block reflects it."""
    audit = c.verify_qmmm_charge_conservation(
        residual_charge_plan=[{
            "residue_label": "LIG", "residue_index": 2,
            "removed_charge_e": 0.5,
            "updates": [{"old_charge_e": 0.0, "new_charge_e": 0.1}],  # only 0.1 applied
        }],
        link_bonds=[],
    )
    assert audit["ok"] is False
    assert audit["combined"]["consistent"] is False
    assert audit["combined"]["max_drift_e"] > 0.0
