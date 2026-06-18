# Phase 7 Prompt: Finalist Deep Evaluation And Reporting

```text
Phase 7 objective: perform deeper evaluation only on finalists using the most expensive or rigorous methods, then produce final deliverables.

Project placeholders:

- [PROJECT_NAME]:
- [DOMAIN]:
- [OBJECTIVE]:
- [WORKSPACE_PATH]:
- [RUN_DIRECTORY]:
- [FINALISTS]:
- [REQUIRED_DELIVERABLES]:
- [TOTAL_TIME_BUDGET_REMAINING]:
- [RISK_CONSTRAINTS]:
- [PREFERRED_OUTPUT_FORMATS]:

What to do:

1. Read Phase 0-6 outputs.
2. Confirm enough time remains for deep evaluation, interpretation, and final reporting.
3. Run only the rigorous methods justified for finalists.
4. Use checkpointing and do not start jobs that cannot finish within the remaining budget.
5. Collect final evidence, uncertainty/confidence estimates, limitations, negative results, and residual risks.
6. Produce a final ranked candidate/output table.
7. Produce the final report using the required structure.
8. Include reproducibility links to manifests, commands, inputs, outputs, environment notes, and validation evidence.
9. State what is ready for human review, what is ready for real-world execution, and what remains provisional.

What not to do:

- Do not add new candidates unless Phase 6 is reopened.
- Do not hide failed finalist evaluations.
- Do not claim production readiness without evidence.
- Do not treat file existence as proof of correctness.

Files to create/update:

- `finalist_deep_eval.*`
- `final_candidate_table.*`
- `final_report.*`
- `handoff_notes.*`
- `limitations_and_risks.*`
- `negative_results.*`
- Current phase log and command log.

Evidence to collect:

- Deep-evaluation outputs, final validation logs, comparison tables, uncertainty estimates, resource/runtime notes, and all final reproducibility links.

Gate to pass:

Phase 7 passes only if final recommendations are supported by evidence, limitations and negative results are visible, candidate ranking is reproducible, and a human can inspect or rerun the work from the recorded artifacts.

If tools fail or evidence is insufficient:

- Downgrade confidence.
- Mark affected deliverables provisional.
- Stop with a handoff note if a required final claim cannot be supported.

End with:

- Phase 7 gate decision.
- Final deliverables.
- Final ranked table.
- Confidence/uncertainty summary.
- Residual risks and next actions for human review.
```

