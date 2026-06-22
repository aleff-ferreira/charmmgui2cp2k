# Folder Audit

Audit date: 2026-05-04

## Summary

This directory is a computational chemistry / molecular simulation workspace centered on converting CHARMM-GUI/AMBER QM/MM assets into CP2K QM/MM workflows. It is not currently a Git repository, so reproducibility and rollback must be handled with explicit manifests, hashes, and backups.

## Files Observed

Core generator:

- `charmmgui2cp2k.py`: 20,039-line Python script. It provides a CLI wizard and optional Textual TUI for CHARMM-GUI to CP2K QM/MM input generation. It includes AMBER topology parsing, ParmEd integration, CP2K version/capability checks, hardware-aware launcher recommendations, MM and QM/MM stage assembly, restart handling, SCF/ADMM policy logic, boundary charge audits, and output reports.

Input data:

- `step3_input.parm7`: AMBER topology, ASCII, about 27 MB. `POINTERS` reports 143,099 atoms.
- `step3_input.rst7`: AMBER restart/coordinate file, ASCII, first record reports 143,099 atoms.
- `step3_input.pdb`: PDB coordinates, 143,099 `ATOM` records.
- `input.config.dat`: CHARMM-GUI metadata for an AMBER force field setup with ff14SB, GAFF2, TIP3P, custom HETA/HETB/HETC/HETD ligand parameter files, and 115 x 115 x 115 A dimensions.

Simulation stage files:

- `step4.0_minimization.mdin`: AMBER minimization input, 5,000 cycles with restraints.
- `step4.1_equilibration.mdin`: AMBER NVT equilibration input, 125,000 steps at 303.15 K.
- `step5_production.mdin`: AMBER NVT production input with QM/MM enabled. It declares 163 QM atom indices, `qmcharge=3`, `qm_theory='DFTB3'`, `qmcut=12.0`, and `dftb_slko_path='#cur_folder/parameters/3ob-3-1'`.

Generated CP2K-related outputs:

- `cp2k_output_20260418_104734/system_mm.prmtop`
- `cp2k_output_20260418_104734/system_qmmm.prmtop`

Other:

- `.claude/settings.local.json`: broad pre-existing permissions including web fetches, reads, package/tool probes, CP2K commands, Python commands, and file moves.
- `__pycache__/`: compiled Python bytecode.
- `.codex`: empty file.

## Scientific/Technical Signals

The PDB contains protein residues, water, ions, and custom ligands/cofactors:

- Water: 127,335 atoms.
- Ions: 128 Na+ atoms and 119 Cl- atoms by PDB residue labels.
- Custom HET groups: HETA 23 atoms, HETB 23 atoms, HETC 88 atoms, HETD 90 atoms.
- The QM/MM atom list in `step5_production.mdin` appears to include atoms from custom HET groups and protein/environment atoms near the active site.

The conversion script already contains many production safeguards: CP2K compatibility reporting, parser validation option, ParmEd backend discovery, ADMM coverage checks, restart policy handling, QM/MM link atom/boundary charge logic, hardware probing, and generated execution wrapper support.

## Immediate Risks To Control

- No Git repository exists, so accidental overwrite risk must be controlled through manual backups.
- Topology and coordinate files are large; avoid repeated full-file copies unless needed.
- QM/MM correctness depends on atom indexing, charge/multiplicity, link boundaries, parameter coverage, CP2K version compatibility, and DFTB/DFT parameter availability.
- File presence is not evidence of scientific correctness.
- Generated CP2K inputs should be parser-checked and scientifically reviewed before production execution.
- Any package installation or global environment change must be logged.

## Recommended Prompt-Kit Defaults For This Folder

- Access mode: unrestricted full-access mode, with audit logs and reversible changes.
- Start with Phase 0 and create `runs/<project>_<timestamp>/` for all logs/manifests.
- Preserve original AMBER/CHARMM-GUI inputs read-only unless a phase explicitly creates a derived copy.
- Use `python3 -m py_compile charmmgui2cp2k.py` as a fast code sanity check.
- Use `python3 charmmgui2cp2k.py --dir . --dry-run --non-interactive` as a later workflow probe only after dependency availability is logged.
- Use CP2K `--input-check` if a compatible CP2K binary exists.
- Validate QM atom count, charge, multiplicity, link atoms, custom residues, and parameter files before production.

