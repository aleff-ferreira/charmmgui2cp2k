# Universal Agentic Project Prompt Kit

This kit turns a broad project request into a phase-gated autonomous workflow. It is customized for the current CHARMM-GUI/AMBER to CP2K QM/MM folder, but the prompts remain domain-adaptive.

## What This Kit Contains

- `../AGENTS.md`: persistent master instruction file for an autonomous coding/research agent.
- `FOLDER_AUDIT.md`: local folder analysis and project-specific risks.
- `PHASE_GATE_MATRIX.md`: phase gates, evidence requirements, and stop rules.
- `EXECUTION_ORDER.md`: exact copy-paste order.
- `MASTER_PROMPT.md`: universal master prompt for generating a customized kit for any project.
- `THIS_PROJECT_MASTER_PROMPT.md`: ready-to-paste master prompt for this exact folder.
- `LOCAL_QMMM_RUNBOOK.md`: local tutorial for applying the phase workflow to this CP2K QM/MM workspace.
- `RECOVERY_PROMPT.md`: resume prompt for interrupted or compacted runs.
- `RED_TEAM_REVIEW_PROMPT.md`: independent critique prompt.
- `prompts/phase_00_workspace_bootstrap.md` through `prompts/phase_07_finalist_deep_evaluation.md`: one optimized prompt per phase.
- `templates/project_manifest.yaml`: editable project manifest.
- `templates/phase_log.md`: phase log format.
- `templates/final_report.md`: final report skeleton.

## Exact Order Of Use

1. Read `FOLDER_AUDIT.md` so you know what is actually in this folder.
2. For this folder, paste `THIS_PROJECT_MASTER_PROMPT.md` into the target AI. For a different project, edit or paste the values from `templates/project_manifest.yaml`.
3. Give the target AI `../AGENTS.md` first if it does not automatically read repository instruction files.
4. Use `LOCAL_QMMM_RUNBOOK.md` as the local tutorial and then paste `prompts/phase_00_workspace_bootstrap.md`.
5. Review the Phase 0 gate. Do not continue until the required files and evidence exist.
6. Paste each next phase prompt only after the previous phase gate passes:
   `phase_01_inventory_audit.md`, `phase_02_domain_intelligence.md`, `phase_03_tool_feasibility.md`, `phase_04_input_preparation.md`, `phase_05_candidate_generation.md`, `phase_06_validation.md`, `phase_07_finalist_deep_evaluation.md`.
7. Use `RECOVERY_PROMPT.md` if the run is interrupted.
8. Use `RED_TEAM_REVIEW_PROMPT.md` before accepting the final outputs.
9. Require the final report to follow `templates/final_report.md`.

## How To Validate Phase Gates

For each phase, check both file evidence and substantive evidence.

File evidence means the required logs, manifests, reports, and outputs exist.

Substantive evidence means the contents are coherent, sourced, reproducible, and sufficient for the phase claim. File presence is not scientific, technical, legal, or operational correctness.

Manual quality checks:

- Open the phase log and confirm commands, timestamps, versions, inputs, outputs, failures, and assumptions are recorded.
- Inspect source references and make sure claims are not unsupported.
- Confirm failed tools and negative results are visible.
- Confirm any generated output links back to exact inputs and methods.
- Confirm the next phase does not depend on unverified assumptions unless those assumptions are explicitly documented as provisional.

## Files Expected After Each Phase

- Phase 0: `run_manifest.*`, `machine_profile.*`, `environment_report.*`, `command_log.*`, `external_writes.*`, `backup_manifest.*`, and a phase 0 decision note.
- Phase 1: inventory manifest, hashes/sizes, prior-run audit, assumption register, data/code risk register.
- Phase 2: domain brief, source bibliography, benchmark/control plan, success metric plan.
- Phase 3: tool feasibility matrix, installation log, license notes, smoke-test evidence, fallback plan.
- Phase 4: curated inputs, QC report, rejected/modified input log, provenance links.
- Phase 5: candidate set, generation logs, ranking funnel, discarded candidate reasons.
- Phase 6: validation report, independent checks, benchmark/control results, uncertainty estimates.
- Phase 7: finalist deep-evaluation report, ranked final table, residual risk review, final report.

## When To Stop

Stop and ask for human review when:

- The agent cannot establish a reversible backup path for critical files.
- Input identity or provenance is unclear.
- Tools fail in ways that invalidate a phase gate.
- Evidence is insufficient to support the next expensive action.
- A long job would consume the final reporting reserve.
- Domain risk requires human authorization, such as publication claims, clinical/legal/financial advice, or real-world operational execution.

## Busy-User Shortcut

For this folder, paste `../AGENTS.md`, then paste the phase prompts in order from `prompts/`. Let the agent create a timestamped `runs/` directory and require it to show the phase gate summary before proceeding.
