# Contributing to charmmgui2cp2k

Thanks for your interest in improving the tool. This project is moving toward a
peer-reviewed software publication, so contributions should preserve scientific
correctness and reproducibility.

## Development setup

```bash
./tui install                       # build the local .conda-tui environment
./.conda-tui/bin/python -m pytest -q tests/
```

The whole pipeline lives in one script, `charmmgui2cp2k.py`, which exposes three
frontends (plain CLI wizard, Textual TUI, and non-interactive batch) over a
single shared scientific core. Changes to the core must keep all three frontends
consistent.

## Ground rules

- **No silent scientific modifications.** Any non-default decision the tool makes
  must be surfaced to the user and recorded in the provenance artifacts.
- **Add tests with code.** New scientific logic needs unit tests in
  `tests/unit/`; changes that alter generated CP2K output must update or justify
  the golden baselines in `tests/regression/`.
- **Keep the CLI path intact.** `--no-tui`, `--non-interactive`, and `--help`
  must continue to work; the TUI is an additive frontend.
- **Determinism.** Generated scientific content must be byte-identical for
  identical inputs (timestamps confined to clearly marked header lines).

## Test markers

`unit`, `regression`, `tui`, `integration`, `requires_cp2k` (see
`pyproject.toml`). Run a subset with, e.g. `pytest -m unit`.

## Pull requests

Open a PR against `main`. CI (GitHub Actions) must be green: `py_compile`, the
test suite, the Textual-absent fallback check, and the coverage report.
