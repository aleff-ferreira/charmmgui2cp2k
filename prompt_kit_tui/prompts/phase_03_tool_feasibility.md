# Phase 3 Prompt: Tool Feasibility And Dependency Isolation

## Objective

Create a reproducible route to run and test the TUI.

## Do Now

1. Choose a dependency strategy, preferring `.venv-tui`.
2. Install only required packages into the isolated environment:
   - `textual`
   - `pytest`
   - `pytest-asyncio`
   - optional `pytest-textual-snapshot`
3. Record exact versions and install commands.
4. Run smoke checks:
   - import Textual.
   - import `charmmgui2cp2k.py` with Textual installed.
   - confirm `HAS_TEXTUAL=True`.
   - confirm `CharmmGui2Cp2kApp` exists.
   - instantiate the app without running a real terminal UI.
5. Test fallback separately:
   - system Python without Textual, or a simulated blocked import.
   - confirm CLI import still works.
6. Assess PTY support:
   - `script`, `tty`, or another available PTY method.
7. Create/update:
   - `manifests/tui_tool_feasibility.md`
   - `installs/install_log.md`
   - `manifests/tui_dependency_lock.md`
   - `manifests/pty_feasibility.md`
   - `logs/phase_03_tool_feasibility.md`
   - `phase_notes/phase_03_gate.md`

## Do Not Do Yet

- Do not edit source code except for non-source environment metadata.
- Do not globally install dependencies unless isolated install is impossible and the reason is logged.

## Gate

PASS only if:

- Textual import works in a reproducible environment, or a clear blocker and fallback plan are documented.
- Fallback behavior remains known.
- PTY/headless test feasibility is known.

