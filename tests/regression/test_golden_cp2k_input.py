"""Golden-output regression tests (audit gap A1.2).

These freeze the byte-for-byte content of the deterministic artifacts the tool
generates for the alanine-dipeptide fixture: the full assembled CP2K QM/MM
input, the QM &KIND block, the boundary &LINK charge directives, and the
boundary-charge audit. Any code change that perturbs generated scientific
output must update the baselines deliberately, which makes silent drift
visible in review.

The assembly path performs no CP2K/Amber detection, timestamping, or
host-specific formatting (verified: the artifacts contain no volatile tokens),
so the baselines are stable across machines and CI.

Regenerate baselines intentionally with::

    CHARMMGUI2CP2K_UPDATE_GOLDEN=1 python -m pytest tests/regression -q
"""

import os
import tempfile
from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.regression

_FIX = Path(__file__).resolve().parent.parent / "fixtures"
_BASELINES = Path(__file__).resolve().parent / "baselines"
ALA_PARM7 = str(_FIX / "ala_dipeptide.parm7")
ALA_RST7 = str(_FIX / "ala_dipeptide.rst7")
ALA_MDIN = str(_FIX / "ala_dipeptide_qmmm.mdin")

_UPDATE = os.environ.get("CHARMMGUI2CP2K_UPDATE_GOLDEN") == "1"


def _build_artifacts():
    """Deterministically build the fixture's generated artifacts as text.

    Mirrors the wizard's Preview/Generate assembly path (see
    PreviewPhase._assemble) with fixed parameters.
    """
    topo, coords, box, emap, _unresolved, alias = c._step2_parse_topology(
        ALA_PARM7, ALA_RST7
    )
    qm_elements, qm_indices, _mdin_meta, _label = c._step3_extract_qm_from_mdin(
        ALA_MDIN, topo, emap, list(alias.atom_aliases),
        prmtop_path=ALA_PARM7, crd_path=ALA_RST7,
    )
    links, adj = c._step4_detect_links(topo, qm_indices, emap)
    charges_e = [q / c.AMBER_CHARGE_SCALE for q in topo.get_float_array("CHARGE")[: topo.natom]]
    c.enrich_link_with_m2(links, adj, set(qm_indices), charges_e)

    qmmm_pp = c.make_qmmm_periodic_policy()
    qm_cell_abc, _ = c.compute_qm_cell(
        list(qm_indices), coords, padding=qmmm_pp.qm_cell_padding,
        box_dims=box, qmmm_periodic_policy=qmmm_pp,
    )
    qm_kinds_lines, _ = c.generate_qm_kinds(
        qm_elements, basis_set="DZVP-MOLOPT-GTH", use_admm=True
    )
    m1_set = {int(l["MM_INDEX"]) for l in links}
    plan = c.build_residual_charge_plan(qm_indices, topo, m1_set=m1_set, coords=coords)
    override = c._apply_residual_charge_plan_to_raw_charges(
        topo.get_float_array("CHARGE"), plan
    )
    mm_data = c.collect_topology_variant_data(
        topo, list(qm_elements.keys()), alias_plan=alias
    )
    qmmm_data = c.collect_topology_variant_data(
        topo, list(qm_elements.keys()),
        charge_array_override=override, alias_plan=alias,
    )
    rec_profile, _ = c.recommended_scf_profile(
        qm_elements.keys(), "B3LYP",
        sum(len(v) for v in qm_elements.values()), multiplicity=1,
    )
    scf = dict(c.SCF_PROFILES[rec_profile])
    sm = c.make_system_spec(
        prmtop_file="system_qmmm.prmtop", xyz_file="system.xyz", box_dims=box,
        qm_elements=qm_elements, link_bonds=list(links),
        qm_kinds_lines=qm_kinds_lines,
        mm_kinds_lines=mm_data["mm_kinds"], mm_stage_kinds_lines=mm_data["mm_kinds"],
        qmmm_stage_kinds_lines=qmmm_data["mm_kinds"],
        mm_prmtop_file="system_mm.prmtop", qmmm_prmtop_file="system_qmmm.prmtop",
        qmmm_periodic_policy=qmmm_pp, qm_cell_abc=qm_cell_abc,
        qm_charge=0, multiplicity=1, natom=topo.natom,
    )
    dft = c.make_dft_config(
        functional="B3LYP", basis_set="DZVP-MOLOPT-GTH", cutoff=500, rel_cutoff=60,
        use_admm=True, scf_profile=rec_profile,
        scf_max_scf=scf["max_scf"], scf_eps_scf=scf["eps_scf"], scf_guess=scf["scf_guess"],
        scf_cholesky=scf.get("cholesky"), qs_eps_default=scf.get("qs_eps_default"),
        scf_added_mos=scf["added_mos"], scf_mixing_method=scf["mixing_method"],
        scf_mixing_alpha=scf["mixing_alpha"], scf_nbroyden=scf["nbroyden"],
        outer_max_scf=scf["outer_max_scf"], outer_eps_scf=scf["outer_eps_scf"],
        qm_elements_for_admm=qm_elements, qm_kinds_lines_for_admm=qm_kinds_lines,
    )
    rc = c.make_run_config(project_name="qmmm_geo_opt", run_type="GEO_OPT")
    full_input = c.assemble_cp2k_input(sm, dft, rc)

    link_directives = "".join(
        c.generate_link_charge_directives(links[0], c.DEFAULT_BOUNDARY_CHARGE_SCHEME)
    )

    with tempfile.TemporaryDirectory() as d:
        meta = c.write_boundary_charges_audit(
            d, links, plan, c.DEFAULT_BOUNDARY_CHARGE_SCHEME, topo
        )
        boundary_dat = Path(meta["dat_path"]).read_text()

    return {
        "qmmm_geo_opt.inp": full_input,
        "qm_kinds.txt": "".join(qm_kinds_lines),
        "link_charge_directives.txt": link_directives,
        "boundary_charges.dat": boundary_dat,
    }


_ARTIFACTS = _build_artifacts()


@pytest.fixture(scope="module", autouse=True)
def _maybe_update_baselines():
    if _UPDATE:
        _BASELINES.mkdir(parents=True, exist_ok=True)
        for name, text in _ARTIFACTS.items():
            (_BASELINES / name).write_text(text)


@pytest.mark.parametrize("name", sorted(_ARTIFACTS.keys()))
def test_generated_artifact_matches_baseline(name):
    baseline = _BASELINES / name
    if not baseline.exists():
        pytest.skip(
            f"baseline {name} missing; run with CHARMMGUI2CP2K_UPDATE_GOLDEN=1"
        )
    expected = baseline.read_text()
    actual = _ARTIFACTS[name]
    assert actual == expected, (
        f"Generated {name} drifted from baseline. If this change is intended, "
        f"regenerate with CHARMMGUI2CP2K_UPDATE_GOLDEN=1 and review the diff."
    )


def test_full_input_has_expected_qmmm_structure():
    """Sanity anchors so an accidental baseline overwrite can't hide a broken input."""
    inp = _ARTIFACTS["qmmm_geo_opt.inp"]
    assert "&QMMM" in inp
    assert "&LINK" in inp
    assert "&CELL" in inp
    assert "RUN_TYPE GEO_OPT" in inp
