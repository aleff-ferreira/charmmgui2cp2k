#!/usr/bin/env python3
"""Render a real TUI screenshot (SVG) headlessly for the manuscript (Fig 2).

    .conda-tui/bin/python figures/make_tui_screenshot.py

Drives the Textual app against the bundled demo system and saves an SVG of the
workbench after the System phase has run its probes. Requires Textual.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import charmmgui2cp2k as c  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


async def _capture(demo_dir, out_path):
    app = c.CharmmGui2Cp2kApp(work_dir=demo_dir)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(5.0)          # let System-phase probes finish
        app.save_screenshot(out_path)


def main():
    if not c.HAS_TEXTUAL:
        sys.exit("Textual not available; cannot render the TUI screenshot.")
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        c.setup_demo_workdir(d)
        out = os.path.join(HERE, "fig2_tui_workbench.svg")
        asyncio.run(_capture(d, out))
        print("wrote", os.path.relpath(out, os.path.dirname(HERE)))


if __name__ == "__main__":
    main()
