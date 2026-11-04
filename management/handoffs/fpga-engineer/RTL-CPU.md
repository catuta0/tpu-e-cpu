# RTL-CPU — RV32I multi-cycle CPU core + testbench + synthesis/P&R
Status: PASS
Agent: fpga-engineer   Date: 2026-11-04T03:34Z   Input revision: assigned 199a3dc; work done on tree 494448a-dirty (HEAD moved while I worked: other agents' commits). Official suite from c2601fa (unchanged since).

## Requirements addressed
- ARCHITECTURE.md §2 (single clock, synchronous active-high `rst`), §3 (native valid/ready bus), §6 (RV32I + FENCE-as-NOP, traps -> halt, reset PC 0, x0 hard-wired, registers reset to 0, debug ports).
- INTERFACES.json `bus` and `cpu` (trap codes 0..6, debug ports `halted`, `trap_cause[3:0]`, `dbg_pc[31:0]`, `retire`).
- Manager clarification rev A.1 / ADR-006: a misaligned jump/branch target traps on the jump/branch itself (halt PC = its address, rd not written, nothing fetched from the target); strict decoding (CSR/SYSTEM other than ECALL/EBREAK, unknown funct7/funct3, FENCE.I, 0x00000000 and 0xFFFFFFFF are illegal). Implemented exactly like this. dir_mmio runs in the core TB because the TB models LED, UART_STATUS and the unmapped path (LED and TOHOST reset to 0).

## Inputs
- design/architecture/ARCHITECTURE.md §2, 3, 6 (rev A + A.1 clarification); management/INTERFACES.json (`bus`, `cpu`).
- sim/data/cpu_tests/ (44 tests: index.txt, .hex/.sig/.meta.json/.lst), committed in c2601fa by SW-01b. Used read-only; sha256 of the .hex/.sig is re-checked against each meta file by scripts/cpu_meta_to_tb.py.
- code/python/rv32/ (gen_cpu_tests.py, iss.py): read only. Before the official suite was published I ran the generator once into a private gitignored directory (sim/cpu/build/pre_tests, with PYTHONDONTWRITEBYTECODE=1, nothing in code/python modified). Its .hex/.sig files are byte-identical to the official ones (same sha256 over all files), so I wrote no hand-assembled local tests (tests/cpu/local not needed).

## Outputs
| Path | Content |
|---|---|
| design/rtl/cpu/rv32i_core.v | FSM + datapath + bus + debug, ASCII FSM diagram, CPI table |
| design/rtl/cpu/rv32i_decode.v | combinational decoder: classes, immediates, strict legality, ALU op |
| design/rtl/cpu/rv32i_alu.v | single 33-bit add/sub chain, compare flags, logic ops, no shifter |
| design/rtl/cpu/rv32i_regfile.v | 32x32 regfile, 2 x SDPX9B BSRAM, 1-cycle synchronous read |
| tests/cpu/tb_rv32i_core.v | self-checking TB: 4 KiB RAM, peripherals, TOHOST, wait states/random stalls, protocol checker |
| tests/cpu/cpu_synth_top.v | synthesis wrapper: core + 4 KiB BSRAM RAM (1 wait state) + LED/XOR outputs |
| scripts/sim_cpu.sh | lint + 44 tests x 4 bus configs + 2 negative checks + summary |
| scripts/cpu_meta_to_tb.py | meta.json -> $readmemh companion file (.tbmeta.hex) |
| scripts/synth_cpu.sh | wrapper lint, synth (in-context + out-of-context), P&R seeds 1..3, pins, pack, report |
| logs/cpu/ | lint.log, sim_cpu_summary.log, runs/<test>__<cfg>.log (176), neg_*.log, synth_*.log, pnr_s{1,2,3}.log, pins.log, pack.log |
| reports/fpga/cpu/cpu_synth_pnr.txt, pnr_report_s{1,2,3}.json | utilisation and Fmax report |
| .claude/skills/rtl-gowin-flow/SKILL.md | 6 new lessons appended (lock taken and released) |

sha256: rv32i_core.v 58375019…, rv32i_decode.v 99d98f03…, rv32i_alu.v 4c9278e8…, rv32i_regfile.v 4091a254…, tb_rv32i_core.v 431a4f53…, cpu_synth_top.v b350a99e…, sim_cpu.sh 5acea509…, synth_cpu.sh 4a97bc7e…, cpu_meta_to_tb.py d376228e….

## Micro-architecture summary (details in the RTL headers)
- States: CLEAR (32 cycles after reset, zeroes x0..x31 in the BSRAM; ir[11:7] is the counter) -> FETCH -> DECODE (regfile read issued; ALU computes pc+imm or 0+imm into alu_q; ECALL/EBREAK/illegal -> HALT) -> EXECUTE (ALU on operands; branch resolved; load/store address and alignment check; shift operand loaded) -> [SHIFT] / [MEM] -> WB -> FETCH; HALT is terminal.
- CPI at 0 wait states (CALCULATION from the FSM): LUI/AUIPC/JAL/FENCE 3, branch 3, OP/OP-IMM/JALR 4, store 4, load 5, shift by n: 4 + floor(n/4) + (n mod 4) (4..14). Add the slave wait states of each access.
- Register file: BSRAM (2 x SDPX9B, one copy per read port). 0 LUT and 0 DFF for the 1 kbit of state. Read latency 1 clock, output held between DECODE edges (clock enable), so rs2 stays stable as store data. Reset-to-zero is done by the CLEAR state, so the first fetch comes 32 cycles after reset.
- Bus: mem_addr = pc (FETCH) or alu_q (MEM); byte and halfword accesses carry the true byte address. Store data is replicated to all lanes (SB x4, SH x2), with wstrb SB 0001<<a, SH 0011/1100, SW 1111. Load data is extracted by addr[1:0] and sign/zero extended. Misaligned loads and stores are detected in EXECUTE and never reach the bus. JALR clears bit 0, then a set bit 1 traps (cause 4) in WB without writing rd. A taken branch with a misaligned target traps in EXECUTE; a not-taken one does not.
- Area decisions: BSRAM regfile; one adder; branch target computed in DECODE so the compare reuses the adder; iterative 4/1-bit shifter instead of a barrel shifter (the barrel version measured ~283 LUT + 164 MUX2 for the shifter alone, and ~1000 LUT/MUX cells for that ALU standalone).
- `retire` is a registered pulse in the cycle after completion. Trapping instructions (including ECALL/EBREAK) do not retire, and dbg_pc keeps the trapping PC. This matches the ISS.

## Checks actually performed
| Check | Command | Tool | Log | Result (quoted) |
|---|---|---|---|---|
| RTL lint | `verilator --lint-only -Wall <4 RTL files> --top-module rv32i_core` | Verilator 5.020 | logs/cpu/lint.log | `LINT_RTL_EXIT=0`, 0 warnings |
| TB lint | `verilator --lint-only -Wall --timing <RTL> tests/cpu/tb_rv32i_core.v` | Verilator 5.020 | logs/cpu/lint.log | `LINT_TB_EXIT=0`, 0 warnings |
| Wrapper lint | `verilator --lint-only -Wall <RTL> tests/cpu/cpu_synth_top.v` | Verilator 5.020 | logs/cpu/synth_top_lint.log | `LINT_TOP_EXIT=0` |
| Regression | `bash scripts/sim_cpu.sh` (44 tests x {ws0, ws1, ws3, rand}) | Icarus 12.0 | logs/cpu/sim_cpu_summary.log | `# runs: 176 / 176 PASS`, `SIM_CPU: ALL PASSED`; every run `viol=0` |
| Negative: signature | same TB with -DINJECT_SIG_FAULT on dir_alu_reg | Icarus 12.0 | logs/cpu/neg_sigfault.log | `TEST FAILED (1 failing checks)`, `VVP_EXIT=1` |
| Negative: protocol | -DINJECT_PROTO_FAULT (checker sees addr^4 while waiting), ws1 | Icarus 12.0 | logs/cpu/neg_protofault.log | `PROTOCOL VIOLATION #1 ... request changed while waiting for mem_ready`, `TEST FAILED`, `VVP_EXIT=1` |
| Synthesis | `bash scripts/synth_cpu.sh` (synth_gowin -nowidelut) | Yosys 0.70 (YoWASP) | logs/cpu/synth_top.log, synth_core_ooc.log | `End of script`, BSRAM mapped (2 SDPX9B regfile + 2 SPX9 RAM) |
| P&R seeds 1..3 | nextpnr-himbaechel-gowin, GW1NR-LV9QN88PC6/I5, GW1N-9C, --freq 27, --threads 1, no --timing-allow-fail | nextpnr-0.11.1 | logs/cpu/pnr_s{1,2,3}.log | `62.46 MHz (PASS at 27.00 MHz)`, `53.26 MHz (PASS ...)`, `55.74 MHz (PASS ...)` |
| Pins | scripts/pnr_pin_report.py | Apicula 0.32 chipdb | logs/cpu/pins.log | clk pin 52, btn_rst_n pin 3, led_n[0..5] pins 10..16; 8 IOs |
| Bitstream (route proof only, never programmed) | gowin_pack -d GW1N-9C | Apicula 0.32 | logs/cpu/pack.log | `PACK_EXIT=0` |

Per-test results (logs/cpu/sim_cpu_summary.log): all 44 PASS in all 4 configs. That is 11 directed (dir_lui_auipc, dir_alu_imm, dir_alu_reg, dir_shifts, dir_branches, dir_jumps, dir_loads, dir_stores, dir_x0, dir_fence_nop, dir_mmio), 20 random (rand_00..rand_19) and 13 trap tests (ecall, ebreak, illegal zero/ones/csr/funct7, misaligned lw/lh/sh/sw/jalr/jal/branch). Each run compares the 32-word signature, stop kind, trap cause, halt or TOHOST-store PC, instret, TOHOST value, bus_err, LED and UART bytes, and checks for zero protocol violations.

Protocol checker rules (tests/cpu/tb_rv32i_core.v): P1 request (valid/instr/addr/wdata/wstrb) stable while valid && !ready; P2 no ready without valid; P3 no X/Z; P4 fetch aligned with wstrb=0; P5 a data access only from a load/store, naturally aligned for its size (so no misaligned access reaches the bus), exact strobe pattern; P6 at most one data access per instruction; P7 no request while halted. Result: 0 violations in 176 runs.

## Numerical findings
| Name | Value | Unit | Label | Evidence |
|---|---|---|---|---|
| Official CPU tests passing | 44/44 (176/176 runs) | tests | SIMULATION | logs/cpu/sim_cpu_summary.log |
| Protocol violations | 0 | count | SIMULATION | every RESULT line `viol=0` |
| Aggregate CPI, 0 wait states | 4.231 (28206 cycles / 6667 instr) | cycles/instr | SIMULATION | sim_cpu_summary.log (cycles from first fetch to the stop point) |
| Per-test CPI, 0 wait states | 3.72 (dir_branches) .. 5.11 (dir_shifts); random tests 4.1..4.5 | cycles/instr | SIMULATION | sim_cpu_summary.log |
| Aggregate CPI, 1 wait state (BSRAM-like slave) | 5.593 (37287/6667) | cycles/instr | SIMULATION | logs/cpu/runs/*__ws1.log RESULT lines |
| Aggregate CPI, 3 wait states / random 0..7 stalls | 8.317 / 9.013 | cycles/instr | SIMULATION | runs/*__ws3.log, *__rand.log |
| Fmax, worst of 3 seeds (cpu_synth_top) | 53.26 | MHz | SIMULATION (nextpnr static timing) | logs/cpu/pnr_s2.log |
| Fmax seeds 1/2/3 | 62.46 / 53.26 / 55.74 | MHz | SIMULATION (STA) | pnr_s{1,2,3}.log |
| Margin vs 27 MHz / vs 29.7 MHz acceptance | +97 % / +79 % | % | CALCULATION (53.26/27-1, 53.26/29.7-1) | — |
| Critical path (seed 2) | 18.77 ns (9.66 logic + 9.11 routing): ir -> decoder -> FSM next state | ns | SIMULATION (STA) | logs/cpu/pnr_s2.log |
| In-context utilisation (core + 4 KiB RAM + wrapper), nextpnr | LUT4 957/8640 (11 %, includes 80 ALU), ALU 80, DFF 126/6480, BSRAM 4/26, RAM16SDP4 0, MUX2_LUT5 0, DSP 0, IOB 8 | cells | SIMULATION (P&R report) | logs/cpu/pnr_s1.log |
| Core only, out-of-context (synth_gowin -nowidelut -noiopads, not placed) | LUT 831 (LUT2 133, LUT3 242, LUT4 456), ALU 74, DFF 111, BSRAM 2 (SDPX9B), RAM16 0, MUX2 0 | cells | SIMULATION (Yosys stat) | logs/cpu/synth_core_ooc.log |
| Core only, default wide-LUT mapping (reference, not chosen) | LUT 1103 + MUX2_LUT5..8 473, ALU 74 | cells | SIMULATION (Yosys stat) | logs/cpu/synth_core_ooc_widelut.log |
| Register file cost | 2 SDPX9B, 0 LUT, 0 DFF | cells | SIMULATION (Yosys stat) | regfile trial synthesis (no_rw_check) |
| Reset-to-first-fetch latency | 32 (CLEAR) | cycles | CALCULATION (FSM) | rv32i_core.v header |

## Assumptions
- ECALL/EBREAK and every other trap do not retire; dbg_pc = trapping PC (same as the ISS and ADR-006).
- FENCE (funct3 000) is a NOP regardless of its other fields; FENCE.I is illegal (same as the ISS).
- In the TB, the SC-TPU window (0x2xxx_xxxx) reads 0 and ignores writes (no CPU test uses it), and CYCLE returns the TB cycle counter (no test reads it).
- "0 wait states" means mem_ready in the first mem_valid cycle (combinational slave). A registered BSRAM slave as in the SoC gives 1 wait state (CPI 5.59 measured).

## Errors / deviations
- Lint waiver (targeted, TB only): `/* verilator lint_off BLKSEQ */` around task `viol` in tests/cpu/tb_rv32i_core.v. The TB violation counter can be incremented several times per edge, so it needs a blocking update; it is benign. The RTL has no lint pragmas. The unused LSB of the carry-in trick is collected in `alu_unused` (matches the linter's default unused-regexp).
- The shared-CST "Cell btn_s2_n/uart_tx/uart_rx/psram not found" Infos in the P&R logs are expected; the wrapper has no such ports.
- Gate-level (post-synthesis) simulation: NOT RUN. The Gowin BSRAM primitives in yowasp-yosys (cells_xtra_gw1n.v SDPX9B/SPX9) are black-box stubs with no behaviour. I inspected the mapped instances instead: READ_MODE 0 (bypass = 1-cycle latency), CEB = read enable, read address ADB[9:5] = ir[19:15], write enables on ADA[3:0].
- First design used a barrel shifter (in-context 1212 LUT4 + 463 MUX2 cells, Fmax 52 MHz). I replaced it with the iterative shifter for area. All regression results above are for the final design.

## Open decisions (for the manager)
- Synthesis flow: `synth_gowin -nowidelut` was ~25 % smaller in LUTs here, with no MUX2 cells and similar Fmax. Recommend trying it for RTL-SOC and RTL-TPU too.
- Shift latency (up to 10 extra cycles) is acceptable for an orchestrating CPU (CPI is reported, not required). A barrel shifter would cost ~450 LUT/MUX cells more.

## Next actions
- RTL-SOC: instantiate `rv32i_core` (ports exactly as in INTERFACES.json `bus` + debug). The SoC RAM can reuse the BSRAM pattern of tests/cpu/cpu_synth_top.v (byte enables, `no_rw_check`, registered ready = 1 wait state). Keep `rst` synchronous (CLEAR runs 32 cycles after every reset).
- Re-run `bash scripts/sim_cpu.sh` if SW-01b regenerates the suite. The meta sha256 checks detect stale companion files.
- Reviewer: independent re-run of `bash scripts/sim_cpu.sh` and `bash scripts/synth_cpu.sh` (about 7 s and 35 s).
