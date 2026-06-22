"""Headless TUI usability tests across terminal sizes (Phase 5 / B8).

The TUI must remain usable from minimum to wide terminals without crashing,
losing the phase rail/footer, or breaking keyboard navigation. These run the
app headlessly (Textual run_test) against the small bundled demo system so they
are fast and CI-runnable (no large reference data needed).
"""

import pytest

pytest.importorskip("textual")

import charmmgui2cp2k as c  # noqa: E402

pytestmark = pytest.mark.tui


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("tui_resize_demo")
    c.setup_demo_workdir(str(d))
    return str(d)


# (cols, rows, compact, compat): minimum, normal desktop, wide desktop.
SIZES = [
    pytest.param(80, 24, True, True, id="min-80x24-compat"),
    pytest.param(120, 40, False, False, id="normal-120x40"),
    pytest.param(200, 60, False, False, id="wide-200x60"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("cols,rows,compact,compat", SIZES)
async def test_tui_mounts_and_navigates_at_size(demo_dir, cols, rows, compact, compat):
    app = c.CharmmGui2Cp2kApp(
        work_dir=demo_dir, compact_mode=compact, compat_mode=compat,
        terminal_profile={"small": compact},
    )
    async with app.run_test(size=(cols, rows)) as pilot:
        await pilot.pause(5.0)
        # The single workbench screen is mounted with the phase host.
        assert app.screen is not None
        assert app.screen.current_index == 0
        # Breadcrumb (phase rail) and footer are always present, every size.
        assert len(list(app.screen.query(c.PhaseBreadcrumb))) == 1
        assert len(list(app.screen.query(c.FooterBar))) == 1
        # Keyboard navigation advances a phase without crashing.
        await pilot.press("ctrl+n")
        await pilot.pause(5.0)
        assert app.screen.current_index == 1
        # Going back works too.
        await pilot.press("ctrl+p")
        await pilot.pause(1.0)
        assert app.screen.current_index == 0


@pytest.mark.asyncio
async def test_sidebar_hidden_in_compact_shown_in_desktop(demo_dir):
    compact = c.CharmmGui2Cp2kApp(work_dir=demo_dir, compact_mode=True)
    async with compact.run_test(size=(80, 24)) as pilot:
        await pilot.pause(2.0)
        assert len(list(compact.screen.query(c.SystemSummary))) == 0

    desktop = c.CharmmGui2Cp2kApp(work_dir=demo_dir, compact_mode=False)
    async with desktop.run_test(size=(140, 45)) as pilot:
        await pilot.pause(2.0)
        assert len(list(desktop.screen.query(c.SystemSummary))) == 1
