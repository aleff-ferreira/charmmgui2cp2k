# Autonomous Project Agent Instructions

This file is the persistent master instruction for autonomous AI agents working in this folder.

## Access Mode

The agent is authorized to operate in unrestricted full-access mode for this project. Internet access, local command execution, filesystem reads/writes, package installation, environment creation, hardware profiling, and long-running local jobs are permitted when they serve the project objective.

Full access does not mean careless access:

- Do not modify unrelated user data.
- Do not delete or overwrite source inputs unless the action is explicitly necessary, logged, and reversible.
- Before changing project-critical files, create a timestamped backup or preserve a patch/rollback note.
- Track package installations, global environment changes, external writes outside the workspace, downloaded artifacts, and generated outputs.
- Prefer isolated environments for new dependencies.
- Record failed tools, negative results, skipped work, and uncertainty. Never fabricate missing results.

## Local Workspace Context

This folder currently contains a CHARMM-GUI/AMBER to CP2K QM/MM project workspace:

- `charmmgui2cp2k.py`: large production-oriented CLI/TUI generator for CP2K QM/MM input workflows.
- `step3_input.parm7`, `step3_input.rst7`, `step3_input.pdb`: AMBER topology, restart/coordinate, and PDB inputs for a 143,099-atom solvated system.
- `step4.0_minimization.mdin`, `step4.1_equilibration.mdin`, `step5_production.mdin`: AMBER MD stage inputs. `step5_production.mdin` defines a QM/MM region with `ifqnt=1`, 163 `iqmatoms`, `qmcharge=3`, `qm_theory='DFTB3'`, and a `3ob-3-1` DFTB parameter path.
- `input.config.dat`: CHARMM-GUI/Amber setup metadata: ff14SB, GAFF2, TIP3P, custom HETA/HETB/HETC/HETD ligand parameters, 115 A cubic cell.
- `cp2k_output_20260418_104734/`: generated CP2K-ready topology variants `system_mm.prmtop` and `system_qmmm.prmtop`.
- `.claude/settings.local.json`: pre-existing broad permission settings.

The folder is not a Git repository at the time this file was created. Use manual backups and manifests unless a repository is initialized by the user.

## Required Operating Pattern

Use the phase-gated workflow in `prompt_kit/`:

1. Phase 0: establish workspace, full-access permissions, machine profile, backups, logs, and reproducibility scaffolding.
2. Phase 1: audit available data, code, prior outputs, and assumptions.
3. Phase 2: gather credible domain intelligence; define the problem, controls, benchmarks, validation criteria, and success metrics.
4. Phase 3: evaluate tools, installations, dependency isolation, runtime tests, licensing, hardware fit, and fallbacks.
5. Phase 4: prepare inputs and project objects with quality-control checks.
6. Phase 5: generate candidates through a staged funnel.
7. Phase 6: validate candidates by independent methods.
8. Phase 7: run the most rigorous evaluation only on finalists.

At every phase:

- State what was done, what was not done yet, and why.
- Create or update the required files.
- Update logs with commands, versions, data sources, outputs, assumptions, and failures.
- Collect evidence before making claims.
- Stop at the gate if required evidence is missing.

## Adaptive Planning

After Phase 0 hardware and environment profiling, tune the plan to the actual machine:

- Select tools according to installed software, CPU/GPU/RAM/storage, license availability, and runtime budget.
- Adjust parallelism, batch sizes, precision modes, checkpoint intervals, and validation depth.
- Prefer fast probes before expensive jobs.
- Stop unproductive branches early when they consume their branch budget without producing gate evidence.
- Reserve final wall time for validation, interpretation, and reporting.
- Do not launch a long job near the end unless it is guaranteed to finish in the remaining time and is needed for the gate.

Default budget allocation for any total wall time `T`:

- Phase 0: 8 percent.
- Phase 1: 10 percent.
- Phase 2: 15 percent.
- Phase 3: 12 percent.
- Phase 4: 15 percent.
- Phase 5: 20 percent.
- Phase 6: 12 percent.
- Phase 7 and final report: 8 percent minimum. Increase this reserve for high-risk or publishable work.

Checkpoint at every phase boundary and at least every 30 minutes during long work.

## Subagents

Use subagents only for bounded tasks with consolidated outputs, such as independent literature review, tool feasibility checks, code audit, validation review, or red-team critique. Do not create uncontrolled branches. Each subagent must return evidence, file paths reviewed, assumptions, risks, and a concise recommendation.

## Final Deliverables

The final report must be domain-neutral but rigorous. Include:

- Executive summary or abstract.
- Objectives and success criteria.
- Assumptions and unresolved questions.
- Machine profile and environment details.
- Prior-art or prior-run audit.
- Input curation and quality-control evidence.
- Tool and pipeline architecture.
- Validation results, controls, negative results, and uncertainty/confidence estimates.
- Limitations and risks.
- Ranked outputs or recommendations.
- Reproducibility links to inputs, scripts, logs, manifests, and generated artifacts.
- Recommended next actions for human review or real-world execution.

The final candidate/output table must include identifiers, source files, generation method, validation evidence, uncertainty/confidence level, risks, rationale, reproducibility links, and recommended next action.

