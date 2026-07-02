"""Unit tests for basis-set recognition (H11) and ADMM coverage-at-recommendation
(M14).

H11: an unrecognized basis label previously sailed through and failed only at
CP2K runtime ("no basis set found"); it is now flagged at generation time.
M14: the ADMM aux-basis coverage gap (e.g. a QM Fe) is now surfaced when the
basis is recommended, not only rejected post-hoc by the coverage gate.
"""

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit


# ---------------- H11: basis-set recognition ----------------

@pytest.mark.parametrize("label", [
    "DZVP-MOLOPT-GTH", "TZV2P-MOLOPT-GTH", "DZVP-MOLOPT-SR-GTH",
    "dzvp-molopt-gth", "DZVP-GTH", "TZVP-GTH",
])
def test_recognized_bases(label):
    assert c.is_recognized_basis_set(label) is True
    assert c.basis_set_recognition_warning(label) is None


@pytest.mark.parametrize("label", ["", "MY-CUSTOM", "DZVP-MOLPT-GTH", "6-31G*"])
def test_unrecognized_bases_warn(label):
    assert c.is_recognized_basis_set(label) is False
    msg = c.basis_set_recognition_warning(label)
    assert msg is not None and "not a recognized" in msg


# ---------------- M14: ADMM coverage at recommendation ----------------

def test_metal_uncovered_by_recommended_admm():
    uncovered = c.admm_recommendation_uncovered_elements(
        {"FE": [1], "C": [2], "H": [3]}, basis_set="DZVP-MOLOPT-GTH")
    assert "FE" in uncovered


def test_organic_region_fully_covered():
    assert c.admm_recommendation_uncovered_elements(
        {"C": [1], "H": [2], "N": [3], "O": [4]},
        basis_set="DZVP-MOLOPT-GTH") == set()


def test_accepts_plain_element_iterable():
    assert "FE" in c.admm_recommendation_uncovered_elements(
        ["FE", "C"], basis_set="DZVP-MOLOPT-GTH")
