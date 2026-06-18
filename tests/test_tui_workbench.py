import os

import pytest

pytest.importorskip("textual")

import charmmgui2cp2k as c

# These tests drive the full wizard over the bundled 143k-atom reference
# system (step3_input.*), which is too large to commit and is .gitignored.
# Phase 2 of the publication-readiness plan replaces it with small committed
# fixtures; until then, skip cleanly when the reference system is absent
# (e.g. on CI) so the suite stays green.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_HAVE_REFERENCE_SYSTEM = all(
    os.path.exists(os.path.join(_ROOT, name))
    for name in ("step3_input.parm7", "step3_input.rst7", "step5_production.mdin")
)

pytestmark = [
    pytest.mark.tui,
    pytest.mark.skipif(
        not _HAVE_REFERENCE_SYSTEM,
        reason="bundled reference system (step3_input.*) not present; "
        "Phase 2 adds small committed fixtures",
    ),
]


def test_tui_core_helpers_match_mdin_qm_region():
    detected = c.detect_files(".")
    topo, _coords, _box, element_map, _unresolved, alias_plan = c._step2_parse_topology(
        detected["prmtop"],
        detected["rst7"],
    )

    result = c._step3_extract_qm_from_mdin(
        detected["mdin"],
        topo,
        element_map,
        list(alias_plan.atom_aliases),
        prmtop_path=detected["prmtop"],
        crd_path=detected["rst7"],
    )

    assert result is not None
    qm_elements, qm_indices, mdin_meta, label = result
    assert len(qm_indices) == 163
    assert mdin_meta["qmcharge"] == 3
    assert label == "iqmatoms"
    assert {key: len(value) for key, value in qm_elements.items()} == {
        "C": 42,
        "H": 90,
        "N": 11,
        "O": 20,
    }

    links, _adjacency = c._step4_detect_links(topo, qm_indices, element_map)
    assert len(links) == 5
    assert {(link["QM_ELEM"], link["MM_ELEM"]) for link in links} == {("C", "C")}


@pytest.mark.asyncio
async def test_tui_flow_sets_scientific_state_before_preview():
    app = c.CharmmGui2Cp2kApp(work_dir=".")
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.pause(5.0)
        for delay in (5.0, 5.0, 1.0, 1.0):
            await pilot.click("#btn-next")
            await pilot.pause(delay)

        assert app.screen.current_index == 4
        assert len(app.qm_indices) == 163
        assert app.qm_charge == 3
        assert app.multiplicity == 2
        assert len(app.links) == 5
        assert app.spin_decision.get("parity_consistent") is True

        await pilot.click("#btn-next")
        await pilot.pause(1.0)
        assert app.screen.current_index == 5


@pytest.mark.asyncio
async def test_tui_screen_safe_compact_mode_keeps_keyboard_navigation():
    app = c.CharmmGui2Cp2kApp(
        work_dir=".",
        compact_mode=True,
        compat_mode=True,
        terminal_profile={"screen_like": True, "small": True},
    )
    async with app.run_test(size=(76, 24)) as pilot:
        await pilot.pause(5.0)

        assert app.compact_mode is True
        assert app.compat_mode is True
        assert len(list(app.screen.query(c.SystemSummary))) == 0

        await pilot.press("ctrl+n")
        await pilot.pause(5.0)
        assert app.screen.current_index == 1
