---
name: engineering-evidence
description: Shared evidence rules for this project - number labels, status words, revisions, checksums, file locks and handoff contents. Load before producing any result, number or handoff.
---

# Engineering evidence rules

## Labels (every number)
`SOURCE` (datasheet/standard/paper, cite in management/SOURCES.md) ·
`CALCULATION` (show formula + inputs) · `SIMULATION` (tool, version, log path) ·
`MEASUREMENT` (real hardware only — none exist in this project so far) ·
`ASSUMPTION` (state why).

## Status words
Only PASS, PARTIAL, FAIL, BLOCKED, NOT RUN. Never relabel a FAIL.
Simulation is not test. Lint/synthesis/P&R passing is not hardware validation.
Exit code 0 is not a pass: open the log and quote the decisive lines.

## Revisions and evidence
- Record the git revision (`git rev-parse --short HEAD`, plus `-dirty` if the
  tree is dirty) of the inputs you used.
- Logs go to `logs/<area>/<name>.log`; reports keep the exact command at the top.
- For released files compute `sha256sum`.
- metrics.json entries: `{"name", "value", "unit", "label", "revision", "evidence"}`.

## Locks
One writer per file. For a shared file create `management/locks/<basename>.lock`
containing `<agent> <ISO-time> <task-id>`; delete it when done. If a lock
exists and is not yours, do not write the file — escalate.

## Handoff contents
Status · Requirements addressed · Inputs (paths+rev) · Outputs · Checks actually
performed · Numerical findings (labelled) · Assumptions · Errors · Open
decisions · Next actions.

## Lessons learned (updated during the run)
- Under `set -e`, a logged `X_EXIT=$?` after a command can only be 0: capture with `cmd || rc=$?` (ST-REV-01 R-004).
- Testbenches must be mutation-checked: a TB that passes a mutated design proves little (ST-REV-01 R-001/R-002).
- Stamp logs with the revision actually used; re-run after committing if the stamp is `-dirty`.
