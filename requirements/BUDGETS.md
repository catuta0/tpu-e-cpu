# Budgets — SC-TPU + RV32I SoC on Tang Nano 9K

Owner: systems-engineer · Task: REQ-02 · Date: 2026-11-04 · Issue: 2 (budget vs achieved)
Issue 1: task REQ-01, input revision `494448a`, spec rev A / A.1 (commit c2601fa).
Issue 2 input revision: `1d67c44` (assigned; HEAD at writing `7537c02`, differs only in
`management/GATES.md`); spec **rev C** (ARCHITECTURE.md 12, INTERFACES.json revision C).

All budget figures are **CALCULATION** made in issue 1 and are **not changed** in
issue 2 (they stay the reference). Issue 2 adds, next to each budget where one now
exists, a column **"achieved (SIMULATION)"**: synthesis / place-and-route tool
reports and RTL / golden-model simulations of the other specialists (not hardware;
nothing has been programmed or measured). Deviation = (achieved - budget) / budget
(CALCULATION); every deviation > 10 % is explained in the row note or right below
the table. "Tool estimate" = a CALCULATION whose inputs come from a Yosys/nextpnr
run of a *calibration micro-benchmark* (not the project RTL, not hardware).
Requirements referenced: [`REQUIREMENTS.md`](REQUIREMENTS.md).

Scripts and logs (all under `scripts/budgets/`):
| Script | Purpose | Log |
|---|---|---|
| `run_ubench.sh` + `ubench/*.v` | synth + P&R of calibration benches (SC tile, CPU proxy) | `logs/ubench_run1.log`, `logs/ubench_run2.log`, `logs/ubench_run3.log` |
| `latency_budget.py` | cycles / throughput vs K (known-answer check) | `logs/latency_budget.log` |
| `lfsr_check.py` | LFSR period, seed phase offsets, correlations (rev A seeds, issue 1) | `logs/lfsr_check.log` |
| `lfsr_rules_revC.py` (issue 2) | rev C seed tables, stream-cycle lags, rules R1/R2, independent of the golden model | `logs/lfsr_rules_revC.log` |
| `achieved_vs_budget.py` (issue 2) | parses the achieved numbers from the specialists' logs and computes every deviation in this file | `logs/achieved_vs_budget.log` |
| `stats_budget.py` | accuracy CI, SC noise bound, post-proc widths | `logs/stats_budget.log` |
| `uart_divider.py` (ST-SYS-01) | UART divider (known-answer check) | `logs/smoke/sys_uart.log` |

Achieved-number sources (read only, produced by other specialists):
| Source | Content | Label |
|---|---|---|
| `reports/fpga/soc/soc_impl.md`, `logs/soc/pnr_nwl_s{1,2,3}.log` (RTL-SOC, rev C, ac0f0a0-dirty) | SoC utilisation and Fmax, release flow `synth_gowin -nowidelut` (ADR-011) | SIMULATION (P&R tool report) |
| `reports/fpga/tpu/variants.md`, `logs/tpu/pnr_*_nwl_s*.log` (RTL-TPU, rev A seeds, 1e853f7-dirty) | TPU stand-alone variants; seed constants do not change the cell count | SIMULATION |
| `management/handoffs/fpga-engineer/RTL-CPU.md`, `logs/cpu/` (494448a-dirty / ac0f0a0-dirty) | CPU utilisation, Fmax, CPI | SIMULATION |
| `logs/tpu/tb_sc_tpu_mode2.log` (rev C), `logs/soc/tb_soc_demo.log` (rev C) | CYCLES, SoC demo timing | SIMULATION |
| `reports/sw/accuracy_revC.json` (SW-03, ba9dfb9-dirty) | accuracy, SC error study | SIMULATION (bit-exact golden model) |

Tool versions (from log headers): Yosys 0.70 (YoWASP), nextpnr-0.11.1
himbaechel-gowin (yowasp 0.11.1.0.post826), Apycula 0.32, Python 3.13.18,
numpy 2.5.4. Device `GW1NR-LV9QN88PC6/I5`, `family=GW1N-9C`, `--freq 27`.

---

## 0. Summary — budget vs achieved (issue 2)

| Budget item | Budget (CALCULATION, issue 1) | Achieved (SIMULATION) | Deviation | > 10 %? | Explanation |
|---|---|---|---|---|---|
| SoC LUT4 | 5735 nominal (66.4 %), 6703 worst (77.6 %) | **5628 (65.1 %)** | -1.9 % vs nominal | no | see 1.4: the total is right by compensation (TPU +20 %, CPU -51 %) |
| SoC LUT4, budget re-evaluated for the configuration built (mode 2, BSRAM regfile) | 5591 | 5628 | +0.7 % | no | 1.5 deltas applied |
| SoC DFF | 2489 (38.4 %); 2713 for mode 2 | **2803 (43.3 %)** | +12.6 % / +3.3 % | yes vs baseline | mode 2 (+224 FF) was chosen after issue 1 (ADR-008); vs the mode-2 budget +3.3 % |
| SoC BSRAM | 3 (11.5 %) | **5 (19.2 %)** | +66.7 % | yes | the "CPU regfile in BSRAM" option (+2) was taken by RTL-CPU; budget for that option = 5 (0 %) |
| SoC RAM16SDP4 | 56; 24 with BSRAM regfile | **16** | -33 % | yes | SCORE kept in 320 FF instead of 8 RAM16SDP4 cells (RTL-TPU choice) |
| SoC worst-seed Fmax | 52.12 MHz (min of path candidates, P1) | **47.46 MHz** | -8.9 % | no | but the critical path moved from P1 (SC MAC) to P3 (CPU), see 5 |
| CPU critical path P3 | 10.95 ns (PicoRV32 proxy) | 18.77 ns (CPU alone), 21.07 ns (in SoC) | +71 % / +92 % | yes | see 5 |
| TPU latency CYCLES(K) | 10*2^K + 409 | **10*2^K + 368** (every K = 4..10) | -7.2 % (K=4) .. -0.4 % (K=10); fixed term -10.0 % | fixed term: borderline (10.02 %) | see 3 |
| CPU CPI | ~4-6 (ASSUMPTION) | 4.231 (0 wait states), 5.593 (1 wait state), 5.51 (SoC demo) | inside range | no | see 3 |
| Throughput K = 8 | 9094 inf/s | 9221 inf/s | +1.4 % | no | follows CYCLES |
| Accuracy K = 8, mode 2 (selected) | 94.4 % (preliminary input, rev A seeds) | **94.4 % (340/360)** rev C | 0 | no | rev C mode-2 seeds = rev A mode-2 seeds (ADR-010) |
| EV accuracy | 95.0 % | 95.0 % (342/360) | 0 | no | same weights |
| SC noise layer 1, K = 8 | <= 0.50 (bound sqrt(N_in/L)) | 0.489 ensemble, 0.353 deployed seeds | -2 % / -29 % | deployed: yes | see 8 |
| UART bit time / frame | 234 / 2340 clocks | 234 / 2340 clocks | 0 | no | see 7 |
| Power | ~5-40 mW (ASSUMPTION; corrected to ~5-50 mW in issue 2) | none (no open power model) | — | — | NOT RUN, see 6 |

---

## 1. Resource budget (logic)

### 1.1 Device capacity and how the tool counts
| Resource | Capacity | Label |
|---|---|---|
| LUT4 positions | 8640 | SOURCE S-001 / S-027 |
| DFF | 6480 | SOURCE S-002 / S-028 |
| ALU (carry) cells | 6480 | SOURCE S-029 |
| RAM16SDP4 (LUT-RAM 16x4) | 270 | SOURCE S-030 |
| BSRAM blocks | 26 | SOURCE S-005 / S-031 |
| MULT9X9 / MULT18X18 | 40 / 20 | SOURCE S-032 |

**Counting rule (CALCULATION, verified on three designs):** the nextpnr "LUT4"
line counts every occupied LUT position, i.e.
`LUT4(nextpnr) = LUT1..4 cells (Yosys) + ALU cells (nextpnr) + 8 x RAM16SDP4`.
- smoke counter: 8 LUT1 + 26 ALU = 34 = LUT4 line (logs/smoke/fpga_synth.log, fpga_pnr.log);
- SC tile mode 1: 157+123+51+766 = 1097 LUT + 1758 ALU = 2855 = LUT4 line;
- CPU proxy: 256+188+392+614 = 1450 LUT + 244 ALU + 32 x 8 = 1950 = LUT4 line.
- Issue 2 check on the release SoC (logs/soc/synth_nwl.log + pnr_nwl_s1.log):
  Yosys LUT1..4 = 12 + 518 + 1486 + 1508 = 3524; + 1976 ALU (nextpnr) + 16 x 8 =
  128 -> 5628 = LUT4 line (CALCULATION; the rule holds on the real design).

Therefore the LUT4 line is the single logic-capacity figure used in
REQ-RES-001 and in this budget ("LUT" below = LUT4 positions).

### 1.2 Calibration benches (tool estimates)
Bench `sc_ubench_top` = one NL x IL tile of the spec 5.3 datapath (weight
registers, input registers, LFSRs per RNG_MODE with 8-step leap, SNG
comparators for every input and weight lane, XNOR, popcount, 17-bit APC
accumulators, registered 16:1 read mux) plus a pin-limiting wrapper (data
LFSR, address/select counters, XOR-reduced output; ~25 LUT / ~45 FF,
ASSUMPTION from its structure). Bench `cpu_proxy_top` = PicoRV32 (default
config without counters; ISC licence, D-21) + 4 KiB byte-enable RAM + LED
register: a *proxy* for a multi-cycle RV32I CPU, not the project CPU.

| Bench | LUT4 | of which ALU | DFF | RAM16SDP4 | BSRAM | Fmax seeds 1/2/3 (MHz) | Log |
|---|---|---|---|---|---|---|---|
| SC tile NL16 IL8 mode 0 | 2855 | 1758 | 1454 | 0 | 0 | 55.73 / 56.48 / 52.36 | ubench_run1.log |
| SC tile NL16 IL8 mode 1 | 2855 | 1758 | 1454 | 0 | 0 | 53.04 / 53.79 / 52.12 | ubench_run1.log |
| SC tile NL16 IL8 mode 2 | 2967 | 1758 | 1678 | 0 | 0 | 52.98 / 54.02 / 54.70 | ubench_run1.log |
| SC tile NL16 IL4 mode 1 | 1447 | 1046 | 909 | 0 | 0 | 68.51 / 71.72 / 70.18 | ubench_run1.log |
| SC tile NL16 IL16 mode 1 | 5281 | 3120 | 2543 | 0 | 0 | NOT obtained (placement did not finish: run 1 stopped after > 12 min, run 3 after ~6 min) | build/sc_nl16_il16_m1_s1.pnr.log (packer report), ubench_run3.log |
| CPU proxy (PicoRV32 + 4 KiB RAM) | 1950 | 244 | 626 | 32 | 2 | 91.32 / 93.21 / 94.46 | ubench_run2.log |

Derived per-element costs (CALCULATION from the table):
- **SC MAC lane** (weight reg + comparator + XNOR + popcount share):
  (2855 - 1447) / 64 = **22.0 LUT / lane** (IL 4 -> 8); (5281 - 2855) / 128 =
  19.0 LUT / lane (IL 8 -> 16); **8.5 FF / lane** (8 weight bits + input share).
  ADR-001 assumed ~9 LUT / lane: the real cost is ~2.4x higher (corrected in ADR-007).
  *Achieved (SIMULATION, RTL-TPU nwl, mode 1):* (4461 - 3542) / 64 = **14.4 LUT / lane**
  (IL 4 -> 8) and (6322 - 4461) / 128 = **14.5 LUT / lane** (IL 8 -> 16), i.e. -35 % /
  -24 % vs the bench. Known part: the bench used the default wide-LUT flow, the
  release uses `-nowidelut` (~2.3 % smaller on the TPU: 4461 vs 4567, variants.md).
  The rest is **not attributed** (flat netlist, no per-module report); possible
  causes (not verified) are differences in how Yosys maps the 136 comparators and
  popcounts in the two designs.
- Breakdown of the IL8 tile FFs (CALCULATION, exact): weights 128x8 = 1024 +
  inputs 8x8 = 64 + accumulators 16x17 = 272 + LFSRs 2x16 = 32 + read register
  17 = 1409; + wrapper 45 = 1454 (matches the tool).
- ALU cells: 136 comparators x 8 + 16 accumulators x 17 + wrapper counters
  = 1371 (Yosys reports 1435); nextpnr adds ~2 cells per carry chain (1758).
- RNG_MODE 2 costs +112 LUT and +224 FF (14 extra LFSRs: 14x16 = 224 FF,
  exact) over modes 0/1; mode 1 rotation costs 0 LUT (wiring) — CALCULATION
  from the bench. *Achieved (SIMULATION, RTL-TPU nwl): +111 LUT4, +224 DFF (-0.9 % / 0 %).*
- 8-step leap-forward LFSR: each of the 8 new bits is the XOR of exactly 4
  current-state bits, the other 8 bits are a pure shift (symbolic GF(2)
  expansion, CALCULATION) -> 8 LUT4 per LFSR, 1 logic level.

### 1.3 Post-processing word widths (CALCULATION, `logs/stats_budget.log`)
acc <= 64 x 1024 = 65536 -> 17 bit unsigned; |D| <= 65536; |B| <=
32768 x 1024 / 128 = 262144; |Dp| <= 327680 -> **20 bit signed**. Hidden shift
exponent s + 7 - K in [-3, +10]; the exact product Dp x 2^(s+7) reaches
~2^32.3 -> must be computed as a saturating shift, not a 32-bit multiply
(REQ-TPU-008).
*Achieved (RTL-TPU, sc_postproc.v; SIMULATION 53328 post-proc vectors, 0 mismatches):*
acc 17 b, D/B/Dp 20 b signed, Dp x 2^(s+7) computed exactly in 34 b signed
(max 327680 x 2^14 < 2^33); identical to the budget widths. The golden model's
value-range analysis (accuracy_revC.json `value_ranges`, SIMULATION) gives
Dp1 in [-327680, 327672] at K = 10, inside the 20-bit bound.

### 1.4 Bottom-up budget per block (baseline: RNG_MODE 1, IL = 8, buffers in LUT-RAM, regfile in LUT-RAM)
Per-element assumptions for the blocks without a bench (ASSUMPTION, LUT
positions incl. ALU; "RAM16" cells count 8 LUT each per 1.1). The last column
gives the achieved number where the flat P&R netlist allows one (most rows
cannot be separated: nextpnr reports only totals).

| Block / element | LUT | FF | RAM16 | BSRAM | Basis | Achieved (SIMULATION) |
|---|---|---|---|---|---|---|
| **SC array 16x8** (bench minus wrapper) | 2830 | 1409 | 0 | 0 | tool estimate, 1.2 | not separable |
| TPU weight RAM 2 KiB (512 x 32, single port shared CPU/TPU) | 0 | 0 | 0 | 1 | 16 Kbit mode 512x32 (S-007, ASSUMPTION mode support) | 1 SDPX9B (bsram_init.log) — 0 % |
| TPU tile loader (9-bit word counter, 32 group enables of 4 weights) | 50 | 10 | 0 | 0 | 11 ALU + 32 decode + control | not separable (RTL loads the tile by shifting) |
| TPU INPUT buffer 16 x 32 | 64 | 0 | 8 | 0 | 16 words x 32 bit = 8 RAM16SDP4 (16x4 each) = 64 LUT positions | INPUT + BIAS = 16 RAM16SDP4 — 0 % |
| TPU HIDDEN 16 x 8 (FF, layer-2 input + CPU read) | 20 | 128 | 0 | 0 | 16 write enables + mux share | 128 FF (RTL-TPU design summary) |
| TPU SCORE 16 x 32 | 64 | 0 | 8 | 0 | 8 RAM16 cells | **16 x 20 FF = 320 FF, 0 RAM16** (RTL choice, sign-extended on read) |
| TPU BIAS 32 x 16 | 64 | 0 | 8 | 0 | depth 32 = 2 x 4 cells | (in the 16 RAM16 above) |
| Post-proc: acc 16:1 mux (17 b) | 90 | 0 | 0 | 0 | 17 x (5 LUT + MUX2 tree) | not separable |
| Post-proc: 2acc - N_in L, + B (2 x 20 b) | 44 | 0 | 0 | 0 | 2 carry chains | not separable |
| Post-proc: bias scale shift by K-7 in -3..+3 (20 b) | 60 | 0 | 0 | 0 | 20 x 3 LUT | not separable |
| Post-proc: hidden shift (-3..+10) + clip 0..127 | 70 | 0 | 0 | 0 | 7 output bits x 14:1 + saturation detect | not separable (RTL: exact 34-bit shifter) |
| Post-proc pipeline registers (2 stages) | 0 | 45 | 0 | 0 | 20 + 20 + 5 | 2-stage pipeline present, FF count not separable |
| Argmax (20 b compare, max + index) | 30 | 25 | 0 | 0 | 22 ALU + control | not separable |
| TPU controller FSM + counters (k 11 b, tile, layer, neuron, state) | 60 | 30 | 0 | 0 | | not separable |
| TPU CYCLES counter + register | 34 | 64 | 0 | 0 | 32 ALU + 2 | not separable |
| TPU CTRL/STATUS/CONFIG/RESULT regs | 10 | 12 | 0 | 0 | | not separable |
| TPU bus slave: decode + read mux (~8 sources x 32 b) + rdata/ready regs | 130 | 33 | 0 | 0 | | not separable |
| **TPU excluding array — subtotal** | **790** | **347** | **24** | **1** | (RAM16 LUTs included in LUT) | ~1530 LUT (+94 %), see note T |
| **TPU total, mode 2** (array + subtotal + 112 LUT / 224 FF, 1.5) | **3732** | **1980** | **24** | **1** | CALCULATION | **~4472 LUT4 (+19.8 %), ~2569 DFF (+29.7 %), 16 RAM16, 1 BSRAM** (RTL-TPU il8_m2_nwl 4572 / 2669 minus ~100 / ~100 wrapper, ASSUMPTION) |
| **CPU RV32I multi-cycle** (proxy minus RAM/LED wrapper) | 1940 | 600 | 32 | 0 | tool estimate (PicoRV32 proxy), regfile in LUT-RAM | **957 LUT4 / 126 DFF / 0 RAM16 / 2 BSRAM regfile** in-context incl. RAM wrapper (-50.7 % / -79.0 %), see note C; core alone 905 LUT positions / 111 DFF (Yosys OOC) |
| RAM 4 KiB (1024 x 32, byte enables) | 0 | 0 | 0 | 2 | tool estimate: inferred as 2 BSRAM in the proxy | 2 x SP BSRAM (bsram_init.log) — 0 % |
| Peripherals: LED (6 FF), UART TX (22 FF, ~25 LUT), CYCLE (32 FF, 34 ALU), TOHOST (32 FF), bus_err, read mux 5:1 x 32, rdata reg | 125 | 126 | 0 | 0 | | not separable (SoC - TPU - CPU = +99 LUT4 / +8 DFF, but both stand-alone numbers include wrappers, so this difference is not a measurement of the block) |
| Bus decoder, 3:1 rdata mux, unmapped responder, RAM ready, reset sync | 50 | 7 | 0 | 0 | | (as above) |
| **TOTAL baseline** | **5735** | **2489** | **56** | **3** | | **5628 LUT4 / 2803 DFF / 16 RAM16 / 5 BSRAM** (logs/soc/pnr_nwl_s1.log, identical for seeds 2, 3) |
| % of capacity | **66.4 %** | **38.4 %** | 20.7 % | 11.5 % | REQ-RES limits 85 % | **65.1 % / 43.3 % / 5.9 % / 19.2 %** |

Uncertainty (ASSUMPTION): +50 % on the 965 LUT of un-benchmarked blocks
(TPU-other, periph, bus) and +/-25 % (+/-485 LUT) on the CPU (a from-scratch
FSM CPU may be smaller or larger than PicoRV32) -> **worst case 5735 + 483 +
485 = 6703 LUT = 77.6 %** (CALCULATION). Margin to the 85 % limit (7344 LUT):
641 LUT worst case, 1609 LUT nominal.
*Achieved margin (CALCULATION from SIMULATION):* 7344 - 5628 = **1716 LUT4**;
5508 - 2803 = 2705 DFF; 22 - 5 = 17 BSRAM.

Explanation of the > 10 % deviations in 1.4 (issue 2):
- **Total LUT4 -1.9 % is right by compensation, not because each block was right.**
  The TPU came out ~+740 LUT above budget and the CPU ~-980 LUT below it; the two
  errors cancel. The budget method (bench + per-element ASSUMPTION) therefore
  predicted the total well but would not have predicted a TPU-only or CPU-only design.
- **Note T (TPU-other +94 %, TPU total +20 % LUT / +30 % FF):** known contributor
  (RTL-TPU design summary): SCORE in FFs (+320 FF and its read mux, -64 LUT of
  LUT-RAM). Likely contributors (from the RTL-TPU description, sizes not verified):
  the exact 34-bit post-processing shifter instead of the budgeted 20-bit
  saturating shift, the read-stall logic of the bus slave (RTL-TPU A1), output
  registers on the INPUT/BIAS LUT-RAM (~48 FF if 32 + 16 bits). The remaining
  ~+270 FF / ~+600 LUT are **not attributed**:
  the release netlist is flattened (Yosys `stat` has one module) and nextpnr gives
  totals only. The overrun is outside the +50 % ASSUMPTION band of the
  un-benchmarked blocks (790 x 1.5 = 1185 < ~1530); lesson: a TPU controller /
  post-processing bench should have been calibrated too.
- **Note C (CPU -51 % LUT, -79 % FF):** the PicoRV32 proxy is a larger core than
  the project CPU: its register file is 32 RAM16SDP4 (= 256 LUT positions) vs
  2 BSRAM (0 LUT, 0 FF) in the project; the project uses one 33-bit adder for ALU,
  branch compare and address, and an iterative 4/1-bit shifter instead of a barrel
  shifter (RTL-CPU: the barrel version cost ~450 LUT/MUX more); PicoRV32 keeps
  extra pipeline / look-ahead state (626 FF) where the project FSM keeps PC, IR,
  ALU result and a few control bits (111 FF core). The +/-25 % proxy uncertainty
  was too narrow; the proxy was an upper bound.
- **DFF +12.6 % vs baseline:** the baseline was mode 1; mode 2 (+224 FF) was
  adopted later (ADR-008). Against the mode-2 budget (2713) the deviation is +3.3 %.
- **BSRAM +67 %, RAM16 -71 %:** design options listed in 1.5 / 2 were taken
  (CPU regfile in BSRAM: +2 BSRAM, -32 RAM16) and SCORE moved from LUT-RAM to FFs
  (-8 RAM16). With these options the budget gives 5 BSRAM (0 %) and 24 RAM16
  (-33 %, the SCORE move).

### 1.5 Variants (CALCULATION, deltas vs baseline)
| Variant | Delta LUT | Delta FF | Total LUT (%) | Total FF (%) | Fits <= 85 %? | Achieved (SIMULATION) |
|---|---|---|---|---|---|---|
| Baseline (mode 1, IL 8) | 0 | 0 | 5735 (66.4) | 2489 (38.4) | yes | not built as SoC (TPU alone il8_m1_nwl 4461 LUT4 / 2445 DFF) |
| RNG_MODE 0 | 0 | 0 | 5735 (66.4) | 2489 (38.4) | yes | TPU alone: mode 0 vs mode 1 +7 LUT4, 0 DFF (nwl) — noise |
| RNG_MODE 2 | +112 | +224 | 5847 (67.7) | 2713 (41.9) | yes | TPU alone: **+111 LUT4, +224 DFF** (nwl) — -0.9 % / 0 %; **chosen (ADR-008/010)** |
| IL = 4 (mode 1) | -1408 | -545 | 4327 (50.1) | 1944 (30.0) | yes (stream time x2) | TPU alone: -919 LUT4 (-35 %), -544 DFF (0 %); fits (40 %) |
| IL = 16 (mode 1) | +2426 | +1089 | 8161 (94.5) | 3578 (55.2) | **NO** | TPU alone: +1861 LUT4 (-23 %), +1088 DFF; TPU alone 73-77 % LUT4 and **no legal placement** (nextpnr, all seeds run) — conclusion "does not fit" confirmed |
| CPU regfile in BSRAM (2 SDP blocks) | -256 | 0 | 5479 (63.4) | 2489 | yes, +2 BSRAM | **chosen (RTL-CPU)**: 2 SDPX9B, 0 LUT, 0 FF for the regfile; costs the 32-cycle CLEAR after reset (REQ-SYS-005 (b) relaxed, ADR-011) |
| CPU regfile in FFs (31 x 32) | +300 (2 x 32 x 31:1 mux ~ +550, -256 LUT-RAM) | +992 | ~6035 (69.8) | 3481 (53.7) | yes | not built |
| TPU buffers in FFs instead of LUT-RAM | +360 (read mux ~550, -192 LUT-RAM) | +1344 | ~6095 (70.5) | 3833 (59.2) | yes | partly: SCORE in FFs (+320 FF), INPUT/BIAS in LUT-RAM |
| Everything worst (mode 2 + FF regfile + FF buffers + full uncertainty of 1.4) | +1740 | +2560 | ~7475 (86.5) | ~5049 (77.9) | **NO** -> keep LUT-RAM/BSRAM for storage | not built |
| *As built (issue 2): mode 2 + BSRAM regfile* | *+112 - 256 = -144* | *+224* | *5591 (64.7)* | *2713 (41.9)* | *yes* | **5628 (65.1 %) / 2803 (43.3 %): +0.7 % / +3.3 %** |

IL-delta deviations > 10 % (IL 4 -35 %, IL 16 -23 %) follow from the lower
achieved per-lane cost (14.4 vs 22.0 LUT / lane, see 1.2); the decision they
supported (IL = 8 frozen, IL = 16 does not fit) is unchanged.

Conclusion (issue 1, confirmed in issue 2): the frozen geometry (IL = 8) fits;
the release SoC uses 65.1 % LUT4 against the 85 % limit; storage stays in
LUT-RAM/BSRAM; IL = 16 does not fit.

## 2. BSRAM budget (CALCULATION; block size S-006/S-007 ASSUMPTION)
| Memory | Size | Organisation | Blocks | Note | Achieved (SIMULATION, logs/soc/bsram_init.log) |
|---|---|---|---|---|---|
| RAM (program + data) | 4 KiB = 32 768 bit | 1024 x 32, byte enables | 2 | 16 Kbit per block in x32 mode; proxy run confirmed 2 BSRAM with byte enables | 2 x SP, non-zero INIT = program image — 0 % |
| TPU weight RAM | 2 KiB = 16 384 bit | 512 x 32 | 1 | single port time-shared CPU/TPU (TPU owns it while BUSY); OD-6 | 1 x SDP (SDPX9B), INIT = weights.hex — 0 % |
| Option: CPU regfile | 31 x 32 bit | 2 x SDP 512 x 32 (one per read port) | +2 | saves ~256 LUT; adds 1 read-latency cycle (fits DECODE state) | **taken**: 2 x SDP, all-zero INIT, cleared by CLEAR |
| Option: TPU INPUT/SCORE/BIAS | 64 B / 64 B / 64 B | 1 block each | +3 | only if LUT-RAM is short | not taken |
| **Baseline total** | | | **3 / 26 = 11.5 %** | | **5 / 26 = 19.2 %** (= baseline + regfile option, 0 % vs that budget) |
| Maximum with all options | | | 8 / 26 = 30.8 % | REQ-RES-004 limit 22 | — |

If BSRAM inference failed, RAM + weight RAM would need 49 152 FF (> 6480
device FF): BSRAM inference is mandatory (REQ-RES-004, risk R-05).
*Achieved:* all three memories and the regfile are BSRAM primitives in the routed
netlist (SIMULATION, logs/soc/bsram_init.log: `BSRAM cells 5, with non-zero init 3`);
gate-level simulation of the BSRAM init/byte enables is NOT RUN (no behavioural
Gowin BSRAM models, RTL-SOC).

## 3. Latency budget (CALCULATION, `logs/latency_budget.log`)
Model: `N(K) = T_START + 10 x (2^K + O_TILE) + 2 x (P_POST + C_LAYER) + A_ARGMAX + T_DONE`

| Input | Value | Label | Achieved (SIMULATION; RTL-TPU sc_tpu_ctrl.v formula, confirmed for every K) |
|---|---|---|---|
| tiles per inference | 8 (64/IL) + 2 (16/IL) = 10 | CALCULATION (spec 5.3) | 10 |
| stream cycles per tile | L = 2^K | SOURCE spec 5.3 | 2^K |
| O_TILE: per-tile load overhead | 32 word reads (128 B / 4 B, 1 word/clock) + 1 BSRAM latency + 3 input-load/FSM = 36 | ASSUMPTION | **33** (= NL*IL/4 + 1 = 32 BSRAM words + 1); input load overlapped |
| P_POST: post-processing per layer | 16 (one neuron/clock) | ASSUMPTION | together with C_LAYER: **19 per layer** (= NL + 3) |
| C_LAYER: acc clear + pipeline drain per layer | 2 | ASSUMPTION | (in the 19 above) |
| A_ARGMAX | 10 | ASSUMPTION | **0** extra (argmax folded into layer-2 post-processing) |
| T_START, T_DONE | 2, 1 | ASSUMPTION | **0** extra (CYCLES counts BUSY edges only, A.2) |
| f_clk | 27 MHz | SOURCE S-020 | 27 MHz |

Closed form: **N(K) = 10 x 2^K + 409 cycles** (known-answer check N(8) = 2969 PASS).
*Achieved:* **CYCLES(K) = 10 x (2^K + 33) + 2 x 19 = 10 x 2^K + 368** (SIMULATION:
tb_sc_tpu D8 `CYCLES = 2928 = measured BUSY cycles 2928 = formula 10*2^8+368 (K=8)`,
logs/tpu/tb_sc_tpu_mode2.log, rev C; every golden vector checks CYCLES == BUSY
cycles == formula for K = 4..10, RTL-TPU; SoC demo D6 = 2928, logs/soc/tb_soc_demo.log).
Fixed-term deviation 368 vs 409 = **-10.0 %** (-41 cycles = 10 tiles x -3 load
cycles + 2 layers x +1 post-processing cycle - 13 cycles of argmax/start/done
that the RTL overlaps with post-processing). This is at the 10 % threshold and in
the favourable direction; the K-dependent term is exact.

| K | L | cycles | time (us) | inferences/s | streaming share | SC bit-ops/s | useful MAC/s | **achieved cycles (SIMULATION)** | **achieved time (us)** | **achieved inf/s** | deviation |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 4 | 16 | 569 | 21.07 | 47 452 | 28.1 % | 9.72e8 | 5.62e7 | 528 | 19.56 | 51 136 | -7.2 % |
| 5 | 32 | 729 | 27.00 | 37 037 | 43.9 % | 1.52e9 | 4.39e7 | 688 | 25.48 | 39 244 | -5.6 % |
| 6 | 64 | 1049 | 38.85 | 25 739 | 61.0 % | 2.11e9 | 3.05e7 | 1008 | 37.33 | 26 786 | -3.9 % |
| 7 | 128 | 1689 | 62.56 | 15 986 | 75.8 % | 2.62e9 | 1.89e7 | 1648 | 61.04 | 16 383 | -2.4 % |
| **8** | **256** | **2969** | **109.96** | **9 094** | **86.2 %** | **2.98e9** | **1.08e7** | **2928** | **108.44** | **9 221** | **-1.4 %** |
| 9 | 512 | 5529 | 204.78 | 4 883 | 92.6 % | 3.20e9 | 5.78e6 | 5488 | 203.26 | 4 920 | -0.7 % |
| 10 | 1024 | 10649 | 394.41 | 2 535 | 96.2 % | 3.32e9 | 3.00e6 | 10608 | 392.89 | 2 545 | -0.4 % |

(achieved time / rate = CALCULATION from the SIMULATION cycle count at 27 MHz.)
Sensitivity: N(8) = 2949 / 2969 / 3009 / 3089 for O_TILE = 34 / 36 / 40 / 48.
Design option (not in spec): double-buffered weight registers hide O_TILE for
8 of 10 tiles when L >= 36 -> N(8) = 2681 (-9.7 %), at a cost of +1024 FF
(would raise FF to ~54 %). Not implemented (RTL-TPU OD-3).
REQ-TIM-004 bound: CYCLES(K) <= 1.10 x N(K) (K = 8: 3265 cycles = 120.9 us).
*Achieved margin to that bound:* 3265 - 2928 = 337 cycles at K = 8 (CALCULATION).

CPU-side overhead per inference (ASSUMPTION, not part of CYCLES): 16 SW for the
input codes + START + polling + RESULT read + LED/UART ~ 25 instructions x
CPI ~4-6 ~ 100-150 cycles (reported by REQ-TIM-005).
*Achieved (SIMULATION, logs/soc/tb_soc_demo.log, rev C):* START store -> RESULT read
2948 cycles = CYCLES 2928 + **20 cycles**; the demo program does **not** write the 64
input codes (inputs come from input.hex), so this number excludes the 16 SW the
budget included — the two are not comparable (REQ-TIM-005 PARTIAL, ADR-011).
Reset release -> TOHOST = 5441 cycles (201.5 us), 981 instructions retired.
*CPI achieved (SIMULATION):* 4.231 aggregate at 0 wait states (28206 cycles /
6667 instructions, 44 tests, logs/cpu/sim_cpu_summary.log), 5.593 at 1 wait state
(RTL-CPU), 5.51 for the SoC demo ((5441 - 31) / 981, CALCULATION); all inside the
assumed 4-6.

## 4. Throughput (CALCULATION)
- Inferences/s = f_clk / N(K): **9094 /s at K = 8**; 2535 /s at K = 10.
  *Achieved:* 27e6 / 2928 = **9221 /s at K = 8** (+1.4 %); 2545 /s at K = 10.
- SC bit-operations (one XNOR + one APC add per lane per stream cycle,
  NL x IL = 128 lanes, layer-2 padding lanes included):
  128 x 10 x 2^K x f_clk / N(K) = **2.98e9 /s at K = 8**; peak (100 %
  streaming) = 128 x 27e6 = 3.456e9 /s. *Achieved:* 3.02e9 /s at K = 8 (+1.4 %).
- Network MACs per inference = 64 x 16 + 16 x 10 = 1184 -> 1.08e7 MAC/s at
  K = 8 (*achieved 1.09e7 MAC/s*). Each SC MAC at L = 256 has an effective
  precision of ~K/2 = 4 bits from the stream variance (std(D/L) <= sqrt(N_in/L),
  sec. 8); comparison with an int8 binary design (ADR-001 B: 20 MULT18X18 = up to
  40 MULT9X9 lanes x 27 MHz = 1.08e9 MAC/s, CALCULATION from S-032) belongs in the
  article. All rates are at the 27 MHz board clock; the 47.46 MHz Fmax is margin,
  not a usable clock (no PLL, REQ-SYS-004).

## 5. Timing budget (tool estimates + CALCULATION)
Requirement: Fmax >= 29.7 MHz (period budget 33.67 ns incl. 10 % margin on
37.04 ns).

Delay basis (tool estimate, nextpnr GW1N-9C timing model, read from the
critical-path reports in `scripts/budgets/build/*.pnr.log`): clk-to-q 0.46 ns,
setup 0.40 ns, LUT4 0.96-1.03 ns, MUX2_LUTx 0.47-0.50 ns, ALU chain entry
0.96 ns, carry 0.06 ns/bit, routing 1.3-3.4 ns per inter-cell net. One LUT
level with routing ~2.5-4.5 ns -> ~7-12 LUT levels fit in 33.67 ns.
**Design rule (derived): <= 7 LUT levels between registers, carry chains
excluded.** The model itself is reverse-engineered and not silicon-validated
(risk R-05).

| # | Path candidate | Est. depth | Tool estimate (worst seed) | Slack vs 33.67 ns | Achieved (SIMULATION, post-route STA, worst of 3 seeds) | Deviation of path delay |
|---|---|---|---|---|---|---|
| P1 | SC MAC: LFSR reg -> 8-bit compare (ALU chain) -> XNOR + popcount(8) (LUT + 4 MUX2 levels) -> 17-bit acc add -> acc reg | ~4 LUT levels + 8 + 17 carry bits | 52.12 MHz = 19.19 ns (IL 8 mode 1); 52.36 (m0); 52.98 (m2); 68.51 (IL 4) | +14.5 ns | TPU alone il8_m2_nwl: worst seed 60.43 MHz = 16.55 ns; path class w_tile reg -> comparator -> popcount -> acc (seed-1 report reports/fpga/tpu/il8_m2_nwl_critical_path.txt, 15.56 ns); **not critical in the SoC** (< 21.07 ns) | -13.8 % |
| P2 | 8-step LFSR next state | 1 LUT level (4-input XOR) | not critical (inside P1 start) | > +25 ns | RTL moved it off the path (look-ahead LFSR register, RTL-TPU) | — |
| P3 | CPU: operand reg -> 32-bit ALU compare/add -> branch decision -> state reg | 2-4 LUT + 32 carry | 91.32 MHz = 10.95 ns (PicoRV32 proxy) | +22.7 ns | CPU alone 53.26 MHz = **18.77 ns** (logs/cpu/pnr_s2.log); in the SoC **21.07 ns = 47.46 MHz = SoC critical path** (8.83 logic + 12.24 routing: ir -> decoder/FSM next state -> ALU operand select -> 32-bit carry chain -> pc; reports/fpga/soc/critical_path_nwl.txt); slack 12.6 ns | **+71 % alone, +92 % in SoC** |
| P4 | Post-proc unpipelined: acc 16:1 mux -> 2acc - N L -> + B (shift) -> hidden shift -> clip | ~8-9 LUT levels + 2 x 20 carry | not benchmarked; CALCULATION ~25-35 ns -> **pipeline in 2 stages** (included as C_LAYER) | ~0 if unpipelined | pipelined in 2 stages as recommended; stage 2 (34-bit shifter + clip) = 17.69 ns, critical path of the TPU alone in the default flow (reports/fpga/tpu/il8_m1_critical_path.txt) | within the pipelined budget |
| P5 | Bus read: slave rdata mux -> CPU load align / sign-extend -> regfile write | ~5-6 LUT levels | not benchmarked; ~15-25 ns | +9..+19 ns | not reported separately (< 21.07 ns, since P3 is critical) | — |
| P6 | TPU read mux (8 sources) -> bus rdata register | ~3-4 LUT levels | not benchmarked | > +15 ns | not reported separately (< 21.07 ns) | — |
| SoC | min over candidates | — | **52.12 MHz** (P1) | — | **47.46 MHz** (seeds 51.98 / 47.46 / 51.21, logs/soc/pnr_nwl_s{1,2,3}.log); REQ-TIM-001 margin +59.8 % vs 29.7 MHz | -8.9 % in Fmax |

Explanation of the > 10 % deviations (issue 2):
- **P3 +71 % / +92 %:** the budget used PicoRV32 as a proxy; its critical path is a
  compare/add into a pipeline register. The project CPU decodes the instruction
  register combinationally into the FSM next-state and the ALU operand select in
  the same cycle (ir -> decoder -> FSM -> operand mux -> 33-bit adder -> pc),
  ~2x the logic depth (9.66 ns logic alone vs 10.95 ns total for the proxy). In the
  SoC the same path gets +3.1 ns more routing (12.24 vs 9.11 ns) at 65 % LUT4
  utilisation — the congestion effect that issue 1 anticipated for P1 hit P3.
  The "<= 7 LUT levels" rule was not violated badly enough to fail: slack 12.6 ns.
- **P1 -13.8 %:** the RTL registers r in a look-ahead LFSR (r is a flop output, P2
  removed from the path; RTL-TPU design summary); the nwl flow maps without MUX2
  cells (0 MUX2_LUTx, variants.md), which plausibly shortens the popcount (not
  separated).
- **SoC Fmax -8.9 % (inside 10 %)** — but for a different reason than budgeted
  (critical path P3 instead of P1); the budget's ranking of path candidates was wrong.

## 6. Power (NOT RUN — no open Gowin power model)
No open-source power model exists for GW1N (the vendor estimator is part of the
proprietary IDE, excluded by REQ-SYS-002). Order-of-magnitude **ASSUMPTION**
only, for the article's context. **No achieved number exists** (no power
simulation, no hardware).

`P_dyn = sum(alpha x C x V^2 x f)`, V = 1.2 V (S-018, ASSUMPTION label), f = 27 MHz.

| Term | Inputs (all ASSUMPTION unless noted) | Range issue 1 | Range issue 2 (achieved cell counts, same coefficients) |
|---|---|---|---|
| Logic + local routing | 5735 / **5628** LUT (CALCULATION 1.4 / SIMULATION) x alpha 0.1-0.3 x C 0.05-0.2 pF | 0.9-11 mW (**arithmetic slip**; the formula gives 1.1-13.4 mW) | 1.1-13.1 mW |
| Clock tree + FF clock pins | 2489 / **2803** FF x alpha 1 x C 0.01-0.05 pF | 1-5 mW | 1.1-5.4 mW |
| BSRAM | 3 / **5** blocks x 0.5-2 mW each (active every cycle) | 1.5-6 mW | 2.5-10 mW |
| Static (core) | unknown without DS117 | a few to ~20 mW | a few to ~20 mW |
| **FPGA core total** | | **~5-40 mW** | **~5-50 mW** |

Board level is dominated by the BL702 bridge, regulators and LEDs (not
estimated). Any power number in the article must carry the ASSUMPTION label;
physical measurement is in the validation plan (REQ-VER-009 step 5).

## 7. UART divider (CALCULATION, reused from ST-SYS-01, `logs/smoke/sys_uart.log`)
D = round(27e6 / 115200) = round(234.375) = **234**; real baud = 115 384.6 Bd;
baud error **+0.16 %** (bit time -0.16 %) <= 2 % (REQ-SYS-012). Frame = 10 bits
= 2340 clocks. A 16x-oversampling RX at 27 MHz would give D = 15 and -2.34 %
error (> 2 %) — relevant only if `uart_rx` is ever used.
*Achieved (SIMULATION, RTL-SOC tb_soc U1 / tb_soc_bfm T9):* every edge on k x 234
clocks, frame 2340 clocks, tx_busy 2340 cycles, bytes 0x00 0x55 0xA5 0xFF and the
demo "7\n" decoded by a real-time 115200 Bd receiver — deviation 0. (Negative run:
UART_DIV = 240 detected, `tx_busy lasted 2400 cycles`.)

## 8. Accuracy / statistics budget (CALCULATION, `logs/stats_budget.log`)
- Test split n = 360: 1 image = 0.28 pp. Wilson 95 % CI half-width: 3.1 pp at
  90 %, 2.7 pp at 93 %, 2.3 pp at 95 %. A 2 pp difference between two
  configurations on the same images is therefore *not* statistically resolved;
  REQ-AI-005/006 use it as an engineering threshold, and REQ-AI-007 requires CIs.
  *Achieved:* SW-03 reports Wilson CIs (mode 2 K = 8: 94.4 %, CI 91.6-96.4 %,
  i.e. -2.8 / +2.0 pp, consistent with the 2.3-2.7 pp budget) and paired exact
  McNemar tests for rev comparisons (e.g. rev B vs C at K = 9, p = 0.0015).
- SC noise bound with independent streams: std(Dp/L) <= sqrt(N_in/L) in units
  of sum v_x v_w: layer 1 (N_in = 64): 2.00 / 1.00 / **0.50** / 0.25 at K = 4 /
  6 / **8** / 10; layer 2 (N_in = 16): 1.00 / 0.50 / **0.25** / 0.125.
  Correlated modes exceed the bound (sec. 9).
- Preliminary SIMULATION input (software-engineer WIP, `logs/sw/accuracy.log`,
  rev d2ed476-dirty, not yet baselined): EV 95.0 %; bit-exact K = 8: mode 0
  65.6 %, mode 1 91.1 %, mode 2 94.4 % (variant qat_noise). Used only to set
  REQ-AI-004/005 thresholds.

Budget input vs achieved (rev C, `reports/sw/accuracy_revC.json`, SIMULATION of the
bit-exact golden model, n = 360 test images, weights qat_noise, s = 0):

| Quantity | Issue-1 value (input / bound) | Achieved rev C | Deviation | Note |
|---|---|---|---|---|
| EV accuracy | 95.0 % (prelim.) | 95.0 % (342/360) | 0 | same weights |
| Mode 2, K = 8, deployed seeds | 94.4 % (prelim., rev A seeds) | **94.4 % (340/360)** | 0 | rev C mode-2 seeds = rev A seeds: identical per image (SW-03 compare_abc) |
| Mode 1, K = 8 | 91.1 % | 89.2 % (321/360) | -2.1 % (-1.9 pp) | modes 0/1 W seed changed 0x7A5C -> 0xF9DE (rev B/C): a different single realisation, 2.8 sd below the mode-1 ensemble mean (92.8 +/- 1.3 %) |
| Mode 0, K = 8 | 65.6 % | 81.9 % (295/360) | **+25 % (+16.3 pp)** | same W-seed change; mode 0 is dominated by realisation noise (ensemble 90.7 +/- 4.4 %, non-monotonic in K: 89.7 % at K = 7, 81.9 % at K = 8); mode 0 is a study mode only |
| K_op (REQ-AI-005, mode 2) | 8 (prelim.) | 8 | 0 | gap 0.56 pp at K = 8, 9 |
| Ensemble mean, mode 2, K = 8 | 92.7 +/- 1.5 % (prelim., REQ-AI-006 rationale) | 92.8 +/- 1.4 % (20 offsets) | +0.1 % | |
| Layer-1 noise, mode 2, K = 8 | <= 0.50 (bound) | ensemble 0.489; deployed seeds 0.353 | -2 % / **-29 %** | the bound sqrt(N_in/L) assumes every product has the maximum variance (v_x v_w = 0); the data-dependent eq. (2) of the software error model gives 0.483. The deployed seed set is one realisation 0.73 x eq. (2) (favourable draw). A bound being undershot is not a defect |
| Layer-2 noise (lanes 0..9), mode 2, K = 8 | <= 0.25 (bound) | ensemble 0.191; deployed 0.198 | **-24 % / -21 %** | same reason (eq. (2) gives 0.199); the 6 padding lanes reach 0.204 vs eq. (2) 0.25 |

The thresholds of REQ-AI-003..006 set from the preliminary data remain
reachable with the same margins; the verification status is set in the status
matrix, not here.

## 9. RNG analysis

### 9.1 Issue 1 (rev A seeds, CALCULATION, `logs/lfsr_check.log`)
- LFSR x^16+x^14+x^13+x^11+1 as written in spec 5.3: period **65535**
  (maximal); 8-step leap period 65535 stream cycles (gcd(65535, 8) = 1).
- No seed is the lock-up state 0 (all 18 seeds checked).
- Steps per inference = 10 x 2^K x 8: 0.31 periods at K = 8, **1.25 periods at
  K = 10** -> at K = 10 every LFSR wraps within one inference (the same random
  sequence is re-used for later tiles; different data, expected low impact).
  **Issue 2 correction:** counted in *states*, the leap-8 sequence S(8k) has period
  65535 stream cycles, so no state and no r value repeats within an inference
  (10240 cycles = 0.156 state periods at K = 10). What does wrap is the underlying
  *bit* sequence (65536 single steps = 8192 stream cycles): at K = 10 the window
  r(k + 8192) is r(k) shifted by one bit, i.e. it shares 7 of 8 bits with r(k)
  (verified on the real LFSR states, `logs/lfsr_rules_revC.log`). The impact
  statement (low, K = 10 only) is unchanged; the measured K = 10 accuracy (95.3 %,
  mode 2) shows no penalty.
- Modes 0/1: LFSR_X reaches LFSR_W's seed after 18027 steps (2253 stream
  cycles) -> for K >= 8 the X stream re-uses numbers the W stream used earlier
  (time-shifted, not same-cycle; low impact). Same-cycle correlation
  corr(r_x, r_w) = +0.050 over one K = 8 inference (independent-sample sigma
  ~0.020, i.e. ~2.5 sigma — mild). *(Rev A pair 0xACE1/0x7A5C; superseded, see 9.2.)*
- Mode 0: all input lanes use identical r -> cross-lane correlation 1.0.
  Mode 1: max cross-lane correlation of rotl8 variants 0.52. Mode 2: max |corr|
  among the 16 LFSRs 0.053; smallest phase distance 553 steps (69 stream
  cycles, X5 vs W3); same-lane X_i/W_i distances >= 1379 steps (lane 6).
  This ranks the modes 2 > 1 >> 0 for decorrelation, consistent with the
  preliminary accuracy data. *(Issue 2 note: "553 steps" is a single-step phase
  distance; it corresponds to the 7-bit sharing lag lambda1 = 69 cycles of SW-03,
  not to the stream-cycle lag lambda8 = 321 cycles used in ARCHITECTURE.md 12.)*
- SNG bias from the missing zero state: max |P(r < c) - c/256| = 1.5e-5 over a
  full period (negligible).

### 9.2 Issue 2 — rev C seeds and rules R1/R2 (CALCULATION, `logs/lfsr_rules_revC.log`)
Independent implementation from the spec text (does not import the golden model):
- The rev C mode-2 tables of ARCHITECTURE.md 12 and INTERFACES.json revision C
  equal the formulas (0xACE1 + 0x3C5A*i, 0x7A5C + 0x2B67*i) mod 2^16; the rev B
  tables of section 11 equal S(4096 i) / S(32768 + 4096 i); S(32768) = 0xF9DE.
- **Rev C mode 2:** minimum pairwise stream-cycle lag **321 (X0-W3)**, next 541
  (X4-X6) — equal to ARCHITECTURE.md 12 / INTERFACES.json `min_lag_stream_cycles`
  and to SW-03; X_i-W_i lags 26829, 28145, 3406, 12607, 13583, 11304, 24748,
  22808; **R1 satisfied** (0 of 28 lane pairs translated); **R2 satisfied**
  (0 direct, 0 swapped violations).
- **Rev B mode 2 (superseded):** minimum lag 512, all X_i-W_i lags 4096; **R1
  violated on 28 of 28 lane pairs**, R2 violated (28 direct + 36 swapped) —
  reproduces the ADR-009 / SW-03 finding with a second implementation.
- **Modes 0/1 pair 0xACE1/0xF9DE:** X->W lag 32768 steps = 4096 stream cycles;
  self-swap |2D| = 1 <= 14 -> R2 violated (accepted, ADR-010 D-B; study modes only).
  The rev A pair 0xACE1/0x7A5C would satisfy R2 (|2D| = 29481).
- Lesson recorded for the budget method: issue 1 ranked seed sets by minimum
  phase distance (and proposed "maximum pairwise phase distance" as the
  mitigation of R-02). That criterion produced rev B, which was worse (ADR-009).
  The relevant property is R1/R2 (no translated or bit-sharing operand-pair
  streams), not maximal spacing.

## Change history

| Issue | Date | Task | Input revision | Change |
|---|---|---|---|---|
| 1 | 2026-11-04 | REQ-01 | 494448a (spec rev A / A.1) | Initial budgets, sections 1-9 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 (spec rev C) | Budgets unchanged; new section 0 summary; "achieved (SIMULATION)" column added to 1.4, 1.5, 2, 3 (inputs and per-K table), 5, 8; achieved notes in 1.2, 1.3, 4, 7; every > 10 % deviation explained; counting rule re-checked on the release SoC (1.1); power table re-evaluated with achieved cell counts and an issue-1 arithmetic slip corrected (logic 0.9-11 -> 1.1-13.4 mW for the issue-1 inputs); issue-1 K = 10 "wrap" statement corrected (bit-sequence wrap, not state wrap); new 9.2 (rev C seeds, R1/R2, independent check); new scripts `lfsr_rules_revC.py`, `achieved_vs_budget.py` |
