# TUI Recovery Prompt

You are resuming an interrupted TUI implementation run.

Do not restart from scratch. Read the latest TUI run manifest, command log, phase log, test logs, and patch notes.

Tasks:

1. Identify the last completed phase and gate decision.
2. Identify modified files and confirm rollback paths.
3. Re-run the smallest relevant smoke checks:
   - `python -m py_compile charmmgui2cp2k.py`
   - Textual import probe in the selected environment.
   - Latest failing test or dispatch command.
4. Continue from the next uncompleted phase.
5. Preserve CLI behavior and source input files.
6. Record what was resumed, what was skipped, and why.

If the interruption happened during dependency installation, inspect and log the environment state before installing or removing anything.

