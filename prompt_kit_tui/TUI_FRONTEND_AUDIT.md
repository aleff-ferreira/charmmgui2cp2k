# TUI Frontend Audit

Audit date: 2026-05-05

Workspace: `/home/nexus/aleff/fcup/laao_codex`

## Existing TUI Surface

The file `charmmgui2cp2k.py` already contains a Textual TUI block:

- Textual import guard near lines `44-77`.
- TUI layer starts near line `13651`.
- `if HAS_TEXTUAL:` guards all TUI classes.
- Intended App class: `CharmmGui2Cp2kApp`.
- Intended screen host: `WorkbenchScreen`.
- Phase widgets include `SystemPhase`, `QMPhase`, `BoundaryPhase`, `MethodPhase`, `ElectronicPhase`, `WorkflowPhase`, `PreviewPhase`, and `GeneratePhase`.
- Dispatch logic near line `20137` routes `--tui` to `CharmmGui2Cp2kApp` only when Textual is available and stdin is a TTY.

## Current Failure Mode

Current import probe:

```text
HAS_TEXTUAL=False
textual_error=ModuleNotFoundError("No module named 'textual'")
App class exists=False
```

Observed behavior:

- `python3 charmmgui2cp2k.py --tui --dry-run --dir .` warns that Textual is unavailable.
- It falls back to the plain CLI wizard.
- In a non-interactive API session, the fallback CLI may hit EOF when it prompts.

## Primary Implementation Risks

1. **Dependency risk**
   - Textual is not installed in the active Python environment.
   - The agent must prefer a project-local virtual environment.

2. **Guarded-code risk**
   - Because the TUI classes are defined only under `if HAS_TEXTUAL:`, import tests must be run with Textual installed.
   - Fallback import tests must also be run without Textual or in a clean environment.

3. **CLI regression risk**
   - The CLI path has been repaired and validated. TUI changes must not break `--non-interactive`, `--no-tui`, or `--help`.

4. **Scientific parity risk**
   - The TUI generation path currently appears to duplicate or partially reassemble CLI behavior in `GeneratePhase`.
   - The implementation should reduce drift by reusing validated core assembly paths or documenting unavoidable differences.

5. **Event-loop risk**
   - Parsing 143,099-atom inputs and generating topology artifacts can block.
   - Blocking operations should run in workers or be clearly staged so the UI remains responsive.

6. **Validation risk**
   - A TUI can appear to launch while still failing navigation, commit, validation, generation, or fallback behavior.
   - Required validation must include Textual `run_test()` interaction tests and command-line dispatch tests.

## Target Definition Of Done

The TUI implementation is done only when:

- Textual dependency is installed in an isolated environment or otherwise reproducibly available.
- `python -c "import charmmgui2cp2k as c; print(c.HAS_TEXTUAL)"` reports `True` in the TUI environment.
- `CharmmGui2Cp2kApp` can be instantiated.
- Headless `run_test()` tests cover launch, phase navigation, validation messaging, resize behavior, and at least one generation dry-run or mocked-generation path.
- CLI regression commands pass.
- Textual-absent fallback behavior remains intact.
- A PTY smoke test is run or explicitly documented as impossible.
- Final docs tell a user exactly how to launch and test the TUI.

