# Copy-Paste Execution Order

Use this order in the target autonomous AI session.

## Initial Context

Paste or point the agent to:

1. `prompt_kit_tui/AGENTS_TUI.md`
2. `prompt_kit_tui/TUI_FRONTEND_AUDIT.md`
3. `prompt_kit_tui/templates/project_manifest.yaml`

Then tell the agent:

```text
Use unrestricted full-access mode as authorized. Create a timestamped TUI implementation run directory, back up `charmmgui2cp2k.py`, use isolated dependencies by default, preserve CLI behavior, log all commands and external writes, and proceed phase by phase. Do not skip gates.
```

## Phase Prompts

Paste one phase prompt at a time:

1. `prompts/phase_00_workspace_bootstrap.md`
2. `prompts/phase_01_tui_code_audit.md`
3. `prompts/phase_02_framework_intelligence.md`
4. `prompts/phase_03_tool_feasibility.md`
5. `prompts/phase_04_architecture_test_harness.md`
6. `prompts/phase_05_iterative_implementation.md`
7. `prompts/phase_06_validation_regression.md`
8. `prompts/phase_07_finalist_release_review.md`

After each phase, ask:

```text
Show the gate decision, files created or updated, evidence collected, failed tools, unresolved assumptions, and whether the next phase is authorized.
```

## Recovery

If interrupted, paste:

1. `RECOVERY_PROMPT.md`
2. Latest TUI run manifest.
3. Latest phase log.
4. Any failing test logs.

## Independent Review

Before accepting the TUI, paste:

1. `RED_TEAM_REVIEW_PROMPT.md`
2. Final report.
3. Test matrix.
4. Validation logs.
5. Patch or diff against original `charmmgui2cp2k.py`.

