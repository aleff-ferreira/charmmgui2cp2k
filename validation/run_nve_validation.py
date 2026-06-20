#!/usr/bin/env python3
"""A4.1 — NVE energy-conservation validation for a tool-generated QM/MM setup.

This is the headline correctness probe for the generator: if the link atoms,
deleted boundary bonded terms, and boundary charge handling are mutually
self-consistent, a microcanonical (NVE) QM/MM trajectory conserves the total
("conserved quantity") energy with only small, non-drifting fluctuations. A
systematic drift signals a broken boundary.

Pipeline
--------
1. Run the validated CLI generation on the alanine-dipeptide fixture to produce
   the CP2K-ready topology variant (system_qmmm.prmtop) and coordinates
   (system.xyz).
2. Assemble a *self-contained* NVE QM/MM MD input via assemble_cp2k_input
   (reads the prmtop/xyz directly; no restart chaining), using PBE for speed —
   the conservation test validates the QM/MM coupling, not the functional.
3. Run CP2K and parse the .ener file for the conserved-quantity drift,
   reported per picosecond and normalized per degree of freedom.

Usage
-----
    .conda-tui/bin/python validation/run_nve_validation.py \
        [--steps 200] [--timestep 0.5] [--functional PBE] [--cp2k cp2k.psmp]

Requires a CP2K binary. Writes results under validation/results/.
"""

import argparse
import os
import shutil
import subprocess
import sys
import glob

# Import the pipeline from the repository root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import charmmgui2cp2k as c  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")
RESULTS = os.path.join(ROOT, "validation", "results")


def generate_topology(work_dir, cp2k_data_dir):
    """Run the CLI generation; return the cp2k_output_* directory."""
    os.makedirs(work_dir, exist_ok=True)
    shutil.copy(os.path.join(FIX, "ala_dipeptide.parm7"),
                os.path.join(work_dir, "step3_input.parm7"))
    shutil.copy(os.path.join(FIX, "ala_dipeptide.rst7"),
                os.path.join(work_dir, "step3_input.rst7"))
    shutil.copy(os.path.join(FIX, "ala_dipeptide.pdb"),
                os.path.join(work_dir, "step3_input.pdb"))
    shutil.copy(os.path.join(FIX, "ala_dipeptide_qmmm.mdin"),
                os.path.join(work_dir, "step5_production.mdin"))
    env = os.environ.copy()
    if cp2k_data_dir:
        env["CP2K_DATA_DIR"] = cp2k_data_dir
    subprocess.run(
        [sys.executable, os.path.join(ROOT, "charmmgui2cp2k.py"),
         "--no-tui", "--non-interactive", "--dir", work_dir, "--no-hardware-aware"],
        cwd=work_dir, env=env, check=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    outs = sorted(glob.glob(os.path.join(work_dir, "cp2k_output_*")))
    if not outs:
        raise RuntimeError("generation produced no cp2k_output_* directory")
    return outs[-1]


def assemble_nve_input(out_dir, project, functional, steps, timestep, temperature):
    """Build a self-contained NVE QM/MM MD input reading the generated files."""
    topo, coords, box, emap, _u, alias = c._step2_parse_topology(
        os.path.join(FIX, "ala_dipeptide.parm7"),
        os.path.join(FIX, "ala_dipeptide.rst7"),
    )
    qm_elements, qm_indices, _meta, _label = c._step3_extract_qm_from_mdin(
        os.path.join(FIX, "ala_dipeptide_qmmm.mdin"), topo, emap,
        list(alias.atom_aliases),
        prmtop_path=os.path.join(FIX, "ala_dipeptide.parm7"),
        crd_path=os.path.join(FIX, "ala_dipeptide.rst7"),
    )
    links, adj = c._step4_detect_links(topo, qm_indices, emap)
    charges_e = [q / c.AMBER_CHARGE_SCALE
                 for q in topo.get_float_array("CHARGE")[: topo.natom]]
    c.enrich_link_with_m2(links, adj, set(qm_indices), charges_e)
    c.verify_link_geometry(links, coords)

    use_admm = functional.upper() in c.HYBRID_DFT_FUNCTIONALS
    qmmm_pp = c.make_qmmm_periodic_policy()
    qm_cell_abc, _ = c.compute_qm_cell(
        list(qm_indices), coords, padding=qmmm_pp.qm_cell_padding,
        box_dims=box, qmmm_periodic_policy=qmmm_pp,
    )
    qm_kinds_lines, _ = c.generate_qm_kinds(
        qm_elements, basis_set="DZVP-MOLOPT-GTH", use_admm=use_admm)
    m1_set = {int(l["MM_INDEX"]) for l in links}
    plan = c.build_residual_charge_plan(qm_indices, topo, m1_set=m1_set, coords=coords)
    override = c._apply_residual_charge_plan_to_raw_charges(
        topo.get_float_array("CHARGE"), plan)
    mm_data = c.collect_topology_variant_data(
        topo, list(qm_elements.keys()), alias_plan=alias)
    qmmm_data = c.collect_topology_variant_data(
        topo, list(qm_elements.keys()),
        charge_array_override=override, alias_plan=alias)
    rec_profile, _ = c.recommended_scf_profile(
        qm_elements.keys(), functional,
        sum(len(v) for v in qm_elements.values()), multiplicity=1)
    scf = dict(c.SCF_PROFILES[rec_profile])

    sm = c.make_system_spec(
        prmtop_file="system_qmmm.prmtop", xyz_file="system.xyz", box_dims=box,
        qm_elements=qm_elements, link_bonds=list(links),
        qm_kinds_lines=qm_kinds_lines,
        mm_kinds_lines=mm_data["mm_kinds"], mm_stage_kinds_lines=mm_data["mm_kinds"],
        qmmm_stage_kinds_lines=qmmm_data["mm_kinds"],
        mm_prmtop_file="system_mm.prmtop", qmmm_prmtop_file="system_qmmm.prmtop",
        qmmm_periodic_policy=qmmm_pp, qm_cell_abc=qm_cell_abc,
        qm_charge=0, multiplicity=1, natom=topo.natom)
    dft = c.make_dft_config(
        functional=functional, basis_set="DZVP-MOLOPT-GTH",
        cutoff=400, rel_cutoff=50, use_admm=use_admm, scf_profile=rec_profile,
        scf_max_scf=scf["max_scf"], scf_eps_scf=scf["eps_scf"],
        scf_guess=scf["scf_guess"], scf_cholesky=scf.get("cholesky"),
        qs_eps_default=scf.get("qs_eps_default"), scf_added_mos=scf["added_mos"],
        scf_mixing_method=scf["mixing_method"], scf_mixing_alpha=scf["mixing_alpha"],
        scf_nbroyden=scf["nbroyden"], outer_max_scf=scf["outer_max_scf"],
        outer_eps_scf=scf["outer_eps_scf"],
        qm_elements_for_admm=qm_elements, qm_kinds_lines_for_admm=qm_kinds_lines)
    rc = c.make_run_config(
        project_name=project, run_type="MD", md_steps=steps,
        md_timestep=timestep, md_temperature=temperature, md_ensemble="NVE")
    inp = c.assemble_cp2k_input(sm, dft, rc)
    # Validation tweak: print the conserved quantity every MD step (the tool's
    # production default is sparser) so the drift fit has dense data. This only
    # changes output frequency, not the dynamics.
    import re
    inp = re.sub(r'(&ENERGY\s*\n\s*&EACH\s*\n\s*MD\s+)\d+', r'\g<1>1', inp)
    inp_path = os.path.join(out_dir, f"{project}.inp")
    with open(inp_path, "w") as fh:
        fh.write(inp)
    return inp_path, len(qm_indices) + len(links), topo.natom


def run_cp2k(cp2k_bin, inp_path, out_dir, cp2k_data_dir, timeout):
    env = os.environ.copy()
    if cp2k_data_dir:
        env["CP2K_DATA_DIR"] = cp2k_data_dir
    log_path = inp_path.replace(".inp", ".out")
    with open(log_path, "w") as log:
        subprocess.run([cp2k_bin, "-i", os.path.basename(inp_path)],
                       cwd=out_dir, env=env, stdout=log, stderr=subprocess.STDOUT,
                       timeout=timeout, check=True)
    return log_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--timestep", type=float, default=0.5)
    ap.add_argument("--temperature", type=float, default=300.0)
    ap.add_argument("--functional", default="PBE")
    ap.add_argument("--cp2k", default=None, help="CP2K binary (auto-detected if omitted)")
    ap.add_argument("--timeout", type=int, default=3600)
    args = ap.parse_args()

    info = c.detect_cp2k_installation(probe_version=False)
    cp2k_bin = args.cp2k or (next(iter(info["binaries"].values())) if info["binaries"] else None)
    if not cp2k_bin:
        sys.exit("No CP2K binary found; pass --cp2k.")
    data_dir = c.locate_cp2k_data_dir(cp2k_info=info)

    os.makedirs(RESULTS, exist_ok=True)
    work = os.path.join(RESULTS, "nve_workdir")
    if os.path.isdir(work):
        shutil.rmtree(work)
    project = "nve_ala_dipeptide"

    print(f"[1/4] generating topology (CP2K data dir: {data_dir}) ...")
    out_dir = generate_topology(work, data_dir)
    print(f"      -> {out_dir}")

    print(f"[2/4] assembling self-contained NVE input "
          f"(functional={args.functional}, steps={args.steps}, dt={args.timestep} fs) ...")
    inp_path, qm_n, natom = assemble_nve_input(
        out_dir, project, args.functional, args.steps, args.timestep, args.temperature)
    print(f"      -> {inp_path}  (QM region ~{qm_n} centres incl. caps, {natom} atoms total)")

    print(f"[3/4] running CP2K ({cp2k_bin}) ...")
    log_path = run_cp2k(cp2k_bin, inp_path, out_dir, data_dir, args.timeout)
    print(f"      -> {log_path}")

    print("[4/4] analyzing energy conservation ...")
    ener = os.path.join(out_dir, f"{project}-1.ener")
    from analyze_energy import analyze_ener_file  # noqa: E402
    header = (
        f"# run: functional={args.functional} steps={args.steps} "
        f"dt={args.timestep} fs T={args.temperature} K\n"
        f"# cp2k: {cp2k_bin}\n"
    )
    report = header + analyze_ener_file(ener, natom=natom, temperature=args.temperature)
    report_path = os.path.join(RESULTS, "nve_energy_report.txt")
    with open(report_path, "w") as fh:
        fh.write(report)
    # Keep small, committable copies of the key artifacts.
    for src in (inp_path, ener):
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(RESULTS, os.path.basename(src)))
    print(report)
    print(f"\nWrote {report_path}")


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    main()
