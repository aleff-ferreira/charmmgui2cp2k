"""Guards for the install-to-usage path (pip/pipx packaging + bundled demo).

These lock in the frictionless onboarding: a zero-dependency pip package whose
console scripts and `--demo` data are declared so `pipx install charmmgui2cp2k`
followed by `charmmgui2cp2k --demo` works with no source checkout.
"""

from pathlib import Path

import pytest

import charmmgui2cp2k as c

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def _pyproject():
    return (_ROOT / "pyproject.toml").read_text()


def test_pyproject_declares_project_and_scripts():
    text = _pyproject()
    assert "[project]" in text and "[build-system]" in text
    assert 'charmmgui2cp2k = "charmmgui2cp2k:main"' in text
    assert 'charmmgui2cp2k-tui = "charmmgui2cp2k:main"' in text


def test_runtime_dependencies_declared():
    """ParmEd (and its NumPy dep) are genuine runtime requirements for
    generation and must be declared so a pip/pipx install works with no
    AmberTools. Textual stays an optional extra (TUI only)."""
    text = _pyproject()
    assert '"parmed' in text and '"numpy"' in text
    assert 'tui = ["textual' in text


def test_cli_imports_without_third_party():
    """The module must still import with the standard library only (ParmEd is
    imported lazily at generation time), so --help/--version and the CLI degrade
    gracefully even before ParmEd is present."""
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.modules.pop('parmed', None); "
         "import charmmgui2cp2k; print('ok')"],
        capture_output=True, text=True, cwd=str(_ROOT),
    )
    assert proc.returncode == 0 and "ok" in proc.stdout, proc.stderr


def test_version_is_consistent():
    assert c.__version__ == "0.1.0"
    assert 'attr = "charmmgui2cp2k.__version__"' in _pyproject()


def test_bundled_demo_data_present():
    demo = _ROOT / "demo"
    for name in ("ala_dipeptide.parm7", "ala_dipeptide.rst7",
                 "ala_dipeptide.pdb", "ala_dipeptide_qmmm.mdin"):
        assert (demo / name).is_file(), f"missing bundled demo file {name}"


def test_locate_demo_data_dir_resolves():
    d = c.locate_demo_data_dir()
    assert d is not None
    assert Path(d, "ala_dipeptide.parm7").is_file()


def test_demo_dir_shipped_via_data_files():
    """The demo data must be declared as installable data so a pip/pipx install
    can find it via sys.prefix (not only from a source checkout)."""
    text = _pyproject()
    assert "share/charmmgui2cp2k/demo" in text
