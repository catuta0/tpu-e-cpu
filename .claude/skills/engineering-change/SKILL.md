---
name: engineering-change
description: Formal engineering change process. Trigger ONLY when the user explicitly types /engineering-change <description>. Never trigger automatically.
---

# Engineering change process

Run only on an explicit `/engineering-change <description>`.

1. **Preserve the baseline**: never modify `releases/V*_BASELINE/`. Verify its
   SHA-256 manifest (`sha256sum -c MANIFEST.sha256`) before starting.
2. **Open a change request**: `changes/CR-<NNN>.md` (next free number) with the
   description, requester, date, motivation, status OPEN.
3. **Impact analysis** in the CR: affected requirements (IDs), interfaces
   (INTERFACES.json fields), RTL modules, tests, Python models, documents,
   resources/timing budgets, risks. Decide which specialists are needed.
4. **Delegate** through the manager with assignments that state input revision,
   paths, acceptance criteria and handoff contract (see CLAUDE.md).
5. **Compare old vs new**: utilisation, Fmax, accuracy, test results, side by side
   in the CR, all numbers labelled.
6. **Re-review**: run `independent-reviewer` on the changed outputs only plus
   the requirements they touch.
7. **Publish** a new release `releases/V<N+1>_BASELINE/` with manifest,
   REPRODUCE.md, status matrix; close the CR with links. Commit.
