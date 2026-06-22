# Phase 0 Prompt: TUI Workspace Bootstrap

You are implementing the Textual TUI for `charmmgui2cp2k.py`.

Access mode: unrestricted full-access mode.

## Do Now

1. Create a timestamped run directory under `runs/`, for example:
   - `runs/LAAO_CP2K_QMMM_TUI_YYYYMMDD_HHMMSS_TZ/`
2. Create subdirectories:
   - `logs/`
   - `manifests/`
   - `backups/`
   - `profiles/`
   - `validation/`
   - `installs/`
   - `external_writes/`
   - `phase_notes/`
3. Back up `charmmgui2cp2k.py` before editing.
4. Record hashes for:
   - `charmmgui2cp2k.py`
   - `AGENTS.md`
   - `prompt_kit_tui/`
   - any existing tests
5. Profile the machine and Python environment:
   - OS, CPU, memory, disk.
   - `python3 --version`, `which python3`, `pip --version`.
   - Current Textual import result.
   - Current `--help` and `--tui` fallback behavior.
6. Create logs:
   - `run_manifest.yaml`
   - `logs/command_log.md`
   - `external_writes/external_writes.md`
   - `installs/install_log.md`
   - `profiles/environment_report.md`
   - `manifests/backup_manifest.md`
   - `manifests/assumption_register.md`

## Do Not Do Yet

- Do not install packages yet.
- Do not edit source code yet.
- Do not claim the TUI works.
- Do not launch CP2K production jobs.

## Evidence To Collect

- Backup path and hash verification.
- Baseline command outputs:
  - `python3 -m py_compile charmmgui2cp2k.py`
  - `python3 charmmgui2cp2k.py --help`
  - Textual import probe.
  - `python3 charmmgui2cp2k.py --tui --dry-run --dir .` if safe; capture expected fallback behavior.

## Gate

PASS only if:

- Backup exists and is hash-verified.
- Run directory and logs exist.
- Baseline CLI compile/help status is known.
- Current Textual availability is documented.
- All writes are logged.

If any gate evidence is missing, stop and repair the scaffold before continuing.

