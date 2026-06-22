# Copy-Paste Execution Order

Use this order in the target autonomous AI session.

## Initial Context

Paste this first if the agent does not automatically read instruction files:

1. `../AGENTS.md`
2. `templates/project_manifest.yaml`
3. `FOLDER_AUDIT.md`

Then tell the agent:

```text
Use unrestricted full-access mode as authorized in AGENTS.md. Create a timestamped run directory, protect original inputs, log all commands and external writes, and proceed phase by phase. Do not skip gates.
```

## Phase Prompts

Paste one phase prompt at a time:

1. `prompts/phase_00_workspace_bootstrap.md`
2. `prompts/phase_01_inventory_audit.md`
3. `prompts/phase_02_domain_intelligence.md`
4. `prompts/phase_03_tool_feasibility.md`
5. `prompts/phase_04_input_preparation.md`
6. `prompts/phase_05_candidate_generation.md`
7. `prompts/phase_06_validation.md`
8. `prompts/phase_07_finalist_deep_evaluation.md`

After each phase, ask:

```text
Show the phase gate decision, required files created/updated, evidence collected, unresolved assumptions, failed tools, and whether the next phase is authorized.
```

## Recovery

If a run is interrupted, paste:

1. `RECOVERY_PROMPT.md`
2. The latest run manifest and phase log.
3. Any error logs or partial output paths.

## Independent Review

Before accepting final deliverables, paste:

1. `RED_TEAM_REVIEW_PROMPT.md`
2. `final_report.*`
3. `final_candidate_table.*`
4. The phase logs and manifests.

The reviewer must produce findings first, with severity and file/line/path references where possible.

