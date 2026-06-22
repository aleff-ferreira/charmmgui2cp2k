# Phase 4 Prompt: Architecture And Test Harness Preparation

## Objective

Prepare the implementation path and tests before changing the TUI.

## Do Now

1. Decide whether to:
   - keep TUI inside `charmmgui2cp2k.py`, or
   - extract UI code to a module while preserving script dispatch.
2. Define a minimal safe test fixture strategy:
   - Prefer mocked functions or tiny synthetic fixtures for TUI interaction tests.
   - Do not require heavy CP2K execution for UI tests.
3. Define the TUI design system before implementation:
   - layout zones.
   - color roles.
   - phase/status components.
   - validation message patterns.
   - disabled-action state.
   - progressive disclosure for advanced controls.
   - resize breakpoints.
4. Create tests for current desired behavior before or alongside edits:
   - import with Textual.
   - instantiate app.
   - `run_test()` launch.
   - navigation.
   - fallback behavior.
   - CLI `--help` and non-interactive dry-run.
   - keyboard-only primary flow.
   - resize behavior.
   - self-explanation review checklist.
5. Define any needed seams to avoid heavy generation in tests.
6. Create/update:
   - `manifests/tui_architecture_plan.md`
   - `manifests/tui_design_system.md`
   - `manifests/test_harness_plan.md`
   - `validation/tui_test_matrix.md`
   - `logs/phase_04_architecture_test_harness.md`
   - `phase_notes/phase_04_gate.md`

## Do Not Do Yet

- Do not make broad UI rewrites.
- Do not run long scientific jobs.
- Do not accept tests that only import modules if interaction behavior is required.

## Gate

PASS only if:

- Test harness can run in the selected environment.
- Implementation plan preserves CLI behavior.
- Heavy work is mocked or isolated for UI tests.
- Design system is explicit enough to prevent ad hoc styling.
