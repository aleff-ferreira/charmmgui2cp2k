"""Integration test for parity enforcement + exit-code standardization
(audit fixes M8, M11).

A parity-inconsistent multiplicity is a physical impossibility; in
non-interactive mode the generator must refuse it and exit with the
scientific-rigor code (STRICT_GATE_EXIT_CODE = 3), distinct from a usage error
(1) or an argparse error (2), so CI/batch can tell rigor failures apart.
"""

import subprocess
import sys

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit

_MODULE = c.__file__


def _run_demo(tmp_path, *extra):
    return subprocess.run(
        [sys.executable, _MODULE, "--no-tui", "--demo",
         "--dir", str(tmp_path / "wd"), *extra],
        capture_output=True, text=True, timeout=300,
    )


def test_parity_violation_exits_with_rigor_code(tmp_path):
    """Demo QM region has 8 (even) electrons -> multiplicity 2 is impossible."""
    proc = _run_demo(tmp_path, "--multiplicity", "2")
    assert proc.returncode == c.STRICT_GATE_EXIT_CODE, (
        f"expected exit {c.STRICT_GATE_EXIT_CODE}, got {proc.returncode}\n"
        f"{proc.stdout[-2000:]}"
    )
    assert "parity-INCONSISTENT" in proc.stdout or "incompatible" in proc.stdout


def test_parity_consistent_multiplicity_succeeds(tmp_path):
    proc = _run_demo(tmp_path, "--multiplicity", "1")
    assert proc.returncode == 0, f"expected 0, got {proc.returncode}\n{proc.stdout[-2000:]}"


def test_rigor_exit_code_distinct_from_usage_and_argparse():
    """Guard the semantic contract: 3 = rigor, distinct from 1 and 2."""
    assert c.STRICT_GATE_EXIT_CODE == 3
