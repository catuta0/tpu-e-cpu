# RTL-SOC — TPU seed update (rev B -> rev C) + SoC integration, simulation, synthesis, P&R, timing
Status: PASS
Agent: fpga-engineer   Date: 2026-11-04   Input revision: assigned 4e5c35a (rev B); final runs on ac0f0a0-dirty
(spec rev C, ARCHITECTURE.md 12, INTERFACES.json revision C, ADR-010). HEAD moved during the task (manager WIP
commits 4060bd9, ba9dfb9, ac0f0a0 included some of my files); nothing committed by me.

Scope change during the task (manager messages): rev B seeds -> rev C seeds (mode-2 tables back to the rev A
values, modes 0/1 keep 0xACE1/0xF9DE, PARAMS.version 0x03). All final results below are for **rev C**, run
against the sim/data files with header `# spec_rev C` (SW-03). Rev B was also run once (quick TPU regression,
SoC TB, one synthesis) and passed; those runs are superseded and not reported as final.

## Requirements addressed
| Req | Evidence | Result |
|---|---|---|
| TPU rev C bit-exact (REQ-TPU-005/006/013/014) | logs/tpu/tb_sc_tpu_mode{0,1,2}.log, sim_tpu_console.log | PASS: 1454 golden inferences + 239 clamp re-runs, 0 mismatching fields |
| TPU-003 PARAMS rev C | D2: 0x03000810 / 0x03010810 / 0x03020810; SoC T1 0x03020810 | PASS |
| TPU-005 seed tables | tb_sc_lfsr8 TC7 (re-derived from the spec formulas, 3 sc_rng instances), R1 RNG trace | PASS |
| SYS-003/004 SoC composition, 1 clock | soc_top.v | PASS (I) |
| SYS-005 reset synchroniser | tb_soc R1..R4: assert/release on the 2nd edge | PASS (a); **(b) deviation**: first fetch 31 cycles after rst falls (bound 8), see Errors |
| SYS-006 reset values | tb_soc R3 (led_n = 111111, uart_tx = 1), tb_soc_bfm T1 | PASS |
| SYS-007 bus protocol | tb_soc checker P1..P7 on demo + 44 CPU tests; tb_soc_bfm T10 | PASS: 0 violations, max latency 3 cycles (<= 4) |
| SYS-008 byte lanes | tb_soc_bfm T6 (SB/SH strobes), CPU tests dir_loads/dir_stores on the SoC | PASS |
| SYS-009 memory map | tb_soc_bfm T5/T6/T7 (first/last words RAM + WEIGHT, aliases) | PASS |
| SYS-010 unmapped | tb_soc_bfm T8 (0x3000_0000, 0xF000_0000 read 0 in 2 cycles, write ignored, sticky bus_err until reset), dir_mmio C5 | PASS |
| SYS-011 peripherals | tb_soc_bfm T2..T5, T9 (CYCLE diff 1004 = 1004, UART_TX ignored while busy) | PASS |
| SYS-012 UART | tb_soc U1/D5, tb_soc_bfm T9: 0x00 0x55 0xA5 0xFF decoded by a real-time 115200 receiver, every edge on k*234 clocks, frame 2340 clocks | PASS |
| SYS-013 LEDs | tb_soc_bfm T2 (0x00/0x3F/0x15/0x2A -> led_n = ~v), tb_soc D4 | PASS |
| SYS-014 / RES-005 ports + pins | soc_top ports = INTERFACES.json; logs/soc/pins.log: 10 IOs on pins 52, 3, 10, 11, 13, 14, 15, 16, 17, 18 | PASS |
| SYS-016 end-to-end demo | tb_soc D1..D7 | PASS: TOHOST = 1 at cycle 5441 (bound 200 000) |
| TIM-005 CPU-side inference time | tb_soc INFO line | PARTIAL: reported (START->RESULT read 2948 cycles), but the demo program does not write the 64 input codes and does not read CYCLE (program owned by SW) |
| RES-001..004 utilisation | reports/fpga/soc/soc_impl.md | PASS: worst 65 % (LUT4), BSRAM 5, DSP 0 |
| TIM-001 Fmax | logs/soc/pnr_nwl_s{1,2,3}.log | PASS: worst 47.46 MHz >= 29.7 MHz |
| TIM-002 sync design | Yosys `check` 0 problems, 0 latches; no async resets | PASS |
| TIM-003 async inputs | btn_rst_n 2-FF synchroniser; uart_rx unused (no logic) | PASS (I) |

## Inputs
- design/architecture/ARCHITECTURE.md sections 2-4, 4.1, 5, 7-12; management/INTERFACES.json revision C (B at task
  start); management/DECISIONS.md ADR-006..008, ADR-010; handoffs RTL-CPU.md, RTL-TPU.md.
- sim/data (SW-02/SW-03, read only): tpu_vectors_*.txt, tpu_rng_trace_mode*.txt (all `# spec_rev C`),
  weights.hex (sha256 b743fe71eb3d...), bias.hex (1d1e138fd265...), input.hex (4eeb1ae6d1c5...),
  soc_expected.json (spec_rev C, sha256 907e51c6e3b5...), soc_demo_prog.hex (bbb6912f44f0...) - all recorded
  at the end of logs/soc/tb_soc_demo.log;
  cpu_tests/ (44 tests). Vector sha256 per mode at the end of logs/tpu/tb_sc_tpu_mode<m>.log
  (mode 2: tpu_vectors_mode2.txt 8b603e07b13e...).
- code/python/sctpu/model.py (imported read-only, spec_rev="C") for the sweep vectors.

## Outputs
| Path | Content |
|---|---|
| design/rtl/soc/soc_bus.v | addr[31:28] decoder, AND-OR ready/rdata mux, unmapped responder (read 0, 1 wait state, sticky bus_err) |
| design/rtl/soc/soc_ram.v | 4 KiB BSRAM RAM, byte enables, INIT_FILE, 1 wait state, no_rw_check |
| design/rtl/soc/soc_periph.v | LED, UART_TX/STATUS (8N1, UART_DIV=234), CYCLE, TOHOST, reserved = 0, 1 wait state |
| design/rtl/soc/soc_top.v | Tang Nano 9K top: 2-FF reset sync, CPU, bus, slaves, TPU (init files), LED inversion, kept uart_rx |
| design/rtl/tpu/sc_rng.v | rev C seed tables as explicit localparams in ONE block (modes 0/1 0xACE1/0xF9DE; mode 2 formula values; IL=16 study lanes 8..15 same formula), default RNG_MODE 2, history B->C in the header |
| design/rtl/tpu/sc_tpu.v | default RNG_MODE 2, P_VERSION 0x03, header updated |
| design/rtl/tpu/sc_tpu_synth_top.v | default RNG_MODE 2 |
| tests/soc/tb_soc.v | system TB (pins only): reset checks, protocol checker, real-time UART receiver, bit-timing checker, demo D1..D7, CPU-suite C1..C8, 3 fault injections |
| tests/soc/tb_soc_bfm.v | fabric TB inside the real soc_top (CPU outputs overridden by `force`): T1..T10 |
| tests/tpu/tb_sc_lfsr8.v | LFSR_W seed 0xF9DE; TC7 rev C seed-table check (formula re-derivation, S(32768) = 0xF9DE, period) |
| tests/tpu/tb_sc_tpu.v | default RNG_MODE 2, EXP_VERSION 0x03 (single parameter) |
| tests/tpu/gen_tpu_sweep_vectors.py | spec_rev "C" passed explicitly, `# spec_rev C` header, // tolerant hex reader |
| scripts/sim_soc.sh | lint + expectation (JSON cross-checked vs vector file and file sha256) + demo + 44 CPU tests + BFM + 4 negative runs; SPEC_REV (default C) |
| scripts/synth_soc.sh | 2 flows x 3 seeds, tables, critical path, yosys check, pins, BSRAM-init check, gowin_pack |
| scripts/sim_tpu.sh | sc_rng.v added to tb_sc_lfsr8, TC7 required, `# spec_rev $SPEC_REV` guard on every vector/trace file (default C) |
| logs/soc/, logs/tpu/ | all logs below |
| reports/fpga/soc/soc_impl.md (+ soc_impl_tables.md, critical_path_{nwl,def}.txt, pnr_report_*.json) | implementation report |

sha256 (first 12 hex): soc_bus.v ba1b495f6f46, soc_periph.v 0a12847c0ae8, soc_ram.v b956a7cfae32, soc_top.v
4ab7fc5de042, sc_rng.v 68dd57e3dca7, sc_tpu.v d6bf17a9ddd1, tb_soc.v 85d1b9c5410e, tb_soc_bfm.v 71133edb9b7b,
tb_sc_lfsr8.v 75467909b241, tb_sc_tpu.v 501cbd34fcd9, sim_soc.sh be367795ff46, sim_tpu.sh b109561fbe13
(synth_soc.sh changed afterwards only in the report parser; re-checked with REPORT_ONLY=1).

## Design summary
- Bus: one master. Decoder on addr[31:28] only; slaves decode their low bits (RAM [11:2], periph [11:2], TPU
  [11:0]); bits [27:12] ignored -> every slave aliased in its 256 MiB region. RAM, peripherals and the unmapped
  responder answer in the 2nd cycle (1 wait state, `ready_q <= valid & ~ready_q` to avoid double accepts on
  back-to-back requests); TPU in the 3rd cycle (RTL-TPU latency). Writes happen once, in the accept cycle.
- UART: 9-bit shift register + bit counter + down-counter; line driven from a flop; tx_busy covers the full frame
  including the stop bit (2340 cycles). 27e6/234 = 115384.6 Bd, +0.16 % (CALCULATION).
- Debug nets (bus_err, cpu_halted, trap_cause, dbg_pc, retire, tohost) have no pins (none in INTERFACES.json);
  they are observed hierarchically by the TBs and removed by synthesis.

## Checks actually performed
| Check | Command | Tool | Log | Result (quoted) |
|---|---|---|---|---|
| SoC RTL lint (whole SoC + each SoC block, UART_DIV 240) | `bash scripts/sim_soc.sh` step 1 | Verilator 5.020 | logs/soc/lint_rtl.log | 5 x `LINT_OK`, no %Warning |
| SoC TB lint | step 2 (`--timing`, default warnings) | Verilator 5.020 | logs/soc/lint_tb.log | `LINT_TB_OK tb_soc`, `LINT_TB_OK tb_soc_bfm` |
| Demo expectation | step 3 | Python 3 | logs/soc/expected.log | `cross-check soc_expected.json == tpu_vectors_mode2.txt idx 0 (HIDDEN, SCORE, RESULT): OK`, sha256 of input/weights/bias match, `EXPECTATION_OK` |
| SoC demo | step 4 | Icarus 12.0 | logs/soc/tb_soc_demo.log | `PASS: D1 ... TOHOST = 1 ... cycle 5441`, `PASS: D2 ... RESULT ... = golden class 7`, `PASS: D3 TPU storage bit-exact ... SCORE[7] = 948`, `PASS: D4 led_n = 6'b111000`, `PASS: D5 ... 0x37 0x0a = "7\n"`, `PASS: D6 CYCLES stored at 0x0E00 = 2928 = 10*2^8+368 (formula) = TB-measured BUSY cycles 2928 = TPU CYCLES register`, `PASS: D7 bus_err = 0 ... 0 protocol violations, max latency 3 cycles`, `TEST PASSED` |
| CPU suite on the SoC | step 5 | Icarus 12.0 | logs/soc/cpu/<test>.log, cpu_suite_summary.log | `# CPU tests on the SoC: 44 / 44 PASS`; dir_mmio: C1..C8 PASS (`C5 bus_err = 1`, `C6 led_n = 6'b010101 = ~LED (LED 42)`) |
| Fabric BFM TB | step 6 | Icarus 12.0 | logs/soc/tb_soc_bfm.log | T1..T10 PASS (`PARAMS = 0x03020810`), `TEST PASSED` |
| Negative runs (4) | step 7 | Icarus 12.0 | logs/soc/neg_*.log | all `TEST FAILED` + non-zero exit: INJECT_FAULT (`FAIL: D3 SCORE[0] = 0xfffffd48 (-696) expected 0xfffffd49`), UART_DIV=240 (`FAIL: tx_busy lasted 2400 cycles`), INJECT_PROTO_FAULT (`PROTOCOL VIOLATION #1 ... P2`), BFM LED polarity |
| Whole SoC regression | `bash scripts/sim_soc.sh` | — | logs/soc/sim_soc_console.log | `SIM_SOC ALL PASSED (revision ac0f0a0-dirty)` |
| TPU regression rev C, full | `bash scripts/sim_tpu.sh` | Verilator 5.020, Icarus 12.0 | logs/tpu/sim_tpu_console.log | 13 x LINT_OK; `PASS: TC7 SEEDS rev C ...`; `spec_rev guard: all vector/trace files of mode m carry '# spec_rev C'` (m = 0,1,2); mode 0 `golden vectors total 474 (+69 clamp re-runs), mismatching inferences 0, mismatching fields 0`; mode 1 `total 506 (+101 ...) ... 0, ... 0`; mode 2 `total 474 (+69 ...) ... 0, ... 0`; D12 x3 PASS; negative run `TEST FAILED`; `SIM_TPU ALL PASSED (revision ac0f0a0-dirty)` |
| Sweep vectors rev C | `.venv/bin/python tests/tpu/gen_tpu_sweep_vectors.py` | Python, golden model | logs/tpu/gen_tpu_sweep_vectors.log | 3 x 63 vectors `reference == fast for all` |
| CPU regression (unchanged CPU RTL) | `bash scripts/sim_cpu.sh` | Icarus 12.0 | logs/cpu/sim_cpu_summary.log | `# runs: 176 / 176 PASS`, `SIM_CPU: ALL PASSED` (revision ac0f0a0-dirty) |
| Synthesis + P&R, 2 flows x 3 seeds | `bash scripts/synth_soc.sh` | Yosys 0.70, nextpnr-0.11.1, Apicula 0.32 | logs/soc/synth_{nwl,def}.log, pnr_{nwl,def}_s{1,2,3}.log | `SYNTH_SOC: PASS (worst nwl seed 2, 47.46 MHz)`; all `PNR_EXIT=0` |
| Yosys check | in synth script | Yosys 0.70 | logs/soc/synth_nwl.log | `Found and reported 0 problems.` (4 x per flow), 0 `Latch inferred` |
| Pins | scripts/pnr_pin_report.py | Apicula chipdb | logs/soc/pins.log | 10 IOs: clk 52, btn_rst_n 3, led_n 10/11/13/14/15/16, uart_tx 17, uart_rx 18 |
| BSRAM init in routed netlist | synth script | Python | logs/soc/bsram_init.log | `BSRAM cells 5, with non-zero init 3` (RAM 2 x SP, weight SDP) |
| Bitstream (never programmed) | gowin_pack -d GW1N-9C | Apicula 0.32 | logs/soc/pack.log | `PACK_EXIT=0`, 3556680 bytes, sha256 152d3c6dada6338e0b98a8fc19557ec95f4e40479e4f264411c72caa85b76258 |

## Numerical findings
| Name | Value | Unit | Label | Evidence |
|---|---|---|---|---|
| TPU golden inferences rev C, mismatching fields | 1454 (+239 clamp re-runs), 0 | count | SIMULATION | logs/tpu/tb_sc_tpu_mode{0,1,2}.log |
| SoC demo RESULT / LED / UART | 7 / led_n 111000 / "7\n" | — | SIMULATION | logs/soc/tb_soc_demo.log |
| SoC demo SCORE[0..9] (TPU storage, = golden) | -696 -320 -1020 -166 -268 -618 -1442 948 238 528 | Dp | SIMULATION | expected.log + D3 |
| End-to-end reset release -> TOHOST write | 5441 | cycles (201.5 us at 27 MHz) | SIMULATION | tb_soc_demo.log INFO |
| START store -> RESULT read (CPU view) | 2948 | cycles | SIMULATION | tb_soc_demo.log (START at cycle 62, RESULT at 3010) |
| TPU BUSY (= CYCLES register = RAM[0x0E00]) | 2928 = 10*2^8+368 | cycles | SIMULATION + CALCULATION | D6 |
| Last UART byte decoded | ~7698 | cycles after reset release | SIMULATION | tb_soc_demo.log |
| Instructions retired up to TOHOST | 981 | instr | SIMULATION | tb_soc_demo.log |
| Bus transactions demo (RAM / PERIPH / TPU / unmapped) | 1722 / 152 / 177 / 0, max latency 2 / 2 / 3 / - | count, cycles | SIMULATION | tb_soc_demo.log |
| Reset synchroniser latency (assert / release / power-up) | 2 / 2 / 2 | rising edges | SIMULATION | tb_soc R1, R2, R4 |
| First fetch after rst falls | 31 | cycles (CPU CLEAR = 32) | SIMULATION | tb_soc R5 |
| UART baud error | +0.16 (rate), bit time 234 clocks exactly, frame 2340 | %, clocks | CALCULATION + SIMULATION | soc_periph.v header, U1/T9 |
| LUT4 (nwl / def) | 5628 (65 %) / 6130 (70 %) of 8640 | cells | SIMULATION (P&R) | pnr_*_s1.log |
| ALU / DFF / BSRAM / RAM16SDP4 / IOB / DSP (nwl) | 1976 (30 %) / 2803 (43 %) / 5 (19 %) / 16 (5 %) / 10 (3 %) / 0 | cells | SIMULATION | pnr_nwl_s*.log |
| MUX2_LUT5..8 (def flow) | 710 / 138 / 49 / 18 (nwl: 0) | cells | SIMULATION | pnr_def_s*.log |
| Fmax nwl seeds 1/2/3 | 51.98 / 47.46 / 51.21 | MHz | SIMULATION (STA) | pnr_nwl_s{1,2,3}.log |
| Fmax def seeds 1/2/3 | 46.47 / 45.79 / 42.80 | MHz | SIMULATION (STA) | pnr_def_s{1,2,3}.log |
| Worst-seed margin (nwl) vs 27 / 29.7 MHz | +75.8 / +59.8 | % | CALCULATION | 47.46/27-1, 47.46/29.7-1 |
| Critical path (nwl seed 2) | 21.07 ns = 8.83 logic + 12.24 routing: u_cpu.ir -> decoder/FSM -> ALU carry chain -> pc | ns | SIMULATION | reports/fpga/soc/critical_path_nwl.txt |
| Bitstream size | 3556680 | bytes | MEASUREMENT of the file (not hardware) | logs/soc/pack.log |

## Assumptions
- A1 Peripheral and unmapped slaves: 1 wait state (registered response), like the RAM; chosen for timing.
- A2 Peripheral block decodes addr[11:2]; offsets 0x14..0xFFC are reserved (read 0, no bus_err): bus_err is
  set only for addr[31:28] not in {0,1,2}, consistent with "decoding uses addr[31:28]" (ARCHITECTURE.md 4).
- A3 CYCLE = rising edges since rst release (0 in the first cycle after reset).
- A4 TOHOST honours byte strobes; UART_TX needs the byte-0 strobe; LED needs the byte-0 strobe.
- A5 uart_rx unused, kept as a pin with `(* keep *)` (no synchroniser because nothing uses it).
- A6 IL=16 study lanes 8..15 (not spec) use the rev C formula continued (manager instruction).
- A7 Expected demo values come from sim/data/soc_expected.json (SW-03, rev C) and are cross-checked against the
  test-position-0 line of tpu_vectors_mode2.txt (fallback to that line if the JSON is absent).
- A8 SCORE/HIDDEN checked by hierarchical peek into sc_tpu storage (manager-approved); RESULT checked both on the
  bus (CPU load data) and in the TPU register.

## Errors / deviations
- **REQ-SYS-005 (b)**: acceptance says the first mem_valid after reset release occurs within 8 cycles; measured
  31 cycles because rv32i_core clears its BSRAM register file in a 32-cycle CLEAR state (RTL-CPU design, not
  modified here). The first request is the correct fetch of 0x0000_0000. Escalated (open decision OD-1).
- **REQ-TIM-005**: partial (see table) - the official demo program neither writes the 64 input codes nor reads
  CYCLE; the TB measures START->RESULT (2948 cycles) instead.
- My first edit of scripts/sim_tpu.sh was made while a QUICK run of that same script was executing; bash reads
  scripts incrementally, so that run died at its last step with a syntax error (logs of steps 1-4 were complete
  and passing). Not a design issue; the final full run was started after all edits and passed.
- The rev B intermediate results (SoC demo with SCORE[7] = 1304, synthesis worst 45.69 MHz, quick TPU regression)
  were overwritten by the rev C runs; only rev C is claimed.
- logs/soc/synth_versions.log was rewritten by the REPORT_ONLY re-run (08:18); the P&R logs themselves carry
  `# input revision: ac0f0a0-dirty`.
- TB -Wall (not required) shows style-only BLKSEQ / UNUSEDSIGNAL warnings in tb_soc.v / tb_soc_bfm.v (TB
  counters updated with blocking assignments); the TBs are lint-clean with the default warning set. RTL has no
  lint waivers (only the Verilator `*unused*` naming idiom for intentionally undecoded address bits and debug nets).
- Gate-level simulation: NOT RUN (no behavioural Gowin BSRAM models). Hardware: NOT RUN (never programmed).
- No CPU RTL edits were needed.

## Open decisions (for the manager)
- OD-1 REQ-SYS-005 (b) "first fetch within 8 cycles" conflicts with the CPU's 32-cycle register-file CLEAR.
  Options: relax the bound to <= 40 cycles (recommended; the CLEAR is what makes the BSRAM regfile cost 0 LUT/FF),
  or change the CPU (register-file reset by other means costs ~1 kbit of FFs or a valid-bit scheme).
- OD-2 REQ-TIM-005: if the CPU-driven "write 64 inputs + START + poll + RESULT" time is wanted, SW would need a
  second demo program (e.g. soc_demo_load_prog.hex); tb_soc can measure it with no change (+MODE=demo).
- OD-3 Keep `synth_gowin -nowidelut` as the release flow (502 fewer LUT4, 0 MUX2, +4.7 MHz worst seed).

## Next actions
- Reviewer (REV-01): `bash scripts/sim_soc.sh` (~2 min), `bash scripts/sim_tpu.sh` (~45 min),
  `bash scripts/sim_cpu.sh` (~10 s), `bash scripts/synth_soc.sh` (~45 min, single thread).
- If seeds change again: edit only the SEED TABLES block of design/rtl/tpu/sc_rng.v, P_VERSION in sc_tpu.v,
  EXP_VERSION in tests/tpu/tb_sc_tpu.v, TC7 in tests/tpu/tb_sc_lfsr8.v, then SPEC_REV=<rev> for sim_tpu.sh /
  sim_soc.sh and re-run gen_tpu_sweep_vectors.py (SPEC_REV constant).
- Proposed lessons for .claude/skills/rtl-gowin-flow (I do not write .claude/): (1) never edit a bash script while
  an instance of it runs (bash reads it incrementally); (2) Yosys prints "Found and reported 0 problems." with a
  capital F - grep -i; (3) a `force` on the CPU's output nets inside the real top gives a BFM fabric TB without
  duplicating the wiring; (4) the .fs grows to ~3.56 MB when BSRAM init data is present; (5) SoC P&R takes
  ~4-5 min per seed single-threaded at 65 % LUT4.
