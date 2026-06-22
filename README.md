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

## Installation

The wizard runs from a single script. The launcher builds an isolated Conda
environment (Python 3.10 + Textual) on first use:

```bash
git clone https://github.com/REPLACE_ME/charmmgui2cp2k.git
cd charmmgui2cp2k
./tui install     # create/repair the local .conda-tui environment
```

Diagnostics and environment management:

```bash
./tui doctor      # environment + terminal diagnostics
./tui --plan      # show the launch plan without starting
./tui reset       # rebuild the environment
```

## Usage

```bash
./tui                         # auto-detect terminal, launch the best frontend
./tui /path/to/charmm-gui-output
./tui --screen-safe           # compact mode for screen/tmux/Android/narrow TTYs
./tui cli                     # plain CLI wizard
```

One-command quickstart on the bundled demo system (no input files needed):

```bash
charmmgui2cp2k --no-tui --demo          # generate from the bundled QM/MM demo
```

After activating the environment once (`conda activate ./.conda-tui`), the
commands `charmmgui2cp2k` and `charmmgui2cp2k-tui` are available directly.

Keyboard: `Tab`/`Shift-Tab` move, `Enter` activates, `Ctrl-N` next phase,
`Ctrl-P` back, `Ctrl-Q` quit, `F1` help.

## Testing

```bash
./.conda-tui/bin/python -m pytest -q tests/
```

Tests are organized as `tests/unit/` (scientific-core unit tests),
`tests/regression/` (golden-output baselines), and the existing TUI / launcher
integration tests at `tests/`. Tests that need the large bundled reference
system skip automatically when it is absent.

## Project status

Pre-release (`0.1.0`), under active development toward a peer-reviewed software
publication. See [`PUBLICATION_READINESS_PLAN.md`](PUBLICATION_READINESS_PLAN.md)
for the rigor, validation, and usability roadmap.

## License

MIT — see [`LICENSE`](LICENSE). If you use this software, please cite it via
[`CITATION.cff`](CITATION.cff).
