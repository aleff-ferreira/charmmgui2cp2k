#!/usr/bin/env python3
"""A4.2/A4.3 — single-point QM/MM probes: reproducibility and boundary scheme.

A4.2 (reproducibility): the generated QM/MM single-point energy is deterministic
— two independent runs of the same input agree to ~machine precision. Bitwise
reproducibility is a FAIR requirement and a prerequisite for any cross-code
comparison (the production cross-code/full-QM agreement is the A4.5 LAAO case).

A4.3 (boundary over-polarization): the boundary charge scheme materially changes
the QM/MM embedding. We compute the single-point energy under three schemes —
NONE (the full M1 frontier charge is retained in the embedding -> frontier
over-polarization), Z1 (M1 removed from embedding only), and CHARGE_SHIFT (M1
removed and redistributed onto M2). The energy spread quantifies how much the
boundary treatment matters; NONE is the uncontrolled baseline the redistribution
schemes are designed to avoid.

Usage:
    .conda-tui/bin/python validation/run_singlepoint_probes.py [--functional PBE]

Requires a CP2K binary. Writes validation/results/singlepoint_probes_report.txt.
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import charmmgui2cp2k as c  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
RESULTS = os.path.join(ROOT, "validation", "results")
_ENERGY_RE = re.compile(r"ENERGY\|\s*Total FORCE_EVAL \( QMMM \) energy.*?([-\d.]+)")


def generate_topology(work_dir, cp2k_data_dir):
    os.makedirs(work_dir, exist_ok=True)
    for src, dst in (("ala_dipeptide.parm7", "step3_input.parm7"),
                     ("ala_dipeptide.rst7", "step3_input.rst7"),
                     ("ala_dipeptide.pdb", "step3_input.pdb"),
                     ("ala_dipeptide_qmmm.mdin", "step5_production.mdin")):
        shutil.copy(os.path.join(FIX, src), os.path.join(work_dir, dst))
    env = os.environ.copy()
    if cp2k_data_dir:
        env["CP2K_DATA_DIR"] = cp2k_data_dir
    subprocess.run(
        [sys.executable, os.path.join(ROOT, "charmmgui2cp2k.py"),
         "--no-tui", "--non-interactive", "--dir", work_dir, "--no-hardware-aware"],
        cwd=work_dir, env=env, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return sorted(glob.glob(os.path.join(work_dir, "cp2k_output_*")))[-1]


def assemble_singlepoint(out_dir, project, functional, scheme):
    topo, coords, box, emap, _u, alias = c._step2_parse_topology(
        os.path.join(FIX, "ala_dipeptide.parm7"), os.path.join(FIX, "ala_dipeptide.rst7"))
    qm_elements, qm_indices, _m, _l = c._step3_extract_qm_from_mdin(
        os.path.join(FIX, "ala_dipeptide_qmmm.mdin"), topo, emap, list(alias.atom_aliases),
        prmtop_path=os.path.join(FIX, "ala_dipeptide.parm7"),
        crd_path=os.path.join(FIX, "ala_dipeptide.rst7"))
    links, adj = c._step4_detect_links(topo, qm_indices, emap)
    charges_e = [q / c.AMBER_CHARGE_SCALE for q in topo.get_float_array("CHARGE")[: topo.natom]]
    c.enrich_link_with_m2(links, adj, set(qm_indices), charges_e)
    c.verify_link_geometry(links, coords)
    use_admm = functional.upper() in c.HYBRID_DFT_FUNCTIONALS
    qmmm_pp = c.make_qmmm_periodic_policy()
    qm_cell_abc, _ = c.compute_qm_cell(list(qm_indices), coords,
                                       padding=qmmm_pp.qm_cell_padding, box_dims=box,
                                       qmmm_periodic_policy=qmmm_pp)
    qm_kinds, _ = c.generate_qm_kinds(qm_elements, basis_set="DZVP-MOLOPT-GTH", use_admm=use_admm)
    plan = c.build_residual_charge_plan(qm_indices, topo,
                                        m1_set={int(l["MM_INDEX"]) for l in links}, coords=coords)
    override = c._apply_residual_charge_plan_to_raw_charges(topo.get_float_array("CHARGE"), plan)
    mm = c.collect_topology_variant_data(topo, list(qm_elements.keys()), alias_plan=alias)
    qmmm = c.collect_topology_variant_data(topo, list(qm_elements.keys()),
                                           charge_array_override=override, alias_plan=alias)
    rec, _ = c.recommended_scf_profile(qm_elements.keys(), functional,
                                       sum(len(v) for v in qm_elements.values()), multiplicity=1)
    scf = dict(c.SCF_PROFILES[rec])
    sm = c.make_system_spec(
        prmtop_file="system_qmmm.prmtop", xyz_file="system.xyz", box_dims=box,
        qm_elements=qm_elements, link_bonds=list(links), qm_kinds_lines=qm_kinds,
        mm_kinds_lines=mm["mm_kinds"], mm_stage_kinds_lines=mm["mm_kinds"],
        qmmm_stage_kinds_lines=qmmm["mm_kinds"], mm_prmtop_file="system_mm.prmtop",
        qmmm_prmtop_file="system_qmmm.prmtop", qmmm_periodic_policy=qmmm_pp,
        qm_cell_abc=qm_cell_abc, qm_charge=0, multiplicity=1, natom=topo.natom)
    dft = c.make_dft_config(
        functional=functional, basis_set="DZVP-MOLOPT-GTH", cutoff=400, rel_cutoff=50,
        use_admm=use_admm, scf_profile=rec, scf_max_scf=scf["max_scf"], scf_eps_scf=scf["eps_scf"],
        scf_guess=scf["scf_guess"], scf_cholesky=scf.get("cholesky"),
        qs_eps_default=scf.get("qs_eps_default"), scf_added_mos=scf["added_mos"],
        scf_mixing_method=scf["mixing_method"], scf_mixing_alpha=scf["mixing_alpha"],
        scf_nbroyden=scf["nbroyden"], outer_max_scf=scf["outer_max_scf"],
        outer_eps_scf=scf["outer_eps_scf"], qm_elements_for_admm=qm_elements,
        qm_kinds_lines_for_admm=qm_kinds, boundary_charge_scheme=scheme)
    # Single point = one MD step; the step-0 FORCE_EVAL energy is the SP energy.
    rc = c.make_run_config(project_name=project, run_type="MD", md_steps=1,
                           md_timestep=0.5, md_temperature=300.0, md_ensemble="NVE")
    inp = c.assemble_cp2k_input(sm, dft, rc)
    path = os.path.join(out_dir, f"{project}.inp")
    with open(path, "w") as fh:
        fh.write(inp)
    return path


def run_and_get_energy(cp2k_bin, inp_path, out_dir, cp2k_data_dir, timeout=1800):
    env = os.environ.copy()
    if cp2k_data_dir:
        env["CP2K_DATA_DIR"] = cp2k_data_dir
    log = inp_path.replace(".inp", ".out")
    with open(log, "w") as fh:
        subprocess.run([cp2k_bin, "-i", os.path.basename(inp_path)], cwd=out_dir,
                       env=env, stdout=fh, stderr=subprocess.STDOUT, timeout=timeout, check=True)
    with open(log) as fh:
        m = _ENERGY_RE.search(fh.read())
    if not m:
        raise RuntimeError(f"no FORCE_EVAL QMMM energy found in {log}")
    return float(m.group(1))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--functional", default="PBE")
    ap.add_argument("--cp2k", default=None)
    args = ap.parse_args()
    info = c.detect_cp2k_installation(probe_version=False)
    cp2k_bin = args.cp2k or (next(iter(info["binaries"].values())) if info["binaries"] else None)
    if not cp2k_bin:
        sys.exit("No CP2K binary found.")
    data_dir = c.locate_cp2k_data_dir(cp2k_info=info)
    os.makedirs(RESULTS, exist_ok=True)
    work = os.path.join(RESULTS, "sp_workdir")
    if os.path.isdir(work):
        shutil.rmtree(work)

    print("[1/3] generating topology ...")
    out_dir = generate_topology(work, data_dir)

    print("[2/3] running single points across boundary schemes (A4.3) ...")
    schemes = ["NONE", "Z1", "CHARGE_SHIFT"]
    energies = {}
    for scheme in schemes:
        inp = assemble_singlepoint(out_dir, f"sp_{scheme.lower()}", args.functional, scheme)
        energies[scheme] = run_and_get_energy(cp2k_bin, inp, out_dir, data_dir)
        print(f"      {scheme:14s} E = {energies[scheme]:.9f} Ha")

    print("[3/3] reproducibility re-run (A4.2) ...")
    inp2 = assemble_singlepoint(out_dir, "sp_charge_shift_rerun", args.functional, "CHARGE_SHIFT")
    e_rerun = run_and_get_energy(cp2k_bin, inp2, out_dir, data_dir)
    repro_diff = abs(e_rerun - energies["CHARGE_SHIFT"])

    ha2kcal = 627.509474
    spread = (max(energies.values()) - min(energies.values())) * ha2kcal
    none_vs_shift = (energies["NONE"] - energies["CHARGE_SHIFT"]) * ha2kcal

    lines = [
        f"# Single-point QM/MM probes (A4.2 reproducibility, A4.3 boundary scheme)",
        f"# functional={args.functional} cp2k={cp2k_bin}",
        "",
        "# A4.3 — boundary-scheme over-polarization (total QM/MM single-point energy)",
    ]
    for scheme in schemes:
        lines.append(f"E[{scheme:14s}] = {energies[scheme]:.9f} Ha")
    lines += [
        f"energy_spread_across_schemes = {spread:.4f} kcal/mol",
        f"NONE - CHARGE_SHIFT          = {none_vs_shift:.4f} kcal/mol "
        f"(NONE retains full M1 charge in embedding -> over-polarization baseline)",
        "",
        "# A4.2 — reproducibility (CHARGE_SHIFT run twice)",
        f"E[run1] = {energies['CHARGE_SHIFT']:.12f} Ha",
        f"E[run2] = {e_rerun:.12f} Ha",
        f"|delta| = {repro_diff:.3e} Ha  -> "
        f"{'DETERMINISTIC' if repro_diff < 1e-9 else 'NON-DETERMINISTIC (review)'}",
        "",
        "# Interpretation: a non-zero scheme spread confirms the boundary charge",
        "# treatment is physically active; bitwise reproducibility is a FAIR",
        "# prerequisite. Production cross-code/full-QM agreement is the A4.5 case.",
    ]
    report = "\n".join(lines) + "\n"
    with open(os.path.join(RESULTS, "singlepoint_probes_report.txt"), "w") as fh:
        fh.write(report)
    for scheme in schemes:
        src = os.path.join(out_dir, f"sp_{scheme.lower()}.inp")
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(RESULTS, os.path.basename(src)))
    print("\n" + report)


if __name__ == "__main__":
    main()
