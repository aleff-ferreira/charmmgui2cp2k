import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.integration

# The Conda-dependent launcher tests need a built local environment, which is
# not present on a fresh CI runner. Skip them cleanly there; they still run
# locally after `./tui install`.
_HAVE_CONDA_ENV = (ROOT / ".conda-tui" / "bin" / "python").exists()
requires_conda_env = pytest.mark.skipif(
    not _HAVE_CONDA_ENV,
    reason="local .conda-tui environment not present (run ./tui install)",
)


def run_launcher(*args, env=None):
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        args,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=merged_env,
        timeout=30,
        check=True,
    )


def test_unified_launcher_help_and_plan():
    help_result = run_launcher("./tui", "--launcher-help")
    assert "Usage: ./tui" in help_result.stdout
    assert "./tui doctor" in help_result.stdout

    plan_result = run_launcher("./tui", "--plan", "--no-install")
    assert "root:" in plan_result.stdout
    assert "env:" in plan_result.stdout
    assert "env_status:" in plan_result.stdout
    assert "frontend:" in plan_result.stdout
    if _HAVE_CONDA_ENV:
        assert "env_status: ready" in plan_result.stdout


@requires_conda_env
def test_conda_env_commands_point_to_single_pipeline_script():
    run_launcher("./tui", "install", "--skip-tests")

    pipeline = ROOT / "charmmgui2cp2k.py"
    env_bin = ROOT / ".conda-tui" / "bin"

    for command in ("charmmgui2cp2k", "charmmgui2cp2k-tui"):
        command_path = env_bin / command
        assert command_path.is_symlink()
        assert command_path.resolve() == pipeline

    assert not (env_bin / "laao-tui").exists()

    help_result = run_launcher(str(env_bin / "charmmgui2cp2k-tui"), "--help")
    assert "CHARMM-GUI" in help_result.stdout


def test_legacy_wrappers_are_thin_valid_delegates():
    for script in ("tui", "start_tui.sh", "start_tui_screen.sh", "install_tui_conda.sh"):
        run_launcher("bash", "-n", script)

    result = run_launcher("./start_tui.sh", "--launcher-help")
    assert "Usage: ./tui" in result.stdout


def test_screen_safe_plan_in_a_pty_when_available():
    script_bin = subprocess.run(
        ["bash", "-lc", "command -v script"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()
    if not script_bin:
        return

    result = subprocess.run(
        [
            script_bin,
            "-qfec",
            "./tui --screen-safe --plan --no-install",
            "/dev/null",
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "TERM": "screen-256color",
            "STY": "pytest-screen",
        },
        timeout=30,
        check=True,
    )
    assert "screen=1" in result.stdout
    if "tty_out=1" in result.stdout:
        assert "frontend: compat" in result.stdout
    else:
        assert "frontend: cli" in result.stdout
