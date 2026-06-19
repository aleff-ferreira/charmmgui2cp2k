"""Unit tests for the pure scientific-core functions of charmmgui2cp2k.

These tests exercise the decision logic that determines element identity,
QM electron count, spin-multiplicity parity, CP2K version capability, ring
topology, and boundary charge redistribution -- the functions whose
correctness most directly affects whether a generated QM/MM input is
physically valid.  They use small synthetic inputs and need neither Textual
nor a real CP2K/Amber installation.
"""

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit

AMBER_CHARGE_SCALE = c.AMBER_CHARGE_SCALE


# ── CP2K version parsing / capability gating ────────────────────────────────
@pytest.mark.parametrize(
    "text,expected",
    [
        ("CP2K version 8.1 (Development Version)", (8, 1, 0)),
        ("CP2K 7.7.0 (Development Version)", (7, 7, 0)),
        ("CP2K 2023.1", (2023, 1, 0)),  # year-based versioning
        ("CP2K version 9.1", (9, 1, 0)),
        ("", None),
        ("no version here", None),
        (None, None),
    ],
)
def test_parse_cp2k_version_string(text, expected):
    assert c.parse_cp2k_version_string(text) == expected


@pytest.mark.parametrize(
    "version,required,expected",
    [
        ((8, 1, 0), (7, 1), True),
        ((7, 1, 0), (7, 1), True),   # boundary: equal
        ((7, 0, 0), (7, 1), False),
        ((2023, 1, 0), (8, 1), True),  # year-based compares above semantic
        (None, (7, 1), False),         # unknown version is never "supported"
    ],
)
def test_cp2k_version_at_least(version, required, expected):
    assert c.cp2k_version_at_least(version, required) is expected


# ── Element inference ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "atom_type,expected",
    [
        # GAFF/ff14SB carbon type codes must resolve to carbon, not Ca/Co.
        ("CA", "C"), ("CT", "C"), ("CX", "C"), ("C", "C"), ("C1", "C"),
        ("N", "N"), ("N3", "N"), ("O", "O"), ("OW", "O"),
        ("H", "H"), ("HC", "H"),
        # Genuine two-letter elements are preserved.
        ("CL", "CL"), ("BR", "BR"), ("SE", "SE"),
        ("FE", "FE"), ("ZN", "ZN"),
        # Alias suffix 'X' must not turn CL/FE into C/F.
        ("CLX", "CL"), ("FEX", "FE"),
        # Explicit ionic charge marker.
        ("Na+", "NA"),
    ],
)
def test_infer_element_heuristic(atom_type, expected):
    assert c.infer_element(atom_type) == expected


def test_infer_element_unresolved_returns_none():
    assert c.infer_element("xyz") is None


def test_infer_element_atomic_number_overrides_heuristic():
    # ATOMIC_NUMBER is authoritative: a "NA"-looking type with Z=6 is carbon.
    assert c.infer_element("NA", atomic_numbers=[6], atom_idx=0) == "C"


# ── QM electron counting + multiplicity parity ──────────────────────────────
def test_estimate_qm_electrons_methyl_no_links():
    ec, meta = c.estimate_qm_electrons_for_spin({"C": [1], "H": [2, 3, 4]}, 0, None)
    assert ec == 7  # C(4) + 3*H(1)
    assert meta["final_electron_parity"] == "odd"
    assert meta["link_electrons_added"] == 0


def test_estimate_qm_electrons_adds_link_hydrogens():
    ec, meta = c.estimate_qm_electrons_for_spin(
        {"C": [1], "H": [2, 3, 4]}, 0, [{"QM_INDEX": 1, "MM_INDEX": 9}]
    )
    assert ec == 8  # 7 + 1 link-H cap
    assert meta["link_electrons_added"] == 1
    assert meta["final_electron_parity"] == "even"


def test_estimate_qm_electrons_subtracts_charge():
    ec, _ = c.estimate_qm_electrons_for_spin({"C": [1], "H": [2, 3, 4]}, 1, None)
    assert ec == 6  # 7 - charge(+1)


def test_estimate_qm_electrons_unresolved_element_returns_none():
    ec, meta = c.estimate_qm_electrons_for_spin({"Xx": [1]}, 0, None)
    assert ec is None
    assert "Xx" in meta["unresolved_elements"]


@pytest.mark.parametrize(
    "mult,electrons,expected",
    [
        (1, 8, True),    # even e- -> odd multiplicity (singlet)
        (2, 8, False),   # even e- with doublet is impossible
        (2, 7, True),    # odd e- -> even multiplicity (doublet)
        (1, 7, False),
        (3, 8, True),    # triplet of an 8-electron system is allowed by parity
    ],
)
def test_validate_multiplicity_parity(mult, electrons, expected):
    consistent, _ = c.validate_multiplicity_parity(mult, electrons)
    assert consistent is expected


def test_validate_multiplicity_parity_unknown_electron_count():
    consistent, _ = c.validate_multiplicity_parity(1, None)
    assert consistent is None


# ── Ring detection ──────────────────────────────────────────────────────────
def _ring_adjacency(cycle_nodes):
    adj = {n: set() for n in cycle_nodes}
    k = len(cycle_nodes)
    for i in range(k):
        a, b = cycle_nodes[i], cycle_nodes[(i + 1) % k]
        adj[a].add(b)
        adj[b].add(a)
    return adj


def test_find_small_rings_benzene():
    rings = c._find_small_rings(_ring_adjacency([0, 1, 2, 3, 4, 5]))
    assert len(rings) == 1
    assert set(rings[0]) == {0, 1, 2, 3, 4, 5}


def test_find_small_rings_five_membered():
    rings = c._find_small_rings(_ring_adjacency([0, 1, 2, 3, 4]))
    assert len(rings) == 1
    assert set(rings[0]) == {0, 1, 2, 3, 4}


def test_find_small_rings_open_chain_has_no_rings():
    # 0-1-2-3 path, no closing bond
    adj = {0: {1}, 1: {0, 2}, 2: {1, 3}, 3: {2}}
    assert c._find_small_rings(adj) == []


# ── Residual boundary-charge redistribution ─────────────────────────────────
class FakeTopo:
    """Minimal stand-in exposing only what build_residual_charge_plan reads."""

    def __init__(self, charges_e, residue_pointer, residue_labels):
        self._charges_raw = [q * AMBER_CHARGE_SCALE for q in charges_e]
        self._resptr = list(residue_pointer)
        self._reslab = list(residue_labels)
        self.natom = len(charges_e)

    def get_float_array(self, flag):
        return list(self._charges_raw) if flag == "CHARGE" else []

    def get_int_array(self, flag):
        if flag == "RESIDUE_POINTER":
            return list(self._resptr)
        if flag == "POINTERS":
            return [self.natom]
        return []

    def get_string_array(self, flag):
        return list(self._reslab) if flag == "RESIDUE_LABEL" else []


def test_residual_charge_plan_conserves_charge_uniform():
    # One residue, 4 atoms; atom 1 is QM and carries +0.5 e.
    topo = FakeTopo([0.5, -0.2, -0.1, -0.2], [1], ["ALA"])
    plan = c.build_residual_charge_plan([1], topo, m1_set=set())
    assert len(plan) == 1
    entry = plan[0]
    assert entry["target_atoms"] == [2, 3, 4]
    assert entry["removed_charge_e"] == pytest.approx(0.5)
    # The redistributed total must equal the excised charge (exact invariant).
    redistributed = sum(u["new_charge_e"] - u["old_charge_e"] for u in entry["updates"])
    assert redistributed == pytest.approx(0.5, abs=1e-9)
    # Uniform split: each target gets the same delta.
    deltas = [u["new_charge_e"] - u["old_charge_e"] for u in entry["updates"]]
    assert deltas == pytest.approx([0.5 / 3] * 3)
    # MM charge of the residue is restored to overall neutrality.
    assert entry["mm_charge_after_e"] == pytest.approx(0.0, abs=1e-9)


def test_residual_charge_plan_excludes_frontier_m1_atom():
    topo = FakeTopo([0.5, -0.2, -0.1, -0.2], [1], ["ALA"])
    plan = c.build_residual_charge_plan([1], topo, m1_set={2})
    entry = plan[0]
    assert entry["target_atoms"] == [3, 4]  # atom 2 (M1) excluded
    redistributed = sum(u["new_charge_e"] - u["old_charge_e"] for u in entry["updates"])
    assert redistributed == pytest.approx(0.5, abs=1e-9)


def test_residual_charge_plan_distance_weighted_falls_back_without_coords():
    topo = FakeTopo([0.5, -0.2, -0.1, -0.2], [1], ["ALA"])
    plan = c.build_residual_charge_plan(
        [1], topo, m1_set=set(), redistribute_strategy="distance_weighted", coords=None
    )
    assert "fallback" in plan[0]["redistribute_strategy"]


def test_residual_charge_plan_no_qm_atoms_is_empty():
    topo = FakeTopo([0.5, -0.2, -0.1, -0.2], [1], ["ALA"])
    assert c.build_residual_charge_plan([], topo, m1_set=set()) == []


# ── Combined cross-channel charge-conservation audit (A3.1) ─────────────────
def _consistent_plan():
    return [
        {
            "residue_index": 2, "residue_label": "ALA", "removed_charge_e": 0.5,
            "updates": [
                {"old_charge_e": 0.0, "new_charge_e": 0.25},
                {"old_charge_e": 0.0, "new_charge_e": 0.25},
            ],
        }
    ]


def _consistent_links():
    return [{"QM_INDEX": 11, "M1_INDEX": 9, "M1_CHARGE_E": -0.18,
             "M2_INDICES": [7, 15]}]


def test_charge_conservation_audit_passes_when_both_channels_balance():
    audit = c.verify_qmmm_charge_conservation(_consistent_plan(), _consistent_links())
    assert audit["ok"] is True
    assert audit["fist_residual"]["entries"] == 1
    assert audit["fist_residual"]["total_moved_e"] == pytest.approx(0.5)
    assert audit["embedding_add_mm_charge"]["links"] == 1
    assert audit["embedding_add_mm_charge"]["total_m1_charge_e"] == pytest.approx(0.18)
    assert audit["issues"] == []


def test_charge_conservation_audit_flags_fist_drift():
    bad_plan = [
        {
            "residue_index": 2, "residue_label": "ALA", "removed_charge_e": 0.5,
            "updates": [{"old_charge_e": 0.0, "new_charge_e": 0.20}],  # only 0.2 applied
        }
    ]
    audit = c.verify_qmmm_charge_conservation(bad_plan, [])
    assert audit["ok"] is False
    assert audit["fist_residual"]["consistent"] is False
    assert any("residual" in m.lower() for m in audit["issues"])


def test_charge_conservation_audit_empty_inputs_are_ok():
    audit = c.verify_qmmm_charge_conservation([], [])
    assert audit["ok"] is True
    assert audit["fist_residual"]["entries"] == 0
    assert audit["embedding_add_mm_charge"]["links"] == 0


def test_charge_conservation_audit_ignores_links_without_m2():
    # A link with no M2 neighbours places no ADD_MM_CHARGE source -> not counted.
    links = [{"QM_INDEX": 11, "M1_INDEX": 9, "M1_CHARGE_E": -0.18, "M2_INDICES": []}]
    audit = c.verify_qmmm_charge_conservation([], links)
    assert audit["ok"] is True
    assert audit["embedding_add_mm_charge"]["links"] == 0


def test_format_charge_conservation_reports_status():
    lines = c.format_qmmm_charge_conservation(
        c.verify_qmmm_charge_conservation(_consistent_plan(), _consistent_links())
    )
    text = "\n".join(lines)
    assert "Boundary charge conservation: OK" in text
    assert "FIST residual redistribution" in text
    assert "ADD_MM_CHARGE embedding" in text


# ── Boundary & method decision trail (A3.4) ─────────────────────────────────
def test_decision_trail_records_strategy_and_method():
    plan = [{"residue_label": "ALA", "redistribute_strategy": "uniform"}]
    trail = c.build_boundary_decision_trail(
        residual_charge_plan=plan, boundary_charge_scheme="CHARGE_SHIFT",
        functional="B3LYP", basis_set="DZVP-MOLOPT-GTH",
        admm_aux_basis="cFIT3", use_admm=True,
    )
    assert trail["boundary_charge_scheme"] == "CHARGE_SHIFT"
    assert trail["n_redistributed_residues"] == 1
    assert trail["redistribution_strategies"] == ["uniform"]
    assert "proxy" in trail["pp_choice"]  # B3LYP uses a GTH-BLYP proxy
    assert trail["admm"] == "enabled, aux=cFIT3"


def test_decision_trail_admm_disabled():
    trail = c.build_boundary_decision_trail(use_admm=False)
    assert trail["admm"] == "disabled"


def test_decision_trail_emitted_in_electronic_state(tmp_path):
    qm_meta = {"qm_valence_electrons": 8, "link_electrons_added": 1,
               "final_electron_count": 8, "link_count": 1, "link_h_valence": 1}
    trail = c.build_boundary_decision_trail(
        residual_charge_plan=[{"redistribute_strategy": "uniform"}],
        boundary_charge_scheme="CHARGE_SHIFT", functional="PBE",
        basis_set="DZVP-MOLOPT-GTH", use_admm=False,
    )
    out = tmp_path / "electronic_state.dat"
    c.write_electronic_state_dat(str(out), qm_meta, 0, 1, boundary_decisions=trail)
    text = out.read_text()
    assert "Boundary & Method Decision Trail" in text
    assert "REDISTRIBUTION_STRATEGY: uniform" in text
    assert "PSEUDOPOTENTIAL_CHOICE:" in text
