# Manuscript figures

All figures are vector (PDF + SVG) with PNG companions, sharing one style
(`_style.py`: Okabe–Ito colourblind-safe palette, consistent type scale,
despined axes).

| Files | Figure | Source | Regenerate |
|-------|--------|--------|------------|
| `fig1_architecture.{svg,pdf,png}` | Fig 1: architecture / data flow | hand-authored SVG (`fig1_architecture.svg`) | edit the SVG; PDF/PNG via headless Chrome (below) |
| `fig2_tui.{svg,pdf,png}` | Fig 2: annotated TUI workbench | `fig2_tui_raw.png` (live TUI render) + callouts | `python figures/make_tui_figure.py` |
| `fig3_validation.{svg,pdf,png}` | Fig 3: (a) NVE conservation, (b) boundary over-polarization | `validation/results/` | `python figures/make_figures.py` |

Run from the repo root with the project environment, e.g.
`./.conda-tui/bin/python figures/make_figures.py`. `make_figures.py` and
`make_tui_figure.py` require matplotlib.

## Regenerating the raster/PDF from SVG (headless Chrome)

`fig1` is authored as SVG; `fig2_tui_raw.png` is a render of the live TUI SVG.
Both PDFs/PNGs are produced with headless Chrome, e.g.:

```bash
# capture the live TUI as SVG, then render it to PNG for annotation
python figures/make_tui_screenshot.py          # -> fig2_tui_workbench.svg
google-chrome --headless --screenshot=figures/fig2_tui_raw.png \
  --force-device-scale-factor=2 --window-size=820,560 figures/fig2_tui_workbench.svg
```

## Pending (need the production system / external suite)

A flavoenzyme case-study figure (LAAO, FAD cofactor; A4.5) and a BioExcel
benchmark agreement table (A4.4).
