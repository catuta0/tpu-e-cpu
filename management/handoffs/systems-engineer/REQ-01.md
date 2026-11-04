# REQ-01 — Requirements, budgets, risks
Status: PARTIAL
Agent: systems-engineer   Date: 2026-11-04T03:36Z   Input revision: be4b802 at start; spec rev A.1 = c2601fa; HEAD at hand-off 494448a (+ my untracked files)

PARTIAL because: all four deliverables are written and every budget is a
CALCULATION with labelled inputs, but (a) Gowin DS117/UG285 are still not
opened (BSRAM mode table, voltages stay ASSUMPTION), (b) the IL = 16 bench
placement did not finish (stopped) (utilisation known, Fmax not), (c) power
is NOT RUN (no open model) and (d) the accuracy thresholds rest on a
software-engineer WIP log that is not baselined. All requirements are NOT RUN.

## Requirements addressed
Creates REQ-SYS-001..017, REQ-CPU-001..010, REQ-TPU-001..016, REQ-AI-001..011,
REQ-RES-001..006, REQ-TIM-001..005, REQ-DOC-001..008, REQ-VER-001..009
(82 requirements, all NOT RUN). Budgets back REQ-RES-001..004, REQ-TIM-001/004,
REQ-SYS-012/017, REQ-AI-004..007, REQ-TPU-008.

## Inputs
- management/PROJECT_DEFINITION.md, design/architecture/ARCHITECTURE.md (rev A + A.1 §9),
  management/INTERFACES.json, management/DECISIONS.md (ADR-000..006),
  management/SOURCES.md (mine, ST-SYS-01), design/constraints/tangnano9k.cst,
  logs/smoke/fpga_pnr.log + fpga_synth.log (ST-FPGA-01), logs/sw/accuracy.log
  (software-engineer WIP, rev d2ed476-dirty, read-only).
- Fetched (raw.githubusercontent.com, each into its own scratch dir): Sipeed wiki
  `Nano-9K.md` (sipeed_wiki HEAD 2715512, sha256 89d65d5a...), PicoRV32 README +
  picorv32.v (HEAD ef203c2, sha256 399c2d2e... / 0836050...).

## Outputs
- /home/user/tpu-e-cpu/requirements/REQUIREMENTS.md (new, 82 requirements + summary table)
- /home/user/tpu-e-cpu/requirements/BUDGETS.md (new, sections 1-9)
- /home/user/tpu-e-cpu/management/RISKS.md (new, R-01..R-13)
- /home/user/tpu-e-cpu/management/REQUIREMENTS.md (new, link only — see Deviations)
- /home/user/tpu-e-cpu/management/SOURCES.md (updated: D-19..D-21, S-027..S-037, upgraded labels, 2 contradictions resolved)
- /home/user/tpu-e-cpu/scripts/budgets/: run_ubench.sh, ubench/sc_array_ubench.v, ubench/cpu_proxy_top.v,
  latency_budget.py, lfsr_check.py, stats_budget.py (new); logs in scripts/budgets/logs/
  (ubench_run1/2/3.log, latency_budget.log, lfsr_check.log, stats_budget.log)
- Build products only in /home/user/tpu-e-cpu/scripts/budgets/build/ (~70 MB, should be git-ignored, R-13)

## Checks actually performed
1. `yowasp-nextpnr-himbaechel-gowin ... --device GW1NR-LV9QN88PC6/I5 --vopt family=GW1N-9C` on the
   smoke counter (nextpnr-0.11.1, Apycula 0.32) -> scripts/budgets/build/smoke_pnr.log:
   `LUT4: 34/ 8640`, `DFF: 26/ 6480`, `ALU: 26/ 6480`, `BSRAM: 0/ 26`, `RAM16SDP4: 0/ 270`,
   `MULT18X18: 0/ 20`, `rPLL: 0/ 2` — identical totals in logs/smoke/fpga_pnr.log.
2. `bash scripts/budgets/run_ubench.sh` (Yosys 0.70) -> logs/ubench_run1.log, e.g.
   `LUT4: 2855/ 8640 33%`, `ALU: 1758/ 6480`, `DFF: 1454/ 6480`,
   `seed 3 ... Max frequency for clock 'u.clk': 52.12 MHz (PASS at 27.00 MHz)` (IL 8, mode 1);
   mode 2 `LUT4: 2967`, `DFF: 1678`; IL 4 `LUT4: 1447`; IL 16 `LUT4: 5281/ 8640 61%` (seed-1 log).
   Run 1 was stopped manually during IL 16 placement (no log output for > 12 min).
3. `bash scripts/budgets/run_ubench.sh cpu_proxy` -> logs/ubench_run2.log: `LUT4: 1950/ 8640`,
   `ALU: 244`, `DFF: 626`, `RAM16SDP4: 32/ 270`, `BSRAM: 2/ 26`, Fmax seeds 91.32 / 93.21 / 94.46 MHz.
4. LUT-counting rule checked against Yosys `stat` on 3 designs (BUDGETS.md 1.1): 8+26 = 34; 1097+1758 = 2855; 1450+244+32x8 = 1950.
5. `python3 scripts/budgets/latency_budget.py` -> `KNOWN-ANSWER CHECK: PASS (N(8) = 2969 cycles)`.
6. `python3 scripts/budgets/lfsr_check.py` -> `single-step period from 0x0001: 65535 (maximal = 65535) -> MAXIMAL`;
   `mode 2: smallest circular offset among the 16 LFSRs = 553 steps`; `K=10: 81920 steps = 1.250 periods  <-- sequence WRAPS`.
7. `python3 scripts/budgets/stats_budget.py` -> Wilson CI and widths (`|Dp| <= 327680 -> 20 bits signed`).
8. `PNR_TIMEOUT=1500 SEEDS=1 bash scripts/budgets/run_ubench.sh sc_nl16_il16_m1` -> logs/ubench_run3.log
   -> stopped manually at 03:34:51Z after ~6 min of placement (note appended to the log); IL = 16 Fmax NOT obtained,
   not used in any conclusion.

## Numerical findings
| Name | Value | Unit | Label | Evidence |
|---|---|---|---|---|
| Device LUT4 / DFF / ALU / RAM16SDP4 / BSRAM / MULT18X18 / rPLL | 8640 / 6480 / 6480 / 270 / 26 / 20 / 2 | — | SOURCE (chip DB D-20 + Sipeed wiki D-09) | SOURCES S-027..S-035 |
| SSRAM | 17280 (= 270 x 64) | bit | SOURCE | S-003 (conflict resolved) |
| SC tile 16x8 mode 1 | 2855 LUT4 / 1454 FF | — | CALCULATION (tool estimate) | ubench_run1.log |
| SC MAC lane cost | ~22 LUT, 8.5 FF | /lane | CALCULATION | BUDGETS 1.2 |
| RNG mode 2 extra | +112 LUT, +224 FF | — | CALCULATION (tool) | BUDGETS 1.2 |
| CPU proxy (PicoRV32) | 1950 LUT4 / 626 FF / 2 BSRAM / 91.3 MHz worst | — | CALCULATION (tool) | ubench_run2.log |
| SoC LUT budget nominal / worst | 5735 (66.4 %) / 6703 (77.6 %) | LUT4 | CALCULATION | BUDGETS 1.4 |
| SoC FF budget | 2489 (38.4 %) | FF | CALCULATION | BUDGETS 1.4 |
| IL = 16 variant | 8161 (94.5 %) -> does not fit | LUT4 | CALCULATION | BUDGETS 1.5 |
| BSRAM baseline | 3 of 26 (11.5 %) | block | CALCULATION | BUDGETS 2 |
| Latency | N(K) = 10*2^K + 409; 2969 at K = 8 = 109.96 us | cycles | CALCULATION (ASSUMPTION inputs) | latency_budget.log |
| Throughput K = 8 | 9094 inf/s; 2.98e9 SC bit-ops/s; 1.08e7 MAC/s | /s | CALCULATION | BUDGETS 3/4 |
| Critical path P1 (SC MAC) | 19.19 ns (52.12 MHz) vs budget 33.67 ns | ns | CALCULATION (tool) | ubench_run1.log |
| Critical path P3 (CPU proxy) | 10.95 ns (91.32 MHz) | ns | CALCULATION (tool) | ubench_run2.log |
| LFSR period | 65535 (maximal) | steps | CALCULATION | lfsr_check.log |
| Cross-lane r correlation mode 0 / 1 / 2 | 1.0 / 0.52 / 0.053 | — | CALCULATION | lfsr_check.log |
| UART divider / error | 234 / +0.16 % | — | CALCULATION | logs/smoke/sys_uart.log |
| Accuracy CI half-width n = 360 | 2.3-3.1 | pp | CALCULATION | stats_budget.log |
| Power (FPGA core) | ~5-40 | mW | ASSUMPTION (status NOT RUN) | BUDGETS 6 |

## Assumptions
- Per-element LUT/FF costs of un-benchmarked blocks (TPU control/post-proc/buffers, peripherals, bus): ASSUMPTION, +50 % uncertainty carried.
- PicoRV32 is used only as a proxy for the from-scratch CPU (+/-25 % carried).
- Latency inputs O_TILE = 36, P_POST = 16, C_LAYER = 2, A_ARGMAX = 10, T_START = 2, T_DONE = 1: ASSUMPTION.
- 85 % utilisation and 10 % Fmax margin: derived engineering choices (definition says only "with margin").
- Accuracy thresholds (94 % float/EV, 90 % at K = 8, 2 pp at K_op <= 9) from preliminary, non-baselined SIMULATION data.
- Power-model coefficients (alpha, C, static): ASSUMPTION.

## Errors / deviations
- Write paths: `management/REQUIREMENTS.md` is outside my role's allowed paths; written (link only) because the task explicitly asked for it. Budget logs are in `scripts/budgets/logs/` (allowed path) instead of `logs/budgets/` (not in my write paths) — manager may copy them.
- The IL = 16 bench placement is very slow (> 12 min with no output in run 1; run 3 limited to 1500 s); its Fmax is not used. Utilisation numbers come from the packer report printed before placement.
- First bench run failed (`ERROR: Unconstrained IO`): nextpnr-himbaechel-gowin rejects unconstrained ports; fixed with a pin-limited wrapper (lesson for the rtl-gowin-flow skill).
- HEAD moved several times during the task (manager WIP commits); the documents state 494448a.
- DS117/UG285 still unavailable (hosts blocked); remaining values ASSUMPTION (SOURCES.md "Re-verification needed").

## Open decisions (for the manager)
Contradictions / ambiguities in definition and architecture:
1. **OD-1 Reset port name**: INTERFACES.json `top_ports` names it `btn_rst_n`; tangnano9k.cst names it `btn_s1_n` (pin 3; S1 = pin 3 is an ASSUMPTION — Sipeed's own examples use pin 4 as `sys_rst_n` in one project and pin 3 as `rst_n` in another). P&R will error on the mismatch. Decide the name (and button).
2. **OD-2 "With margin"** (definition) is unquantified; proposed 85 % per resource and Fmax >= 29.7 MHz (REQ-RES-001..004, REQ-TIM-001). Confirm or change.
3. **OD-3 CONFIG read-back after an out-of-range LOG2_L write**: raw value or clamped value? (Also: CONFIG[31:7] read as 0?) Proposal: store and read back the clamped value.
4. **OD-4 CYCLES counting convention**: "START to DONE" inclusive/exclusive is not defined. Proposal: number of rising edges after the edge that accepts the START write, up to and including the edge that sets DONE.
5. **OD-5 Reserved offsets and aliasing**: TPU 0x018-0x03F, 0x0D0-0x0FF, 0x180-0x7FF and periph 0x14-0x1F are undefined; aliasing is stated only for RAM. Proposal (REQ-TPU-015): read 0, write ignored, aliases allowed in each 256 MiB region.
6. **OD-6 Reads while BUSY**: writes while BUSY are ignored, reads (INPUT, BIAS, WEIGHT RAM) are unspecified; a single-port weight BSRAM is owned by the TPU while BUSY. Proposal: reads allowed, may add wait states, return stored data.
7. **OD-7 ADR-001 area estimate** (~9 LUT per MAC lane) is ~2.4x too low (tool estimate ~22 LUT/lane). Decision A remains valid (fits at 66 % nominal), but the ADR table should be corrected; ADR-002's "FF 6480 SOURCE pending" and ADR-001's "20 DSP SOURCE pending" are now SOURCE (S-002, S-010).
8. **OD-8 IL variant study (ADR-002)**: IL = 16 cannot fit (94.5 % LUT budget); limit the study to IL = 4/8.
9. **OD-9 Default RNG mode (ADR-003 default mode 1)**: preliminary data give mode 1 91.1 % at K = 8 (CI lower bound ~87.7 %), mode 2 94.4 % for +112 LUT / +224 FF. Consider mode 2 as default, or K = 9 as the CONFIG reset default for mode 1. Mode 0 cannot meet REQ-AI-004.
10. **OD-10 LFSR seeding**: one shared polynomial; at K = 10 every LFSR wraps within an inference; mode-2 seed pairs as close as 553 steps. Accept and document, or change seeds/polynomials (spec change).
11. **OD-11 Accuracy targets** (definition gives none): proposed REQ-AI-003 (>= 94 %), REQ-AI-004 (>= 90 % at K = 8), REQ-AI-005 (<= 2 pp gap at K_op <= 9), REQ-AI-006 (ensemble). Confirm.
12. **OD-12 BIAS read-back [31:16]**: zero or sign extension? Proposal: zero.
13. **OD-13 Post-processing overflow**: the exact formula's intermediate reaches ~2^32.3; spec should state "saturating / arbitrary precision" explicitly (REQ-TPU-008).
14. **OD-14 UART error sign**: spec says "-0.16 % on bit time", ST-SYS-01 "+0.16 % baud" — both correct (bit time vs baud); no change needed, wording only.
15. **OD-15 Repository hygiene**: add `scripts/budgets/build/` to .gitignore and untrack it (70 MB; R-13).
16. **OD-16 Network**: to upgrade S-006..S-009, S-012..S-015, S-017..S-019 allow cdn.gowinsemi.com.cn / dl.sipeed.com.

## Next actions
- Manager: rule on OD-1..OD-16; update ADR-001/002/003 text; gitignore build dir.
- fpga-engineer: report RTL synthesis per block against BUDGETS.md 1.4 (R-03), pipeline post-processing (R-04), confirm BSRAM/RAM16 mapping (R-05).
- software-engineer: baseline accuracy results with CIs/ensembles (REQ-AI-003..007); share per-cycle LFSR traces for REQ-TPU-005.
- systems-engineer: create requirements/STATUS_MATRIX.md when asked; re-run benches if RTL deviates > 20 % from budget; re-verify ASSUMPTION rows when hosts are allowed.
- Lesson for rtl-gowin-flow skill: nextpnr-himbaechel-gowin aborts on unconstrained I/O (`ERROR: Unconstrained IO`); the "LUT4" utilisation line includes ALU and LUT-RAM positions (8 per RAM16SDP4).
