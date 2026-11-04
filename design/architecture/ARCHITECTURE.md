# Architecture specification — SC-TPU + RV32I SoC (rev A, FROZEN for G1)

Owner: engineering manager. Machine-readable twin: `management/INTERFACES.json`.
Any change after freeze goes through the manager (and after V1 through
`/engineering-change`). Sections marked **[BIT-EXACT]** define behaviour that the
Python golden model and the RTL must reproduce bit for bit.

## 1. Block diagram

```
                 27 MHz osc (pin 52)        S1 button (reset, active-low)
                        |                          |
                 +------v--------------------------v-----------------------+
                 |  soc_top (Tang Nano 9K)    reset synchroniser           |
                 |                                                         |
                 |  +-----------+  native mem bus (valid/ready)            |
                 |  | RV32I     |----+-----------+-------------+           |
                 |  | multicycle|    |           |             |           |
                 |  +-----------+    v           v             v           |
                 |              +--------+  +----------+  +-----------+    |
                 |              | RAM 4KB|  | periph   |  | SC-TPU    |    |
                 |              | BSRAM  |  | LED,UART,|  | regs, in/ |    |
                 |              | prog+  |  | cycles,  |  | out bufs, |    |
                 |              | data   |  | tohost   |  | weight RAM|    |
                 |              +--------+  +----------+  | 2KB BSRAM |    |
                 |                              |  |      | 16x8 SC   |    |
                 |                              |  |      | MAC array |    |
                 +------------------------------|--|------+-----------+----+
                                         6 LEDs (n)  UART TX (115200 8N1)
```

## 2. Clock, reset
- Single clock domain `clk` = 27 MHz board oscillator (no PLL in rev A).
- Board button S1 (active-low) -> 2-FF synchroniser -> synchronous active-high
  `rst` for all logic. Reset value of every architectural register is defined.

## 3. Bus (CPU <-> slaves) — native valid/ready (PicoRV32-style)
| Signal | Dir (CPU view) | Width | Meaning |
|---|---|---|---|
| mem_valid | out | 1 | request active; address/data/strobe stable while 1 |
| mem_instr | out | 1 | request is an instruction fetch (debug only) |
| mem_addr | out | 32 | byte address (word aligned for fetch and word access) |
| mem_wdata | out | 32 | write data, already shifted to the byte lanes |
| mem_wstrb | out | 4 | byte write enables; 0000 = read |
| mem_ready | in | 1 | one-cycle pulse: transaction completes this cycle |
| mem_rdata | in | 32 | read data, valid when mem_ready=1 |

Rules: the CPU keeps `mem_valid` high until it sees `mem_ready`; it deasserts
`mem_valid` in the cycle after `mem_ready` (or starts the next transaction).
Slaves must not assert `mem_ready` unless `mem_valid` is 1. Little-endian.

## 4. Memory map
| Base | Size | Slave | Notes |
|---|---|---|---|
| 0x0000_0000 | 4 KiB | RAM (BSRAM), init file `INIT_FILE` (32-bit words, $readmemh) | program + data; reset PC = 0 |
| 0x1000_0000 | 0x20 | Peripherals | see 4.1 |
| 0x2000_0000 | 4 KiB | SC-TPU | see 5.4 |
| other | — | none | read 0, write ignored, sticky `bus_err` debug flag set, mem_ready still returned (no hang) |

Decoding uses addr[31:28] (0x0, 0x1, 0x2) and the low 12 bits inside a slave;
RAM aliases inside 0x0000_0000–0x0FFF_FFFF are allowed (ASSUMPTION: decoder uses
addr[11:2] only).

### 4.1 Peripheral registers (base 0x1000_0000)
| Offset | Name | Access | Bits |
|---|---|---|---|
| 0x00 | LED | RW | [5:0] 1 = LED lit (top inverts for active-low pins) |
| 0x04 | UART_TX | W | [7:0] byte to send; ignored if busy |
| 0x08 | UART_STATUS | R | [0] tx_busy |
| 0x0C | CYCLE | R | free-running 32-bit cycle counter since reset |
| 0x10 | TOHOST | RW | testbench mailbox: TB watches writes; value 1 = pass, other odd = fail code |

UART: 115200 baud 8N1, divider = 234 clocks/bit at 27 MHz (CALCULATION:
27e6/115200 = 234.375, error -0.16 % on bit time).

## 5. SC-TPU (stochastic-computing tensor processing unit)

### 5.1 Workload (fixed in rev A)
MLP 64-16-10: input 64 pixel codes -> hidden 16 neurons (clipped-ReLU) ->
output 10 scores -> argmax. Hardware geometry: NL = 16 neuron lanes, IL = 8
input lanes (weight-stationary tile of 16x8 weights).

### 5.2 Number representation [BIT-EXACT]
- Every input, activation and weight is an 8-bit unsigned **code** c in 0..255
  representing the bipolar value v(c) = (c - 128) / 128 in [-1, 127/128].
- Stochastic number generator (SNG): stream bit b = (r < c) with r an 8-bit
  pseudo-random number, so P(b=1) ~ c/256 = (v+1)/2.
- Bipolar multiplication: p = XNOR(b_x, b_w); E[p] = (1 + v_x v_w)/2.
- Accumulation: an accumulative parallel counter (APC) adds popcount over the IL
  lanes of p every stream cycle into a per-neuron binary accumulator acc_j.

### 5.3 Algorithm of one inference [BIT-EXACT]
Parameters: K = CONFIG.LOG2_L (clamped by hardware to 4..10), L = 2^K stream
cycles per tile; s = CONFIG.ACT_SHIFT (0..7).

RNG: 16-bit Fibonacci LFSR, polynomial x^16+x^14+x^13+x^11+1:
`fb = s[15]^s[13]^s[12]^s[10]; s' = ((s<<1)|fb) & 0xFFFF` (one *step*).
One *stream cycle* advances every LFSR by **8 steps** (unrolled leap-forward) and
uses the low byte of the new state as r (8 fresh bits per cycle).

RNG_MODE (synthesis parameter, readable in PARAMS register):
- 0 SHARED: one LFSR_X (seed 0xACE1) and one LFSR_W (seed 0x7A5C). Input lane i
  uses r_x; weight lane (j,i) uses r_w.
- 1 ROTATE: same two LFSRs; input lane i uses rotl8(r_x, i); weight lane (j,i)
  uses rotl8(r_w, i) (i = 0..IL-1).
- 2 INDEPENDENT: IL LFSR_X_i with seed (0xACE1 + 0x3C5A*i) mod 2^16 and IL
  LFSR_W_i with seed (0x7A5C + 0x2B67*i) mod 2^16; input lane i uses r_x_i;
  weight lane (j,i) uses r_w_i (shared across neuron lanes j).
LFSRs are loaded with their seeds when START is accepted, and advance only in
stream cycles (never during loads/post-processing). They are NOT reset between
tiles or layers.

Sequence after START:
1. For layer l = 1 (N_in = 64, tiles T = 8) then l = 2 (N_in = 16, T = 2):
   a. acc_j = 0 for j = 0..15.
   b. For tile t = 0..T-1: load weight tile W[j][i] (j = 0..15, i = 8t..8t+7)
      and the 8 input codes x_i of the layer (l=1: INPUT buffer, l=2: HIDDEN
      buffer); then for k = 0..L-1 (stream cycles):
      `acc_j += sum_{i} XNOR(r_x(i,k) < x_i, r_w(j,i,k) < W[j][i])`.
   c. Post-process j = 0..15:
      `D_j = 2*acc_j - N_in*L`
      `B_j = floor(bias_j * 2^K / 128)` (bias_j signed 16-bit, arithmetic)
      `Dp_j = D_j + B_j`
      - l = 1: `u = floor(Dp_j * 2^(s+7) / 2^K)`; `h_j = clip(u, 0, 127)`;
        HIDDEN[j] = 128 + h_j.
      - l = 2: SCORE[j] = Dp_j (signed, sign-extended to 32 bits).
2. RESULT = argmax_{j=0..9} SCORE[j]; ties -> lowest index.
3. STATUS.DONE = 1, BUSY = 0; CYCLES = clock cycles from START to DONE.

Interpretation (not part of bit-exact behaviour): Dp_j / L estimates
sum_i v(x_i) v(W_ji) + bias_j/128; hidden value h/128 = clip(2^s * Dp_j/L, 0, 127/128).

### 5.4 Register map (base 0x2000_0000, word accesses; byte writes allowed on buffers and weight RAM)
| Offset | Name | Access | Bits / content |
|---|---|---|---|
| 0x000 | CTRL | W | [0] START (write 1; ignored while BUSY) |
| 0x004 | STATUS | R | [0] BUSY, [1] DONE (cleared by START) |
| 0x008 | CONFIG | RW | [3:0] LOG2_L (reset 8), [6:4] ACT_SHIFT (reset 0) |
| 0x00C | RESULT | R | [3:0] argmax class |
| 0x010 | CYCLES | R | cycles of last inference |
| 0x014 | PARAMS | R | [7:0] NL=16, [15:8] IL=8, [17:16] RNG_MODE, [31:24] version 0x01 |
| 0x040–0x07F | INPUT[0..63] | RW | byte i = code of input i (little-endian packing, 4 per word) |
| 0x080–0x0BF | SCORE[0..15] | R | one signed 32-bit word per output lane |
| 0x0C0–0x0CF | HIDDEN[0..15] | R | byte j = hidden code (4 per word) |
| 0x100–0x17F | BIAS[0..31] | RW | word b: [15:0] signed bias; b = 16*(l-1) + j |
| 0x800–0xFFF | WEIGHT RAM | RW | 2 KiB BSRAM, layout 5.5 |
CPU writes to buffers/weights while BUSY: ignored (ASSUMPTION; documented).

### 5.5 Weight memory layout [BIT-EXACT]
Byte address inside the weight RAM for layer l, neuron j (0..15), input i:
`addr = base_l + (floor(i/IL)*NL + j)*IL + (i mod IL)`, base_1 = 0, base_2 = 1024.
Layer 1 uses 0..1023, layer 2 uses 1024..1279 (neurons 10..15 of layer 2 are
padding; any code, ignored by argmax). Word w holds bytes 4w..4w+3 little-endian.
A tile is 128 contiguous bytes = 32 words.

### 5.6 Init files (for simulation and bitstream initialisation)
- `weights.hex`: 512 lines, 32-bit words of the weight RAM.
- `bias.hex`: 32 lines, 16-bit two's complement (4 hex digits).
- `input.hex`: 16 lines, 32-bit words of INPUT (default image).
- `prog.hex`: 1024 lines, 32-bit words of RAM.

## 6. CPU — RV32I multi-cycle
- ISA: RV32I unprivileged base (LUI, AUIPC, JAL, JALR, BEQ/BNE/BLT/BGE/BLTU/BGEU,
  LB/LH/LW/LBU/LHU, SB/SH/SW, ADDI/SLTI/SLTIU/XORI/ORI/ANDI/SLLI/SRLI/SRAI,
  ADD/SUB/SLL/SLT/SLTU/XOR/SRL/SRA/OR/AND, FENCE (as NOP)). ECALL/EBREAK,
  illegal instructions and misaligned load/store/jump targets stop the CPU:
  `halted` = 1, `trap_cause` (0 none, 1 ecall, 2 ebreak, 3 illegal, 4 misaligned
  fetch, 5 misaligned load, 6 misaligned store). No CSRs, no interrupts.
- Reset PC 0x0000_0000; x0 hard-wired to 0; registers reset to 0 (ASSUMPTION for determinism).
- Multi-cycle FSM (FETCH -> DECODE -> EXECUTE -> MEM -> WRITEBACK), CPI depends on
  the instruction and slave latency; measured CPI is reported, not required.
- Debug outputs: `halted`, `trap_cause[3:0]`, `dbg_pc[31:0]`, `retire` pulse.

## 7. Top level (Tang Nano 9K) ports
`clk` (27 MHz), `btn_rst_n` (S1), `led_n[5:0]`, `uart_tx`, `uart_rx` (input,
unused in rev A). Pin numbers: `design/constraints/tangnano9k.cst` (sourced).

## 8. Verification hooks
- CPU programs used for verification are generated by the Python reference
  assembler (`code/python/rv32/`) and checked against the Python ISS; they are
  testbench stimuli, not firmware.
- The SoC demo program (`sim/data/soc_demo_prog.hex`): configure TPU, START, poll
  DONE, read RESULT, write LED and UART, write TOHOST.

## 9. Rev A.1 clarifications (2026-11-04, see ADR-006)
- Misaligned jump/branch target traps on the jump/branch (halt PC = its address, rd not written).
- Strict decoding: CSR instructions, unknown funct3/funct7 (e.g. MUL), FENCE.I,
  0x00000000 and 0xFFFFFFFF are illegal (cause 3).
- Reset values: LED=0, TOHOST=0, TPU STATUS=0, RESULT=0, CYCLES=0, SCORE/HIDDEN=0.

## 10. Rev A.2 clarifications (2026-11-04, from REQ-01 open decisions; ADR-007)
- CONFIG reads back the clamped LOG2_L value actually used (write 15 -> read 10, write 1 -> read 4).
- CYCLES = number of rising clock edges during which STATUS.BUSY = 1 for the last inference.
- Reserved / unmapped offsets inside the TPU window read 0 and ignore writes.
- Reads are allowed while BUSY and return the current storage contents (SCORE/HIDDEN may be partially updated).
- BIAS words read back sign-extended from [15:0]; bits [31:16] of a write are ignored.
- Post-processing intermediates must be wide enough (or saturate early) so that the
  result equals the mathematical formula of 5.3 for every legal input (worst-case
  |Dp * 2^(s+7)| < 2^34); the RTL documents its chosen widths.
- Margins: "with margin" means each FPGA resource <= 85 % of the device total and
  post-route Fmax >= 29.7 MHz (27 MHz + 10 %) on the worst of 3 seeds.

## 11. Rev B (2026-11-04, ADR-008) — supersedes the seed values and default mode above
- Default RNG_MODE = 2 (INDEPENDENT).
- Phase-spaced seeds. Let S(n) be the state of the LFSR started at 0xACE1 after n
  single steps. Modes 0/1: seed_x = S(0) = 0xACE1, seed_w = S(32768) = 0xF9DE.
  Mode 2: seed_x_i = S(4096 i) = 0xACE1, 0x357B, 0x6F4D, 0xEAD3, 0x0348, 0x70BC,
  0xB617, 0xC223; seed_w_i = S(32768 + 4096 i) = 0xF9DE, 0x71EC, 0xAA39, 0x520B,
  0x9DB1, 0xF251, 0x5D8E, 0x91AB. Because 4096 is a multiple of 8, any two of the
  16 LFSRs are >= 512 stream cycles apart on the common sequence, and X_i vs W_i
  (the operands that are multiplied together) are 4096 stream cycles apart — more
  than one full inference at K <= 8 (2560 stream cycles).
- PARAMS.version = 0x02.

## 12. Rev C (2026-11-04, ADR-010) — CURRENT; supersedes the seed text of sections 5.3 and 11
- Default RNG_MODE = 2. PARAMS.version = 0x03.
- Modes 0/1: seed_x = 0xACE1, seed_w = 0xF9DE (= S(32768), unchanged from rev B).
- Mode 2: seed_x_i = (0xACE1 + 0x3C5A*i) mod 2^16, seed_w_i = (0x7A5C + 0x2B67*i) mod 2^16:
  X = 0xACE1 0xE93B 0x2595 0x61EF 0x9E49 0xDAA3 0x16FD 0x5357;
  W = 0x7A5C 0xA5C3 0xD12A 0xFC91 0x27F8 0x535F 0x7EC6 0xAA2D
  (identical to the rev A mode-2 seeds). Minimum pairwise lag 321 stream cycles (X0-W3).
- Rationale: the seed set must satisfy R1 (no two lanes' operand-pair streams are
  translates: (lag_x(i)-lag_x(j)) != (lag_w(i)-lag_w(j)) for i != j) and R2 (no direct
  or swapped shared-bit lag between operand pairs). Rev B violated R1 on all 28 lane
  pairs. Among 5 candidates satisfying/violating the rules, this set had the best
  worst-case validation accuracy over K in {8,9,10} (reports/sw/seed_selection_revC.md).
  Maximal phase spacing alone is not a sufficient criterion.

## 13. Rev C.1 text clarification (review RA-012)
Section 3 "write data, already shifted to the byte lanes": the CPU replicates the
store data on all byte lanes (SB: byte x4, SH: halfword x2) and `mem_wstrb` selects
the lanes; slaves must use `mem_wstrb`. This is a superset of the shifted form and
is the normative behaviour.

## 14. Rev D — Deterministic tensor unit (DT-TPU), CR-001 — CURRENT PRODUCT DESIGN
The SC-TPU (sections 5, 9-13) remains the documented *comparison design*; the
product SoC uses the DT-TPU below. Bus, memory map, register OFFSETS, buffers,
BIAS, START/STATUS/RESULT/CYCLES semantics, writes-while-BUSY rule, reset values
and the A.2 clarifications are unchanged unless stated here.

### 14.1 Arithmetic [BIT-EXACT]
- Codes c in 0..255 as before; signed value q(c) = c - 128 in -128..127 (int8).
- Layer l, neuron j: `acc_j = sum_{i<N_in} q(x_i) * q(W_ji)` exact (|acc| <= 2^20).
- `Dp_j = acc_j + 128 * bias_j` (bias int16).
- Hidden (layer 1): `u = floor(Dp_j * 2^s / 128)`; `h = clip(u, 0, 127)`; HIDDEN[j] = 128 + h.
- Score (layer 2): SCORE[j] = Dp_j sign-extended to 32 bits; RESULT = argmax over j = 0..9, ties -> lowest index.
- Equivalence: Dp_j / 2^14 = sum v_x v_w + bias/128 with v = q/128 — exactly the
  expected value the SC-TPU estimates, so the same trained codes are used unchanged.
- Internal widths must be sufficient for every legal input (document them).

### 14.2 Dataflow
NL = 16 neuron lanes, one input per cycle: in cycle i every lane j computes
q(x_i) * q(W_ji) and accumulates. Layer 1 = 64 MAC cycles, layer 2 = 16 MAC cycles
(lanes 10..15 padding, computed but ignored by argmax), plus pipeline latency,
post-processing and argmax. The 16 weights of input row i are read in one cycle.

### 14.3 Weight memory layout [BIT-EXACT] (changed)
Byte address inside the weight RAM: `addr = base_l + 16*i + j`, base_1 = 0
(i < 64: 0..1023), base_2 = 1024 (i < 16: 1024..1279). Word w = bytes 4w..4w+3,
little-endian. (Implementation hint: 4 BSRAM banks of 32 bits, bank = w mod 4.)

### 14.4 Register changes
- CONFIG: [6:4] ACT_SHIFT (reset 0); [3:0] reserved: read 0, writes ignored.
- PARAMS: [7:0] NL = 16, [15:8] inputs per cycle = 1, [19:16] reserved 0,
  [23:20] TPU_KIND = 1 (deterministic), [31:24] version = 0x10.
- CYCLES: rising edges with BUSY = 1 (unchanged definition). Target <= 300 cycles.
