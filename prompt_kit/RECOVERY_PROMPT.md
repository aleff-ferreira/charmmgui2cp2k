# Recovery Prompt For Interrupted Runs

```text
You are resuming an interrupted autonomous project run.

Access mode remains unrestricted full-access mode. Continue to protect unrelated user data, avoid destructive actions unless necessary and reversible, and log all commands, package installs, external writes, failures, and assumptions.

Project placeholders:

- [PROJECT_NAME]:
- [WORKSPACE_PATH]:
- [RUN_DIRECTORY]:
- [LAST_KNOWN_PHASE]:
- [INTERRUPTION_REASON]:
- [TOTAL_TIME_REMAINING]:
- [REQUIRED_DELIVERABLES]:

First, do not run new expensive jobs. Reconstruct state:

1. Read the latest run manifest, phase logs, command log, external writes log, install log, backup manifest, and any final/partial reports.
2. Identify the last phase gate that clearly passed.
3. Identify files created after that gate and classify them as verified, partial, failed, or unknown.
4. Check whether any process is still running before starting new work.
5. Verify that original inputs still exist and match their recorded hashes if hashes are available.
6. Summarize what is safe to trust and what must be revalidated.

Then produce a recovery decision:

- Resume at [PHASE_ID] because [EVIDENCE].
- Re-run [TASKS] because [MISSING_OR_UNTRUSTED_EVIDENCE].
- Stop for human review because [BLOCKER], if applicable.

Update or create:

- `recovery_report.*`
- `resumption_plan.*`
- The current phase log.
- The command log.
- The assumption register.

Do not fabricate missing state. If logs are inconsistent, label the run state as partially trusted and rebuild from the last verified checkpoint.
```

