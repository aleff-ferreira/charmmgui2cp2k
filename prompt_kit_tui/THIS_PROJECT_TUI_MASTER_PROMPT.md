# This Project TUI Master Prompt

You are an autonomous coding AI working in `/home/nexus/aleff/fcup/laao_codex`.

Implement and validate the Textual TUI frontend for `charmmgui2cp2k.py` using the phase-gated workflow in `prompt_kit_tui/`.

Access mode: unrestricted full-access mode. Internet access, local command execution, filesystem reads/writes, package installation, isolated environment creation, terminal/PTY testing, and long-running local jobs are authorized when they serve the TUI implementation objective.

Critical constraints:

- Preserve the validated CLI and non-interactive generation path.
- Do not change scientific defaults silently.
- Use isolated dependency environments by default.
- Keep rollback notes for every source edit.
- Record all installs, external writes, commands, failures, and negative results.
- Do not claim the TUI works until headless Textual tests and CLI regression gates pass.

Known local facts:

- `charmmgui2cp2k.py` contains a Textual TUI block guarded by `if HAS_TEXTUAL:`.
- The TUI block starts near line `13651`.
- Dispatch for `--tui` is near line `20137`.
- Current environment lacks Textual: `HAS_TEXTUAL=False`, `ModuleNotFoundError("No module named 'textual'")`.
- The final validated CP2K CLI package from the previous run is `cp2k_output_20260504_175325/`.

Use prompts in this order:

1. `prompt_kit_tui/prompts/phase_00_workspace_bootstrap.md`
2. `prompt_kit_tui/prompts/phase_01_tui_code_audit.md`
3. `prompt_kit_tui/prompts/phase_02_framework_intelligence.md`
4. `prompt_kit_tui/prompts/phase_03_tool_feasibility.md`
5. `prompt_kit_tui/prompts/phase_04_architecture_test_harness.md`
6. `prompt_kit_tui/prompts/phase_05_iterative_implementation.md`
7. `prompt_kit_tui/prompts/phase_06_validation_regression.md`
8. `prompt_kit_tui/prompts/phase_07_finalist_release_review.md`

Final goal: a working, documented, tested Textual TUI that can launch through `--tui`, has fallback behavior when Textual is absent, and preserves CLI behavior.

Design goal: the finished TUI must feel like a modern scientific operations console: futuristic, aesthetically polished, keyboard-first, calm under complexity, and self-explanatory enough that the main workflow can be completed without external documentation. Use `prompt_kit_tui/TUI_DESIGN_BRIEF.md` as a hard requirement, not optional styling guidance.
