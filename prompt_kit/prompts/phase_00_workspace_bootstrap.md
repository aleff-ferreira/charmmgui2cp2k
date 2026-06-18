# Phase 0 Prompt: Workspace Bootstrap

```text
Phase 0 objective: establish workspace, unrestricted full-access permissions, machine profile, environment constraints, logging, backups, and reproducibility scaffolding.

Project placeholders:

- [PROJECT_NAME]:
- [DOMAIN]:
- [OBJECTIVE]:
- [WORKSPACE_PATH]:
- [TOTAL_TIME_BUDGET]:
- [ACCESS_MODE]: unrestricted full-access mode
- [AVAILABLE_INPUTS]:
- [REQUIRED_DELIVERABLES]:
- [RISK_CONSTRAINTS]:
- [PREFERRED_OUTPUT_FORMATS]:

What to do:

1. Confirm that access mode is unrestricted full-access mode for this project.
2. Create a timestamped run directory under [WORKSPACE_PATH]/runs/ unless an existing run directory is provided.
3. Create logs and manifests before doing substantive work:
   - `run_manifest.*`
   - `command_log.*`
   - `machine_profile.*`
   - `environment_report.*`
   - `backup_manifest.*`
   - `external_writes.*`
   - `install_log.*`
   - `assumption_register.*`
4. Profile the machine: OS, kernel, CPU, RAM, GPU, disk space, shell, Python/R/Node/compiled toolchains as relevant, package managers, network availability, and current working directory.
5. Detect whether the workspace is a Git repository. If not, use manual backups and file hashes.
6. Identify critical files and create a reversible backup strategy. Do not copy huge files unnecessarily; record hashes or metadata when full copies are impractical.
7. Establish time-budget allocation using [TOTAL_TIME_BUDGET]. If no budget is given, propose a conservative default and reserve final reporting time.
8. Define command logging format and external-write tracking.
9. State environment constraints and likely bottlenecks.

What not to do yet:

- Do not install new packages unless needed to complete profiling.
- Do not transform input data.
- Do not run domain analysis or long jobs.
- Do not optimize the pipeline.

Evidence to collect:

- Machine and environment command outputs.
- Workspace path and file summary.
- Backup/hash strategy.
- Available storage.
- Access mode statement.

Gate to pass:

Phase 0 passes only if logs/manifests exist, machine profile is recorded, critical inputs have backup or hash protection, external writes are tracked, and the time-budget strategy is documented.

If tools fail or evidence is insufficient:

- Record the failure in `command_log.*`.
- Use fallback commands where possible.
- If critical files cannot be protected, stop and request human review.
- If hardware profiling is partial, label unknowns and choose conservative defaults.

End with:

- Phase 0 gate decision: PASS, PASS WITH RISKS, or STOP.
- Files created/updated.
- Evidence summary.
- Assumptions and unresolved risks.
- Whether Phase 1 is authorized.
```

