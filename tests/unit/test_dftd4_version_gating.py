"""Unit tests for DFTD4 CP2K-version gating (audit fixes C1 + H8).

DFTD4 requires the s-dftd4 library linked into CP2K >= 8.1. Before this fix the
interactive upgrade path checked the version, but `--dispersion-scheme DFTD4`
(CLI override) bypassed every check, so a user on CP2K 7.x could generate input
that aborts at parse time. These tests pin the gate so that hole cannot regress.
"""

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit


def test_dftd4_keyword_registered_at_8_1():
    """The DFTD4 TYPE keyword is in the version-gate dict at its min version."""
    assert c.CP2K_DFTD4_TYPE_KEYWORD in c.CP2K_KEYWORD_MIN_VERSION
    assert c.CP2K_KEYWORD_MIN_VERSION[c.CP2K_DFTD4_TYPE_KEYWORD] == c.CP2K_DFTD4_MIN_VERSION
    assert c.CP2K_DFTD4_MIN_VERSION == (8, 1)


def test_dftd4_declared_optional_above_hard_floor():
    """Being (8,1) > hard floor (7,1), DFTD4 must be declared optional, else
    assert_version_gate_coherence would (correctly) fail."""
    assert c.CP2K_DFTD4_TYPE_KEYWORD in c.CP2K_OPTIONAL_ABOVE_HARD_FLOOR


def test_version_gate_coherence_still_holds():
    """Adding the DFTD4 entry must not break the internal coherence self-check."""
    assert c.assert_version_gate_coherence() is True


@pytest.mark.parametrize("ver", [(7, 1), (7, 5), (8, 0)])
def test_dftd4_rejected_below_floor(ver):
    """DFTD4 on a CP2K below 8.1 is a hard error (the C1 bug)."""
    with pytest.raises(ValueError, match=r"DFTD4.*requires CP2K >= 8\.1"):
        c.validate_dispersion_scheme_version("DFTD4", ver, source="--dispersion-scheme")


@pytest.mark.parametrize("ver", [(8, 1), (8, 2), (9, 1), (2024, 1)])
def test_dftd4_accepted_at_or_above_floor(ver):
    """DFTD4 on CP2K >= 8.1 passes silently."""
    assert c.validate_dispersion_scheme_version("DFTD4", ver) is None


def test_dftd4_unknown_version_warns_but_does_not_raise(capsys):
    """Unknown target version: warn (offline prep may target a newer build),
    but do not hard-fail."""
    assert c.validate_dispersion_scheme_version("DFTD4", None) is None
    out = capsys.readouterr().out
    assert "DFTD4" in out and "could not be verified" in out


@pytest.mark.parametrize("scheme", ["DFTD3_BJ", "dftd3", "NONE", None])
@pytest.mark.parametrize("ver", [(7, 1), None, (9, 9)])
def test_non_dftd4_schemes_never_gated(scheme, ver):
    """Only DFTD4 is version-gated; everything else is a no-op at any version."""
    assert c.validate_dispersion_scheme_version(scheme, ver) is None


def test_dftd4_case_insensitive():
    """Lowercase/mixed-case 'dftd4' is still gated."""
    with pytest.raises(ValueError):
        c.validate_dispersion_scheme_version("dftd4", (7, 5))
