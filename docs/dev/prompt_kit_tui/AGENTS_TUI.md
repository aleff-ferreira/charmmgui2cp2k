# Autonomous TUI Implementation Agent Instructions

This is the persistent master instruction for an autonomous coding agent implementing the `charmmgui2cp2k.py` Textual TUI in this folder.

## Access Mode

The agent is authorized to operate in unrestricted full-access mode for this project. Internet access, local command execution, filesystem reads/writes, package installation, isolated environment creation, terminal/PTY testing, and long-running local jobs are permitted when they serve the TUI implementation objective.

Full access does not mean careless access:

- Do not modify unrelated user data.
- Do not delete or overwrite source inputs unless the action is explicitly necessary, logged, and reversible.
- Before changing `charmmgui2cp2k.py` or project-critical files, create a timestamped backup or preserve a patch/rollback note.
- Track package installations, virtual environments, downloaded artifacts, generated outputs, and writes outside the workspace.
- Prefer isolated environments for Textual and test dependencies. Do not pollute global Python unless explicitly justified and logged.
- Record failed tools, negative results, skipped work, and uncertainty. Never fabricate missing results.

## Objective

Implement and validate the Textual TUI frontend for `charmmgui2cp2k.py` while preserving the validated CLI/non-interactive generation path.

The final TUI must:

- Launch with `python3 charmmgui2cp2k.py --tui --dir .` when Textual is available and stdin is a TTY.
- Keep `--no-tui` and `--non-interactive` on the CLI path.
- Import cleanly when Textual is absent, preserving the current fallback behavior.
- Use the same scientific core functions and defaults as the CLI unless a difference is explicitly documented and tested.
- Avoid freezing the event loop during file parsing, topology work, generation, or CP2K checks.
- Provide clear phase navigation, validation messages, recoverable errors, and generation progress.
- Be testable headlessly through Textual `run_test()` and, when possible, smoke-tested in a real PTY.
- Meet the design standard in `prompt_kit_tui/TUI_DESIGN_BRIEF.md`: polished, futuristic, aesthetically coherent, keyboard-first, self-explanatory, and suitable for expert scientific operations.
- Make the primary workflow understandable from the UI itself. External docs are still required for reproducibility, but not for basic operation.

## Required Phase-Gated Workflow

Use the phase prompts in `prompt_kit_tui/prompts/`:

1. Phase 0: workspace, full-access permissions, backups, environment, TUI run scaffold.
2. Phase 1: current TUI/CLI code audit and parity map.
3. Phase 2: Textual/domain UX intelligence, acceptance criteria, test strategy.
4. Phase 3: isolated dependency/tool feasibility and smoke imports.
5. Phase 4: architecture and test harness preparation.
6. Phase 5: iterative TUI implementation.
7. Phase 6: validation, regression, PTY/headless testing, and repair.
8. Phase 7: final release review, red-team critique, docs, and handoff.

At every phase:

- State what was done, what was not done yet, and why.
- Create or update the required files.
- Update logs with commands, versions, data sources, outputs, assumptions, and failures.
- Collect evidence before making claims.
- Stop at the gate if required evidence is missing.

## Non-Negotiable Constraints

- Do not degrade the previously validated CLI/non-interactive path.
- Do not silently alter scientific defaults to fit the TUI.
- Do not claim a visual or interaction behavior works without test or PTY evidence.
- Do not hide Textual import/version failures.
- Do not launch CP2K production jobs merely to test the TUI.
- Treat file presence as weaker evidence than actual import, headless UI interaction, command dispatch, and regression tests.
- Do not substitute long in-app tutorial prose for good interaction design. Use labels, layout, validation state, disabled-action reasons, and progressive disclosure.

## Final Deliverables

The final report must include:

- Executive summary.
- Objectives and success criteria.
- Environment and Textual versions.
- Code architecture and files changed.
- CLI/TUI parity map.
- Test matrix and results.
- UX/design validation results, including resize, keyboard-only operation, visual hierarchy, and self-explanation review.
- Headless Textual test evidence.
- PTY/manual smoke evidence or explicit reason it could not be run.
- Fallback behavior when Textual is absent.
- Known limitations, risks, and negative results.
- Rollback notes.
- Exact run commands for users.
