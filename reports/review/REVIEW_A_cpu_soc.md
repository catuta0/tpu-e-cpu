# REVIEW_A — Independent review of the CPU, bus, SoC and board integration (task REV-01a)

Reviewer: independent-reviewer · Date: 2026-11-04 · Status of the review: **PARTIAL**: all planned checks were run; 4 MAJOR and 4 MINOR findings remain open for the manager.

**Revisions.** The review started at `fdeeab9`. During the review HEAD moved to `99ee941` and then to `7e978be`.
`git diff fdeeab9 7e978be -- design tests code sim scripts/sim_*.sh scripts/synth_*.sh` is empty, so every
design, test and stimulus input is identical at all three revisions. All re-runs below were done at
`99ee941` (`git status --porcelain -- design tests code sim` empty, i.e. clean). Input sha256 values are in
`reports/review/build/REV-01a/sha256_inputs.txt`.

**Independence.** I did not read `management/handoffs/`, `PROJECT_STATE.md`, `GATES.md` or `TASK_BOARD.md`.
I modified no design, test or code file. Every reviewer artefact is under `reports/review/build/REV-01a/`
(scripts in `scripts/`, mutants in `mut/<id>/`, hand tests in `hand/`, P&R re-run in `pnr/`).

**Tools.** Icarus Verilog 12.0, Verilator 5.020, Yosys 0.70 (YoWASP), nextpnr-0.11.1 himbaechel-gowin (YoWASP), Python 3.13 (.venv).

**Labels.** Every count, cycle and frequency below is SIMULATION: an RTL simulation, or the STA estimate of
the synthesis and P&R tools. None is a MEASUREMENT. Synthesis and P&R passing is not hardware validation.

## 1. Commands actually run (reviewer re-runs)

| # | Command (from repo root) | Result (decisive line, log) |
|---|---|---|
| 1 | `reports/review/build/REV-01a/scripts/run_cpu_suite.sh .../cpu/baseline "ws0 ws1 ws3 rand" design/rtl/cpu/*.v` (copy of scripts/sim_cpu.sh steps 2-4) | `RUNS 176/176 PASS` (44 tests x 4 bus configs), logs `cpu/baseline/runs/` |
| 2 | `verilator --lint-only -Wall` soc_top (CPU+TPU+SoC) and rv32i_core | `LINT_SOC_EXIT=0`, `LINT_CPU_EXIT=0`, no %Warning (`lint.log`) |
| 3 | `scripts/run_soc.sh .../soc/baseline design/rtl/soc design/rtl/cpu dir_mmio dir_stores rand_00 trap_misaligned_sw` (copy of scripts/sim_soc.sh steps 3-6) | `demo=PASS bfm=PASS` + 4 CPU tests PASS; demo: RESULT 7, `led_n = 6'b111000`, UART "7\n", TOHOST at cycle 5441, CYCLES 2928 (`soc/baseline/demo.log`) |
| 4 | `python code/python/rv32/gen_soc_demo.py --out <rev>/regen/...`; `gen_cpu_tests.py --out <rev>/regen/cpu_tests --summary ...` | demo .hex byte-identical to `sim/data/soc_demo_prog.hex`; all 44 `.hex`/`.sig` byte-identical (`regen/`) |
| 5 | `scripts/hand_tests.py` (reviewer encoder from the RV32I encoding tables, not `asm.py`) + `scripts/run_hand.sh` | ISS agrees with all hand values; RTL `HAND RUNS 64/64 PASS` (16 programs x 4 bus configs) (`hand/`) |
| 6 | `scripts/mutate_cpu.py` (30 CPU mutants on copies, full 176-run suite each) | 21 KILLED, **9 SURVIVED** (`mut/cpu_mutation_results.txt`) |
| 7 | `scripts/mutate_soc.py` (18 SoC mutants: demo + BFM + 4 CPU tests on the SoC) | 17 KILLED, **1 SURVIVED** (`mut/soc_mutation_results.txt`) |
| 8 | `scripts/rerun_pnr.sh`: `synth_gowin -nowidelut` + nextpnr seeds 1/2/3, `--freq 27 --threads 1` | post-route Fmax 51.98 / 47.46 / 51.21 MHz, `PNR_EXIT=0` x3, LUT4 5628/8640, DFF 2803/6480 (`pnr/`) |
| 9 | `curl https://raw.githubusercontent.com/YosysHQ/apicula/master/examples/tangnano9k.cst` | fetched, `ext/apicula_tangnano9k.cst` |

## 2. What was checked, and the result

### 2.1 RV32I semantics (inspection of design/rtl/cpu against RISC-V Unprivileged ISA ch. 2)
Every item below was checked by inspection, and each line names a mutant or hand test that confirms it:
- **Immediates, bit by bit** (`rv32i_decode.v:141-152`): I = {20{ir31}, ir[31:20]}, S = {20{ir31}, ir[31:25], ir[11:7]},
  B = {19{ir31}, ir31, ir7, ir[30:25], ir[11:8], 0}, U = {ir[31:12], 0}, J = {11{ir31}, ir31, ir[19:12], ir20, ir[30:21], 0}.
  These are correct, and the widths add up to 32 for every format.
- **SRA/SRAI** fill with `ir[30] & alu_q[31]` (`rv32i_core.v:402`), and the amount is `alu_b[4:0]`, i.e. rs2[4:0] or shamt (`:398`). Correct; killed by mutants C01, C02 and C26.
- **SLT and SLTU** (`rv32i_alu.v:93-97`): ltu = NOT carry-out of a-b; lt is corrected with the sign bits. SLTIU compares the sign-extended immediate as unsigned. Correct (C09, C25 killed).
- **Branches** (`rv32i_core.v:325-326`): BEQ/BNE/BLT/BGE/BLTU/BGEU map correctly, and the target is pc of the branch + B-imm. A not-taken branch never traps. Correct (C04, C16 killed).
- **JALR** (`rv32i_core.v:527`, `:275`): the target is rs1+imm, bit 0 is dropped, and the instruction traps (cause 4) when bit 1 is set. rd = rs1 is handled, because the target is already in alu_q before WB. Correct (C03 killed).
- **Load extension** (`:379-388`): LB and LH sign-extend; LBU, LHU and LW do not. Correct (C07, C08, C28 killed).
- **Store strobes** (SB 0001<<a, SH 0011/1100, SW 1111) and replicated data lanes (`:343-364`). Correct (C05 killed).
- **AUIPC** (pc of the AUIPC instruction + U-imm) and **LUI** (0 + U-imm). Correct (C20 killed).
- **x0**: never written in WB, and cleared in CLEAR. Correct (C10 killed).
- **Misalignment** (`:336-337`): a halfword traps on ea[0]=1, which **includes byte offset 3**; a word traps on ea[1:0]≠0. The check happens in EXECUTE, so a misaligned access never reaches the bus (protocol rule P5 is clean in every run). The RTL is correct; the hand tests below confirm it.
- **Trap codes** 1..6 match INTERFACES.json `cpu.traps`. The halt PC is the address of the trapping instruction, and a trap does not retire.
- **Strict decoding**: FENCE.I, CSR instructions, shift-immediates with imm[11:5]≠0/0x20, JALR funct3≠0, BRANCH funct3 010/011, LOAD/STORE funct3 011, and ECALL with rs1≠0 are all illegal. The RTL is correct, confirmed by hand tests.

### 2.2 The ISS as an oracle: could a shared misunderstanding make the RTL and the ISS wrong in the same way?
- The directed tests carry **hand-derived expectations** in `gen_cpu_tests.py` (`expect=` dicts), checked against the ISS. They are independent of the ISS. The random tests rely on the ISS alone.
- I wrote my own encoder (`hand_tests.py`, from the spec field layouts) and derived 15 results by hand (program `hand_h1`, CALCULATION):
  1. SRAI 0x80000000 by 4 = 0xF8000000
  2. SRA 0x80000010 by rs2 = 36, which uses 36&31 = 4 → 0xF8000001
  3. SLT -1 < 1 → 1
  4. SLTU 0xFFFFFFFF <u 1 → 0
  5. SLTIU 0 <u imm -1 → 1
  6. ADDI imm 0x800 → 0xFFFFF800
  7. AUIPC 0xFFFFF at 0x2C → 0xFFFFF02C
  8. SW 0, then SH 0x1234 at 0x802, then SB 0x80 at 0x801 → LW = 0x12348000
  9. LB at 0x801 → 0xFFFFFF80
  10. LH at 0x800 → 0xFFFF8000 (LHU at 0x802 → 0x1234; LBU at 0x801 → 0x80)
  11. JALR 13(0x64) → target 0x70, link 0x6C
  12. BEQ +0x804, which sets B-imm bit 11 → 0x878
  13. JAL +0x1008, which sets J-imm bit 12 and lands at the RAM alias 0x1884; link 0x880
  14. AUIPC at the alias → 0x1884
  15. A backward BLTU loop leaves x30 = 3

  Expected instret = 77 and TOHOST PC = 0x1920.
  **Result:** the ISS matches all 32 signature words, the instret and the stop PC (`hand/iss_vs_hand.log`). The RTL passes `hand_h1` in all 4 bus configurations.
- 15 trap programs (LH@3, LHU@1, LW@1, LW@3, SH@3, SW@1, SW@3, FENCE.I, SLLI/SRLI with a bad imm[11:5], JALR f3=1, BRANCH f3=2, LOAD f3=3, STORE f3=3, ECALL with rs1=1): the ISS and the RTL both give the hand-derived cause, halt PC 0x10 and instret 4.
- **Conclusion:** I found no shared misunderstanding. The modelling choices that the ISS and the RTL share (strict ECALL/EBREAK match, FENCE fields ignored, halt-on-trap, a trap does not retire) are spec decisions (ARCHITECTURE 6/9), not ISA errors.

### 2.3 Bus, SoC, reset, UART, LEDs
- **Valid/ready.** The CPU holds valid, addr, wdata, wstrb and instr stable until ready (`rv32i_core.v:414-418`; outputs come from state registers). The RAM, the peripherals and the unmapped responder all register their ready (`ready_q <= accept`, with `accept = valid & ~ready_q`), so ready is a single pulse and is never re-accepted on a back-to-back request. The protocol checkers P1-P7 of tb_rv32i_core and tb_soc report 0 violations in every run. Mutant S12 (double accept) is killed.
- **Unmapped access** (`soc_bus.v:102-125`): reads 0, ignores writes, ready after 2 cycles, sticky `bus_err` cleared only by rst. Correct (S06, S10, S17 killed).
- **Aliasing.** RAM uses addr[11:2], peripherals addr[11:2], TPU addr[11:0]; bits [27:12] are ignored. This is allowed by ARCHITECTURE 4 and tested (BFM T5/T6).
- **Reset.** A 2-FF synchroniser powers up at 11 (`soc_top.v:315-318`). R1/R2/R4: rst follows the button on the 2nd edge. The first fetch is at 0x0 in cycle 31 after rst fell (SIMULATION), inside the 40-cycle bound. Every register has a synchronous reset (S07 killed).
- **UART** (`soc_periph.v:156-183`): start bit 0, d0..d7 LSB first, stop bit 1, idle 1, 234 clocks per bit.
  CALCULATION: 27e6/234 = 115384.6 Bd, i.e. +0.16 %.
  The TB receiver is independent of the DUT. It samples real time at 1e9/115200 ns per bit, takes 3 samples per bit, and needs no DUT parameter. The cycle checker uses the spec constant 234, not the DUT parameter. Mutants S02, S03, S04, S08 and S11 are all killed.
- **LEDs.** `led_n = ~led` (`soc_top.v:436`), so the LEDs are active-low, consistent with the CST schematic note. BFM T2 checks the values 0x00/0x3F/0x15/0x2A (S01 killed).

### 2.4 Pins and IO standards against the Apicula reference CST
| Port | Project CST | Apicula `examples/tangnano9k.cst` | Match |
|---|---|---|---|
| clk | 52, LVCMOS33, PULL UP | `clk` 52, LVCMOS33, UP | yes |
| led_n[0..5] | 10, 11, 13, 14, 15, 16, LVCMOS18, NONE | `led[0..5]` 10, 11, 13, 14, 15, 16, LVCMOS18, NONE | yes |
| uart_tx / uart_rx | 17 / 18, LVCMOS33, UP | `TXD` 17 / `RXD` 18, LVCMOS33, UP | yes |
| btn_rst_n | 3, LVCMOS18, UP | `key_i` 3 (`rst_i` is 4) | pin is valid; which button is S1 is an ASSUMPTION (RA-011) |

The routed netlist places all 10 IOs on these pins (`logs/soc/pins.log`). The only "not found" lines in the P&R logs are Info lines for `btn_s2_n` and the in-package PSRAM pins; there is no constraint warning.

### 2.5 Timing and utilisation (re-run at 99ee941, logs `reports/review/build/REV-01a/pnr/pnr_nwl_s{1,2,3}.log`)
| Seed | Post-route Fmax (last "Max frequency" line) | Exit | Project log value |
|---|---|---|---|
| 1 | 51.98 MHz | 0 | 51.98 |
| 2 | 47.46 MHz (worst seed) | 0 | 47.46 |
| 3 | 51.21 MHz | 0 | 51.21 |

The reviewer's re-run matches the project logs exactly, so the "-dirty" stamps on those logs do not hide a difference (see RA-010).

Each log contains exactly one clock: the net is called `u_bus.clk`, which is the alias of the board `clk`, so there is no second domain. The critical path runs from u_cpu.ir through the decoder and the ALU to u_cpu.pc.

Worst seed against the target: 47.46 ≥ 29.7 MHz, a margin of +59.8 % (CALCULATION: 47.46/29.7 - 1).

Utilisation is identical on all seeds:

| Resource | Used / device | Share |
|---|---|---|
| LUT4 | 5628 / 8640 | 65 % |
| ALU | 1976 / 6480 | 30 % |
| DFF | 2803 / 6480 | 43 % |
| BSRAM | 5 / 26 | 19 % |
| RAM16SDP4 | 16 / 270 | 5 % |
| IOB | 10 / 276 | 3 % |
| DSP | 0 | 0 % |

These values match `reports/fpga/soc/soc_impl.md`. Yosys `check` reports "Found and reported 0 problems" 4 times (no latches, loops or multiple drivers).

### 2.6 Testbench strength (mutation experiments on RTL copies, full logs in `mut/`)
- **CPU:** 30 mutants, 21 killed. The 9 survivors are:
  - C11: halfword misalignment at offset 3 is missed
  - C12: word misalignment at offset 1 is missed
  - C13: FENCE.I is treated as a NOP
  - C14: the shift-immediate funct7 is not checked
  - C15: the JALR funct3 is not checked
  - C17: B-imm bit 11 is taken from the sign bit
  - C19: J-imm bits 19:12 are taken from the sign bit
  - C29: a trapping JAL/JALR writes rd
  - C30: the CLEAR state writes nothing

  My hand tests kill C11, C12, C13, C14, C15, C17 and C19 (`hand/run_mutants.summary`). That shows the RTL is correct and the gaps are in the official stimuli.
- **SoC:** 18 mutants, 17 killed. The survivor is S09 (CYCLE reset value 5).

### 2.7 Comment quality (sample: rv32i_core.v, rv32i_decode.v, soc_periph.v, soc_bus.v, tb_soc.v)
All five files have complete headers: purpose, interfaces, FSM or timing, reset, parameters, assumptions and
requirement references. Comments sit on almost every signal and are accurate against the code: the CPI
table, the UART sequencing and the bus timing were all verified. The defects found are minor: stale revision
references and unlabelled numbers (RA-014).

## 3. Findings

| ID | Severity | Location | Finding | Evidence | Recommendation | Disposition |
|---|---|---|---|---|---|---|
| RA-001 | MAJOR | code/python/rv32/gen_cpu_tests.py:772-779 (trap defs) | REQ-CPU-004 acceptance asks for misaligned byte offsets 1, 2, 3 for LW/SW and 1, 3 for LH/SH. The suite tests only LW@2, LH@1, SH@1 and SW@2; LW/SW@1, LW/SW@3, LH/SH@3 and LHU are untested. The RTL itself is correct. | Mutants C11 (half@3 missed) and C12 (word@1 missed) both pass 176/176. The reviewer hand tests hand_lh_off3, hand_lhu_off1, hand_lw_off1/3, hand_sh_off3 and hand_sw_off1/3 pass on the RTL and kill C11/C12. | Add the missing offset tests (the trap template already exists) and re-run. Until then, REQ-CPU-004 cannot be PASS. | |
| RA-002 | MAJOR | gen_cpu_tests.py:757-790 | REQ-CPU-006 asks for at least one test per illegal class. FENCE.I and "SLLI/SRLI/SRAI imm[11:5]" have no test. JALR funct3≠0, BRANCH funct3 010/011 and LOAD/STORE funct3 011 are also untested. | C13, C14 and C15 survive 176/176. The reviewer hand tests (hand_fence_i, hand_slli_f7, hand_srli_f7, hand_jalr_f3, hand_br_f3, hand_ld_f3, hand_st_f3) pass on the RTL and kill those mutants. | Add these trap tests. | |
| RA-003 | MAJOR | tests/cpu/tb_rv32i_core.v:449-478; gen_cpu_tests.py:794 | REQ-CPU-005 says a trapping instruction must leave rd unchanged. This is checked only in the ISS. The RTL testbenches dump the signature before the trapping instruction and never read the register file afterwards, so an RTL that writes rd on a trap passes. | C29 (a misaligned JAL/JALR still writes rd) passes the CPU suite (176/176) and tb_soc (trap_misaligned_jal/jalr). | Compare dut.u_regfile after halt with the ISS `final_regs` from the meta file (both banks), or let the TB dump the register file hierarchically. | |
| RA-004 | MAJOR | design/rtl/cpu/rv32i_regfile.v:226-233; tests/soc/tb_soc.v:478 | The CLEAR state is never exercised. The `initial` block that zeroes the register file in simulation masks it, and the only button reset (tb_soc) comes 3 cycles after power-up, before any register is non-zero. REQ-CPU-003 / REQ-SYS-006 (x1..x31 = 0 after reset) is therefore unverified for a reset during a run. The design is correct by inspection. | C30 (CLEAR writes nothing) passes all 176 CPU runs, the tb_soc demo, the BFM and 3 CPU tests on the SoC. | Add a test that runs a program, presses the button mid-run, then checks a full register dump of 0s. Alternatively, guard the `initial` zeroing with a define that is off in one regression. | |
| RA-005 | MAJOR | gen_cpu_tests.py:632 (`n_body=200`), sim/data/cpu_tests/index.txt | REQ-CPU-010 acceptance asks for ≥ 10 000 retired instructions over ≥ 10 seeds. The 20 random programs retire 5300 in total (SIMULATION), of which 3390 are inside the random bodies (SIMULATION, reviewer ISS count). The rest are prologue and dump. | `grep RESULT cpu/baseline/runs/rand_*__ws0.log` instret sum = 5300; ISS body count = 3390. | Increase `--n-random` or `--body` (e.g. 40 seeds x 400 slots) and re-run, or have the manager change the number. Do not report PASS as it stands. | |
| RA-006 | MAJOR | tests/cpu/tb_rv32i_core.v:449-478 | REQ-CPU-001 acceptance says "after every retired instruction PC and x1..x31 equal the ISS". The testbench compares only the end state: 32 signature words, stop PC, instret, TOHOST, LED and UART. There is no per-retire lockstep or trace comparison, so a transient wrong value that is later overwritten (common in the random tests) cannot be seen. | Inspection of the TB checks list (lines 453-478). The random programs overwrite registers freely. | Add a retire trace: dump (pc, rd, value) on every retire pulse, compare it with an ISS trace, and gate PASS on 0 mismatches. Alternatively, amend the acceptance text through the manager. | |
| RA-007 | MINOR | gen_cpu_tests.py (dir_branches, dir_jumps) | Some immediate bits are never exercised: no branch has \|offset\| ≥ 2048 (B-imm bit 11), and no JAL reaches beyond ±4 KiB (J-imm bits 19:12), although RAM aliasing makes the latter testable. The RTL is correct by inspection (rv32i_decode.v:145,147). | C17 and C19 survive 176/176. Reviewer test hand_h1 (BEQ +0x804, JAL +0x1008 into the alias) passes on the RTL and kills both. | Add a long branch and a JAL into the alias region to the directed tests. | |
| RA-008 | MINOR | tests/soc/tb_soc_bfm.v:228-281 | REQ-SYS-006 lists CYCLE = 0 after reset. T1 never reads CYCLE, and T4 checks only a difference, so the reset value is untested. | S09 (CYCLE resets to 5) passes the demo, the BFM and 4 CPU tests. | Read CYCLE right after reset and check it against the number of BFM cycles since rst fell. | |
| RA-009 | MINOR | tests/soc/tb_soc.v:512-514 | REQ-SYS-005(b) has a 40-cycle bound on the first fetch. The value is printed (cycle 31) but never asserted. | R5 checks only fetch = 1 and address 0. | Add `first_req_cyc <= 40` to R5. | |
| RA-010 | OBSERVATION | logs/cpu/*, logs/soc/*, reports/fpga/cpu/cpu_synth_pnr.txt, reports/fpga/soc/soc_impl.md | The evidence files are stamped with dirty revisions: CPU sim `ac0f0a0-dirty`, CPU P&R `494448a-dirty`, SoC sim/P&R `ac0f0a0-dirty`. This breaks the rule "re-run after committing if dirty". | Reviewer re-runs at the clean `99ee941` reproduce 176/176 CPU, the SoC demo/BFM PASS, and identical Fmax/utilisation (section 2.5). The CPU-only P&R (53.26 MHz) was not re-run. | Re-run the official scripts at the release commit so the logs carry a clean stamp. | |
| RA-011 | OBSERVATION | design/constraints/tangnano9k.cst:33-39,65 | Which of pins 3 and 4 is silkscreen S1 is an ASSUMPTION. The Apicula reference names pin 3 `key_i` and pin 4 `rst_i`; the Sipeed LED example uses pin 4 as reset. A wrong guess changes only which button resets the board. All other pins and IO types match Apicula exactly. | Section 2.4; `ext/apicula_tangnano9k.cst`. | Check against the official schematic before any hardware use; record the outcome. | |
| RA-012 | OBSERVATION | rv32i_core.v:39-43,352-364 vs ARCHITECTURE.md 3 / REQ-CPU-007 | Store data is replicated across all lanes, not "shifted to the addressed byte lanes". The enabled lanes are identical either way and every slave honours wstrb, so behaviour is equal (the ISS models shifted data). | Inspection; S13 shows the slaves depend on wstrb. | Make the spec wording precise: "enabled lanes carry the data; other lanes undefined". | |
| RA-013 | OBSERVATION | tests/soc/tb_soc.v:232-244 | ADR-012 (OD-R2-1) allows up to 40 cycles for TPU buffer accesses while the TPU loads a tile. The SoC checker enforces ≤ 4 cycles, and the demo never takes that path, so the exception path is not exercised at SoC level (max SoC latency seen: 3, SIMULATION). | demo.log `max latency 3`. | Cover it in the TPU review or in an SoC test that reads INPUT while BUSY. | |
| RA-014 | MINOR | soc_top.v:41; tangnano9k.cst:41,46; iss.py:4; rv32i_alu.v:37-40; rv32i_regfile.v:38,90; soc_ram.v:161 | Some comments are stale: "rev A", "rev A/B", "INTERFACES rev A". Some numbers in comments carry no label (~283 LUT, +72 DFF, CPI 5.59). | grep output in this review. | Update the revision references and add the SIMULATION label with a log reference. | |
| RA-015 | OBSERVATION | reports/fpga/soc/soc_impl.md:127 | Gate-level simulation was NOT RUN. I confirmed that the Yosys Gowin BSRAM models (SP/SDP/SDPX9) are specify-only shells, and that a routed nextpnr JSON cannot be read back by Yosys (duplicate-cell assert). The design relies on the BSRAM output holding while CE = 0, which keeps rs2 stable during MEM (rv32i_regfile.v:151-157); that behaviour is unverified at netlist level. | `gl/json2v.log`; inspection of share/gowin/cells_sim.v. | Keep this as a documented risk for the hardware validation plan. | |
| RA-016 | OBSERVATION | scripts/synth_soc.sh:221 | The BSRAM-init check passes with only one initialised block (`n_init >= 1`), so a lost program-RAM init would not be detected. The current log shows all 3 expected blocks initialised (u_ram.mem.0.0/0.1, u_tpu.wram). | logs/soc/bsram_init.log | Require the named u_ram and wram cells to be non-zero. | |

## 4. Status suggestions (for the manager; the status matrix is not the reviewer's file)
| Requirement | Suggested status | Reason |
|---|---|---|
| REQ-SYS-005, 007, 008, 009, 010, 011, 012, 013, 014, 016 | PASS (SIMULATION / I) | Reviewer re-runs and mutants killed. For 005(b), see RA-009. |
| REQ-SYS-006 | PARTIAL | CYCLE and register-file reset not verified (RA-008, RA-004) |
| REQ-CPU-001 | PARTIAL | End-state only (RA-006); immediate bits (RA-007) |
| REQ-CPU-002, 007, 008, 009 | PASS (SIMULATION) | |
| REQ-CPU-003 | PARTIAL | RA-004 |
| REQ-CPU-004, 006 | PARTIAL | RA-001, RA-002. The RTL is correct per the reviewer hand tests, but the official suite is incomplete. |
| REQ-CPU-005 | PARTIAL | RA-003 |
| REQ-CPU-010 | FAIL against the written acceptance | 5300 < 10 000 (RA-005) |
| REQ-TIM-001 (SoC) | PASS (tool STA, not hardware) | 47.46 MHz worst seed, reproduced |
| REQ-RES-001..005 (SoC) | PASS (tool report) | 65 % LUT4 maximum |

Not done: TPU internals and bit-exactness (outside REV-01a); CPU-only P&R re-run; gate-level simulation (RA-015); any hardware test (never in scope).
