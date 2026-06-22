# Phase 6 Prompt: Validation, Regression, And Repair

## Objective

Prove the TUI works to the defined standard, or document exactly where it does not.

## Do Now

Run the full test matrix:

1. Compile:
   - `python -m py_compile charmmgui2cp2k.py`
2. Import:
   - Textual-installed import.
   - Textual-absent fallback import.
3. CLI regression:
   - `--help`
   - `--no-tui`
   - `--non-interactive --dry-run --dir .`
4. Headless Textual tests:
   - app mount.
   - navigation.
   - validation messaging.
   - resize.
   - safe generate/dry-run or mocked generation.
   - keyboard-only primary path.
   - disabled-action reasons.
   - advanced settings disclosure.
5. UX/design validation:
   - inspect at 100x30, 120x40, and 160x50 terminal sizes.
   - confirm no critical overlap or clipping.
   - confirm phase, risk, and next action are obvious.
   - confirm warnings/errors are identifiable without color alone.
   - run a red-team self-explanation checklist.
6. PTY smoke:
   - run `--tui` in a real TTY or PTY tool if available.
   - capture evidence or blocker.
7. Optional snapshot test:
   - only if the dependency is installed and stable.
8. Repair failures iteratively and rerun affected tests.

Create/update:

- `validation/tui_test_matrix.md`
- `manifests/validation_report.md`
- `manifests/ux_validation_report.md`
- `manifests/negative_results.md`
- `logs/phase_06_validation_regression.md`
- `phase_notes/phase_06_gate.md`

## Do Not Do

- Do not claim "works perfectly."
- Do not accept launch-only evidence.
- Do not skip fallback or CLI regression checks.
- Do not claim "documentation unnecessary" unless the self-explanation review and keyboard-only test support it.

## Gate

PASS only if:

- Required tests pass, or failures are documented as accepted limitations.
- CLI regression passes.
- TUI launch/interaction evidence exists.
- UX/design validation supports the self-explanatory, polished UI claim.
- Remaining limitations are clear enough for user decision-making.
