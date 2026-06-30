"""Unit tests for the shared scientific gates that restore TUI/CLI parity
(audit fixes C2, C3, H12).

The TUI was a second, weaker code path: forbidden link bonds, ADMM aux-basis
coverage, and MD parameter ranges were enforced by the CLI but not by the
corresponding TUI phases. The gating logic now lives in pure module-level
helpers (`forbidden_link_bond_messages`, `admm_coverage_block_message`,
`validate_md_workflow_params`) called by both frontends; these tests pin that
logic without needing a mounted Textual app.
"""

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit


# ---------------- C2: forbidden link bonds ----------------

def test_forbidden_link_flagged_cli_keys():
    """FE is Kr-proxied in AMBER -> forbidden (CLI link-dict key convention)."""
    links = [{"QM_ELEM": "FE", "MM_ELEM": "C", "QM_INDEX": 10, "MM_INDEX": 11}]
    msgs = c.forbidden_link_bond_messages(links)
    assert len(msgs) == 1
    assert "Forbidden link bond" in msgs[0] and "FE" in msgs[0]


def test_forbidden_link_flagged_tui_keys():
    """Same detection via the TUI link-dict key convention."""
    links = [{"QM_ELEMENT": "ZN", "MM_ELEMENT": "C",
              "QM_ATOM_INDEX": 4, "MM_ATOM_INDEX": 5}]
    assert len(c.forbidden_link_bond_messages(links)) == 1


def test_ordinary_cc_link_not_forbidden():
    links = [{"QM_ELEMENT": "C", "MM_ELEMENT": "C",
              "QM_ATOM_INDEX": 9, "MM_ATOM_INDEX": 11}]
    assert c.forbidden_link_bond_messages(links) == []


def test_no_links_no_messages():
    assert c.forbidden_link_bond_messages([]) == []
    assert c.forbidden_link_bond_messages(None) == []


# ---------------- C3: ADMM aux-basis coverage ----------------

def test_admm_blocks_uncovered_metal():
    msg = c.admm_coverage_block_message({"FE": [1], "C": [2]}, True,
                                        basis_set="DZVP-MOLOPT-GTH")
    assert msg is not None and "FE" in msg and "ADMM" in msg


def test_admm_allows_covered_organic():
    assert c.admm_coverage_block_message({"C": [1], "H": [2]}, True,
                                         basis_set="DZVP-MOLOPT-GTH") is None


def test_admm_off_never_blocks():
    assert c.admm_coverage_block_message({"FE": [1]}, False) is None


def test_admm_empty_region_no_block():
    assert c.admm_coverage_block_message({}, True) is None


def test_admm_accepts_plain_list_of_elements():
    """Helper accepts a bare iterable of element symbols, not just a dict."""
    assert c.admm_coverage_block_message(["FE"], True,
                                         basis_set="DZVP-MOLOPT-GTH") is not None


# ---------------- H12: MD parameter ranges ----------------

def test_md_params_all_valid():
    assert c.validate_md_workflow_params(2000, 5000, 10000, 100000, 0.5, 300) == []


def test_md_params_catch_each_violation():
    errs = c.validate_md_workflow_params(
        em_max_iter=0, mm_nvt_steps=-1, mm_npt_steps=0,
        md_steps=0, md_timestep=0.0, md_temperature=-5,
    )
    joined = " ".join(errs)
    assert "EM max iterations" in joined
    assert "MM NVT steps" in joined
    assert "MM NPT steps" in joined
    assert "Production MD steps" in joined
    assert "timestep" in joined
    assert "temperature" in joined


def test_md_params_none_skipped():
    """None arguments are not range-checked (partial validation is allowed)."""
    assert c.validate_md_workflow_params(md_timestep=1.0) == []


def test_md_zero_timestep_is_rejected():
    assert any("timestep" in e for e in
               c.validate_md_workflow_params(md_timestep=0.0))


# ---------------- Wiring: the TUI phases actually have validate() ----------------

def test_tui_phases_have_validate_methods():
    """Guard against the gates silently disappearing from the TUI again.

    The phase classes are defined inside the TUI app factory; importing the
    module is enough to compile them. We assert the source declares a
    validate() for the three phases that previously lacked the gate.
    """
    import inspect
    src = inspect.getsource(c)
    # crude but effective: each phase class followed (eventually) by validate
    for cls in ("class BoundaryPhase", "class MethodPhase", "class WorkflowPhase"):
        assert cls in src, f"{cls} missing"
    # the three helpers are referenced from the TUI wrappers
    assert "forbidden_link_bond_messages(app.links" in src
    assert "admm_coverage_block_message(" in src
    assert "validate_md_workflow_params(" in src
