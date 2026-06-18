# Phase 1 Prompt: TUI Code Audit And CLI Parity Map

## Objective

Audit the existing TUI code and CLI path before changing anything.

## Do Now

1. Locate and map:
   - Textual import guard.
   - TUI classes.
   - phase widgets.
   - dispatch logic.
   - CLI `_main_cli_wizard()`.
   - shared scientific core functions.
2. Build a CLI/TUI parity map:
   - file detection.
   - topology parsing.
   - QM region extraction.
   - boundary detection.
   - method/electronic defaults.
   - workflow/staging settings.
   - generation/wrapper/report outputs.
3. Identify duplicated logic between TUI and CLI.
4. Identify likely broken API calls, missing imports, undefined attributes, and stale Textual usage.
5. Audit existing visual and interaction design against `prompt_kit_tui/TUI_DESIGN_BRIEF.md`:
   - phase clarity.
   - next-action clarity.
   - validation visibility.
   - keyboard-only flow.
   - resize risk.
   - excessive explanatory text or visual clutter.
6. Identify testable units and hard-to-test UI behaviors.
6. Create/update:
   - `manifests/tui_code_map.md`
   - `manifests/cli_tui_parity_map.md`
   - `manifests/tui_design_gap_audit.md`
   - `manifests/tui_risk_register.md`
   - `logs/phase_01_tui_code_audit.md`
   - `phase_notes/phase_01_gate.md`

## Do Not Do Yet

- Do not install Textual.
- Do not patch code.
- Do not redesign the UI based on preference alone.

## Evidence To Collect

- File/line references for every TUI class and dispatch branch.
- Baseline behavior for CLI and fallback.
- List of exact implementation hypotheses, separated from verified facts.

## Gate

PASS only if:

- The current TUI implementation surface is mapped.
- CLI/TUI parity risks are explicit.
- Design and usability gaps are explicit.
- The next phase has a focused research and acceptance plan.
