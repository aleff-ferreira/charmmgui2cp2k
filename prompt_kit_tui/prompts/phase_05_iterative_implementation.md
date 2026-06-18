# Phase 5 Prompt: Iterative TUI Implementation

## Objective

Implement the TUI in small, validated increments.

## Do Now

Work in short increments. After each increment, run the relevant smallest tests.

Required increments:

1. Make the TUI import and instantiate cleanly with Textual installed.
2. Fix dispatch so `--tui` launches the TUI only when Textual and a TTY are available.
3. Ensure fallback messages are clear and do not cause unexpected EOF in non-interactive contexts.
4. Make all phase widgets mount without crashing.
5. Implement the product-quality layout:
   - persistent phase rail or breadcrumb.
   - sticky system summary.
   - validation/status tray.
   - main task area with one dominant action per phase.
   - generation progress surface.
   - restrained futuristic visual language.
6. Make navigation work:
   - next.
   - back.
   - quit/help.
7. Make the UI self-explanatory:
   - clear control labels.
   - local validation reasons.
   - disabled controls with concise reason.
   - progressive disclosure for advanced controls.
   - no long tutorial text.
8. Make validation records visible and non-fatal.
9. Make generation phase safe:
   - dry-run or mocked path for tests.
   - worker or non-blocking handling for heavy operations.
10. Preserve CLI paths:
   - `--non-interactive`
   - `--no-tui`
   - `--help`

Create/update:

- `manifests/tui_implementation_log.md`
- `manifests/tui_design_implementation_notes.md`
- `manifests/code_change_log.md`
- `logs/phase_05_iterative_implementation.md`
- `phase_notes/phase_05_gate.md`
- test files or test logs under `validation/`

## Do Not Do

- Do not hide failing tests.
- Do not degrade CLI to make TUI pass.
- Do not add untested scientific behavior inside UI callbacks.
- Do not run production CP2K jobs.
- Do not accept a merely functional UI if it is confusing, cluttered, or requires documentation for the primary path.

## Gate

PASS only if:

- TUI imports with Textual installed.
- `run_test()` can mount the app.
- Basic navigation passes.
- The primary workflow is visually coherent and self-explanatory under review.
- CLI smoke tests still pass.
- All code edits have rollback notes.
