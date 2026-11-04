# SW-01b — RV32I reference assembler, ISS and CPU verification programs
Status: PASS (Python reference only: SIMULATION on the Python ISS. No RTL has run these programs yet)
Agent: software-engineer   Date: 2026-11-04   Input revision: ece09f0 (ARCHITECTURE.md and INTERFACES.json unchanged at HEAD d2ed476, checked with `git diff --stat ece09f0`). Work tree at generation: d2ed476-dirty. Nothing committed by me.

## Requirements addressed
- ARCHITECTURE.md §8: CPU verification programs come from the Python reference assembler and are checked on the Python ISS. They are testbench stimuli, not firmware.
- ARCHITECTURE.md §3, §4, §4.1, §6 and INTERFACES.json `bus`, `memory_map`, `periph_regs`, `cpu.traps`, `tpu.regs` (TPU stub only): all modelled in `iss.py`.
- SW-01b items 1–5: assembler, disassembler, ISS, test generator, SoC demo generator, unit tests.

## Inputs
- `design/architecture/ARCHITECTURE.md` §3, 4, 6, 8 and `management/INTERFACES.json` (rev A, frozen, git ece09f0).
- RISC-V Unprivileged ISA, RV32I base v2.1: instruction formats, immediate encodings, opcode map and semantics (SOURCE).

## Outputs
Code (`code/python/rv32/`, every function has a docstring and the comments cite the spec):
- `__init__.py`: package overview.
- `asm.py`: two-pass assembler.
  - Instructions: all 37 RV32I instructions plus FENCE, ECALL and EBREAK.
  - Labels and expressions: `.`, `+ - * ~ ()`, `%hi`/`%lo`, character literals.
  - Pseudo-instructions: `li` (1 or 2 instructions, with sign carry), `la` (AUIPC+ADDI), `mv nop j ret beqz bnez not neg seqz snez jr`, `jal target`, `jalr rs`.
  - Directives: `.word .org .align .space/.zero .equ`.
  - Every field is range-checked (AsmError).
  - Outputs: `$readmemh` hex (1024 lines × 8 lowercase hex digits, zero padded, no header) and a listing.
- `disasm.py`: disassembler that writes only canonical text and gives `.word` for anything else, so that `asm(disasm(w)) == w` for every word. Includes `roundtrip_mismatches()`.
- `iss.py`: the ISS.
  - CPU state: 32 registers, x0 = 0, registers reset to 0, reset PC = 0.
  - Memory: 4 KiB RAM decoded on addr[11:2], so it repeats (aliases) every 4 KiB.
  - Peripherals:
    - LED: 6 bits, read/write.
    - UART_TX: bytes are captured.
    - UART_STATUS: always reads 0, i.e. never busy.
    - CYCLE: always reads 0.
    - TOHOST: any write stops the run.
  - Unmapped addresses: read 0, writes ignored, sticky `bus_err` set.
  - `TpuStub`: STATUS reads DONE=1 after a configurable number of BUSY polls (default 0). RESULT and CYCLES are configurable. CONFIG is clamped as in INTERFACES.json. PARAMS = 0x01000810.
  - Traps follow `cpu.traps` and halt the CPU.
  - A run returns the registers, RAM, stop reason, trap cause, PC, retired-instruction count, UART bytes, LED writes and `bus_err`.
- `gen_cpu_tests.py`: generates the test programs (see Checks).
- `gen_soc_demo.py`: generates the SoC demo program; `--act-shift` (0..7, default 0) and `--out` options.
- `code/python/tests/test_rv32.py`: 93 tests.

Generated data:
- `sim/data/cpu_tests/`: 44 tests. Each has `<name>.hex`, `.sig` (32 lines), `.meta.json` and `.lst`, plus `index.txt` (44 names; sha256 cd9d107e…5e80). The tests are:
  - 11 directed: `dir_lui_auipc dir_alu_imm dir_alu_reg dir_shifts dir_branches dir_jumps dir_loads dir_stores dir_x0 dir_fence_nop dir_mmio`.
  - 20 random: `rand_00..rand_19`, numpy `default_rng` seeds 1000..1019 (seed = 1000 + i, recorded in each meta file and in the summary).
  - 13 trap: `trap_ecall trap_ebreak trap_illegal_{zero,ones,csr,funct7} trap_misaligned_{lw,lh,sh,sw,jalr,jal,branch}`.
- `sim/data/soc_demo_prog.hex` (sha256 bbb6912f…2411), `.lst` and `.meta.json`. Built with ACT_SHIFT=0, CONFIG=0x08, 112 bytes of code.
- `reports/sw/cpu_tests_summary.json`: per-test results, seeds, and retired instructions per mnemonic.
- Logs:
  - `logs/sw/gen_cpu_tests.log`
  - `logs/sw/gen_soc_demo.log`
  - `logs/sw/pytest_rv32.log`

**Signature convention (exact):** at label `sig_dump`, the word at 0x0F00+4k holds xk for k = 1..31, and 0x0F00 holds 0.
- 0x0F00 is out of range of a 12-bit offset from x0, so the dump first parks x1 at 0x7FC. It then sets x1 = 0x1000 and stores x2..x31 with negative offsets. Finally it loads the old x1 back through x2 and stores it.
- After the dump the program writes TOHOST = 1 at label `tohost_store` and then loops on `j .`.
- `.sig` line k (0-based) is the word at 0x0F00+4k.
- Code before the data area stays below 0x7FC; the generator checks this. The image never occupies 0x7FC or 0x0F00..0x0F7F.

**Trap programs:**
- They dump the signature without the TOHOST write, then execute the trapping instruction.
- If the CPU does not trap, it falls through to TOHOST = 3, an odd fail code.
- The misaligned SH and SW targets (0xF41, 0xF42) lie inside the signature area. A store that the CPU performs wrongly therefore corrupts the `.sig` comparison.

## Checks actually performed
- `.venv/bin/python -m pytest -v code/python/tests/test_rv32.py` (pytest 9.2.0, Python 3.13.18), logged to `logs/sw/pytest_rv32.log`. Result: `============================== 93 passed in 1.92s ==============================` (0 failed, 0 skipped). The tests cover:
  - 25 hand-derived spec encodings, with the derivation in each case, e.g. `addi x1,x0,1 = 0x00100093`, `jal x0,.-4 = 0xFFDFF06F`, `bne x0,x0,.-4 = 0xFE001EE3`, `sb x5,-1(x2) = 0xFE510FA3`, `li x1,0x12345FFF = 0x123460B7, 0xFFF08093`.
  - 11 rejection cases: out-of-range or malformed input must raise an error.
  - `li` on 17 edge values and on 2000 random values (seed 7).
  - ISS behaviour: sign extension, SRA vs SRL, shift amounts 0/31/rs2[4:0], SLT/SLTU with 0x80000000, add/sub wrap-around, JALR clearing bit 0 with rd == rs1, branches, x0, LUI/AUIPC, store byte lanes and load-after-store.
  - 15 trap cases. Each checks the cause, halt PC = PC of the trapping instruction, rd unchanged, no memory write, and the retired-instruction count.
  - A not-taken branch to a misaligned target does not trap. FENCE variants act as NOP. MMIO, TOHOST, CYCLE = 0, unmapped access, RAM aliasing, the TPU stub and the demo on the ISS.
  - Round trip over 48 502 seeded words (seed 20261104): random words, opcode-biased words, funct7-biased words, FENCE words, ECALL and EBREAK. Result: 0 mismatches.
  - Two-decoder cross-check: disasm prints `.word` exactly when the ISS reports an illegal instruction (FENCE variants excepted). 0 disagreements.
  - Generator mutation test: a deliberately wrong expected value makes the build fail.
  - Determinism, and consistency of every generated file: 1024/32 line counts, `.sig` equal to an ISS re-run, cause, PC and retired count equal to the meta file, and all trap causes 0..6 present.
- `.venv/bin/python code/python/rv32/gen_cpu_tests.py`, logged to `logs/sw/gen_cpu_tests.log`: 44 × `PASS`, then `wrote 44 tests + index.txt ...; failures: 0`, exit code 0. Each test is checked in this order:
  1. Layout.
  2. Disasm/re-asm round trip of the whole image (0 mismatches for every test).
  3. ISS run stops as expected: TOHOST=1 at `tohost_store`, or the expected cause at label `trap_here`.
  4. The signature in RAM equals the register snapshot from a second ISS run stopped at `sig_dump`.
  5. Directed and trap tests only: hand-derived register values match. These values were written from the RV32I semantics independently of the ISS, and they matched on the first run except for one error in my trap-test setup (see Errors).
- Determinism: regenerating into a scratch directory and running `diff -r` against `sim/data/cpu_tests` gives no differences. The demo `.hex` is byte-identical when regenerated.
- `.venv/bin/python code/python/rv32/gen_soc_demo.py --act-shift 0`, logged to `logs/sw/gen_soc_demo.log`: `round-trip mismatches: 0`, `ISS checks (RESULT 0..9 x busy_polls 0/3 = 20 runs): 0 errors`. Each run checks the CONFIG write = 0x08, one START, LED = RESULT, UART = `'0'+RESULT, '\n'`, [0x0E00] = CYCLES, TOHOST = 1 at `tohost_store`, and no `bus_err`. ACT_SHIFT=3 was also run into scratch with 0 errors.

## Numerical findings
| name | value | unit | label | evidence |
|---|---|---|---|---|
| tests generated | 44 (11 directed / 20 random / 13 trap) | programs | SIMULATION (Python ISS) | logs/sw/gen_cpu_tests.log |
| generator self-check failures | 0 | count | SIMULATION | logs/sw/gen_cpu_tests.log |
| round-trip mismatches (random-word sample) | 0 of 48 502 | words | SIMULATION | logs/sw/pytest_rv32.log |
| round-trip mismatches (all program images) | 0 | words | SIMULATION | logs/sw/gen_cpu_tests.log |
| unit tests | 93 passed / 0 failed / 0 skipped | tests | SIMULATION | logs/sw/pytest_rv32.log |
| random program length | 200 body + ~50 prologue + 37 epilogue | instructions | CALCULATION (generator constants) | gen_cpu_tests.py |
| random programs, retired instructions | 232..288 | instructions | SIMULATION | logs/sw/gen_cpu_tests.log |
| base mnemonics never retired | none (all 37 + FENCE retired; ECALL/EBREAK covered by trap tests) | — | SIMULATION | reports/sw/cpu_tests_summary.json |
| branches retired with next_pc ≠ pc+4 / = pc+4 (all tests) | 160 / 158 | count | SIMULATION | logs/sw/gen_cpu_tests.log |
| SoC demo code size | 112 | bytes | CALCULATION (assembler) | sim/data/soc_demo_prog.lst |

## Assumptions (all implemented in iss.py, documented in its docstring; the RTL must match them, or the manager must decide otherwise)
1. **Traps are precise.** The trapping instruction does not retire:
   - no register write and no memory or peripheral write;
   - halt PC = address of the trapping instruction;
   - `instret` does not count it.
2. **Misaligned fetch (cause 4)** follows the RISC-V convention:
   - it is raised by the JAL, JALR or *taken* branch whose target has target[1:0] ≠ 0 (after JALR clears bit 0);
   - halt PC = the jump or branch itself, and rd is not written;
   - a not-taken branch never traps.
3. **Strict illegal decoding (cause 3)** covers:
   - inst[1:0] ≠ 11 and unknown opcodes;
   - JALR with funct3 ≠ 0;
   - undefined funct3 of BRANCH, LOAD or STORE;
   - shift-immediates with a bad imm[11:5] (including shamt[5] = 1);
   - OP with any funct7 except 0000000, or 0100000 for SUB and SRA (so M-extension words are illegal);
   - every SYSTEM word except exactly 0x00000073 and 0x00100073 (no CSRs);
   - MISC-MEM with funct3 ≠ 000 (so FENCE.I is illegal).
4. **FENCE** (funct3 000) is a NOP whatever fm, pred, succ, rs1 and rd hold.
5. **Misalignment is checked before address decode**, for every region: LH/LHU/SH need addr[0] = 0, and LW/SW need addr[1:0] = 0.
6. **Peripherals:**
   - LED read-back returns bits [5:0] only. `dir_mmio` uses 0x2A, so that test passes either way.
   - Any write to TOHOST stops the ISS once the store retires.
   - Undefined peripheral offsets read 0 and ignore writes without setting `bus_err`. No program uses them.
   - Byte and halfword MMIO accesses merge byte lanes (wstrb). Generated programs use only word accesses.
7. **TPU stub:**
   - STATUS = DONE also before the first START, as the task asked.
   - CONFIG clamps LOG2_L on write.
   - All other TPU offsets are plain storage.
   - It is not a golden model.
8. **CYCLE and UART timing are not modelled.** CYCLE reads 0 and UART_STATUS reads 0. No generated test reads CYCLE. `dir_mmio` reads UART_STATUS only before anything has been sent, which assumes tx_busy resets to 0. The demo stores only the TPU CYCLES value, at 0x0E00, and that value is not part of any signature.
9. **Directed tests rely on registers resetting to 0** (ARCHITECTURE.md §6, an ASSUMPTION there). Random tests initialise every register first.

## Errors / deviations
- None open.
- During development, one trap-test setup error (I reused x6 in `trap_misaligned_jalr`) was caught by the generator's own check and fixed.
- One label clash was fixed: `T0` was rejected because it collides with the ABI register name `t0`.
- Extras beyond the brief, which the RTL testbench may use or ignore:
  - `.lst` files for every test;
  - trap tests `trap_illegal_csr`, `trap_illegal_funct7`, `trap_misaligned_lh`, `trap_misaligned_sw`, `trap_misaligned_jal` and `trap_misaligned_branch`;
  - `dir_mmio`, which needs the peripherals and the unmapped-bus path; its meta `requires` field lists them.

## Open decisions (for the manager)
1. **Halt PC and misaligned fetch (cause 4).** I assumed the trap is raised at the jump or branch, with halt PC = the jump. The other reading of "misaligned fetch" is a trap when the CPU fetches the target, with halt PC = target. Please confirm assumption 2 for the RTL. The 3 `trap_misaligned_j*` and `trap_misaligned_branch` tests encode assumption 2.
2. **Strict decoding.** Please confirm that the CPU must decode strictly as in assumption 3. `trap_illegal_csr` and `trap_illegal_funct7` depend on it, and they can be removed from `index.txt` if decoding is relaxed.
3. **Which testbench runs `dir_mmio`.** It needs LED, UART_STATUS and the unmapped-bus path; every test needs at least TOHOST. Is the CPU testbench a SoC-level bench, or a CPU+RAM+TOHOST bench that skips `dir_mmio` using its meta `requires` field?
4. **Reset values not given in the spec:** LED, TOHOST, and TPU DONE before the first START. The ISS uses 0, 0 and 1 (the stub value). No test depends on any of them.

## Next actions
- fpga-engineer: run the CPU testbench over `sim/data/cpu_tests/index.txt`. For each test:
  1. Load `<name>.hex` into RAM.
  2. Stop on the TOHOST write, or on `halted`, or at a timeout.
  3. Compare `trap_cause` and `dbg_pc` with the meta file (`expected_trap_cause`, `expected_halt_pc` or `tohost_pc`), and RAM 0x0F00..0x0F7C with `<name>.sig`.
  4. Optionally compare the retire count with `instret`, and the registers with `final_regs`.
- SoC testbench: load `sim/data/soc_demo_prog.hex`. Expect the LED and the UART byte to equal the golden-model class, then `'\n'`, then TOHOST = 1. [0x0E00] should equal the TPU CYCLES value.
- To regenerate: `.venv/bin/python code/python/rv32/gen_cpu_tests.py` and `.venv/bin/python code/python/rv32/gen_soc_demo.py --act-shift S`.
