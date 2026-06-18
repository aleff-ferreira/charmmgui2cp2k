# TUI Conda Workflow

The pipeline implementation remains one script:

```text
/home/nexus/aleff/fcup/laao_codex/charmmgui2cp2k.py
```

The Conda environment installs command names that point directly to that script. After activation, you do not need to call `./tui` or any path.

## One-Time Setup

```bash
cd /home/nexus/aleff/fcup/laao_codex
./tui install
```

This creates or repairs:

```text
/home/nexus/aleff/fcup/laao_codex/.conda-tui
```

and installs these commands into the env:

```text
charmmgui2cp2k
charmmgui2cp2k-tui
```

They are symlinks to `charmmgui2cp2k.py`; there is no second pipeline script.

## Daily Use

Activate the env once per terminal session:

```bash
conda activate /home/nexus/aleff/fcup/laao_codex/.conda-tui
```

Then start the adaptive TUI from any directory:

```bash
charmmgui2cp2k-tui
```

For the current project inputs:

```bash
cd /home/nexus/aleff/fcup/laao_codex
charmmgui2cp2k-tui
```

For another CHARMM-GUI folder:

```bash
cd /path/to/charmm-gui-output
charmmgui2cp2k-tui
```

or:

```bash
charmmgui2cp2k-tui --dir /path/to/charmm-gui-output
```

## Commands

Adaptive TUI:

```bash
charmmgui2cp2k-tui
```

Same TUI name, explicit compatibility mode:

```bash
charmmgui2cp2k-tui --tui-screen-safe
```

Regular CLI wizard:

```bash
charmmgui2cp2k
```

Regular CLI wizard, no TUI:

```bash
charmmgui2cp2k --no-tui
```

TUI using the CP2K script command name:

```bash
charmmgui2cp2k --tui
```

## Device Compatibility

`charmmgui2cp2k-tui` auto-detects:

- GNU `screen`
- `tmux`
- Android / Termux-like shells
- narrow terminals

When needed, it uses compact inline mode and disables unreliable mouse handling.

Keyboard controls:

```text
Tab / Shift-Tab  move between controls
Enter            activate focused controls
Ctrl-N           next step
Ctrl-P           previous step
Ctrl-Q           quit
```

## Maintenance

Use `./tui` only for setup and diagnostics:

```bash
./tui doctor
./tui reset
./tui --plan
```

Legacy wrappers still work, but are no longer the recommended interface:

```bash
./start_tui.sh
./start_tui_screen.sh
./install_tui_conda.sh
```
