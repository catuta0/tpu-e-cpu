# Budgets — SC-TPU + RV32I SoC on Tang Nano 9K

Owner: systems-engineer · Task: REQ-01 · Date: 2026-11-04 · Issue: 1
Input revision: `494448a` (HEAD at writing, + untracked budget scripts); spec rev A / A.1 (commit c2601fa).
All budget figures are **CALCULATION** unless labelled otherwise. "Tool
estimate" = a CALCULATION whose inputs come from a Yosys/nextpnr run of a
*calibration micro-benchmark* (not the project RTL, not hardware). Requirements
referenced: [`REQUIREMENTS.md`](REQUIREMENTS.md).

Scripts and logs (all under `scripts/budgets/`):
| Script | Purpose | Log |
|---|---|---|
| `run_ubench.sh` + `ubench/*.v` | synth + P&R of calibration benches (SC tile, CPU proxy) | `logs/ubench_run1.log`, `logs/ubench_run2.log`, `logs/ubench_run3.log` |
| `latency_budget.py` | cycles / throughput vs K (known-answer check) | `logs/latency_budget.log` |
| `lfsr_check.py` | LFSR period, seed phase offsets, correlations | `logs/lfsr_check.log` |
| `stats_budget.py` | accuracy CI, SC noise bound, post-proc widths | `logs/stats_budget.log` |
| `uart_divider.py` (ST-SYS-01) | UART divider (known-answer check) | `logs/smoke/sys_uart.log` |

Tool versions (from log headers): Yosys 0.70 (YoWASP), nextpnr-0.11.1
himbaechel-gowin (yowasp 0.11.1.0.post826), Apycula 0.32, Python 3.13.18,
numpy 2.5.4. Device `GW1NR-LV9QN88PC6/I5`, `family=GW1N-9C`, `--freq 27`.

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
  ADR-001 assumed ~9 LUT / lane: the real cost is ~2.4x higher (see OD-7).
- Breakdown of the IL8 tile FFs (CALCULATION, exact): weights 128x8 = 1024 +
  inputs 8x8 = 64 + accumulators 16x17 = 272 + LFSRs 2x16 = 32 + read register
  17 = 1409; + wrapper 45 = 1454 (matches the tool).
- ALU cells: 136 comparators x 8 + 16 accumulators x 17 + wrapper counters
  = 1371 (Yosys reports 1435); nextpnr adds ~2 cells per carry chain (1758).
- RNG_MODE 2 costs +112 LUT and +224 FF (14 extra LFSRs: 14x16 = 224 FF,
  exact) over modes 0/1; mode 1 rotation costs 0 LUT (wiring) — CALCULATION
  from the bench.
- 8-step leap-forward LFSR: each of the 8 new bits is the XOR of exactly 4
  current-state bits, the other 8 bits are a pure shift (symbolic GF(2)
  expansion, CALCULATION) -> 8 LUT4 per LFSR, 1 logic level.

### 1.3 Post-processing word widths (CALCULATION, `logs/stats_budget.log`)
acc <= 64 x 1024 = 65536 -> 17 bit unsigned; |D| <= 65536; |B| <=
32768 x 1024 / 128 = 262144; |Dp| <= 327680 -> **20 bit signed**. Hidden shift
exponent s + 7 - K in [-3, +10]; the exact product Dp x 2^(s+7) reaches
~2^32.3 -> must be computed as a saturating shift, not a 32-bit multiply
(REQ-TPU-008).

### 1.4 Bottom-up budget per block (baseline: RNG_MODE 1, IL = 8, buffers in LUT-RAM, regfile in LUT-RAM)
Per-element assumptions for the blocks without a bench (ASSUMPTION, LUT
positions incl. ALU; "RAM16" cells count 8 LUT each per 1.1):

| Block / element | LUT | FF | RAM16 | BSRAM | Basis |
|---|---|---|---|---|---|
| **SC array 16x8** (bench minus wrapper) | 2830 | 1409 | 0 | 0 | tool estimate, 1.2 |
| TPU weight RAM 2 KiB (512 x 32, single port shared CPU/TPU) | 0 | 0 | 0 | 1 | 16 Kbit mode 512x32 (S-007, ASSUMPTION mode support) |
| TPU tile loader (9-bit word counter, 32 group enables of 4 weights) | 50 | 10 | 0 | 0 | 11 ALU + 32 decode + control |
| TPU INPUT buffer 16 x 32 | 64 | 0 | 8 | 0 | 16 words x 32 bit = 8 RAM16SDP4 (16x4 each) = 64 LUT positions |
| TPU HIDDEN 16 x 8 (FF, layer-2 input + CPU read) | 20 | 128 | 0 | 0 | 16 write enables + mux share |
| TPU SCORE 16 x 32 | 64 | 0 | 8 | 0 | 8 RAM16 cells |
| TPU BIAS 32 x 16 | 64 | 0 | 8 | 0 | depth 32 = 2 x 4 cells |
| Post-proc: acc 16:1 mux (17 b) | 90 | 0 | 0 | 0 | 17 x (5 LUT + MUX2 tree) |
| Post-proc: 2acc - N_in L, + B (2 x 20 b) | 44 | 0 | 0 | 0 | 2 carry chains |
| Post-proc: bias scale shift by K-7 in -3..+3 (20 b) | 60 | 0 | 0 | 0 | 20 x 3 LUT |
| Post-proc: hidden shift (-3..+10) + clip 0..127 | 70 | 0 | 0 | 0 | 7 output bits x 14:1 + saturation detect |
| Post-proc pipeline registers (2 stages) | 0 | 45 | 0 | 0 | 20 + 20 + 5 |
| Argmax (20 b compare, max + index) | 30 | 25 | 0 | 0 | 22 ALU + control |
| TPU controller FSM + counters (k 11 b, tile, layer, neuron, state) | 60 | 30 | 0 | 0 | |
| TPU CYCLES counter + register | 34 | 64 | 0 | 0 | 32 ALU + 2 |
| TPU CTRL/STATUS/CONFIG/RESULT regs | 10 | 12 | 0 | 0 | |
| TPU bus slave: decode + read mux (~8 sources x 32 b) + rdata/ready regs | 130 | 33 | 0 | 0 | |
| **TPU excluding array — subtotal** | **790** | **347** | **24** | **1** | (RAM16 LUTs included in LUT) |
| **CPU RV32I multi-cycle** (proxy minus RAM/LED wrapper) | 1940 | 600 | 32 | 0 | tool estimate (PicoRV32 proxy), regfile in LUT-RAM |
| RAM 4 KiB (1024 x 32, byte enables) | 0 | 0 | 0 | 2 | tool estimate: inferred as 2 BSRAM in the proxy |
| Peripherals: LED (6 FF), UART TX (22 FF, ~25 LUT), CYCLE (32 FF, 34 ALU), TOHOST (32 FF), bus_err, read mux 5:1 x 32, rdata reg | 125 | 126 | 0 | 0 | |
| Bus decoder, 3:1 rdata mux, unmapped responder, RAM ready, reset sync | 50 | 7 | 0 | 0 | |
| **TOTAL baseline** | **5735** | **2489** | **56** | **3** | |
| % of capacity | **66.4 %** | **38.4 %** | 20.7 % | 11.5 % | REQ-RES limits 85 % |

Uncertainty (ASSUMPTION): +50 % on the 965 LUT of un-benchmarked blocks
(TPU-other, periph, bus) and +/-25 % (+/-485 LUT) on the CPU (a from-scratch
FSM CPU may be smaller or larger than PicoRV32) -> **worst case 5735 + 483 +
485 = 6703 LUT = 77.6 %** (CALCULATION). Margin to the 85 % limit (7344 LUT):
641 LUT worst case, 1609 LUT nominal.

### 1.5 Variants (CALCULATION, deltas vs baseline)
| Variant | Delta LUT | Delta FF | Total LUT (%) | Total FF (%) | Fits <= 85 %? |
|---|---|---|---|---|---|
| Baseline (mode 1, IL 8) | 0 | 0 | 5735 (66.4) | 2489 (38.4) | yes |
| RNG_MODE 0 | 0 | 0 | 5735 (66.4) | 2489 (38.4) | yes |
| RNG_MODE 2 | +112 | +224 | 5847 (67.7) | 2713 (41.9) | yes |
| IL = 4 (mode 1) | -1408 | -545 | 4327 (50.1) | 1944 (30.0) | yes (stream time x2) |
| IL = 16 (mode 1) | +2426 | +1089 | 8161 (94.5) | 3578 (55.2) | **NO** |
| CPU regfile in BSRAM (2 SDP blocks) | -256 | 0 | 5479 (63.4) | 2489 | yes, +2 BSRAM |
| CPU regfile in FFs (31 x 32) | +300 (2 x 32 x 31:1 mux ~ +550, -256 LUT-RAM) | +992 | ~6035 (69.8) | 3481 (53.7) | yes |
| TPU buffers in FFs instead of LUT-RAM | +360 (read mux ~550, -192 LUT-RAM) | +1344 | ~6095 (70.5) | 3833 (59.2) | yes |
| Everything worst (mode 2 + FF regfile + FF buffers + full uncertainty of 1.4) | +1740 | +2560 | ~7475 (86.5) | ~5049 (77.9) | **NO** -> keep LUT-RAM/BSRAM for storage |

Conclusion: the frozen geometry (IL = 8) fits with ~23 % (nominal) / ~7 %
(worst case) LUT headroom against the 85 % limit; storage must stay in
LUT-RAM/BSRAM; IL = 16 does not fit.

## 2. BSRAM budget (CALCULATION; block size S-006/S-007 ASSUMPTION)
| Memory | Size | Organisation | Blocks | Note |
|---|---|---|---|---|
| RAM (program + data) | 4 KiB = 32 768 bit | 1024 x 32, byte enables | 2 | 16 Kbit per block in x32 mode; proxy run confirmed 2 BSRAM with byte enables |
| TPU weight RAM | 2 KiB = 16 384 bit | 512 x 32 | 1 | single port time-shared CPU/TPU (TPU owns it while BUSY); OD-6 |
| Option: CPU regfile | 31 x 32 bit | 2 x SDP 512 x 32 (one per read port) | +2 | saves ~256 LUT; adds 1 read-latency cycle (fits DECODE state) |
| Option: TPU INPUT/SCORE/BIAS | 64 B / 64 B / 64 B | 1 block each | +3 | only if LUT-RAM is short |
| **Baseline total** | | | **3 / 26 = 11.5 %** | |
| Maximum with all options | | | 8 / 26 = 30.8 % | REQ-RES-004 limit 22 |

If BSRAM inference failed, RAM + weight RAM would need 49 152 FF (> 6480
device FF): BSRAM inference is mandatory (REQ-RES-004, risk R-05).

## 3. Latency budget (CALCULATION, `logs/latency_budget.log`)
Model: `N(K) = T_START + 10 x (2^K + O_TILE) + 2 x (P_POST + C_LAYER) + A_ARGMAX + T_DONE`

| Input | Value | Label |
|---|---|---|
| tiles per inference | 8 (64/IL) + 2 (16/IL) = 10 | CALCULATION (spec 5.3) |
| stream cycles per tile | L = 2^K | SOURCE spec 5.3 |
| O_TILE: per-tile load overhead | 32 word reads (128 B / 4 B, 1 word/clock) + 1 BSRAM latency + 3 input-load/FSM = 36 | ASSUMPTION |
| P_POST: post-processing per layer | 16 (one neuron/clock) | ASSUMPTION |
| C_LAYER: acc clear + pipeline drain per layer | 2 | ASSUMPTION |
| A_ARGMAX | 10 | ASSUMPTION |
| T_START, T_DONE | 2, 1 | ASSUMPTION |
| f_clk | 27 MHz | SOURCE S-020 |

Closed form: **N(K) = 10 x 2^K + 409 cycles** (known-answer check N(8) = 2969 PASS).

| K | L | cycles | time (us) | inferences/s | streaming share | SC bit-ops/s | useful MAC/s |
|---|---|---|---|---|---|---|---|
| 4 | 16 | 569 | 21.07 | 47 452 | 28.1 % | 9.72e8 | 5.62e7 |
| 5 | 32 | 729 | 27.00 | 37 037 | 43.9 % | 1.52e9 | 4.39e7 |
| 6 | 64 | 1049 | 38.85 | 25 739 | 61.0 % | 2.11e9 | 3.05e7 |
| 7 | 128 | 1689 | 62.56 | 15 986 | 75.8 % | 2.62e9 | 1.89e7 |
| **8** | **256** | **2969** | **109.96** | **9 094** | **86.2 %** | **2.98e9** | **1.08e7** |
| 9 | 512 | 5529 | 204.78 | 4 883 | 92.6 % | 3.20e9 | 5.78e6 |
| 10 | 1024 | 10649 | 394.41 | 2 535 | 96.2 % | 3.32e9 | 3.00e6 |

Sensitivity: N(8) = 2949 / 2969 / 3009 / 3089 for O_TILE = 34 / 36 / 40 / 48.
Design option (not in spec): double-buffered weight registers hide O_TILE for
8 of 10 tiles when L >= 36 -> N(8) = 2681 (-9.7 %), at a cost of +1024 FF
(would raise FF to ~54 %).
REQ-TIM-004 bound: CYCLES(K) <= 1.10 x N(K) (K = 8: 3265 cycles = 120.9 us).

CPU-side overhead per inference (ASSUMPTION, not part of CYCLES): 16 SW for the
input codes + START + polling + RESULT read + LED/UART ~ 25 instructions x
CPI ~4-6 ~ 100-150 cycles (reported by REQ-TIM-005).

## 4. Throughput (CALCULATION)
- Inferences/s = f_clk / N(K): **9094 /s at K = 8**; 2535 /s at K = 10.
- SC bit-operations (one XNOR + one APC add per lane per stream cycle,
  NL x IL = 128 lanes, layer-2 padding lanes included):
  128 x 10 x 2^K x f_clk / N(K) = **2.98e9 /s at K = 8**; peak (100 %
  streaming) = 128 x 27e6 = 3.456e9 /s.
- Network MACs per inference = 64 x 16 + 16 x 10 = 1184 -> 1.08e7 MAC/s at
  K = 8. Each SC MAC at L = 256 has an effective precision of ~K/2 = 4 bits
  from the stream variance (std(D/L) <= sqrt(N_in/L), sec. 8); comparison with
  an int8 binary design (ADR-001 B: 20 MULT18X18 = up to 40 MULT9X9 lanes x
  27 MHz = 1.08e9 MAC/s, CALCULATION from S-032) belongs in the article.

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

| # | Path candidate | Est. depth | Tool estimate (worst seed) | Slack vs 33.67 ns |
|---|---|---|---|---|
| P1 | SC MAC: LFSR reg -> 8-bit compare (ALU chain) -> XNOR + popcount(8) (LUT + 4 MUX2 levels) -> 17-bit acc add -> acc reg | ~4 LUT levels + 8 + 17 carry bits | 52.12 MHz = 19.19 ns (IL 8 mode 1); 52.36 (m0); 52.98 (m2); 68.51 (IL 4) | +14.5 ns |
| P2 | 8-step LFSR next state | 1 LUT level (4-input XOR) | not critical (inside P1 start) | > +25 ns |
| P3 | CPU: operand reg -> 32-bit ALU compare/add -> branch decision -> state reg | 2-4 LUT + 32 carry | 91.32 MHz = 10.95 ns (PicoRV32 proxy) | +22.7 ns |
| P4 | Post-proc unpipelined: acc 16:1 mux -> 2acc - N L -> + B (shift) -> hidden shift -> clip | ~8-9 LUT levels + 2 x 20 carry | not benchmarked; CALCULATION ~25-35 ns -> **pipeline in 2 stages** (included as C_LAYER) | ~0 if unpipelined |
| P5 | Bus read: slave rdata mux -> CPU load align / sign-extend -> regfile write | ~5-6 LUT levels | not benchmarked; ~15-25 ns | +9..+19 ns |
| P6 | TPU read mux (8 sources) -> bus rdata register | ~3-4 LUT levels | not benchmarked | > +15 ns |

The tile-bench path P1 is ~52 % routing; at ~66 % LUT utilisation of the full
SoC, routing delays will grow — the 10 % margin plus the ~1.75x headroom of
P1 is judged sufficient (ASSUMPTION), P4 must be pipelined.

## 6. Power (NOT RUN — no open Gowin power model)
No open-source power model exists for GW1N (the vendor estimator is part of the
proprietary IDE, excluded by REQ-SYS-002). Order-of-magnitude **ASSUMPTION**
only, for the article's context:

`P_dyn = sum(alpha x C x V^2 x f)`, V = 1.2 V (S-018, ASSUMPTION label), f = 27 MHz.

| Term | Inputs (all ASSUMPTION unless noted) | Range |
|---|---|---|
| Logic + local routing | 5735 LUT (CALCULATION 1.4) x alpha 0.1-0.3 x C 0.05-0.2 pF | 0.9-11 mW |
| Clock tree + FF clock pins | 2489 FF x alpha 1 x C 0.01-0.05 pF | 1-5 mW |
| BSRAM | 3 blocks x 0.5-2 mW each (active every cycle) | 1.5-6 mW |
| Static (core) | unknown without DS117 | a few to ~20 mW |
| **FPGA core total** | | **~5-40 mW** |

Board level is dominated by the BL702 bridge, regulators and LEDs (not
estimated). Any power number in the article must carry the ASSUMPTION label;
physical measurement is in the validation plan (REQ-VER-009 step 5).

## 7. UART divider (CALCULATION, reused from ST-SYS-01, `logs/smoke/sys_uart.log`)
D = round(27e6 / 115200) = round(234.375) = **234**; real baud = 115 384.6 Bd;
baud error **+0.16 %** (bit time -0.16 %) <= 2 % (REQ-SYS-012). Frame = 10 bits
= 2340 clocks. A 16x-oversampling RX at 27 MHz would give D = 15 and -2.34 %
error (> 2 %) — relevant only if `uart_rx` is ever used.

## 8. Accuracy / statistics budget (CALCULATION, `logs/stats_budget.log`)
- Test split n = 360: 1 image = 0.28 pp. Wilson 95 % CI half-width: 3.1 pp at
  90 %, 2.7 pp at 93 %, 2.3 pp at 95 %. A 2 pp difference between two
  configurations on the same images is therefore *not* statistically resolved;
  REQ-AI-005/006 use it as an engineering threshold, and REQ-AI-007 requires CIs.
- SC noise bound with independent streams: std(Dp/L) <= sqrt(N_in/L) in units
  of sum v_x v_w: layer 1 (N_in = 64): 2.00 / 1.00 / **0.50** / 0.25 at K = 4 /
  6 / **8** / 10; layer 2 (N_in = 16): 1.00 / 0.50 / **0.25** / 0.125.
  Correlated modes exceed the bound (sec. 9).
- Preliminary SIMULATION input (software-engineer WIP, `logs/sw/accuracy.log`,
  rev d2ed476-dirty, not yet baselined): EV 95.0 %; bit-exact K = 8: mode 0
  65.6 %, mode 1 91.1 %, mode 2 94.4 % (variant qat_noise). Used only to set
  REQ-AI-004/005 thresholds.

## 9. RNG analysis (CALCULATION, `logs/lfsr_check.log`)
- LFSR x^16+x^14+x^13+x^11+1 as written in spec 5.3: period **65535**
  (maximal); 8-step leap period 65535 stream cycles (gcd(65535, 8) = 1).
- No seed is the lock-up state 0 (all 18 seeds checked).
- Steps per inference = 10 x 2^K x 8: 0.31 periods at K = 8, **1.25 periods at
  K = 10** -> at K = 10 every LFSR wraps within one inference (the same random
  sequence is re-used for later tiles; different data, expected low impact).
- Modes 0/1: LFSR_X reaches LFSR_W's seed after 18027 steps (2253 stream
  cycles) -> for K >= 8 the X stream re-uses numbers the W stream used earlier
  (time-shifted, not same-cycle; low impact). Same-cycle correlation
  corr(r_x, r_w) = +0.050 over one K = 8 inference (independent-sample sigma
  ~0.020, i.e. ~2.5 sigma — mild).
- Mode 0: all input lanes use identical r -> cross-lane correlation 1.0.
  Mode 1: max cross-lane correlation of rotl8 variants 0.52. Mode 2: max |corr|
  among the 16 LFSRs 0.053; smallest phase distance 553 steps (69 stream
  cycles, X5 vs W3); same-lane X_i/W_i distances >= 1379 steps (lane 6).
  This ranks the modes 2 > 1 >> 0 for decorrelation, consistent with the
  preliminary accuracy data.
- SNG bias from the missing zero state: max |P(r < c) - c/256| = 1.5e-5 over a
  full period (negligible).
