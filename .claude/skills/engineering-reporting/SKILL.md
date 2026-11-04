---
name: engineering-reporting
description: How specialists and the manager report - handoff file template, gate summaries, status vocabulary and the 10-line chat summary.
---

# Engineering reporting

## Handoff file template (`management/handoffs/<agent>/<task-id>.md`)
```
# <task-id> — <title>
Status: PASS | PARTIAL | FAIL | BLOCKED | NOT RUN
Agent: <name>   Date: <ISO>   Input revision: <git short sha>
## Requirements addressed
## Inputs
## Outputs
## Checks actually performed   (command · tool+version · log path · result line quoted)
## Numerical findings          (name · value · unit · label · evidence)
## Assumptions
## Errors / deviations
## Open decisions (for the manager)
## Next actions
```

## Gate summary (manager)
What was done · status per requirement · numbers with labels · open risks ·
decisions the user must take. Short.

## Chat summary
Your last message to the manager: ≤10 lines, status first, paths to the handoff.
