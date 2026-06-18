# TUI Implementation Prompt Kit

This kit is a phase-gated implementation package for making the `charmmgui2cp2k.py` Textual TUI real, tested, and safe to use without weakening the validated CLI path.

It is customized for `/home/nexus/aleff/fcup/laao_codex`, where the TUI code already exists but is currently unavailable because `textual` is not installed in the active Python environment.

## Current Local Facts

- Existing script: `charmmgui2cp2k.py`.
- Textual import guard: lines near `44-77`.
- TUI block: starts near line `13651`, guarded by `if HAS_TEXTUAL:`.
- App class intended by code: `CharmmGui2Cp2kApp`.
- Dispatch: `--tui`, `--no-tui`, and fallback logic near line `20137`.
- Current environment result: `HAS_TEXTUAL=False`, `ModuleNotFoundError("No module named 'textual'")`.
- Previously validated path: non-interactive CLI generation, not the TUI.

## What This Kit Contains

- `AGENTS_TUI.md`: persistent master instruction for the TUI implementation run.
- `TUI_FRONTEND_AUDIT.md`: local code and risk audit.
- `TEXTUAL_SOURCE_NOTES.md`: primary Textual documentation references checked for this kit.
- `TUI_DESIGN_BRIEF.md`: product-quality design standard for a futuristic, self-explanatory TUI.
- `THIS_PROJECT_TUI_MASTER_PROMPT.md`: ready-to-paste project prompt.
- `MASTER_PROMPT.md`: reusable universal prompt to generate a TUI implementation kit for another project.
- `PHASE_GATE_MATRIX.md`: phase gates and stop rules.
- `EXECUTION_ORDER.md`: exact order of use.
- `TUI_IMPLEMENTATION_RUNBOOK.md`: tutorial for a busy but competent user.
- `RECOVERY_PROMPT.md`: restart prompt for interrupted work.
- `RED_TEAM_REVIEW_PROMPT.md`: independent review prompt.
- `prompts/phase_00_workspace_bootstrap.md` through `prompts/phase_07_finalist_release_review.md`: phase prompts.
- `templates/project_manifest.yaml`: editable manifest.
- `templates/tui_test_matrix.md`: required test matrix.
- `templates/final_report.md`: final report skeleton.

## Standards

The implementation agent must:

- Preserve unrestricted full-access mode.
- Use isolated dependency environments by default.
- Protect existing scientific inputs and validated CLI behavior.
- Keep the TUI as a frontend over the same scientific core, not a divergent generator.
- Build a polished, futuristic, self-explanatory scientific operations console, not a merely functional widget wrapper.
- Prove usability with design-specific checks: keyboard-only flow, terminal resizing, readable validation states, and a primary workflow that does not require a manual.
- Prove behavior with headless Textual tests, CLI regression checks, import/fallback checks, and at least one real TTY smoke run when possible.
- Record failed tools, negative results, and incomplete validation.
- Never claim the TUI works perfectly unless the defined gates pass.
