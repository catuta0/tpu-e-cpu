# Requirements — SC-TPU + RV32I SoC on Tang Nano 9K

Owner: systems-engineer · Task: REQ-02 · Date: 2026-11-04 · Issue: 2 (rev C baseline)
Input revision: `1d67c44` (assigned; HEAD at writing `7537c02`, which differs only in
`management/GATES.md`). Architecture spec **rev C** (ARCHITECTURE.md sections 1-8 as
amended by 9 (A.1, ADR-006), 10 (A.2, ADR-007), 11 (rev B, ADR-008, superseded) and
**12 (rev C, ADR-010, CURRENT)**); `management/INTERFACES.json` revision C; ADR-006..011.
Issue 1 (REQ-01, input `494448a`, spec rev A/A.1) is superseded; every change is listed
in the [change history](#change-history) at the bottom, and the disposition of the
REQ-01 open decisions in [section 9](#9-disposition-of-the-req-01-open-decisions).
Inputs: `management/PROJECT_DEFINITION.md`, `design/architecture/ARCHITECTURE.md`,
`management/INTERFACES.json`, `management/DECISIONS.md`, `management/SOURCES.md`.
Budgets backing the numeric criteria: [`requirements/BUDGETS.md`](BUDGETS.md).
Risks: [`management/RISKS.md`](../management/RISKS.md).

## Conventions
- **ID** `REQ-<AREA>-nnn`. Areas: SYS (system, bus, memory map, peripherals),
  CPU, TPU, AI (workload / accuracy), RES (resources), TIM (timing, latency),
  DOC (documentation), VER (verification process).
- **Text** uses *shall* for a mandatory requirement and *should* for a goal.
- **Source**: `user` (stated by the user), `definition` (PROJECT_DEFINITION.md),
  `architecture` (ARCHITECTURE.md rev A / A.1, INTERFACES.json, ADR-xxx),
  `derived` (proposed by the systems engineer to make a higher-level requirement
  verifiable; the manager may change the number).
- **Verification method**: **A** Analysis (calculation, tool report reading),
  **S** Simulation (self-checking testbench / Python model), **I** Inspection
  (review of code, logs, documents), **T** Test on real hardware.
  *T is never executed in this project* (no flashing, no powering up); every T
  item belongs to the physical validation plan and stays NOT RUN.
- **Status**: PASS / PARTIAL / FAIL / BLOCKED / NOT RUN. All requirements are
  still NOT RUN at issue 2: verification status is assigned only in
  `requirements/STATUS_MATRIX.md` after the independent review (REV-01), even
  where specialist handoffs already report evidence. Simulation is not test;
  synthesis/P&R is not hardware validation.
- **IDs are stable**: no requirement has been renumbered or deleted; changed
  requirements keep their ID and are listed in the change history.
- Number labels as in `.claude/skills/engineering-evidence/SKILL.md`.
- Definitions used in acceptance criteria:
  - *Test split*: the 360-image stratified test split of the scikit-learn
    digits set (`train_test_split(test_size=360, stratify=y, random_state=0)`,
    as implemented in `code/python/sctpu/train.py`); never used for training
    or model selection.
  - *EV model*: the golden model with every stream replaced by its expected
    value (K -> infinity); *bit-exact model*: the Python golden model that
    reproduces the [BIT-EXACT] sections of the spec.
  - *Selected RNG mode*: RNG_MODE **2 (INDEPENDENT)**, chosen by the ADR-003
    study and fixed by ADR-008 / ADR-010 (closes ADR-003); it is the synthesis
    default of the release build.
  - *Deployed seeds*: the **rev C** seed set of ARCHITECTURE.md section 12 /
    INTERFACES.json revision C: modes 0/1 seed_x = 0xACE1, seed_w = 0xF9DE
    (= S(32768)); mode 2 seed_x_i = (0xACE1 + 0x3C5A*i) mod 2^16 =
    0xACE1 0xE93B 0x2595 0x61EF 0x9E49 0xDAA3 0x16FD 0x5357 and
    seed_w_i = (0x7A5C + 0x2B67*i) mod 2^16 =
    0x7A5C 0xA5C3 0xD12A 0xFC91 0x27F8 0x535F 0x7EC6 0xAA2D (i = 0..7).
  - *Seed rules R1 / R2* (ARCHITECTURE.md 12, ADR-009/010; S(n) = LFSR state
    after n single steps from 0xACE1, n_x(i), n_w(i) = phase of seed_x_i,
    seed_w_i, D_i = n_w(i) - n_x(i) mod 65535):
    **R1** no two lanes' operand-pair streams are translates:
    (lag_x(i) - lag_x(j)) != (lag_w(i) - lag_w(j)), i.e. D_i != D_j for i != j;
    **R2** no direct or swapped shared-bit lag between operand pairs:
    |D_i - D_j| > 14 for i != j and |D_i + D_j| > 14 for all i, j (circular
    distance mod 65535; the +/-14 window comes from r being an 8-bit window of
    one bit sequence, SW-03). R1/R2 apply to mode 2; the modes 0/1 pair violates
    R2 by self-swap (|2D| = 1) and is accepted as a non-default study mode
    (ADR-010 D-B).
  - *Validation split*: the 288-image subset `val_idx` of the training split
    (`train_test_split(train_idx, test_size=288, stratify, random_state=0)`),
    used for ACT_SHIFT, variant and seed selection (SW-01a, SW-03).
  - *Device logic capacity*: 8640 LUT4 positions, 6480 DFF, 6480 ALU, 26 BSRAM,
    270 RAM16SDP4 (SOURCE: Apicula/nextpnr chip database, see SOURCES.md S-027..S-033).
  - *LUT4 utilisation* means the nextpnr-himbaechel "LUT4" line, which counts
    every occupied LUT position including ALU (carry) cells and LUT-RAM
    (CALCULATION, BUDGETS.md sec. 1.1).

## Summary table
"Issue" = issue in which the requirement text, source or acceptance last
changed (details in the change history). Status stays NOT RUN until the
status matrix.

| ID | Title | Src | V | Status | Issue |
|---|---|---|---|---|---|
| REQ-SYS-001 | Target device and board | definition | I | NOT RUN | 1 |
| REQ-SYS-002 | Open-source toolchain only | definition | I | NOT RUN | 1 |
| REQ-SYS-003 | SoC composition | definition | I | NOT RUN | 1 |
| REQ-SYS-004 | Single 27 MHz clock domain | architecture | I | NOT RUN | 2 |
| REQ-SYS-005 | Reset synchroniser and reset release | architecture | S | NOT RUN | 2 |
| REQ-SYS-006 | Defined reset values | architecture | S | NOT RUN | 1 |
| REQ-SYS-007 | Bus protocol (valid/ready) | architecture | S | NOT RUN | 2 |
| REQ-SYS-008 | Little-endian byte lanes | architecture | S | NOT RUN | 1 |
| REQ-SYS-009 | Memory map and address decoding | architecture | S | NOT RUN | 1 |
| REQ-SYS-010 | Unmapped access behaviour | architecture | S | NOT RUN | 1 |
| REQ-SYS-011 | Peripheral registers | architecture | S | NOT RUN | 1 |
| REQ-SYS-012 | UART transmitter format and baud error | architecture | A, S | NOT RUN | 1 |
| REQ-SYS-013 | LED outputs | architecture | S, I | NOT RUN | 1 |
| REQ-SYS-014 | Top-level ports and pin constraints | architecture | I | NOT RUN | 2 |
| REQ-SYS-015 | No firmware | user, definition | I | NOT RUN | 1 |
| REQ-SYS-016 | SoC end-to-end demo | architecture | S | NOT RUN | 1 |
| REQ-SYS-017 | Power estimate | derived | A | NOT RUN | 1 |
| REQ-CPU-001 | RV32I instruction set | definition, architecture | S | NOT RUN | 1 |
| REQ-CPU-002 | Register x0 | architecture | S | NOT RUN | 1 |
| REQ-CPU-003 | CPU reset state | architecture | S | NOT RUN | 1 |
| REQ-CPU-004 | Trap causes and halt | architecture | S | NOT RUN | 1 |
| REQ-CPU-005 | Trap side-effect freedom | derived | S | NOT RUN | 1 |
| REQ-CPU-006 | Strict decoding (illegal set) | architecture (A.1) | S | NOT RUN | 1 |
| REQ-CPU-007 | Loads/stores: extension, strobes, lanes | architecture | S | NOT RUN | 1 |
| REQ-CPU-008 | Debug outputs and retire count | architecture | S | NOT RUN | 1 |
| REQ-CPU-009 | CPI reported | architecture | S | NOT RUN | 1 |
| REQ-CPU-010 | Random-program cross-check vs ISS | derived | S | NOT RUN | 1 |
| REQ-TPU-001 | Geometry and dataflow | architecture | I | NOT RUN | 1 |
| REQ-TPU-002 | Register map and reset values | architecture | S | NOT RUN | 2 |
| REQ-TPU-003 | PARAMS register value (version 0x03) | architecture | S | NOT RUN | 2 |
| REQ-TPU-004 | Code representation, SNG, XNOR, APC | architecture | S | NOT RUN | 1 |
| REQ-TPU-005 | LFSR definition and sequencing | architecture | S | NOT RUN | 2 |
| REQ-TPU-006 | RNG modes, default mode 2, seed rules R1/R2 | architecture | S | NOT RUN | 2 |
| REQ-TPU-007 | LOG2_L clamp | architecture | S | NOT RUN | 2 |
| REQ-TPU-008 | Post-processing exactness and widths | architecture, derived | A, S | NOT RUN | 2 |
| REQ-TPU-009 | Argmax and tie rule | architecture | S | NOT RUN | 1 |
| REQ-TPU-010 | START / BUSY / DONE semantics | architecture | S | NOT RUN | 1 |
| REQ-TPU-011 | Writes while BUSY ignored | architecture | S | NOT RUN | 2 |
| REQ-TPU-012 | Weight memory layout and init files | architecture | S, I | NOT RUN | 1 |
| REQ-TPU-013 | Bit-exact equivalence RTL vs golden model | definition, architecture | S | NOT RUN | 2 |
| REQ-TPU-014 | CYCLES register | architecture | S | NOT RUN | 2 |
| REQ-TPU-015 | Reserved TPU offsets | derived | S | NOT RUN | 2 |
| REQ-TPU-016 | Reset during an inference | derived | S | NOT RUN | 1 |
| REQ-AI-001 | Network and dataset | definition | I | NOT RUN | 1 |
| REQ-AI-002 | Reproducible split and training | derived | I, S | NOT RUN | 2 |
| REQ-AI-003 | Reference (float / EV) accuracy | derived | S | NOT RUN | 1 |
| REQ-AI-004 | SC accuracy at L = 256 | derived | S | NOT RUN | 2 |
| REQ-AI-005 | SC accuracy gap vs EV at the operating K | derived | S | NOT RUN | 1 |
| REQ-AI-006 | Seed-ensemble accuracy | derived | S | NOT RUN | 2 |
| REQ-AI-007 | Statistical reporting | derived | A | NOT RUN | 1 |
| REQ-AI-008 | int8 binary baseline | architecture (ADR-001) | S | NOT RUN | 1 |
| REQ-AI-009 | Error analysis vs K | definition | S, A | NOT RUN | 1 |
| REQ-AI-010 | RNG mode selection study | architecture (ADR-003) | S, A | NOT RUN | 2 |
| REQ-AI-011 | Golden model and hex export | definition, architecture | S, I | NOT RUN | 1 |
| REQ-RES-001 | LUT4 utilisation | definition, derived | A | NOT RUN | 2 |
| REQ-RES-002 | Flip-flop utilisation | definition, derived | A | NOT RUN | 1 |
| REQ-RES-003 | ALU / LUT-RAM / DSP utilisation | definition, derived | A | NOT RUN | 1 |
| REQ-RES-004 | BSRAM utilisation and inference | definition, derived | A | NOT RUN | 1 |
| REQ-RES-005 | I/O usage | architecture | I | NOT RUN | 1 |
| REQ-RES-006 | Variant resource report | architecture (ADR-002/003) | A | NOT RUN | 2 |
| REQ-TIM-001 | Timing closure at 27 MHz with margin | definition, derived | A | NOT RUN | 2 |
| REQ-TIM-002 | Synchronous design rules | derived | I, A | NOT RUN | 1 |
| REQ-TIM-003 | Asynchronous inputs | architecture | I | NOT RUN | 1 |
| REQ-TIM-004 | Inference latency | derived | S, A | NOT RUN | 1 |
| REQ-TIM-005 | CPU-side inference time reported | derived | S | NOT RUN | 2 |
| REQ-DOC-001 | RTL commenting standard | user | I, A | NOT RUN | 1 |
| REQ-DOC-002 | Python / script commenting standard | user | I, A | NOT RUN | 1 |
| REQ-DOC-003 | Language | user | I | NOT RUN | 1 |
| REQ-DOC-004 | Number labels and status words | definition (CLAUDE.md) | I | NOT RUN | 1 |
| REQ-DOC-005 | Scientific article | definition | I, A | NOT RUN | 1 |
| REQ-DOC-006 | Engineering report | definition | I, A | NOT RUN | 1 |
| REQ-DOC-007 | Requirement status matrix | definition | I | NOT RUN | 1 |
| REQ-DOC-008 | Release baseline | definition | I | NOT RUN | 1 |
| REQ-VER-001 | Self-checking testbench per block | definition | I, S | NOT RUN | 1 |
| REQ-VER-002 | Testbench fault-injection check | derived | S | NOT RUN | 1 |
| REQ-VER-003 | Lint clean | derived | A | NOT RUN | 1 |
| REQ-VER-004 | Python unit tests | derived | S | NOT RUN | 1 |
| REQ-VER-005 | Full FPGA flow on the final SoC | definition | A | NOT RUN | 1 |
| REQ-VER-006 | Traceability | derived | I | NOT RUN | 1 |
| REQ-VER-007 | Evidence and reproducibility | definition (CLAUDE.md) | I | NOT RUN | 1 |
| REQ-VER-008 | Independent review | definition | I | NOT RUN | 1 |
| REQ-VER-009 | Physical validation plan (future Test) | definition | I (plan), T (future) | NOT RUN | 1 |

---

## 1. System (SYS)

### REQ-SYS-001 — Target device and board
- **Text:** The design shall target the Gowin GW1NR-LV9QN88PC6/I5 on the Sipeed
  Tang Nano 9K and shall be placed and routed with
  `--device GW1NR-LV9QN88PC6/I5 --vopt family=GW1N-9C`.
- **Rationale:** fixed board (bought-in, not to be redesigned).
- **Source:** definition (Context, Bought-in parts).
- **Verification:** I — P&R log of the release build.
- **Acceptance:** the release P&R log shows that device/family, exit code 0 and
  `0 errors`; the bitstream is produced by `gowin_pack -d GW1N-9C`.
- **Status:** NOT RUN

### REQ-SYS-002 — Open-source toolchain only
- **Text:** All synthesis, P&R, bitstream generation, simulation, modelling and
  document builds shall use only the open-source tools listed in
  `management/TOOLCHAIN.md`; no proprietary or paid tool shall be required to
  reproduce any result.
- **Rationale:** hard constraint "no budget for paid tools".
- **Source:** definition (Hard constraints, Toolchain).
- **Verification:** I — scripts and logs name only the listed tools and versions.
- **Acceptance:** 100 % of build/sim scripts in the release invoke only tools
  from TOOLCHAIN.md; tool versions recorded in every log header.
- **Status:** NOT RUN

### REQ-SYS-003 — SoC composition
- **Text:** The SoC shall contain an RV32I multi-cycle CPU, a 4 KiB RAM, a
  peripheral block (LED, UART TX, cycle counter, TOHOST) and the SC-TPU, all
  connected by the native bus of REQ-SYS-007, all RTL written in this project
  (Gowin primitives inferred through the open flow only).
- **Rationale:** product definition items 1-2.
- **Source:** definition (Product), architecture §1.
- **Verification:** I — RTL file list and hierarchy in the synthesis log.
- **Acceptance:** synthesis hierarchy of `soc_top` contains the four blocks; no
  third-party CPU/IP source files in `design/rtl/`.
- **Status:** NOT RUN

### REQ-SYS-004 — Single 27 MHz clock domain
- **Text:** All sequential logic shall be clocked by one clock `clk` driven
  from the 27 MHz board oscillator on pin 52; no PLL, no derived or gated
  clocks (rev A..C).
- **Rationale:** simplest timing closure; the 27 MHz board clock is a hard
  constraint (PLL allowed by the definition but not used by rev A).
- **Source:** architecture §2; definition (Hard constraints). Value 27 MHz:
  SOURCE S-020 (board), pin 52: tangnano9k.cst sources.
- **Verification:** I — synthesis/P&R log lists exactly one clock net.
- **Acceptance:** nextpnr reports exactly 1 clock domain (`Max frequency for
  clock ...` printed for one clock only); no rPLL/CLKDIV cells in utilisation.
- **Status:** NOT RUN

### REQ-SYS-005 — Reset synchroniser and reset release
- **Text:** The active-low board button S1 shall reach the logic only through a
  2-flip-flop synchroniser producing the synchronous, active-high reset `rst`.
  After `rst` deasserts, the first bus request shall be an instruction fetch
  (`mem_instr` = 1) from address 0x0000_0000.
- **Rationale:** avoids metastability and reset-release skew; deterministic start.
- **Source:** architecture §2, §6; INTERFACES.json `reset`.
- **Verification:** S — SoC testbench.
- **Acceptance:** (a) `rst` rises on the 2nd or 3rd rising `clk` edge after the
  button input goes low, and falls on the 2nd or 3rd edge after it goes high
  (same latency as the ST-FPGA-01 smoke counter); (b) the first `mem_valid`
  after reset release has `mem_instr` = 1, `mem_addr` = 0x0000_0000 and occurs
  within **40** clock cycles of `rst` falling (issue 2, ADR-011; issue 1 had 8).
- **Rationale of the bound (b):** the CPU register file is in BSRAM (saves ~1000
  FF, BUDGETS.md 1.5) and is zeroed by a 32-cycle CLEAR state after every reset
  (REQ-CPU-003), so the first fetch cannot come before cycle ~32; 40 = 32 + 8
  keeps the original 8-cycle allowance for the bus and FSM on top of CLEAR. The
  issue-1 bound of 8 cycles was an unjustified guess (ADR-011).
- **Status:** NOT RUN

### REQ-SYS-006 — Defined reset values
- **Text:** Every architectural register shall have the reset value given by the
  spec: CPU PC = 0 and x1..x31 = 0; LED = 0; TOHOST = 0; UART idle (line high,
  tx_busy = 0); CYCLE = 0; TPU STATUS = 0, RESULT = 0, CYCLES = 0, CONFIG =
  {ACT_SHIFT 0, LOG2_L 8}, SCORE/HIDDEN = 0; bus_err = 0.
- **Rationale:** determinism of simulations and of the bit-exact comparison.
- **Source:** architecture §2, §6, §9 (rev A.1, ADR-006).
- **Verification:** S — read-back of every listed register after reset.
- **Acceptance:** 100 % of the listed registers read their reset value in the
  SoC/TPU/periph testbenches; LED pins `led_n` = 6'b111111 (all off) during and
  after reset.
- **Status:** NOT RUN

### REQ-SYS-007 — Bus protocol (native valid/ready)
- **Text:** Master and slaves shall implement the protocol of architecture §3:
  (1) the CPU holds `mem_valid`, `mem_addr`, `mem_wdata`, `mem_wstrb`,
  `mem_instr` stable while `mem_valid` = 1 and `mem_ready` = 0; (2) `mem_ready`
  is a single-cycle pulse per transaction; (3) a slave asserts `mem_ready` only
  while `mem_valid` = 1; (4) `mem_rdata` is valid in the `mem_ready` cycle;
  (5) the CPU deasserts `mem_valid` in the cycle after `mem_ready` or starts a
  new transaction; (6) `mem_wstrb` = 0000 means read.
- **Rationale:** the bus is the only CPU <-> TPU interface; protocol errors break
  every system test.
- **Source:** architecture §3; INTERFACES.json `bus`.
- **Verification:** S — a protocol checker (assertions) instantiated in the SoC
  testbench and in each slave testbench.
- **Acceptance:** 0 protocol-checker violations over all CPU test programs and
  the SoC demo; every slave returns `mem_ready` within 4 cycles of
  `mem_valid` (derived bound; no hang).
- **Note (issue 2, open decision OD-R2-1):** ARCHITECTURE.md 10 (A.2) allows reads
  while BUSY; the RTL-TPU slave stalls a READ of INPUT/BIAS/WEIGHT while the TPU
  controller owns those memory ports (tile load / post-processing, <= 33 cycles;
  longest observed valid->ready 35 cycles, SIMULATION, RTL-TPU handoff). That
  case exceeds the 4-cycle bound; the SoC demo itself saw at most 3 cycles. The
  acceptance text is unchanged until the manager rules (proposal: bound 4 cycles
  except reads of INPUT/BIAS/WEIGHT while BUSY, bounded by 40 cycles).
- **Status:** NOT RUN

### REQ-SYS-008 — Little-endian byte lanes
- **Text:** Byte address A maps to `mem_wdata`/`mem_rdata` bits
  [8*(A mod 4)+7 : 8*(A mod 4)]; sub-word writes shall modify only the strobed
  bytes in RAM, TPU buffers and weight RAM.
- **Rationale:** RISC-V is little-endian; buffers pack 4 codes per word.
- **Source:** architecture §3, §5.4, §5.5.
- **Verification:** S.
- **Acceptance:** directed SB/SH/SW then LW/LBU tests on RAM, INPUT, BIAS and
  WEIGHT RAM: 0 mismatches vs the Python ISS memory image.
- **Status:** NOT RUN

### REQ-SYS-009 — Memory map and address decoding
- **Text:** The decoder shall select RAM for addr[31:28] = 0x0, peripherals for
  0x1, SC-TPU for 0x2, using the low 12 bits inside a slave (RAM uses
  addr[11:2]; aliases inside 0x0000_0000–0x0FFF_FFFF allowed).
- **Rationale:** frozen memory map.
- **Source:** architecture §4; INTERFACES.json `memory_map`.
- **Verification:** S.
- **Acceptance:** write/read-back test of every slave register and of first/last
  word of RAM (0x000, 0xFFC) and WEIGHT RAM (0x2000_0800, 0x2000_0FFC):
  0 mismatches.
- **Status:** NOT RUN

### REQ-SYS-010 — Unmapped access behaviour
- **Text:** An access with addr[31:28] not in {0x0, 0x1, 0x2} shall read 0,
  ignore writes, return `mem_ready`, and set the sticky `bus_err` debug flag.
- **Rationale:** a wrong address must not hang the CPU (no bus timeout logic).
- **Source:** architecture §4.
- **Verification:** S.
- **Acceptance:** read of 0x3000_0000 and 0xF000_0000 returns 0x0000_0000 within
  4 cycles; a write there changes no other state; `bus_err` = 1 afterwards and
  stays 1 until reset.
- **Status:** NOT RUN

### REQ-SYS-011 — Peripheral registers
- **Text:** The peripheral block shall implement LED (RW [5:0]), UART_TX (W
  [7:0], ignored while busy), UART_STATUS (R [0] tx_busy), CYCLE (R, free-running
  32-bit counter since reset, wraps modulo 2^32) and TOHOST (RW 32-bit mailbox).
- **Rationale:** minimal observability without firmware.
- **Source:** architecture §4.1; INTERFACES.json `periph_regs`.
- **Verification:** S.
- **Acceptance:** directed tests: each register written/read as specified;
  CYCLE read twice N cycles apart differs by exactly N (N known in TB); a
  UART_TX write while tx_busy = 1 does not alter the frame in progress.
- **Status:** NOT RUN

### REQ-SYS-012 — UART transmitter format and baud error
- **Text:** UART_TX shall send 8N1 frames (1 start bit 0, 8 data bits LSB first,
  1 stop bit 1) at 115200 Bd using a divider of 234 clocks per bit at 27 MHz;
  the absolute baud-rate error shall be <= 2.0 %.
- **Rationale:** standard host terminal setting; 2 % keeps the receiver sampling
  point inside the bit over a 10-bit frame (generic UART tolerance, ASSUMPTION).
- **Source:** architecture §4.1; tolerance derived.
- **Verification:** A — CALCULATION (BUDGETS.md sec. 7: error +0.16 %);
  S — testbench measures the bit period and decodes the frame.
- **Acceptance:** |error| = |27e6/234/115200 - 1| <= 2.0 % (CALCULATION gives
  0.16 %); simulated bit period = 234 clocks exactly; frame = 2340 clocks;
  bytes 0x00, 0x55, 0xA5, 0xFF decoded correctly by the TB receiver.
- **Status:** NOT RUN

### REQ-SYS-013 — LED outputs
- **Text:** `led_n[i]` shall equal NOT LED[i] (LED register bit 1 = LED lit;
  board LEDs active-low).
- **Rationale:** visible result of the demo on hardware.
- **Source:** architecture §4.1; SOURCES S-021; tangnano9k.cst header.
- **Verification:** S (and I of the top-level code).
- **Acceptance:** for LED values 0x00, 0x3F, 0x15, 0x2A the TB observes
  `led_n` = ~value[5:0].
- **Status:** NOT RUN

### REQ-SYS-014 — Top-level ports and pin constraints
- **Text:** `soc_top` shall have exactly the ports of INTERFACES.json
  `top_ports` and every port shall be constrained in
  `design/constraints/tangnano9k.cst` with sourced pin numbers.
- **Rationale:** a bitstream for the real board must route to the right pins.
- **Source:** architecture §7; INTERFACES.json.
- **Verification:** I — compare port list, CST and P&R log (no "unconstrained IO"
  error, no warning about a SoC port missing from the CST).
- **Acceptance:** 10 top-level I/O (clk, reset button, 6 LEDs, uart_tx,
  uart_rx), all with IO_LOC; P&R log has 0 constraint warnings for SoC ports.
  (Issue 2: the REQ-01 note on a `btn_s1_n` / `btn_rst_n` name mismatch is
  withdrawn - the CST names the port `btn_rst_n` since commit 199a3dc, OD-1
  closed. Which of pins 3/4 is silkscreen S1 remains an ASSUMPTION, CST header.)
- **Status:** NOT RUN

### REQ-SYS-015 — No firmware
- **Text:** The project shall not contain target firmware (no C/assembly
  application, driver or bootloader). CPU programs shall exist only as
  instruction sequences generated by the Python reference assembler for
  testbenches / ROM init files used for verification.
- **Rationale:** explicit scope limit.
- **Source:** user, definition (Out of scope), CLAUDE.md.
- **Verification:** I — repository scan.
- **Acceptance:** 0 files `*.c`, `*.S`, `*.s`, `*.ld` and no cross-compiler use in
  the release; every `prog.hex` traceable to a generator script in
  `code/python/rv32/`.
- **Status:** NOT RUN

### REQ-SYS-016 — SoC end-to-end demo
- **Text:** With the SoC demo program the simulated SoC shall configure the TPU,
  START an inference, poll DONE, read RESULT, write RESULT to LED and UART and
  write TOHOST = 1.
- **Rationale:** demonstrates CPU + bus + TPU integration.
- **Source:** architecture §8.
- **Verification:** S — SoC testbench.
- **Acceptance:** TOHOST = 1 within a TB timeout of 200 000 cycles; RESULT,
  LED value and the UART byte equal the golden-model class of the default image.
- **Status:** NOT RUN

### REQ-SYS-017 — Power estimate
- **Text:** The engineering report shall state an order-of-magnitude power
  estimate with its basis and labels, and state that no open Gowin power model
  exists.
- **Rationale:** article/report completeness; no power requirement exists in the
  definition.
- **Source:** derived.
- **Verification:** A — BUDGETS.md sec. 6.
- **Acceptance:** estimate present, labelled ASSUMPTION; no power value
  presented as SIMULATION or MEASUREMENT.
- **Status:** NOT RUN

## 2. CPU (CPU)

### REQ-CPU-001 — RV32I instruction set
- **Text:** The CPU shall execute the 37 RV32I base instructions (LUI, AUIPC,
  JAL, JALR, BEQ, BNE, BLT, BGE, BLTU, BGEU, LB, LH, LW, LBU, LHU, SB, SH, SW,
  ADDI, SLTI, SLTIU, XORI, ORI, ANDI, SLLI, SRLI, SRAI, ADD, SUB, SLL, SLT,
  SLTU, XOR, SRL, SRA, OR, AND) with the semantics of the RISC-V Unprivileged
  ISA (RV32I base, document D-19 in SOURCES.md), FENCE as a NOP, and ECALL /
  EBREAK as traps (REQ-CPU-004).
- **Rationale:** product definition item 1.
- **Source:** definition; architecture §6.
- **Verification:** S — directed per-instruction tests compared with the Python
  ISS (`code/python/rv32/iss.py`).
- **Acceptance:** every instruction has >= 1 directed test covering its corner
  cases (rd = x0, negative immediates, sign extension, shift amounts 0 and 31,
  signed/unsigned compare of 0x8000_0000 vs 0x7FFF_FFFF, branches taken and not
  taken forward and backward, JALR with odd target bit 0 cleared); after every
  retired instruction PC and x1..x31 equal the ISS: 0 mismatches.
- **Status:** NOT RUN

### REQ-CPU-002 — Register x0
- **Text:** x0 shall read 0 at all times; writes to x0 shall have no effect.
- **Source:** architecture §6 (RISC-V base).
- **Verification:** S.
- **Acceptance:** each instruction class with rd = x0 followed by a read of x0
  returns 0 (0 mismatches).
- **Status:** NOT RUN

### REQ-CPU-003 — CPU reset state
- **Text:** On reset PC = 0x0000_0000, x1..x31 = 0, `halted` = 0,
  `trap_cause` = 0.
- **Source:** architecture §6 (register reset ASSUMPTION for determinism).
- **Verification:** S.
- **Acceptance:** TB reads all registers through a test program (stores to RAM)
  after reset: all 0; first fetch at 0 (REQ-SYS-005).
- **Status:** NOT RUN

### REQ-CPU-004 — Trap causes and halt
- **Text:** ECALL, EBREAK, illegal instructions, a taken jump/branch to a target
  not 4-byte aligned, misaligned LH/LHU/LW and misaligned SH/SW shall stop the
  CPU with `halted` = 1 and `trap_cause` = 1, 2, 3, 4, 5, 6 respectively;
  for cause 4 the halt PC is the address of the jump/branch (rev A.1).
  No interrupts and no CSRs exist.
- **Rationale:** without CSRs/trap vectors, halting is the simplest observable
  and safe trap behaviour for verification.
- **Source:** architecture §6, §9; INTERFACES.json `cpu.traps`; ADR-006.
- **Verification:** S.
- **Acceptance:** one directed test per cause (>= 6 tests, plus misaligned
  byte offsets 1, 2, 3 for LW/SW and 1, 3 for LH/SH): `halted` and
  `trap_cause` as specified, `dbg_pc` = address of the trapping instruction.
- **Status:** NOT RUN

### REQ-CPU-005 — Trap side-effect freedom
- **Text:** A trapping instruction shall not write rd, shall not perform its
  memory write, and the CPU shall issue no further bus request after halting.
- **Rationale:** makes trap behaviour comparable with the ISS and prevents
  spurious writes to TPU/peripheral registers.
- **Source:** derived (from architecture §6 "stop the CPU").
- **Verification:** S.
- **Acceptance:** in every REQ-CPU-004 test: target rd unchanged, the addressed
  memory word unchanged, 0 `mem_valid` assertions during 100 cycles after `halted`.
- **Status:** NOT RUN

### REQ-CPU-006 — Strict decoding (illegal set)
- **Text:** The following shall raise cause 3 (illegal): any opcode not in the
  RV32I set; SYSTEM instructions other than ECALL/EBREAK (all CSR*); unknown
  funct3/funct7 combinations (e.g. the M extension); FENCE.I; 0x0000_0000 and
  0xFFFF_FFFF; SLLI/SRLI/SRAI with imm[11:5] other than 0x00 / 0x00 / 0x20.
- **Source:** architecture §9 (rev A.1, ADR-006); last item derived from the
  RV32I encoding (shamt[5] = 1 is reserved in RV32).
- **Verification:** S.
- **Acceptance:** >= 1 directed test per listed class: trap cause 3, no state change.
- **Status:** NOT RUN

### REQ-CPU-007 — Loads/stores: extension, strobes, lanes
- **Text:** LB/LH shall sign-extend, LBU/LHU zero-extend; SB/SH/SW shall drive
  `mem_wstrb` = 0001<<(A mod 4), 0011<<(A mod 4), 1111 respectively, with
  `mem_wdata` already shifted to the addressed byte lanes.
- **Source:** architecture §3, §6.
- **Verification:** S.
- **Acceptance:** all aligned offsets (0..3 bytes, 0/2 halves) tested with data
  0x80/0x7F and 0x8000/0x7FFF: 0 mismatches vs ISS.
- **Status:** NOT RUN

### REQ-CPU-008 — Debug outputs and retire count
- **Text:** The CPU shall provide `halted`, `trap_cause[3:0]`, `dbg_pc[31:0]`
  and a one-cycle `retire` pulse per completed (non-trapping) instruction.
- **Source:** architecture §6; INTERFACES.json `cpu.debug_ports`.
- **Verification:** S.
- **Acceptance:** number of `retire` pulses = ISS retired-instruction count for
  every CPU test program (0 differences).
- **Status:** NOT RUN

### REQ-CPU-009 — CPI reported
- **Text:** The CPI per instruction class (ALU, branch taken/not taken, jump,
  load, store) shall be measured in simulation and reported; no CPI value is
  required.
- **Source:** architecture §6.
- **Verification:** S.
- **Acceptance:** table of measured CPI (SIMULATION, log path) in the engineering report.
- **Status:** NOT RUN

### REQ-CPU-010 — Random-program cross-check vs ISS
- **Text:** The CPU should be cross-checked against the ISS on generated
  random (non-trapping) instruction sequences.
- **Rationale:** directed tests miss interaction bugs (forwarding of the same
  register, back-to-back loads/stores).
- **Source:** derived.
- **Verification:** S.
- **Acceptance:** >= 10 000 retired instructions over >= 10 seeds with 0
  architectural-state mismatches (seeds recorded).
- **Status:** NOT RUN

## 3. SC-TPU (TPU)

### REQ-TPU-001 — Geometry and dataflow
- **Text:** The SC-TPU shall be a weight-stationary array of NL = 16 neuron
  lanes x IL = 8 input lanes executing MLP 64-16-10 as 8 + 2 tiles.
- **Source:** architecture §5.1; ADR-002.
- **Verification:** I — RTL parameters and PARAMS register.
- **Acceptance:** RTL parameters NL = 16, IL = 8 in the release build.
- **Status:** NOT RUN

### REQ-TPU-002 — Register map and reset values
- **Text:** The TPU shall implement the register map of architecture §5.4
  (CTRL, STATUS, CONFIG, RESULT, CYCLES, PARAMS, INPUT, SCORE, HIDDEN, BIAS,
  WEIGHT RAM) with the stated access types, packing and reset values.
  Read-back rules of rev A.2: CONFIG returns the clamped LOG2_L actually used
  (REQ-TPU-007); BIAS words read back sign-extended from [15:0] and bits
  [31:16] of a write are ignored.
- **Source:** architecture §5.4, §9, §10 (A.2, ADR-007); INTERFACES.json `tpu.regs`.
- **Verification:** S.
- **Acceptance:** register test writes/reads every RW location with two
  patterns (0x5555_5555, 0xAAAA_AAAA, masked to the defined bits; BIAS
  expected = sign-extension of [15:0], i.e. 0x0000_5555 and 0xFFFF_AAAA) and
  checks R registers are not modified by writes: 0 mismatches.
- **Status:** NOT RUN

### REQ-TPU-003 — PARAMS register value (version 0x03)
- **Text:** PARAMS shall read {[31:24] version **0x03**, [17:16] RNG_MODE,
  [15:8] IL = 8, [7:0] NL = 16}, all other bits 0. The version identifies the
  seed revision of the build (0x01 rev A, 0x02 rev B, 0x03 rev C); a build
  with version != 0x03 is not a release build.
- **Rationale:** lets a testbench (and later the hardware validation) detect a
  bitstream built with superseded seeds, which would invalidate the rev C
  golden vectors.
- **Source:** architecture §5.4, §12 (rev C, ADR-010); INTERFACES.json `tpu.regs.PARAMS`.
- **Verification:** S.
- **Acceptance:** PARAMS = 0x0300_0810 (mode 0), 0x0301_0810 (mode 1),
  **0x0302_0810 (mode 2, release default)** (CALCULATION from the bit fields:
  0x03<<24 | mode<<16 | 8<<8 | 16).
- **Status:** NOT RUN

### REQ-TPU-004 — Code representation, SNG, XNOR, APC
- **Text:** Each code c in 0..255 shall be converted to a stream bit
  b = (r < c) with r the 8-bit random value of the lane; products shall be
  XNOR(b_x, b_w); each stream cycle acc_j shall increase by the popcount of the
  IL products of neuron lane j.
- **Source:** architecture §5.2, §5.3 [BIT-EXACT].
- **Verification:** S — covered by REQ-TPU-013 plus a unit test of one lane.
- **Acceptance:** unit test with forced r values: b and acc increments equal
  the model for all 256 c values and r in {0, 1, 127, 128, 254, 255}.
- **Status:** NOT RUN

### REQ-TPU-005 — LFSR definition and sequencing
- **Text:** Each LFSR shall implement fb = s[15]^s[13]^s[12]^s[10],
  s' = ((s<<1)|fb) & 0xFFFF, advance 8 steps per stream cycle and use the low
  byte of the new state as r; LFSRs shall load the **rev C deployed seeds**
  (Conventions) when START is accepted and advance only in stream cycles (not
  during loads, post-processing or idle), and shall not be reloaded between
  tiles or layers.
- **Source:** architecture §5.3, §12 (rev C, supersedes the seed text of §5.3
  and §11); ADR-005, ADR-010; INTERFACES.json revision C `tpu.lfsr`.
- **Verification:** S — LFSR state trace compared with `code/python/sctpu/lfsr.py`
  (rev C trace files); A — seed tables re-derived from the formulas.
- **Acceptance:** for one full inference at K = 4 in each RNG mode, the TB
  compares every LFSR state at every stream cycle with the model (trace files
  stamped `# spec_rev C`): 0 mismatches; the state does not change in
  non-stream cycles (checked every cycle); the 18 seed values in the RTL equal
  the rev C tables (16 mode-2 values + 0xACE1/0xF9DE). (Analysis, CALCULATION:
  the polynomial is maximal-length, period 65535; the mode-2 tables equal the
  formulas and 0xF9DE = S(32768) — `scripts/budgets/logs/lfsr_check.log`,
  `scripts/budgets/logs/lfsr_rules_revC.log`.)
- **Status:** NOT RUN

### REQ-TPU-006 — RNG modes, default mode 2, seed rules R1/R2
- **Text:** RNG_MODE shall be a synthesis parameter with default **2** and
  modes 0 SHARED (one LFSR_X seed 0xACE1, one LFSR_W seed 0xF9DE),
  1 ROTATE (same two LFSRs; lane i uses rotl8(r, i)), 2 INDEPENDENT
  (per-input-lane LFSR pairs, seed_x_i = (0xACE1 + 0x3C5A*i) mod 2^16,
  seed_w_i = (0x7A5C + 0x2B67*i) mod 2^16, i = 0..7, rev C tables in the
  Conventions). The mode-2 seed set shall satisfy the seed rules **R1** and
  **R2** (Conventions). Any future seed change shall be re-checked against R1
  and R2 *and* re-selected on the validation split before the test split is
  evaluated (ADR-009 protocol); maximal phase spacing alone is not an
  acceptable criterion (rev B lesson, ADR-009).
- **Rationale:** rev B (phase-spaced seeds, all X_i/W_i advanced by the same
  4096 steps per lane) violated R1 on all 28 lane pairs and lost 4.7 pp at K = 9
  (p = 0.0015, ADR-009); R1 excludes exactly that failure, R2 also excludes the
  second-order shared-bit coupling (SW-03).
- **Source:** architecture §5.3, §11, §12; ADR-003 (closed), ADR-008, ADR-009,
  ADR-010; INTERFACES.json revision C `tpu.rng_mode_default`,
  `tpu.lfsr.seed_rule`, `tpu.lfsr.decorrelation_rules`.
- **Verification:** S — REQ-TPU-013 run for each mode; A — R1/R2 check of the
  seed set (CALCULATION, exhaustive over the m-sequence).
- **Acceptance:** (a) all three modes simulate bit-exactly (REQ-TPU-013 (b))
  and synthesise/P&R (REQ-RES-006); (b) the release build (default parameter)
  has RNG_MODE = 2 (PARAMS = 0x0302_0810, REQ-TPU-003); (c) for the mode-2 seed
  set: R1 0 violating lane pairs of 28, R2 0 direct and 0 swapped violations,
  minimum pairwise lag 321 stream cycles (X0-W3), as stated in ARCHITECTURE.md
  12 / INTERFACES.json `min_lag_stream_cycles`, computed by two independent
  implementations (software-engineer golden model, SW-03; systems-engineer
  `scripts/budgets/lfsr_rules_revC.py`).
- **Status:** NOT RUN

### REQ-TPU-007 — LOG2_L clamp
- **Text:** The effective K shall be clamp(CONFIG.LOG2_L, 4, 10), and CONFIG
  shall read back the clamped value actually used.
- **Source:** architecture §5.3, §10 (A.2, ADR-007; closes OD-3).
- **Verification:** S.
- **Acceptance:** CONFIG.LOG2_L = 0, 3 give results and CYCLES identical to
  K = 4; 11, 15 identical to K = 10; read-back after writing 15 is 10 and after
  writing 1 is 4 (every raw value 0..15 checked).
- **Status:** NOT RUN

### REQ-TPU-008 — Post-processing exactness and widths
- **Text:** Post-processing shall compute exactly D = 2*acc - N_in*L,
  B = floor(bias*2^K/128), Dp = D + B, hidden code = 128 + clip(floor(Dp *
  2^(s+7) / 2^K), 0, 127) and SCORE = Dp (sign-extended), with internal widths
  that cannot overflow for any legal input (K in 4..10, s in 0..7, any int16
  bias, any codes).
- **Rationale:** the formula's intermediate Dp*2^(s+7) reaches ~2^32.3 in exact
  arithmetic (beyond int32); a 32-bit or truncating implementation would silently differ from
  the model at extreme settings.
  ARCHITECTURE.md 10 (A.2) states the same: intermediates wide enough (or
  early saturation) so that the result equals the formula for every legal
  input, worst case |Dp * 2^(s+7)| < 2^34; the RTL documents its widths.
- **Source:** architecture §5.3 [BIT-EXACT], §10 (A.2, ADR-007; closes OD-13);
  widths derived (BUDGETS.md sec. 1.3).
- **Verification:** A (width analysis) + S (corner vectors).
- **Acceptance:** analysis shows |D| <= 65536, |B| <= 262144, |Dp| <= 327680
  (>= 20-bit signed) and a saturating or wide-enough hidden shift; corner sims
  with bias = +32767 and -32768, K = 4 and 10, s = 0 and 7, all-0 and all-255
  codes: 0 mismatches vs the model.
- **Status:** NOT RUN

### REQ-TPU-009 — Argmax and tie rule
- **Text:** RESULT shall be the index of the maximum SCORE over lanes 0..9 with
  ties resolved to the lowest index; lanes 10..15 shall be ignored.
- **Source:** architecture §5.3.
- **Verification:** S.
- **Acceptance:** directed tests with a 2-way tie, a 10-way tie (expect 0), and
  a maximum in a padding lane 10..15 (expect it ignored): 0 mismatches.
- **Status:** NOT RUN

### REQ-TPU-010 — START / BUSY / DONE semantics
- **Text:** Writing CTRL[0] = 1 while BUSY = 0 shall start an inference
  (BUSY = 1, DONE = 0); writes to CTRL while BUSY = 1 shall be ignored; at the
  end BUSY = 0 and DONE = 1 until the next START.
- **Source:** architecture §5.3, §5.4.
- **Verification:** S.
- **Acceptance:** directed test: START while BUSY does not restart (CYCLES and
  RESULT equal a single run); DONE stays 1 across >= 1000 idle cycles.
- **Status:** NOT RUN

### REQ-TPU-011 — Writes while BUSY ignored
- **Text:** CPU writes to INPUT, BIAS, WEIGHT RAM and CONFIG while BUSY = 1
  shall be ignored (still acknowledged with `mem_ready`). CPU reads while
  BUSY = 1 are allowed and return the current storage contents (SCORE/HIDDEN
  may be partially updated).
- **Source:** architecture §5.4, §10 (A.2, ADR-007; closes OD-6),
  INTERFACES.json `busy_writes`. Read latency while BUSY: see REQ-SYS-007 note.
- **Verification:** S.
- **Acceptance:** writes during BUSY leave the result bit-exact with the
  undisturbed run, and read-back afterwards shows the old contents; reads
  during BUSY complete (no hang) and return the stored value.
- **Status:** NOT RUN

### REQ-TPU-012 — Weight memory layout and init files
- **Text:** Weight RAM byte address = base_l + (floor(i/IL)*NL + j)*IL +
  (i mod IL), base_1 = 0, base_2 = 1024; init files weights.hex (512 x 32 bit),
  bias.hex (32 x 16 bit), input.hex (16 x 32 bit), prog.hex (1024 x 32 bit) in
  `sim/data/`.
- **Source:** architecture §5.5, §5.6.
- **Verification:** S (model and RTL use the same files) + I (line counts).
- **Acceptance:** line counts exactly 512/32/16/1024; RTL weight RAM after init
  equals the model's weight array byte for byte.
- **Status:** NOT RUN

### REQ-TPU-013 — Bit-exact equivalence RTL vs golden model
- **Text:** For every tested (image, K, ACT_SHIFT, RNG_MODE) the RTL shall
  produce SCORE[0..15], HIDDEN[0..15] and RESULT identical to the Python
  bit-exact golden model.
- **Rationale:** accuracy is measured on the model; it transfers to the RTL only
  if the two are bit-identical.
- **Source:** definition (item 3: "bit-exact model vs RTL"); architecture §5.
- **Verification:** S — TPU testbench reading model-generated expected values.
- **Acceptance:** all expected values generated by the golden model for spec
  rev C (files stamped `# spec_rev C`, deployed seeds); 0 mismatching words
  over (a) all 360 test-split images at K = 8, selected ACT_SHIFT and selected
  RNG mode (2); (b) >= 3 images x K in
  {4,5,...,10} x RNG_MODE in {0,1,2} x ACT_SHIFT in {0, 3, 7}; (c) corner
  vectors of REQ-TPU-008 and REQ-TPU-009.
- **Status:** NOT RUN

### REQ-TPU-014 — CYCLES register
- **Text:** CYCLES shall hold the number of rising clock edges during which
  STATUS.BUSY = 1 for the last inference, and shall be deterministic (a
  function of K only).
- **Source:** architecture §5.3, §5.4, §10 (A.2, ADR-007; closes OD-4).
- **Verification:** S.
- **Acceptance:** for K = 4..10 CYCLES equals the RTL designer's documented
  closed-form formula exactly, and the TB-counted BUSY cycles (rising edges
  with BUSY = 1) equal CYCLES. Upper bound: REQ-TIM-004.
- **Status:** NOT RUN

### REQ-TPU-015 — Reserved TPU offsets
- **Text:** Reads of offsets inside the TPU window that are not listed in §5.4
  (0x018–0x03F, 0x0D0–0x0FF, 0x180–0x7FF) shall return 0 and writes shall be
  ignored, with `mem_ready` returned.
- **Rationale:** removes ambiguity; proposed in REQ-01 (OD-5) and adopted in
  the spec as rev A.2.
- **Source:** architecture §10 (A.2, ADR-007; closes OD-5 for the TPU window;
  issue 1: derived).
- **Verification:** S.
- **Acceptance:** read of 0x2000_0018, 0x2000_00D0, 0x2000_0180, 0x2000_07FC
  returns 0; writes there change no register.
- **Status:** NOT RUN

### REQ-TPU-016 — Reset during an inference
- **Text:** Asserting `rst` while BUSY = 1 shall return the TPU to the reset
  state of REQ-SYS-006 within 1 cycle of `rst` being sampled; a subsequent
  START shall produce a bit-exact result.
- **Source:** derived (from "reset value of every architectural register is defined").
- **Verification:** S.
- **Acceptance:** reset at a random stream cycle, then START: 0 mismatches.
- **Status:** NOT RUN

## 4. AI workload (AI)

### REQ-AI-001 — Network and dataset
- **Text:** The workload shall be an MLP 64-16-10 with clipped-ReLU hidden
  layer, trained offline in Python on the scikit-learn 8x8 digits dataset,
  weights quantised to 8-bit codes.
- **Source:** definition (item 3); architecture §5.1.
- **Verification:** I.
- **Acceptance:** training script and exported hex files present; shapes 64x16,
  16x10 (+ padding), biases int16.
- **Status:** NOT RUN

### REQ-AI-002 — Reproducible split and training
- **Text:** The train/test split, the validation split and the training shall
  be deterministic (fixed seeds), and the test split shall never be used for
  training, early stopping or hyper-parameter / mode / K / **LFSR seed**
  selection; a seed or mode selection shall follow a protocol fixed before the
  candidates are evaluated (ADR-009) and shall load only the validation split.
- **Rationale:** otherwise the reported accuracy is optimistic.
- **Source:** derived.
- **Verification:** I (code) + S (re-run reproduces identical weights.hex).
- **Acceptance:** two runs give identical sha256 of weights.hex/bias.hex; the
  test split appears only in evaluation code; the seed-selection run
  (`sctpu.seed_select`) does not load the test split.
- **Status:** NOT RUN

### REQ-AI-003 — Reference (float / EV) accuracy
- **Text:** The float master model and the EV model shall reach >= 94.0 %
  accuracy on the test split.
- **Rationale:** a 64-16-10 MLP on 8x8 digits commonly reaches about 95-97 %;
  the preliminary project SIMULATION (WIP, `logs/sw/accuracy.log`,
  rev d2ed476-dirty) shows float = EV = 95.0-95.8 % for the trained variants.
  94.0 % leaves ~1 pp (~4 images) for retraining variance.
- **Source:** derived.
- **Verification:** S.
- **Acceptance:** float >= 94.0 %, EV >= 94.0 % (n = 360).
- **Status:** NOT RUN

### REQ-AI-004 — SC accuracy at L = 256
- **Text:** The bit-exact model with the selected RNG mode, the deployed seeds,
  K = 8 (L = 256) and the selected ACT_SHIFT shall reach >= 90.0 % accuracy on
  the test split.
- **Rationale:** L = 256 is the reset default and the latency/accuracy
  compromise of the budget (~110 us per inference, BUDGETS.md sec. 3). The
  preliminary SIMULATION (same WIP log) gives 91.1 % (mode 1) and 94.4 %
  (mode 2) for the selected variant and 65.6 % (mode 0), so 90 % is
  achievable by modes 1/2 and rules out mode 0. (Issue 2: the selected mode is
  2 and the deployed seeds are rev C; the threshold itself is unchanged and
  still awaits explicit confirmation, OD-11.)
- **Source:** derived (manager proposal confirmed by the preliminary data).
- **Verification:** S.
- **Acceptance:** accuracy >= 90.0 % (>= 324 of 360 images correct).
- **Status:** NOT RUN

### REQ-AI-005 — SC accuracy gap vs EV at the operating K
- **Text:** For the selected RNG mode there shall be an operating point
  K_op <= 9 such that for every K in K_op..10 the bit-exact accuracy is
  >= (EV accuracy - 2.0 pp); K_op shall be reported.
- **Rationale:** quantifies the SC penalty; the preliminary SIMULATION gives
  K_op = 9 (mode 1) and K_op = 8 (mode 2); at K = 8 mode 1 is 3.9 pp below EV,
  so the 2 pp criterion is applied at K_op, not at K = 8.
- **Source:** derived.
- **Verification:** S.
- **Acceptance:** K_op reported and <= 9; gap <= 2.0 pp for all K >= K_op.
- **Status:** NOT RUN

### REQ-AI-006 — Seed-ensemble accuracy
- **Text:** The mean accuracy of the bit-exact model over >= 20 alternative LFSR
  seed sets at K = 8 (selected mode) shall be >= 90.0 %, and the deployed-seed
  accuracy shall lie within mean +/- 2 standard deviations of the ensemble.
  An alternative seed set may be the deployed rev C set with every generator
  advanced by a common, randomly drawn start offset (method of SW-02/SW-03);
  this keeps the relative lags, hence R1/R2, of the deployed set (issue 2
  clarification).
- **Rationale:** the hardware uses one fixed seed set; this shows the reported
  number is not a lucky (or unlucky) seed choice. Preliminary SIMULATION:
  93.3 +/- 1.9 % (mode 1), 92.7 +/- 1.5 % (mode 2).
- **Source:** derived.
- **Verification:** S.
- **Acceptance:** ensemble mean >= 90.0 %; |deployed - mean| <= 2 sigma.
- **Status:** NOT RUN

### REQ-AI-007 — Statistical reporting
- **Text:** Every reported accuracy shall state n, the number of correct images
  and a 95 % binomial confidence interval (Wilson).
- **Rationale:** with n = 360 the 95 % half-width is about +/-2.6 pp at 93 %
  (CALCULATION, BUDGETS.md sec. 8), larger than the 2 pp gap of REQ-AI-005.
- **Source:** derived.
- **Verification:** A / I.
- **Acceptance:** all accuracy tables in article and report include n, k and CI.
- **Status:** NOT RUN

### REQ-AI-008 — int8 binary baseline
- **Text:** The accuracy of an exact int8 (binary MAC) implementation of the same
  quantised network shall be reported as the non-SC baseline.
- **Source:** architecture (ADR-001 option B kept as baseline).
- **Verification:** S.
- **Acceptance:** value present with label SIMULATION and log path.
- **Status:** NOT RUN

### REQ-AI-009 — Error analysis vs K
- **Text:** The RMS error of the layer-1 and layer-2 pre-activations of the
  bit-exact model with respect to the EV model shall be reported for K = 4..10
  and all RNG modes, together with an analytic prediction.
- **Source:** definition ("accuracy / error analysis").
- **Verification:** S + A.
- **Acceptance:** table/figure present; the measured RMS for the selected mode
  is within a factor 2 of the analytic prediction for K >= 7 (derived sanity bound).
- **Status:** NOT RUN

### REQ-AI-010 — RNG mode selection study
- **Text:** RNG_MODE and the deployed seed set shall be selected by comparing
  test-independent (validation) accuracy against the LUT/FF cost of each
  mode, and the decision recorded in an ADR. The rev A -> B -> C iteration
  (ADR-008, ADR-009, ADR-010), including the defective rev B, shall be
  reported as part of the study (negative result kept in the record).
- **Source:** architecture (ADR-003, closed by ADR-008 and ADR-010; ADR-009).
- **Verification:** S + A.
- **Acceptance:** table accuracy(K, mode) and LUT/FF(mode) in the report;
  the closing ADR (ADR-010) names the selected mode (2) and seed set (rev C)
  and cites the validation-split evidence (`reports/sw/seed_selection_revC.md`);
  rev B is reported as a negative result.
- **Status:** NOT RUN

### REQ-AI-011 — Golden model and hex export
- **Text:** The Python golden model shall implement every [BIT-EXACT] rule of
  the spec, export the init files of REQ-TPU-012 and the per-image expected
  SCORE/HIDDEN/RESULT used by the RTL testbenches.
- **Source:** definition; architecture §5.3, §5.6.
- **Verification:** S (unit tests incl. LFSR known answers) + I.
- **Acceptance:** pytest suite passes (0 failures); LFSR period test = 65535.
- **Status:** NOT RUN

## 5. Resources (RES)

All figures from the nextpnr-himbaechel-gowin "Device utilisation" report of
the release SoC build (worst of the RNG modes actually released). Capacities:
SOURCES S-027..S-033.

### REQ-RES-001 — LUT4 utilisation
- **Text:** LUT4 utilisation shall be <= 85 % of 8640, i.e. <= 7344 LUT4.
- **Rationale:** "fit with margin" (definition). 15 % headroom keeps the router
  out of the congestion region and leaves room for fixes after V1 (engineering
  practice, ASSUMPTION). Budget: ~68 % predicted (BUDGETS.md sec. 1.4).
- **Source:** definition (Hard constraints) -> derived number; 85 % rule
  confirmed by ARCHITECTURE.md 10 (A.2, ADR-007; closes OD-2).
- **Verification:** A — P&R report.
- **Acceptance:** LUT4 used <= 7344.
- **Status:** NOT RUN

### REQ-RES-002 — Flip-flop utilisation
- **Text:** DFF utilisation shall be <= 85 % of 6480, i.e. <= 5508.
- **Source:** definition -> derived.
- **Verification:** A.
- **Acceptance:** DFF used <= 5508 (budget ~40 %).
- **Status:** NOT RUN

### REQ-RES-003 — ALU / LUT-RAM / DSP utilisation
- **Text:** ALU <= 85 % of 6480 (<= 5508), RAM16SDP4 <= 85 % of 270 (<= 229),
  multipliers (MULT9X9/MULT18X18/MULT36X36/ALU54D) <= 85 % of capacity; the
  SC datapath should use 0 DSP blocks.
- **Source:** definition -> derived.
- **Verification:** A.
- **Acceptance:** each line of the report within its bound.
- **Status:** NOT RUN

### REQ-RES-004 — BSRAM utilisation and inference
- **Text:** BSRAM utilisation shall be <= 85 % of 26 (<= 22 blocks); the 4 KiB
  RAM and the 2 KiB weight RAM shall be implemented in BSRAM, not in LUTs/FFs.
- **Rationale:** a failed BSRAM inference would add ~49 000 bits of FFs, which
  does not fit (BUDGETS.md sec. 2).
- **Source:** definition, architecture §1/§5.4 -> derived.
- **Verification:** A — utilisation report and synthesis log (memory mapping).
- **Acceptance:** BSRAM used >= 3 and <= 22; synthesis log shows the RAM and
  weight-RAM memories mapped to BSRAM primitives (SP/SDPB/DPB).
- **Status:** NOT RUN

### REQ-RES-005 — I/O usage
- **Text:** The design shall use only the 10 top-level I/Os of REQ-SYS-014.
- **Source:** architecture §7.
- **Verification:** I.
- **Acceptance:** IOB used = 10 in the report.
- **Status:** NOT RUN

### REQ-RES-006 — Variant resource report
- **Text:** LUT4/ALU/DFF/BSRAM and Fmax shall be reported for RNG_MODE 0, 1, 2
  (and for IL = 4/16 if the IL study of ADR-002 is run). A variant that does not
  place/route is reported as such with its utilisation (ADR-007: IL = 16 is kept
  only as a reported variant that does not fit; closes OD-8).
- **Source:** architecture (ADR-002, ADR-003, ADR-007).
- **Verification:** A.
- **Acceptance:** table in the engineering report with log paths; for a
  variant without a routed design the nextpnr error line is quoted.
- **Status:** NOT RUN

## 6. Timing and latency (TIM)

### REQ-TIM-001 — Timing closure at 27 MHz with margin
- **Text:** The post-route maximum frequency of `clk` reported by nextpnr shall
  be >= 29.7 MHz (27 MHz + 10 %), i.e. worst register-to-register path
  <= 33.67 ns, for the worst of placement seeds 1, 2 and 3.
- **Rationale:** hard constraint "meet timing at 27 MHz"; 10 % margin covers
  seed variation and the unverified accuracy of the reverse-engineered timing
  model (risk R-05). Budget: critical candidates 52-91 MHz (BUDGETS.md sec. 5).
  The release flow is `synth_gowin -nowidelut` (ADR-011).
- **Source:** definition -> derived; margin definition confirmed by
  ARCHITECTURE.md 10 (A.2, ADR-007; closes OD-2).
- **Verification:** A — P&R logs (`Max frequency for clock`).
- **Acceptance:** min over seeds 1..3 of Fmax >= 29.7 MHz. NOTE: the nextpnr
  Gowin timing model is not validated against silicon; PASS here is not a
  hardware timing proof.
- **Status:** NOT RUN

### REQ-TIM-002 — Synchronous design rules
- **Text:** The RTL shall contain no latches, no combinational loops, no
  asynchronous resets of internal logic and no clock gating.
- **Source:** derived (single synchronous domain, architecture §2).
- **Verification:** I + A — Yosys log (`check`, latch inference) and nextpnr log.
- **Acceptance:** 0 latches (`$dlatch`), 0 combinational-loop warnings in the
  release logs.
- **Status:** NOT RUN

### REQ-TIM-003 — Asynchronous inputs
- **Text:** Every asynchronous input (reset button; `uart_rx` if ever used) shall
  pass through a >= 2-FF synchroniser before use.
- **Source:** architecture §2.
- **Verification:** I.
- **Acceptance:** code review checklist item ticked for every top-level input.
- **Status:** NOT RUN

### REQ-TIM-004 — Inference latency
- **Text:** The TPU latency CYCLES(K) shall be <= 1.10 x N_budget(K) with
  N_budget(K) = 10*2^K + 409 cycles, for K = 4..10.
- **Rationale:** keeps the RTL within the latency budget; at K = 8 this is
  <= 3265 cycles = 120.9 us at 27 MHz (CALCULATION).
- **Source:** derived (BUDGETS.md sec. 3).
- **Verification:** S (CYCLES register) + A.
- **Acceptance:** measured CYCLES(K) <= floor(1.10 x N_budget(K)) for all K:
  K=4: 625, 5: 801, 6: 1153, 7: 1857, 8: 3265, 9: 6081, 10: 11713 cycles.
- **Status:** NOT RUN

### REQ-TIM-005 — CPU-side inference time reported
- **Text:** The SoC simulation shall report the end-to-end cycles of one
  inference driven by the CPU (write 64 input codes, START, poll DONE, read
  RESULT) measured with the CYCLE register.
- **Source:** derived.
- **Verification:** S.
- **Acceptance:** value reported (SIMULATION, log path); no bound (information).
- **Note (issue 2, ADR-011):** the release demo program does not write the 64
  input codes and does not read CYCLE; the manager accepted for V1 that only
  START -> RESULT-read and reset -> TOHOST are reported, listed as a
  limitation. Text and acceptance unchanged; the verification status is set
  in the status matrix.
- **Status:** NOT RUN

## 7. Documentation (DOC)

### REQ-DOC-001 — RTL commenting standard
- **Text:** Every RTL and testbench file shall have a header (purpose,
  interfaces, timing/latency, parameters, assumptions, requirement IDs), a
  comment on every port, register/state variable, FSM state and always/assign
  block explaining what and why, and use `default_nettype none` /
  `default_nettype wire`.
- **Rationale:** user requirement "comment everything thoroughly".
- **Source:** user; CLAUDE.md; rtl-gowin-flow skill.
- **Verification:** I (checklist per file) + A (comment-ratio script).
- **Acceptance:** checklist 100 % of files; comment lines >= 30 % of non-blank
  lines per file (derived indicative metric; a file below it needs a reviewer
  waiver).
- **Status:** NOT RUN

### REQ-DOC-002 — Python / script commenting standard
- **Text:** Every Python module, class and function and every script shall have
  a docstring/header stating purpose, inputs/outputs, units and assumptions.
- **Source:** user; CLAUDE.md.
- **Verification:** I + A.
- **Acceptance:** 100 % of public functions have docstrings (checked by script);
  comment+docstring lines >= 25 % of non-blank lines per file (indicative).
- **Status:** NOT RUN

### REQ-DOC-003 — Language
- **Text:** All files, code, comments and reports shall be in English.
- **Source:** user; CLAUDE.md.
- **Verification:** I.
- **Acceptance:** reviewer finds 0 non-English passages.
- **Status:** NOT RUN

### REQ-DOC-004 — Number labels and status words
- **Text:** Every number in reports, article and handoffs shall carry one of
  SOURCE / CALCULATION / SIMULATION / MEASUREMENT / ASSUMPTION, and statuses
  shall use only PASS / PARTIAL / FAIL / BLOCKED / NOT RUN; no MEASUREMENT label
  shall appear (no hardware).
- **Source:** CLAUDE.md, engineering-evidence skill.
- **Verification:** I (independent reviewer).
- **Acceptance:** 0 unlabelled numbers in sampled sections; 0 MEASUREMENT labels.
- **Status:** NOT RUN

### REQ-DOC-005 — Scientific article
- **Text:** A scientific article in English, IEEE style (IEEEtran), shall be
  delivered as LaTeX source and PDF, covering architecture, SC method, accuracy
  vs K and RNG mode, resources, timing, latency, limitations (simulation only,
  no hardware validation) and references.
- **Source:** definition (Deliverables).
- **Verification:** I + A (build log).
- **Acceptance:** `latexmk` exit 0, log with 0 errors and 0 undefined
  references/citations; all REQ-AI and REQ-RES/TIM headline numbers present
  with labels.
- **Status:** NOT RUN

### REQ-DOC-006 — Engineering report
- **Text:** An engineering report (LaTeX + PDF) shall contain requirements and
  status matrix, budgets vs results, risks, verification evidence and the
  physical validation plan.
- **Source:** definition (Deliverables).
- **Verification:** I + A.
- **Acceptance:** builds with 0 errors; contains the listed chapters.
- **Status:** NOT RUN

### REQ-DOC-007 — Requirement status matrix
- **Text:** `requirements/STATUS_MATRIX.md` shall give, for every requirement,
  status, evidence path and revision.
- **Source:** definition (Deliverables); systems-engineer role.
- **Verification:** I.
- **Acceptance:** 100 % of IDs in this file appear in the matrix.
- **Status:** NOT RUN

### REQ-DOC-008 — Release baseline
- **Text:** The release shall be an immutable folder in `releases/` with a
  manifest of sha256 checksums of all deliverables.
- **Source:** definition (Deliverables); CLAUDE.md.
- **Verification:** I.
- **Acceptance:** `sha256sum -c` of the manifest passes for 100 % of files.
- **Status:** NOT RUN

## 8. Verification process (VER)

### REQ-VER-001 — Self-checking testbench per block
- **Text:** Every RTL block (CPU, TPU and its sub-blocks, peripherals/UART,
  bus/SoC) shall have a deterministic self-checking testbench that prints
  `TEST PASSED`/`TEST FAILED`, calls `$fatal(1)` on failure and has a timeout
  watchdog.
- **Source:** definition (Deliverables); rtl-gowin-flow skill.
- **Verification:** I + S.
- **Acceptance:** one TB per block; all pass in the release regression log.
- **Status:** NOT RUN

### REQ-VER-002 — Testbench fault-injection check
- **Text:** Each testbench shall be shown to fail on at least one injected
  fault (mutated RTL or expected value).
- **Rationale:** proves the checker can fail (exit code 0 is not a pass).
- **Source:** derived (engineering-evidence rule).
- **Verification:** S.
- **Acceptance:** for each TB a log showing `TEST FAILED` and non-zero exit for
  the injected fault.
- **Status:** NOT RUN

### REQ-VER-003 — Lint clean
- **Text:** All synthesisable RTL shall pass `verilator --lint-only -Wall` with
  0 warnings, or each remaining warning waived in writing with a reason.
- **Source:** derived.
- **Verification:** A.
- **Acceptance:** lint log: 0 unwaived warnings.
- **Status:** NOT RUN

### REQ-VER-004 — Python unit tests
- **Text:** Golden model, assembler and ISS shall have pytest unit tests,
  including known-answer tests (LFSR sequence, ISA examples).
- **Source:** derived.
- **Verification:** S.
- **Acceptance:** pytest: 0 failures, 0 errors.
- **Status:** NOT RUN

### REQ-VER-005 — Full FPGA flow on the final SoC
- **Text:** The release SoC shall pass Yosys synthesis, nextpnr P&R and
  `gowin_pack` bitstream generation without errors. The bitstream shall not be
  loaded to hardware in this project.
- **Source:** definition (Deliverables, Out of scope).
- **Verification:** A.
- **Acceptance:** three logs with exit 0, `0 errors`, `.fs` file with sha256.
- **Status:** NOT RUN

### REQ-VER-006 — Traceability
- **Text:** Every requirement with method S or A shall map to at least one test
  case or analysis with an evidence path.
- **Source:** derived.
- **Verification:** I.
- **Acceptance:** STATUS_MATRIX has >= 1 evidence entry for 100 % of S/A requirements.
- **Status:** NOT RUN

### REQ-VER-007 — Evidence and reproducibility
- **Text:** Every PASS shall be backed by a log in `logs/<area>/` containing the
  exact command, tool versions and git revision, and the decisive result line.
- **Source:** CLAUDE.md, engineering-evidence skill.
- **Verification:** I.
- **Acceptance:** reviewer re-runs >= 3 sampled commands and obtains identical
  decisive lines.
- **Status:** NOT RUN

### REQ-VER-008 — Independent review
- **Text:** RTL, golden model, budgets and documents shall be reviewed by the
  independent-reviewer before release.
- **Source:** definition (Specialists: independent-reviewer always).
- **Verification:** I.
- **Acceptance:** review handoff with all major findings closed or accepted.
- **Status:** NOT RUN

### REQ-VER-009 — Physical validation plan (future Test)
- **Text:** The engineering report shall contain a physical validation plan for
  a future hardware campaign (not executed here): (1) load the bitstream into
  SRAM with an open loader; (2) confirm LED pattern after reset; (3) capture the
  UART at 115200 8N1 and compare RESULT with the model for >= 20 images stored
  in prog/init files; (4) read CYCLE/CYCLES over UART and compare with
  simulation (expect identical counts); (5) measure board supply current at
  5 V idle and during continuous inference; (6) repeat at 3 board power-ups.
- **Source:** definition (Out of scope: "physical validation is planned but
  not executed").
- **Verification:** I (plan present now); T (future, by the user).
- **Acceptance:** plan present with pass criteria per step; status of every T
  step stays NOT RUN in this project.
- **Status:** NOT RUN

## 9. Disposition of the REQ-01 open decisions

Status of each REQ-01 open decision (management/handoffs/systems-engineer/REQ-01.md)
at issue 2. "Closed" means a manager ruling exists in ARCHITECTURE.md / DECISIONS.md
and the requirements now follow it.

| OD | Subject | Disposition | Ruling | Requirements touched |
|---|---|---|---|---|
| OD-1 | Reset port name `btn_s1_n` vs `btn_rst_n` | **Closed — REQ-01 finding was wrong.** The CST already names the port `btn_rst_n` (pin 3) since commit 199a3dc, i.e. before the REQ-01 input revision; the SoC P&R places `btn_rst_n` on pin 3 (logs/soc/pins.log). S1 = pin 3 stays an ASSUMPTION (CST header). | none needed | REQ-SYS-014 (note withdrawn) |
| OD-2 | "With margin" | Closed: <= 85 % per resource, Fmax >= 29.7 MHz on the worst of 3 seeds | ARCH 10 (A.2), ADR-007, G1 | REQ-RES-001..004, REQ-TIM-001 (source) |
| OD-3 | CONFIG read-back after out-of-range LOG2_L | Closed: clamped value | ARCH 10 (A.2) | REQ-TPU-007 |
| OD-4 | CYCLES counting convention | Closed: rising edges with BUSY = 1 | ARCH 10 (A.2) | REQ-TPU-014 |
| OD-5 | Reserved offsets | Closed for the TPU window (read 0, writes ignored). Peripheral offsets 0x14..0x1F (and the aliased rest of the 0x1 region) are not in the spec; RTL-SOC assumption A2 implements read 0 / no `bus_err`. Residual: spec wording for the peripheral window (low impact). | ARCH 10 (A.2) | REQ-TPU-015 |
| OD-6 | Reads while BUSY | Closed: allowed, return current contents. **Residual -> OD-R2-1** (read latency while BUSY vs the 4-cycle bound of REQ-SYS-007). | ARCH 10 (A.2) | REQ-TPU-011, REQ-SYS-007 (note) |
| OD-7 | ADR-001 area estimate too low | Closed: ADR text corrected (2855 LUT4 / 1454 FF tile) | ADR-007 | none (BUDGETS only) |
| OD-8 | IL = 16 variant | Closed: kept only as a reported variant that does not fit (confirmed: no legal placement, RTL-TPU) | ADR-007 | REQ-RES-006 |
| OD-9 | Default RNG mode | Closed: RNG_MODE 2 | ADR-008, ADR-010 (closes ADR-003) | REQ-TPU-003, -006, REQ-AI-004..006, -010 |
| OD-10 | LFSR seeding / shared polynomial | Closed: rev C seeds selected on validation data; rules R1/R2; different polynomials rejected (verification effort). The K = 10 bit-sequence self-overlap (lag 8192 stream cycles, 7 of 8 bits; BUDGETS.md 9) is not ruled on explicitly but is covered by the measured K = 10 accuracy (no requirement change). | ADR-008, ADR-009, ADR-010 | REQ-TPU-005, -006, REQ-AI-002, -010 |
| OD-11 | Accuracy targets (REQ-AI-003..006) | **Open.** No ADR confirms the thresholds; SW-03 evaluates exactly these thresholds (`accuracy_revC.json` `requirement_checks`), so they are applied de facto. Explicit confirmation requested. | — | — |
| OD-12 | BIAS read-back [31:16] | Closed: **sign-extended** (REQ-01 proposed zero) | ARCH 10 (A.2) | REQ-TPU-002 |
| OD-13 | Post-processing overflow wording | Closed: exact result, abs(Dp*2^(s+7)) < 2^34, widths documented in RTL | ARCH 10 (A.2) | REQ-TPU-008 |
| OD-14 | UART error sign wording | Closed: no change needed (bit time -0.16 %, baud +0.16 %) | — | none |
| OD-15 | Repository hygiene (budget build dir) | Closed: `scripts/budgets/build/` untracked and git-ignored | ADR-007 | none |
| OD-16 | Network access to Gowin/Sipeed hosts | **Open (user decision)**, listed at G1; S-006..S-009, S-012..S-015, S-017..S-019 stay ASSUMPTION | G1 (user) | none |

New open decision raised at issue 2:
- **OD-R2-1** REQ-SYS-007 bounds slave latency to 4 cycles, but a TPU read of
  INPUT/BIAS/WEIGHT while BUSY waits up to ~35 cycles (RTL-TPU, SIMULATION).
  Proposal: keep 4 cycles in general and allow <= 40 cycles for reads of
  INPUT/BIAS/WEIGHT while BUSY (no hang; the CPU program does not read them
  while BUSY in the demo).

## Change history

| Issue | Date | Task | Input revision | Change | Reason / authority |
|---|---|---|---|---|---|
| 1 | 2026-11-04 | REQ-01 | 494448a (spec rev A + A.1) | Initial issue: 82 requirements, all NOT RUN | — |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 (spec rev C) | Header, conventions: spec rev C; IDs declared stable; status deferred to the status matrix; definitions *selected RNG mode* = 2, *deployed seeds* = rev C tables, *seed rules R1/R2*, *validation split* | ARCH 12, ADR-008/010 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | **REQ-SYS-005 (b): first fetch within 8 -> 40 cycles** of `rst` falling; rationale added | ADR-011: the BSRAM register file (saves ~1000 FF) is cleared by a 32-cycle CLEAR state; first fetch measured at cycle 31 (SIMULATION, tb_soc R5); the 8-cycle bound was an unjustified guess |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-SYS-007: note on TPU read latency while BUSY (acceptance unchanged) | RTL-TPU handoff (35 cycles, SIMULATION); OD-R2-1 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-SYS-004: "no PLL in rev A" -> "rev A..C" | wording |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-SYS-014: OD-1 note withdrawn (REQ-01 finding was wrong) | CST at 199a3dc |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-TPU-002: CONFIG clamped read-back and BIAS sign-extended read-back added to text and acceptance | ARCH 10 (A.2), OD-3/OD-12 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | **REQ-TPU-003: PARAMS version 0x01 -> 0x03**; expected values 0x0300_0810 / 0x0301_0810 / 0x0302_0810; release = mode 2 | ARCH 12, ADR-010 (rev B had 0x02) |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | **REQ-TPU-005: rev C seeds**; seed-table check (18 values, 0xF9DE = S(32768)) added; trace files must be `# spec_rev C` | ARCH 12, ADR-010 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | **REQ-TPU-006: default mode 2, rev C seeds, rules R1/R2**, re-selection protocol for future seed changes; acceptance (b) PARAMS of release build, (c) R1/R2/min-lag check by two independent implementations | ADR-008/009/010; rev B defect (ADR-009) |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-TPU-007: read-back of clamped value made part of text/acceptance (OD-3 reference removed) | ARCH 10 (A.2) |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-TPU-008: A.2 width statement (< 2^34) cited | ARCH 10 (A.2), OD-13 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-TPU-011: reads while BUSY allowed, return current contents | ARCH 10 (A.2), OD-6 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-TPU-013: expected values must be spec rev C; selected mode = 2 | ARCH 12 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-TPU-014: CYCLES = rising edges with BUSY = 1 (OD-4 reference removed) | ARCH 10 (A.2) |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-TPU-015: source changed from derived to architecture §10 | ARCH 10 (A.2), OD-5 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-AI-002: seed selection added to the list of selections that must not use the test split; pre-registered protocol | ADR-009, SW-03 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-AI-004: rationale note (mode 2, rev C seeds, OD-11 pending); threshold unchanged | ADR-010 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-AI-006: clarification that a common start offset of the deployed set is an admissible alternative seed set; threshold unchanged | SW-02/SW-03 method (`sctpu.accuracy.ensemble_offsets`) |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-AI-010: closing ADR is ADR-010 (not ADR-003 status); seed set included; rev B reported as negative result | ADR-003 closed by ADR-008/010; ADR-009 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-RES-001, REQ-TIM-001: source notes (85 % / 29.7 MHz confirmed by A.2; release flow `-nowidelut`) | ADR-007, ADR-011 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-RES-006: non-placing variants reported with the error line | ADR-007, OD-8 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | REQ-TIM-005: note on the ADR-011 V1 limitation (text/acceptance unchanged) | ADR-011 |
| 2 | 2026-11-04 | REQ-02 | 1d67c44 | New section 9: disposition of REQ-01 OD-1..OD-16, new OD-R2-1 | — |
