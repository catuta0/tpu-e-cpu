# RTL-TPU — Stochastic-computing TPU: RTL, testbenches, synthesis/P&R, variant study
Status: PASS
Agent: fpga-engineer   Date: 2026-11-04   Input revision: 199a3dc (assignment); work done on a moving tree, last HEAD seen 1e853f7, all my files uncommitted (`-dirty`). Spec: ARCHITECTURE.md rev A + 9 (A.1) + 10 (A.2).

## Requirements addressed
REQ-TPU-001..016 (all simulated, see table below), REQ-RES-001..004/006 and REQ-TIM-001/004 for the
stand-alone TPU (the SoC-level closure belongs to RTL-SOC). Acceptance of the assignment:
unit TBs pass; bit-exact 0 mismatches on every vector set; RTL lint clean; worst-seed Fmax 55.26 MHz
(>= 29.7 MHz); utilisation reported.

| Req | Evidence (log) | Result |
|---|---|---|
| TPU-001 geometry | RTL params NL=16, IL=8; PARAMS readback D2 | PASS |
| TPU-002 register map / reset | D1 reset values, D4 strobes/RO regs, D4b 0x5555/0xAAAA on all 16+32+512 RW words + CONFIG | PASS |
| TPU-003 PARAMS | D2: 0x01000810 / 0x01010810 / 0x01020810 | PASS |
| TPU-004 SNG/XNOR/APC | tb_sc_lane_array: 9216 stream cycles, forced r in {0,1,127,128,254,255} x all 256 codes | PASS |
| TPU-005 LFSR | tb_sc_lfsr8 (70000 cycles leap vs 8x1-step, period 65535); R1 r of 8+8 lanes vs golden RNG trace for the first 64 stream cycles after EVERY START (35392-39488 stream cycles per mode); R2 LFSR frozen in all ~300k non-stream cycles | PASS |
| TPU-006 RNG modes | all checks run for modes 0/1/2 | PASS |
| TPU-007 clamp | D3 readback (raw 0..15 -> 4..10); every K=4/K=10 vector re-run with raw 0..3 / 11..15: 69/101/69 re-runs, identical results and CYCLES | PASS |
| TPU-008 post-proc widths | tb_sc_postproc 53328 vectors incl. every K, s, extreme acc/bias; widths documented in sc_postproc.v | PASS |
| TPU-009 argmax/ties | corner psets 5 (all tie -> 0), 6 (tie 3/7, padding max ignored) | PASS |
| TPU-010 START/BUSY/DONE | D6, D7 (START while BUSY ignored, 1 BUSY pulse), D10 (DONE stays 1 over 1000 idle cycles) | PASS |
| TPU-011 writes while BUSY | D7: INPUT/BIAS/WEIGHT/CONFIG/CTRL writes during BUSY -> results identical, read-back unchanged | PASS |
| TPU-012 layout / init files | D12 (INIT_FILES=1): $readmemh contents read back, inference with no bus load bit-exact, 3 modes | PASS |
| TPU-013 bit-exact | 1454 golden inferences + 239 clamp re-runs, 0 mismatching words (detail below) | PASS |
| TPU-014 CYCLES | every inference: CYCLES reg == TB-measured BUSY cycles == formula, K = 4..10 | PASS |
| TPU-015 reserved offsets | D4: 0x018, 0x03C, 0x0D0, 0x0FC, 0x180, 0x7FC read 0, writes ignored | PASS |
| TPU-016 reset during inference | D11: rst in tile-3 stream phase, all regs reset after 1 cycle, re-run bit-exact | PASS |
| RES-001..004, TIM-001 (TPU alone) | reports/fpga/tpu/variants.md | PASS (TPU alone; SoC not yet) |

## Inputs
- design/architecture/ARCHITECTURE.md sections 3, 5, 9, 10; management/INTERFACES.json (tpu, bus);
  requirements/REQUIREMENTS.md (REQ-TPU-*); manager messages A.1 / A.2 (both now in the spec).
- Golden data (SW-01a, read only): sim/data/README.md, weights.hex (sha256 b743fe71eb3d...),
  bias.hex (1d1e138fd265...), input.hex, corner/pset1..8_*.hex, tpu_vectors_mode{0,1,2}.txt
  (b34652ba3761..., 3273131667ac..., 964a81a7a403...), tpu_vectors_K4_mode1.txt,
  tpu_vectors_K10_mode1.txt, tpu_vectors_corner_mode{0,1,2}.txt, tpu_rng_trace_mode{0,1,2}.txt.
  Full sha256 of every vector file used is appended to each logs/tpu/tb_sc_tpu_mode<m>.log.
- code/python/sctpu/model.py + gen_hex.py (imported, not modified) for the K/s sweep vectors.

## Outputs
RTL (Verilog-2005, `default_nettype none`, every file with a theory/timing/requirements header):
- design/rtl/tpu/sc_lfsr8.v — 16-bit Fibonacci LFSR, 8 steps per enabled clock, look-ahead register.
- design/rtl/tpu/sc_rng.v — RNG_MODE 0/1/2 generate (shared / rotl8 by lane / IL independent pairs).
- design/rtl/tpu/sc_lane_array.v — 8 input SNGs + 128 weight SNGs + XNOR + popcount + 16 x 17-bit APC accumulators.
- design/rtl/tpu/sc_postproc.v — D, B, Dp, clipped ReLU / score, 2-stage pipeline, 34-bit exact shifter.
- design/rtl/tpu/sc_tpu_ctrl.v — FSM IDLE/LOAD/STREAM/POST, argmax, CYCLES, port ownership.
- design/rtl/tpu/sc_tpu.v — top: bus slave + register map 5.4, BSRAM weight RAM, LUT-RAM INPUT/BIAS, HIDDEN/SCORE regs, init-file parameters.
- design/rtl/tpu/sc_tpu_synth_top.v — synthesis-only wrapper (reset sync, PRNG bus master, read-data signature to LEDs).
Testbenches / generators:
- tests/tpu/tb_sc_lfsr8.v, tb_sc_postproc.v, tb_sc_lane_array.v (unit), tb_sc_tpu.v (system: BFM + protocol checker + directed D1..D12 + RNG monitor + golden vectors).
- tests/tpu/gen_tpu_sweep_vectors.py -> sim/tpu/vectors/tpu_vectors_sweep_mode{0,1,2}.txt (63 vectors each).
Scripts: scripts/sim_tpu.sh (full regression), scripts/synth_tpu_variants.sh (synth + P&R + table; REPORT_ONLY=1 rebuilds the table).
Logs: logs/tpu/ (lint_rtl, lint_tb, tb_*, tb_sc_tpu_mode{0,1,2}, tb_sc_tpu_init_mode{0,1,2}, *_inject_fault, sim_tpu_console, synth_*, pnr_*_s{1,2,3}, synth_tpu_variants*_console, gen_tpu_sweep_vectors).
Reports: reports/fpga/tpu/variants.md (table), reports/fpga/tpu/<variant>_utilisation.txt, <variant>_critical_path.txt.

## Design summary (choices the next engineer must know)
- **Bus slave latency (my choice, documented in sc_tpu.v):** request accepted in the first cycle of
  mem_valid when the slave is idle; mem_ready is a one-cycle pulse in the 3rd cycle (2 cycles after
  acceptance) for every register, buffer and the weight RAM; mem_rdata is registered and 0 outside the
  mem_ready cycle (OR-able in the SoC). Back-to-back requests are accepted from the cycle after mem_ready.
  Exception: a READ of INPUT/BIAS/WEIGHT while the controller owns the memory read ports (tile load or
  post-processing, <= 33 cycles) waits; longest observed valid->ready = 35 cycles (SIMULATION). The slave
  takes `mem_addr[11:0]` only; the SoC decoder qualifies mem_valid with addr[31:28] = 2.
- **Inference timing (CALCULATION, confirmed by SIMULATION for every K):**
  CYCLES = (T1+T2)(NL*IL/4 + 1 + 2^K) + 2(NL+3) = 10*2^K + 368 for IL=8
  (K=4: 528, K=8: 2928 = 108.4 us at 27 MHz, K=10: 10608). Tile load = 33 cycles (32 BSRAM words + 1),
  post-processing = 19 cycles per layer.
- **LFSR look-ahead:** each LFSR register holds the state after the NEXT stream cycle's 8 steps
  (loaded with leap8(seed) on START), so r is a flop output and the XOR network is off the comparator
  path. Bit-exactness against the golden RNG trace is checked every run (R1).
- Storage: weight RAM = 1 SDPX9B BSRAM (512x32, byte enables); INPUT (16x32) and BIAS (32x16) = 16
  RAM16SDP4 LUT-RAM cells with output registers; HIDDEN 128 FF, SCORE 16 x 20 FF (sign-extended on read),
  weight tile register 1024 FF loaded by shifting (no 32:1 demux).
- CONFIG.LOG2_L clamped at write time (read-back = effective K, A.2); BIAS read-back sign-extended,
  write bits [31:16] ignored (A.2); reserved offsets read 0 (A.2); reads while BUSY return current
  storage (A.2); widths: acc 17 b, D/B/Dp 20 b signed, Dp*2^(s+7) 34 b signed (max |.| = 327680*2^14 < 2^33).

## Checks actually performed
| Check | Command | Tool | Log | Result (quoted) |
|---|---|---|---|---|
| RTL lint, 13 configurations (each module; sc_tpu RNG_MODE 0/1/2, IL 4/16; wrapper) | `bash scripts/sim_tpu.sh` step 1 (`verilator --lint-only -Wall ...`) | Verilator 5.020 | logs/tpu/lint_rtl.log | 13 x `LINT_OK`, no %Warning |
| TB lint | step 2 (`verilator --lint-only --timing -Wno-INITIALDLY`) | Verilator 5.020 | logs/tpu/lint_tb.log | 4 x `LINT_TB_OK` |
| LFSR unit | step 3 | Icarus 12.0 | logs/tpu/tb_sc_lfsr8.log | `PASS: TC2 LEAP==8x1 70000 cycles, 0 mismatches`, `PASS: TC3 PERIOD x=65535 w=65535`, `TEST PASSED` |
| Post-proc unit | step 3 | Icarus 12.0 | logs/tpu/tb_sc_postproc.log | `INFO: vectors checked = 53328, mismatches = 0`, `TEST PASSED` |
| Lane array unit | step 3 | Icarus 12.0 | logs/tpu/tb_sc_lane_array.log | `PASS: TC1 9216 stream cycles ...`, `TEST PASSED` |
| Negative runs (-DINJECT_FAULT) x 4 | steps 3, 5 | Icarus 12.0 | logs/tpu/*_inject_fault.log | all `TEST FAILED` + non-zero exit, as required |
| System TB mode 0 | step 4 | Icarus 12.0 | logs/tpu/tb_sc_tpu_mode0.log | `INFO: golden vectors total 474 (+69 clamp re-runs), mismatching inferences 0, mismatching fields 0`, `TEST PASSED` |
| System TB mode 1 | step 4 | Icarus 12.0 | logs/tpu/tb_sc_tpu_mode1.log | `... total 506 (+101 clamp re-runs), mismatching inferences 0, mismatching fields 0`, `TEST PASSED` |
| System TB mode 2 | step 4 | Icarus 12.0 | logs/tpu/tb_sc_tpu_mode2.log | `... total 474 (+69 clamp re-runs), mismatching inferences 0, mismatching fields 0`, `TEST PASSED` |
| Init files (D12) x 3 modes | step 4b | Icarus 12.0 | logs/tpu/tb_sc_tpu_init_mode{0,1,2}.log | `PASS: D12 ...`, `TEST PASSED` |
| Whole regression | `bash scripts/sim_tpu.sh` | — | logs/tpu/sim_tpu_console.log | `SIM_TPU ALL PASSED (revision 1e853f7-dirty)`, `RC=0` |
| Sweep vectors | `.venv/bin/python tests/tpu/gen_tpu_sweep_vectors.py` | Python 3.13, golden model | logs/tpu/gen_tpu_sweep_vectors.log | 3 x 63 vectors, `reference == fast for all` |
| Synth + P&R, 10 variants x 3 seeds | `bash scripts/synth_tpu_variants.sh` (+ `VARIANTS=... `, see report) | Yosys 0.70 (YoWASP), nextpnr-0.11.1 himbaechel-gowin | logs/tpu/synth_*.log, pnr_*_s*.log | see table |

Golden vectors per mode (all 0 mismatching words): mode files 360 images K=8 s=0; corner 51 (psets 1..8,
s 0/3/7, K=4); sweep 63 (3 images x K 4..10 x s 0/3/7); mode 1 also K4 16 + K10 16. Every inference also
checks CYCLES == measured BUSY cycles == formula. Bus protocol checker: 0 errors in every run.

## Numerical findings
Synthesis / P&R (label SIMULATION = tool estimate, not hardware; GW1NR-LV9QN88PC6/I5, 27 MHz, seeds 1/2/3,
utilisation from the nextpnr "Device utilisation" block; LUT4 includes ALU positions):

| Variant | Flow | LUT4 | ALU | DFF | BSRAM | RAM16SDP4 | MUX2 | worst Fmax (MHz), 3 seeds | max util | Latency K=4/8/10 (cycles) |
|---|---|---|---|---|---|---|---|---|---|---|
| **IL8 mode 1 (rev A default)** | default | 4567 (52 %) | 1846 | 2445 (37 %) | 1 (3 %) | 16 (5 %) | 352 | 55.26 (56.52/57.04/55.26) | 52 % | 528/2928/10608 SIM |
| IL8 mode 1 | -nowidelut | 4461 (51 %) | 1846 | 2445 | 1 | 16 | 0 | **61.41** (61.41/64.54/62.16) | 51 % | same |
| IL8 mode 0 | default / -nowidelut | 4539 / 4468 | 1848 | 2445 | 1 | 16 | 403 / 0 | 54.95 / 59.44 | 52 / 51 % | same |
| IL8 mode 2 | default / -nowidelut | 4692 / 4572 | 1846 | 2669 (41 %) | 1 | 16 | 364 / 0 | 54.34 / 60.43 | 54 / 52 % | same |
| IL4 mode 1 | default / -nowidelut | 3693 / 3542 | 1146 | 1901 (29 %) | 1 | 16 | 343 / 0 | 71.34 / 65.30 | 42 / 40 % | 698/5498/20858 CALC |
| IL16 mode 1 | default / -nowidelut | 6699 / 6322 | 3206 | 3533 (54 %) | 1 | 16 | 698 / 0 | no legal placement (3/3 seeds; 1/1 seed nwl) | 77 / 73 % | 443/1643/5483 CALC |

- Fmax margin vs 27 MHz (rev A default build): +104.7 % worst seed (55.26 MHz), >= 29.7 MHz: PASS. SIMULATION, logs/tpu/pnr_il8_m1_s{1,2,3}.log.
- Every resource <= 85 % for all IL=8 and IL=4 variants (worst 54 %). PASS (TPU stand-alone; with the CPU in-context ~957 LUT4 from RTL-CPU the SoC estimate is ~5.4-5.6k LUT4 = 63-65 %, CALCULATION, to be confirmed by RTL-SOC).
- Critical path, IL8 mode 1 default (17.69 ns = 9.47 logic + 8.22 routing): sc_postproc stage 2, from the registered ACT_SHIFT s1 flop through the 34-bit `Dp << (s+7)` / `>>> K` barrel shifters and the 0..127 clip into out_hcode (reports/fpga/tpu/il8_m1_critical_path.txt).
  With -nowidelut (16.29 ns = 7.86 logic + 8.43 routing): LFSR r_w flop -> 8-bit weight comparator (ALU carry chain) -> XNOR -> popcount -> 17-bit accumulator adder -> acc flop, i.e. the SC datapath itself (reports/fpga/tpu/il8_m1_nwl_critical_path.txt).
- RNG_MODE cost at IL=8 (default flow, CALCULATION from the table): mode 0 -> mode 1: +28 LUT4, 0 DFF (rotation is wiring; the LUT delta is synthesis noise); mode 1 -> mode 2: +125 LUT4, +224 DFF (14 extra 16-bit LFSRs = 224 FF exactly).
- IL scaling (default flow): IL 4 -> 8: +874 LUT4, +544 DFF; IL 8 -> 16: +2132 LUT4, +1088 DFF; IL=16 does not fit/place on the GW1NR-9.
- Latency per inference (SIMULATION for IL=8, every K in 4..10 checked; CALCULATION for IL 4/16): K=8: IL4 5498 cycles (203.6 us), IL8 2928 (108.4 us), IL16 1643 (60.9 us) at 27 MHz.
- Simulation volume (SIMULATION, Icarus 12.0): 1454 golden inferences + 239 clamp re-runs, 0 mismatching words; 53328 post-proc vectors; 70000 LFSR cycles x 2 seeds; 9216 lane-array cycles; bus protocol errors 0; longest valid->ready 35 cycles (read stalled by a tile load), 3 cycles otherwise.

## Assumptions
- A1 Bus slave latency 2 cycles after acceptance, read stall while the controller owns the memory ports (my choice; spec leaves latency free). ASSUMPTION documented in sc_tpu.v.
- A2 Mode-1 rotation by lane index i (0..IL-1, mod 8 for IL=16), first r = low byte after the first 8 steps: same readings as SW-01a (A1/A2 of its handoff); proven equal by the RNG trace and all vectors.
- A3 HIDDEN/SCORE reset 0 and keep it until overwritten; a read during the first inference returns the current storage (A.2 wording). The earlier A.1 message "0 until the first inference completes" was implemented first with a read gate, then removed because A.2 (in the spec) says reads while BUSY return current contents. See open decision OD-1.
- A4 The weight tile register and accumulators have no reset (they are always written before use); D11 proves a mid-inference reset + re-run is bit-exact.

## Errors / deviations
- IL=16 does not place with the default synth flow (all 3 seeds: `ERROR: Unable to find legal placement for all cells, design is probably at utilisation limit`, LUT4 77 %); see -nowidelut row. IL is a synthesis-only study, rev A is IL=8.
- TB lint uses `-Wno-INITIALDLY` (BFM tasks deliberately use non-blocking assignments inside initial-block tasks, standard Icarus semantics; the TBs are not meant to run in Verilator). Under `-Wall` the TBs additionally show style-only BLKSEQ (TB counters) and UNUSEDSIGNAL (TB scratch) warnings: tb_sc_postproc 5+3, tb_sc_lane_array 0+1, tb_sc_tpu 17+14, tb_sc_lfsr8 0. RTL is -Wall clean with no waivers (only the Verilator `*unused*` naming idiom for mem_addr[1:0] and the floor-discarded bias bits).
- Icarus run time: ~7 min per 360-vector K=8 file; the whole regression takes ~35 min.
- The default-flow variants il8_m1/il8_m0/il8_m2/il4_m1/il16_m1 were synthesised before I added the `// Reqs` header lines and one comment paragraph in sc_tpu_ctrl.v (comment-only edits, no functional change); the `_nwl` variants and the final simulation regression ran on the final files.
- il16_m1_nwl: seed 1 failed placement after ~10 min; I aborted seeds 2/3 to free the shared cores (marked in logs/tpu/pnr_il16_m1_nwl_s2.log and the report).

## Open decisions (for the manager)
- OD-1 A.1 message vs A.2 text: I follow A.2 (reads while BUSY return current storage). If "SCORE/HIDDEN read 0 until the first inference completes" is really wanted, it is a 1-FF read gate (was implemented and tested, then removed).
- OD-2 Synthesis flow for RTL-SOC: `synth_gowin -nowidelut` gives a better TPU (worst-seed Fmax 61.41 vs 55.26 MHz, LUT4 4461 vs 4567, 0 MUX2 cells). Recommend using it for the SoC (RTL-CPU uses it too).
- OD-3 Latency is dominated by the tile load at small K (33 of 49 cycles per tile at K=4). Double-buffering the weight tile (+1024 FF, ~16 % of the device) would hide it (K=4: 528 -> ~200 cycles). Not done (rev A frozen).

## Next actions
- RTL-SOC: instantiate `sc_tpu` with `mem_valid & (addr[31:28]==2)`, `mem_addr[11:0]`, OR its mem_rdata into the read mux (it is 0 when not ready), pass WEIGHT_INIT/BIAS_INIT/INPUT_INIT = "sim/data/weights.hex"/"bias.hex"/"input.hex".
- Re-run `bash scripts/sim_tpu.sh` if sim/data is regenerated (vector sha256 are in the logs).
- Proposed lesson for .claude/skills/rtl-gowin-flow (I may not write .claude/): a design with LUT4 ~77 % (ALU-heavy) can fail placement in nextpnr-himbaechel-gowin after ~8-14 min per seed; and `-nowidelut` helped Fmax on the TPU too.
