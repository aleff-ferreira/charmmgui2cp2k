# TUI Implementation Runbook

This runbook is for a competent but busy user who wants the Textual TUI implemented without breaking the validated CLI path.

## What To Run First

Start with:

```bash
cd /home/nexus/aleff/fcup/laao_codex
python3 -m py_compile charmmgui2cp2k.py
python3 - <<'PY'
import charmmgui2cp2k as c
print("HAS_TEXTUAL=", c.HAS_TEXTUAL)
print("textual_error=", repr(c._textual_import_error))
print("App class exists=", hasattr(c, "CharmmGui2Cp2kApp"))
PY
```

Expected current result before implementation: Textual is absent and `HAS_TEXTUAL=False`.

## Recommended Dependency Strategy

Use a local environment:

```bash
python3 -m venv .venv-tui
. .venv-tui/bin/activate
python -m pip install --upgrade pip
python -m pip install textual pytest pytest-asyncio
```

Optional visual regression:

```bash
python -m pip install pytest-textual-snapshot
```

Record exact versions in the run manifest.

## Manual Quality Checks

After implementation, check:

```bash
. .venv-tui/bin/activate
python -m py_compile charmmgui2cp2k.py
python -c "import charmmgui2cp2k as c; print(c.HAS_TEXTUAL, hasattr(c, 'CharmmGui2Cp2kApp'))"
python charmmgui2cp2k.py --help
python charmmgui2cp2k.py --no-tui --dry-run --non-interactive --dir .
python charmmgui2cp2k.py --tui --dir .
```

The final command needs a real TTY. If running through an API or non-TTY environment, use Textual `run_test()` tests and a PTY tool such as `script` where available.

## Design Quality Checks

The TUI is not accepted merely because it launches. Inspect whether:

- The current phase, completed phases, warnings, and next safe action are obvious.
- A competent user can move from file detection to generation without reading this runbook.
- Advanced controls are discoverable but not in the default path.
- Validation failures explain the corrective action in concise, local language.
- Terminal resize does not cause text overlap or clipped critical controls.
- The visual style is coherent: restrained futuristic console, semantic colors, stable spacing, and no decorative noise.

## Gate Validation

File presence is not enough. Require:

- Import evidence with Textual installed.
- Import/fallback evidence with Textual absent or simulated absent.
- Headless interaction tests using `App.run_test()`.
- UX tests or review evidence for keyboard-only flow, resize behavior, visual hierarchy, and self-explanation.
- CLI non-regression.
- PTY smoke evidence or a documented blocker.
- Clear run instructions.

## What "Done" Means

The TUI is done when a user can launch it with `--tui`, navigate phases, understand the next safe action without a manual, see validation feedback, generate or dry-run through the same core logic, and still use the CLI exactly as before.
