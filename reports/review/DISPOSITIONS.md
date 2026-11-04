# Review finding dispositions (manager)

| ID | Severity | Disposition | Action / reason | Evidence of closure |
|---|---|---|---|---|
| RA-001 | MAJOR | FIX | SW-04 adds misaligned offset tests; FIX-CPU runs them | pending |
| RA-002 | MAJOR | FIX | SW-04 adds missing illegal-class tests | pending |
| RA-003 | MAJOR | FIX | FIX-CPU full-regfile check at trap (+ .regs from SW-04), mutant demo | pending |
| RA-004 | MAJOR | FIX | FIX-CPU garbage-init mode + mid-run reset test, mutant demo | pending |
| RA-005 | MAJOR | FIX | SW-04 enlarges random suite to >= 10 000 retired instructions | pending |
| RA-006 | MAJOR | FIX | SW-04 ISS retire trace + FIX-CPU lock-step comparison | pending |
| RA-007 | MINOR | FIX | SW-04 long-immediate tests | pending |
| RA-008 | MINOR | FIX | FIX-CPU CYCLE reset assertion | pending |
| RA-009 | MINOR | FIX | FIX-CPU first-fetch <= 40 assertion | pending |
| RA-010 | OBS | FIX | manager re-runs all evidence scripts at the clean release-candidate commit | pending |
| RA-011 | OBS | ACCEPTED RISK | S1/S2 pin mapping unverifiable without the Sipeed schematic; consequence: the other button resets; physical validation item | — |
| RA-012 | OBS | SPEC FIX | spec text updated: store data replicated on all byte lanes, wstrb selects (superset of "shifted", legal for every slave) | ARCHITECTURE.md §13 |
| RA-013 | OBS | FIX | FIX-CPU checks ADR-012 bounds in SoC TB | pending |
| RA-014 | MINOR | FIX | FIX-CPU stale comments | pending |
| RA-015 | OBS | ACCEPTED LIMITATION | gate-level sim impossible (empty Gowin BSRAM models); mitigated by BSRAM-config inspection; listed in report limitations | — |
| RA-016 | OBS | FIX | FIX-CPU strict BSRAM-init check | pending |
