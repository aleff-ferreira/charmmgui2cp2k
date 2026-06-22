# Local QM/MM Runbook

This tutorial applies the universal phase kit to the current CHARMM-GUI/AMBER to CP2K workspace.

## Before Running The Agent

Keep the original scientific inputs unchanged:

- `step3_input.parm7`
- `step3_input.rst7`
- `step3_input.pdb`
- `step4.0_minimization.mdin`
- `step4.1_equilibration.mdin`
- `step5_production.mdin`
- `input.config.dat`

The folder is not a Git repository, so the agent should create a timestamped `runs/` directory and use hashes/manifests before deriving new files.

## Paste Order For This Folder

1. Paste `../AGENTS.md` if the target AI does not automatically read it.
2. Paste `THIS_PROJECT_MASTER_PROMPT.md`.
3. Paste `prompts/phase_00_workspace_bootstrap.md`.
4. Continue with phases 1-7 only after each gate passes.

## Useful Local Checks

The agent should log commands like these during the appropriate phases:

```bash
python3 -m py_compile charmmgui2cp2k.py
```

Use later, after dependency state is logged:

```bash
python3 charmmgui2cp2k.py --dir . --dry-run --non-interactive
```

If CP2K is available and candidate CP2K inputs are generated:

```bash
cp2k.psmp --version
cp2k.psmp --input-check <generated_input.inp>
```

If the script generates a wrapper, inspect it before running production:

```bash
bash -n <generated_run_wrapper.sh>
```

## Manual Quality Checks

Review these before accepting any generated QM/MM workflow:

- Does the QM atom list in `step5_production.mdin` match the intended active-site chemistry?
- Are QM charge and multiplicity justified?
- Are HETA/HETB/HETC/HETD parameter sources and residue identities understood?
- Are link atoms and boundary charge treatment documented?
- Are DFTB parameters or CP2K basis/pseudopotential files available on the actual machine?
- Did `charmmgui2cp2k.py` produce compatibility reports, boundary audits, and wrapper notes?
- Did CP2K parser checks pass for every generated input?
- Were failed tools, warnings, and negative results included in the final report?

## Expected Output Pattern

A serious run should eventually contain:

- `runs/<project>_<timestamp>/run_manifest.*`
- `runs/<project>_<timestamp>/machine_profile.*`
- `runs/<project>_<timestamp>/inventory_manifest.*`
- `runs/<project>_<timestamp>/tool_feasibility_matrix.*`
- `runs/<project>_<timestamp>/qc_report.*`
- `runs/<project>_<timestamp>/validation_report.*`
- `runs/<project>_<timestamp>/final_report.*`
- Generated CP2K outputs in a timestamped output directory, if generation is authorized.

File presence is not correctness. The contents must support the scientific and technical claims.

