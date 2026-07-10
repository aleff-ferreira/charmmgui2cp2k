# charmmgui2cp2k

**Automated generation of CP2K QM/MM input from CHARMM-GUI / AMBER biomolecular setups.**

`charmmgui2cp2k` is a terminal-native wizard — a plain CLI and a full-screen
[Textual](https://textual.textualize.io/) TUI sharing one validated core — that
turns CHARMM-GUI QM/MM Interfacer / AMBER topology and coordinate files into
immediately runnable [CP2K](https://www.cp2k.org/) QM/MM inputs. It automates the
error-prone, CP2K-specific authoring steps (`QM_KIND`/`MM_INDEX` enumeration,
`LINK` atom definition, charge and Lennard-Jones pre-edits) and embeds the
scientific safeguards a careful QM/MM setup requires.

## Statement of need

Setting up a biomolecular QM/MM simulation in CP2K from an existing AMBER /
CHARMM-GUI system is currently a manual, expert task: users hand-enumerate the
QM region, define every boundary `LINK` atom, redistribute boundary charges, and
pre-edit the AMBER topology. Mistakes in any of these silently produce
physically wrong simulations.

No existing tool closes this gap end-to-end. CHARMM-GUI's QM/MM Interfacer is
web-based, semiempirical-only, and emits CHARMM/AMBER engine input (not CP2K);
CP2K ships no setup wizard; ASH is a scripting library rather than a guided
wizard; MiMiCPy targets CPMD + GROMACS. `charmmgui2cp2k` is, to our knowledge,
the first automated CHARMM-GUI/AMBER → CP2K QM/MM input generator, and the only
one delivered as an offline terminal wizard aimed at enzyme active sites,
metalloproteins, and redox cofactors.

## Scientific safeguards

The generator does not just reformat files; it validates the QM/MM partition:

- **Topology validation** — PRMTOP pointer cross-checks, CHAMBER rejection,
  mixed-SCEE detection.
- **Boundary / link atoms** — automatic detection of bonds crossing the QM/MM
  boundary, hydrogen link-atom capping, forbidden-cut classification (rejects
  chemically impossible cuts), M1/M2 enrichment, GEEP embedding radii.
- **Charge conservation** — residual-charge redistribution with PRMTOP
  round-trip verification and severity escalation against literature thresholds.
- **Spin-state risk analysis** — a multi-detector taxonomy (transition metals,
  redox cofactors, π-stacking geometry, unresolved elements, electron parity)
  that refuses to auto-assign multiplicity when the choice is unreliable.
- **CP2K version-capability gating** — keyword/basis/dispersion emission gated
  against the detected CP2K version with documented fallbacks.
- **Provenance** — every non-default decision is logged
  (`run_provenance.txt`, `boundary_charges.json/.dat`, `electronic_state.dat`,
  compatibility report).

## Quickstart

```bash
pipx install "charmmgui2cp2k[tui]"     # isolated install with the full-screen TUI
charmmgui2cp2k --demo                   # try it now on the bundled QM/MM system
charmmgui2cp2k /path/to/charmm-gui-output   # ...then on your own system
```

That is the whole path from nothing to a complete, runnable CP2K QM/MM input set.
[`pipx`](https://pipx.pypa.io) installs it into its own environment and puts the
`charmmgui2cp2k` / `charmmgui2cp2k-tui` commands on your `PATH`.

## Installation

Pick whichever fits — **no AmberTools, compilers, or Conda required.** The only
runtime dependencies are ParmEd and NumPy (for correct topology preparation),
both pip-installed automatically; Textual is an optional extra for the TUI.

**A. pipx (recommended).** Isolated, one command, always up to date:

```bash
pipx install "charmmgui2cp2k[tui]"   # CLI + TUI
pipx install charmmgui2cp2k          # CLI only
```

**B. pip into a virtual environment:**

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install "charmmgui2cp2k[tui]"    # drop [tui] for the CLI only
```

**C. Zero-config, no Python setup (Conda TUI launcher).** Clone and run — the
`./tui` launcher builds an isolated Conda env (Python 3.10 + Textual) on first
use and auto-detects your terminal:

```bash
git clone https://github.com/aleff-ferreira/charmmgui2cp2k.git
cd charmmgui2cp2k
./tui                 # first run creates the env, then launches the TUI
./tui doctor          # environment + terminal diagnostics
./tui reset           # rebuild the environment
```

The **CLI wizard imports with the standard library only** (fast start; `--help`
and `--version` work immediately), and pulls ParmEd + NumPy for the actual
topology preparation at generation time. Textual is an optional extra used
solely for the full-screen TUI.

## Usage

The `charmmgui2cp2k-tui` command launches the full-screen TUI; `charmmgui2cp2k`
runs the plain CLI wizard. Both share one validated scientific core.

```bash
charmmgui2cp2k-tui                       # full-screen TUI (needs the [tui] extra)
charmmgui2cp2k                           # guided CLI wizard (current directory)
charmmgui2cp2k /path/to/charmm-gui-output   # point it at your CHARMM-GUI/AMBER output
charmmgui2cp2k --demo                    # one-command demo, no input files needed
charmmgui2cp2k --non-interactive --strict --dir run/   # scripted / CI-safe run
```

`--strict` turns any unresolved scientific concern (bad boundary cut,
parity-inconsistent spin, unrunnable input, …) into a non-zero exit, so bad
setups never silently reach a queue.

TUI keyboard: `Tab`/`Shift-Tab` move, `Enter` activates, `Ctrl-N` next phase,
`Ctrl-P` back, `Ctrl-Q` quit, `F1` help. On GNU screen / tmux / Android / narrow
terminals use the `./tui --screen-safe` launcher (or `charmmgui2cp2k-tui`, which
auto-detects and adapts).

## Testing

```bash
pip install "charmmgui2cp2k[dev]"   # or: ./.conda-tui/bin/python -m pytest -q tests/
pytest -q tests/
```

Tests are organized as `tests/unit/` (scientific-core unit tests),
`tests/regression/` (golden-output baselines), and the existing TUI / launcher
integration tests at `tests/`. Tests that need the large bundled reference
system skip automatically when it is absent.

## Project status

Pre-release (`0.1.0`), under active development toward a peer-reviewed software
publication. See [`docs/dev/PUBLICATION_READINESS_PLAN.md`](docs/dev/PUBLICATION_READINESS_PLAN.md)
for the rigor, validation, and usability roadmap.

## License

MIT — see [`LICENSE`](LICENSE). If you use this software, please cite it via
[`CITATION.cff`](CITATION.cff).
