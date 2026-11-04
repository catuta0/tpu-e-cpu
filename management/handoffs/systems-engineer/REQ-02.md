# REQ-02 — Requirements and budgets to rev C
Status: PASS
Agent: systems-engineer   Date: 2026-11-04T08:45Z   Input revision: 1d67c44 (assigned); HEAD during the work 7537c02 (differs from 1d67c44 only in management/GATES.md); my outputs uncommitted (`-dirty`), not committed as instructed

PASS means: the three requested updates are done, every new number is labelled and
parsed from its source log by a script, and every > 10 % deviation is explained.
It is NOT a verification status of any requirement: all 82 requirements stay NOT RUN
(status matrix after REV-01, as instructed).

## Requirements addressed
- Updated (ID kept, change history entry each): REQ-SYS-004, -005 (b: 8 -> 40 cycles, ADR-011),
  -007 (note), -014; REQ-TPU-002, -003 (version 0x03), -005 (rev C seeds), -006 (default mode 2,
  rules R1/R2), -007, -008, -011, -013, -014, -015; REQ-AI-002, -004, -006, -010; REQ-RES-001, -006;
  REQ-TIM-001, -005. No ID renumbered, deleted or added.
- Budgets backing REQ-RES-001..004, REQ-TIM-001/004, REQ-AI-003..007, REQ-SYS-012/017: achieved
  columns added.

## Inputs
- design/architecture/ARCHITECTURE.md sections 9-12 (12 = rev C current); management/INTERFACES.json
  revision C; management/DECISIONS.md ADR-006..011 (and ADR-000..005 for context);
  management/handoffs/systems-engineer/REQ-01.md; management/GATES.md (G1, G3, G3b).
- Achieved numbers (read only): reports/fpga/soc/soc_impl.md + logs/soc/pnr_nwl_s{1,2,3}.log,
  synth_nwl.log, bsram_init.log, pins.log, tb_soc_demo.log (RTL-SOC, ac0f0a0-dirty, rev C);
  management/handoffs/fpga-engineer/RTL-CPU.md + logs/cpu/pnr_s{1,2,3}.log, sim_cpu_summary.log;
  management/handoffs/fpga-engineer/RTL-TPU.md + reports/fpga/tpu/variants.md +
  logs/tpu/pnr_il{4,8,16}_m*_nwl_s*.log (rev A seeds, 1e853f7-dirty; seed constants do not change
  cell counts) + logs/tpu/tb_sc_tpu_mode2.log (rev C); reports/sw/accuracy_revC.json (SW-03,
  ba9dfb9-dirty), accuracy_revA.json, accuracy_revB.json, seed_selection_revC.md;
  management/handoffs/software-engineer/SW-03.md; code/python/sctpu/accuracy.py and model.py
  (read only, to confirm the ensemble = common start offset).

## Outputs
- /home/user/tpu-e-cpu/requirements/REQUIREMENTS.md — issue 2: rev C header and conventions
  (selected mode 2, deployed rev C seed tables, R1/R2 definitions, validation split), "Issue" column
  in the summary table (22 rows changed in issue 2), updated requirements above, new section 9
  (disposition of REQ-01 OD-1..OD-16 + new OD-R2-1), change-history table at the bottom.
- /home/user/tpu-e-cpu/requirements/BUDGETS.md — issue 2: budgets unchanged; new section 0 summary;
  "Achieved (SIMULATION)" columns in 1.4, 1.5, 2, 3, 5, 8 and achieved notes in 1.1-1.3, 4, 7;
  explanations of every > 10 % deviation; power table re-evaluated; new 9.2 (rev C seeds, R1/R2);
  change history.
- /home/user/tpu-e-cpu/management/RISKS.md — "Risk state" column; all 13 risks re-assessed; new
  R-14..R-16; change history (lock taken and released: management/locks/RISKS.md.lock).
- /home/user/tpu-e-cpu/scripts/budgets/lfsr_rules_revC.py (new) +
  /home/user/tpu-e-cpu/scripts/budgets/logs/lfsr_rules_revC.log
- /home/user/tpu-e-cpu/scripts/budgets/achieved_vs_budget.py (new) +
  /home/user/tpu-e-cpu/scripts/budgets/logs/achieved_vs_budget.log

## Checks actually performed
| Command | Tool | Log | Result (quoted) |
|---|---|---|---|
| `python3 scripts/budgets/lfsr_rules_revC.py > scripts/budgets/logs/lfsr_rules_revC.log` (exit 0) | Python 3.13.18 | scripts/budgets/logs/lfsr_rules_revC.log | `rev C formula == ARCHITECTURE.md 12 table: X True, W True`; `rev C formula == INTERFACES.json rev C table: X True, W True`; `S(32768) = 0xF9DE`; rev C: `min pairwise stream-cycle lag among 16 generators = 321 (X0-W3); next 541 (X4-X6)`, `R1 ... SATISFIED`, `R2 direct violations 0, swapped violations 0 -> SATISFIED`; rev B: `R1 ... VIOLATED on 28 of 28 lane pairs`, `R2 direct violations 28, swapped violations 36`; modes 0/1: `self-swap |2D| mod 65535 = 1 -> R2 VIOLATED`; `ALL SELF-CHECKS PASSED` |
| Inline check (one-off, not saved) of the K = 10 bit-wrap claim on real LFSR states | Python | console | r(k+8192) = (r(k) << 1) with 7 shared bits for k = 0..4: `True` (e.g. 0xe4 -> 0xc8) |
| `python3 scripts/budgets/achieved_vs_budget.py > scripts/budgets/logs/achieved_vs_budget.log` (exit 0) | Python 3.13.18 | scripts/budgets/logs/achieved_vs_budget.log | `SoC nwl utilisation (seeds 1..3 identical): LUT4 5628, ALU 1976, DFF 2803, RAM16SDP4 16, BSRAM 5`; `Fmax SoC nwl seeds [51.98, 47.46, 51.21]`; `CYCLES(K=8) = 2928 = 10*2^8 + 368`; `CPU aggregate CPI (0 wait states, 44 tests): 28206 / 6667 = 4.231`; 34 deviation rows |
| LUT4 counting rule on the release SoC | by hand from logs/soc/synth_nwl.log stat + pnr_nwl_s1.log | — | 12 + 518 + 1486 + 1508 + 1976 + 16 x 8 = 5628 = `LUT4: 5628/ 8640` |
| Markdown table column-count check of the three edited files | Python | console | no mismatches |
| CST history for OD-1 | `git show be4b802:/199a3dc:design/constraints/tangnano9k.cst` | — | be4b802: `IO_LOC "btn_s1_n" 3`; 199a3dc: `IO_LOC "btn_rst_n" 3` |

## Numerical findings
| Name | Value | Unit | Label | Evidence |
|---|---|---|---|---|
| PARAMS expected (mode 0/1/2) | 0x0300_0810 / 0x0301_0810 / 0x0302_0810 | — | CALCULATION | REQ-TPU-003 |
| Rev C mode-2 min pairwise lag | 321 (X0-W3) | stream cycles | CALCULATION | lfsr_rules_revC.log |
| Rev C R1 / R2 violations | 0 / 0 | lane pairs | CALCULATION | lfsr_rules_revC.log |
| Rev B R1 violations | 28 of 28 | lane pairs | CALCULATION | lfsr_rules_revC.log |
| SoC LUT4 budget / achieved | 5735 / 5628 (-1.9 %); as-built-config budget 5591 (+0.7 %) | LUT4 | CALC / SIMULATION | BUDGETS 0, 1.4 |
| SoC DFF budget / achieved | 2489 (mode 1) / 2713 (mode 2) / 2803 (+12.6 % / +3.3 %) | FF | CALC / SIMULATION | BUDGETS 1.4 |
| SoC BSRAM budget / achieved | 3 / 5 (+67 %; = budget with the regfile option) | block | CALC / SIMULATION | BUDGETS 2 |
| TPU total (mode 2) budget / achieved | 3732 / ~4472 LUT4 (+19.8 %); 1980 / ~2569 FF (+29.7 %) | — | CALC / SIMULATION (wrapper ~100 ASSUMPTION) | BUDGETS 1.4 note T |
| CPU budget / achieved | 1940 / 957 LUT4 (-50.7 %); 600 / 126 FF (-79.0 %) | — | CALC / SIMULATION | BUDGETS 1.4 note C |
| Achieved SC MAC lane cost | 14.4 (IL 4->8), 14.5 (IL 8->16) vs bench 22.0 / 19.0 | LUT / lane | CALCULATION from SIMULATION | BUDGETS 1.2 |
| SoC Fmax budget / achieved | 52.12 / 47.46 (-8.9 %) | MHz | CALC / SIMULATION | BUDGETS 5 |
| CPU path P3 budget / achieved | 10.95 / 18.77 alone (+71 %), 21.07 in SoC (+92 %) | ns | CALC / SIMULATION | BUDGETS 5 |
| CYCLES budget / achieved | 10*2^K + 409 / 10*2^K + 368 (K=8: 2969 / 2928, -1.4 %; fixed term -10.0 %) | cycles | CALC / SIMULATION | BUDGETS 3 |
| Throughput K = 8 | 9094 / 9221 inf/s (+1.4 %) | 1/s | CALC / CALC from SIMULATION | BUDGETS 4 |
| CPI | ~4-6 (ASSUMPTION) / 4.231 (0 ws), 5.593 (1 ws), 5.51 (SoC demo) | cycles/instr | SIMULATION | BUDGETS 3 |
| Accuracy mode 2 K = 8 | 94.4 % prelim. / 94.4 % (340/360) rev C | % | SIMULATION | BUDGETS 8 |
| Accuracy mode 0 K = 8 | 65.6 % / 81.9 % (+25 %, W-seed change + realisation noise) | % | SIMULATION | BUDGETS 8 |
| SC noise layer 1 K = 8 mode 2 | bound 0.50 / ensemble 0.489 (-2 %), deployed 0.353 (-29 %) | v | CALC / SIMULATION | BUDGETS 8 |
| Power (FPGA core) | ~5-50 (issue 1: ~5-40) | mW | ASSUMPTION, NOT RUN | BUDGETS 6 |

## Assumptions
- The TPU synthesis wrapper costs ~100 LUT / ~100 FF (RTL-TPU variants.md wording); used only to
  subtract it from the stand-alone TPU numbers (TPU rows of 1.4 are therefore approximate).
- TPU stand-alone variant numbers were produced with rev A seed constants; seed constants do not
  change the cell count (only the init values of 16-bit registers), so they are used for rev C.
- "Budget re-evaluated for the configuration built" = issue-1 baseline plus the issue-1 variant
  deltas of BUDGETS 1.5 (mode 2, BSRAM regfile); no new estimate was made after seeing the results.
- R2 implemented from the SW-03 definition (|D_i - D_j| <= 14 direct, |D_i + D_j| <= 14 swapped,
  circular mod 65535); the ARCHITECTURE.md 12 one-line wording is consistent with it.

## Errors / deviations
- **REQ-01 OD-1 was wrong**: the CST already named the port `btn_rst_n` at commit 199a3dc, before the
  REQ-01 input revision (494448a); REQ-01 apparently quoted the older be4b802 text. Withdrawn
  (REQUIREMENTS.md section 9, R-09).
- **REQ-01 R-02 mitigation proposal was wrong**: "choose seeds by maximum pairwise phase distance"
  is the criterion that produced the defective rev B. Recorded in R-02 and BUDGETS 9.2.
- **BUDGETS issue-1 power arithmetic slip**: logic term 0.9-11 mW should have been 1.1-13.4 mW for the
  stated inputs; corrected (total ~5-40 -> ~5-50 mW, still ASSUMPTION).
- **BUDGETS issue-1 K = 10 "every LFSR wraps"** was imprecise: the state sequence does not repeat
  (0.156 state periods); the bit sequence wraps after 8192 stream cycles (7-of-8 bit self-overlap).
  Corrected in 9.1.
- Per-block attribution inside the TPU (~+270 FF / ~+600 LUT) is not possible from the flattened
  netlist; stated as "not attributed" rather than guessed.
- HEAD moved from 1d67c44 to 7537c02 during the task (manager commit of GATES.md only).

## Open decisions (for the manager)
1. **OD-R2-1** (new): REQ-SYS-007 bounds slave latency to 4 cycles, but a TPU read of INPUT/BIAS/WEIGHT
   while BUSY stalls up to ~35 cycles (RTL-TPU, SIMULATION; A.2 allows such reads). Proposal: 4 cycles
   in general, <= 40 cycles for INPUT/BIAS/WEIGHT reads while BUSY. Acceptance text left unchanged
   until you rule (otherwise REQ-SYS-007 cannot be PASS from the TPU TB evidence).
2. **OD-11** (still open): no ADR confirms the accuracy thresholds of REQ-AI-003..006; they are
   applied de facto by SW-03. Please confirm explicitly.
3. **OD-16** (user): network access to Gowin/Sipeed hosts; R-07 remains PARTIAL.
4. Residual of OD-5: peripheral reserved offsets (0x14..0x1F) are not in the spec; RTL-SOC assumption A2
   (read 0, no bus_err). Consider one sentence in ARCHITECTURE.md (low impact).

## Next actions
- Independent reviewer (REV-01): re-run `python3 scripts/budgets/lfsr_rules_revC.py` and
  `python3 scripts/budgets/achieved_vs_budget.py` (seconds each) and compare with the logs above;
  check REQUIREMENTS.md change history against ADR-006..011.
- systems-engineer: create requirements/STATUS_MATRIX.md after REV-01 (statuses deliberately not set).
- documentation-engineer: use BUDGETS.md section 0 for "budget vs result" in the engineering report;
  respect R-14 (no significance claim for C0 over C3/C4) and R-15 (rev C numbers only).
- If any design change is considered after V1: re-calibrate per-block costs from the RTL first (R-16).
