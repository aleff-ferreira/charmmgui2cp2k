# Manuscript figures

| File | Figure | Source | How to regenerate |
|------|--------|--------|-------------------|
| `fig1_architecture.mmd` | Fig 1: architecture / data flow | hand-authored Mermaid | `mmdc -i fig1_architecture.mmd -o fig1_architecture.png` (mermaid-cli) |
| `fig2_tui_workbench.svg` | Fig 2: TUI workbench screenshot | live Textual render | `python figures/make_tui_screenshot.py` |
| `fig3_nve_conservation.png` | Fig 3: NVE energy conservation (A4.1) | `validation/results/nve_ala_dipeptide-1.ener` | `python figures/make_figures.py` |
| `fig4_boundary_scheme.png` | Fig 4: boundary over-polarization (A4.3) | `validation/results/singlepoint_probes_report.txt` | `python figures/make_figures.py` |

`make_figures.py` requires matplotlib; `make_tui_screenshot.py` requires Textual.
Figures 3–4 are fully reproducible from the committed validation outputs. Run all
from the repo root with the project environment, e.g.
`./.conda-tui/bin/python figures/make_figures.py`.

Pending (need the production system / external suite): a metalloprotein (LAAO)
case-study figure (A4.5) and a BioExcel benchmark agreement table (A4.4).
