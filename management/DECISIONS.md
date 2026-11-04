# Architecture Decision Records

## ADR-000 — Specialist execution mode (2026-11-04)
Status: ACCEPTED (deviation, labelled)
Context: Claude Code only watches `.claude/agents/` directories that existed at
session start; this project's directory was created mid-session, so the named
agent types are not loadable until restart (verified: Agent tool returned
"Agent type 'fpga-engineer' not found"). The user went to sleep and asked that
the run not stop.
Decision: run each specialist as a real Claude Code subagent of type
`general-purpose` whose first instruction is to load and obey its role file
`.claude/agents/<name>.md` (responsibilities, write paths, checks, handoff).
Consequences: `disallowedTools: [Agent]` and `skills` preload are enforced by
instruction, not by the harness. After a restart (`claude --continue`) the named
agents load natively and must be used.

## ADR-001 — Accelerator arithmetic (G1)
Options (identical workload: MLP 64-16-10, 8-bit operands):
| Option | Multiply | Area per MAC lane (CALCULATION, rough) | Latency per tile | Notes |
|---|---|---|---|---|
| A. Bipolar SC, XNOR + APC | 1 XNOR + 2 shared/one-per-weight 8-bit comparators | ~9 LUT4 (comparator 8b ~8 LUT + XNOR) | L cycles (L=2^K) | tunable accuracy/latency via L; error-tolerant |
| B. Binary int8 MAC | 8x8 multiplier (DSP or ~64 LUT) + adder | 20 DSP total on GW1NR-9 (SOURCE pending) -> max 20 lanes; LUT version ~70 LUT | 1 cycle | exact; parallelism bounded by DSP count |
| C. Unipolar SC (AND) + sign-magnitude | AND + sign logic, two accumulators | ~10 LUT | L cycles | lower variance near 0, more control logic |
Decision: **A** (user asked for a stochastic TPU; bipolar handles signed weights
with one stream per operand). B is kept as a software/analytical baseline in the
article (accuracy of int8 binary vs SC; area estimate), C rejected (extra logic,
no clear gain for signed weights).

## ADR-002 — Parallelism / dataflow (G1)
| Option | Lanes | Weight regs | Est. cycles / inference at L=256 (CALCULATION) |
|---|---|---|---|
| Fully parallel layer 1 (16x64) | 1024 | 8192 FF | 256+256 = 512 | does not fit (FF 6480 SOURCE pending) |
| Weight-stationary tile 16x8 | 128 | 1024 FF | 10 tiles x (256 + ~40 load) ~ 3000 | fits, chosen |
| Serial (1 neuron x 8 inputs) | 8 | 64 FF | 16x8x256 + 10x2x256 ~ 38000 | smallest, slow |
Decision: **16x8 weight-stationary tile** (NL=16 matches hidden width so a layer-1
tile computes all hidden neurons at once). IL is studied as a variant (4/8/16)
in synthesis; the interface layout formula is parameterised by IL, but rev A
freezes IL=8.

## ADR-003 — RNG decorrelation (G1, to be closed at G3 by the variant study)
Three variants implemented as synthesis parameter RNG_MODE (0 shared, 1 rotate,
2 independent). Selection criterion: accuracy on the digits test split vs LUT/FF
cost at identical inputs. Default until the study: mode 1.

## ADR-004 — CPU micro-architecture (G1)
RV32I multi-cycle (user choice). Alternatives considered: 3-stage pipeline
(+~50 % LUT, CPI ~1.3), RV32E (-16 regs). Multi-cycle leaves the most area for
the SC-TPU; the CPU only orchestrates (START, poll, read result).

## ADR-005 — Leap-forward LFSR (G1)
Taking 8 bits of a single-step Fibonacci LFSR gives consecutive r values that
are shifted copies of each other (strong serial correlation). Each stream cycle
advances the LFSR 8 steps (unrolled XOR network) so every r is 8 fresh bits.

## ADR-006 — Spec clarifications rev A.1 (from SW-01b open decisions)
1. Misaligned jump/branch target (cause 4) traps on the taken jump/branch itself
   (RISC-V unprivileged spec: reported on the branch/jump, not the target); halt
   PC = jump address; rd not written.
2. Strict decoding: SYSTEM other than ECALL/EBREAK (i.e. CSR*), unknown
   funct3/funct7 (e.g. MUL), FENCE.I, 0x00000000 and 0xFFFFFFFF -> illegal (cause 3).
3. Reset values: LED=0, TOHOST=0, TPU STATUS=0 (BUSY=0, DONE=0), RESULT=0,
   CYCLES=0, SCORE/HIDDEN=0.
These add precision without changing any INTERFACES.json field; both RTL tasks
were notified.

## ADR-007 — Spec clarifications rev A.2 and budget corrections (from REQ-01)
- Clarifications listed in ARCHITECTURE.md section 10 (CONFIG read-back, CYCLES
  definition, reserved offsets, reads while BUSY, BIAS sign extension,
  post-processing width, margin definition).
- Correction to ADR-001/002: the calibrated 16x8 SC tile costs 2855 LUT4 /
  1454 FF (~22 LUT per MAC lane, SIMULATION of P&R, requirements/BUDGETS.md), not
  ~9 LUT as first estimated. Device totals are now SOURCE (nextpnr/Apicula chip
  database: 8640 LUT4, 6480 FF, 26 BSRAM, 20 MULT18X18). The fully-parallel option
  remains infeasible; IL=16 (94.5 % LUT, CALCULATION) is kept only as a reported
  variant that does not fit.
- Build products under scripts/budgets/build/ are untracked (70 MB).

## ADR-008 — Rev B: RNG mode 2 default + phase-spaced seeds (cross-discipline iteration)
Evidence that forced the change:
- software-engineer SW-01a (reports/sw/accuracy.json, SIMULATION, 360 test images):
  K=8 accuracy mode 0 65.6 %, mode 1 91.1 %, mode 2 94.4 % vs expected-value 95.0 %;
  mode-2 LFSRs X0 and W3 only 321 stream cycles apart (seed formula of rev A).
- systems-engineer REQ-01: cross-lane correlation 1.0 / 0.52 / 0.053 for modes 0/1/2.
- fpga-engineer RTL-TPU (reports/fpga/tpu/variants.md): mode 2 costs only +125 LUT4,
  +224 DFF over mode 1, Fmax unchanged within seed noise.
Decision: default RNG_MODE 2; seeds re-derived as maximally phase-spaced points of
the common m-sequence (spacing 4096 steps = 512 stream cycles; optimal for 16
LFSRs of one polynomial). Rejected: different polynomials per lane (more
verification effort, rev C candidate); double-buffered weight tiles (OD-3, latency
only, rev C candidate).
Re-run required: golden vectors + accuracy (software), TPU regression (fpga).

## ADR-009 — Rev B found defective; rev C seed selection on validation data
Evidence (SW-02, reports/sw/revA_vs_revB.md, SIMULATION, 360 test images):
rev B mode 2 K=9 accuracy 89.7 % vs rev A 94.4 % (McNemar exact p = 0.0015);
cause: X and W seeds advance by the same 4096 steps per lane, so lane i's (r_x, r_w)
pair stream is lane i-1's delayed by 512 stream cycles = an integer number of tiles
at K <= 9 -> identical count tables repeat and errors add coherently.
Lesson: maximal phase spacing is not sufficient; the requirement is that no two
lanes' operand-pair streams are translates of each other:
(lag_x(i) - lag_x(j)) != (lag_w(i) - lag_w(j)) for i != j.
Decision: rev C seeds chosen by a protocol fixed in advance (SW-03): candidates
C0..C4 on the 288-image validation subset only; select the highest worst-case
deployed accuracy over K in {8,9,10}; test split evaluated only afterwards.
Rev B is kept in the record as a negative result (also reported in the article).

## ADR-010 — Rev C adopted (closes ADR-003, ADR-008, ADR-009)
Selection by the pre-registered protocol (SW-03, 288 validation images, test split
not loaded): worst-case deployed accuracy over K=8..10: C0 (rev A mode-2 seeds)
98.96 %, C3 98.26 %, C4 97.22 %, C2 95.83 %, C1 (rev B) 95.14 % (SIMULATION).
C0 vs C3 is not significant (2 images); C0 kept because it also has the longest
verification history (RTL bit-exact since rev A). Caveat recorded: the deployed
weights saw the validation images in training, so absolute validation numbers are
optimistic; only the ranking is used.
Decisions: D-A accept C0; D-B keep the modes 0/1 pair 0xACE1/0xF9DE (fails R2 at
half-period, no measurable effect; modes 0/1 are non-default study modes); D-C R1+R2
are the documented seed rules. Test split afterwards (SIMULATION, n=360): mode 2
deployed K8/K9/K10 = 94.4/94.4/95.3 %, ensemble means 92.8/94.4/94.8 % vs EV 95.0 %.
Net effect of the B->C iteration: the RTL default seeds return to the rev A values,
now justified by an explicit rule and validation evidence instead of by accident.

## ADR-011 — Requirement adjustments after RTL-SOC
- REQ-SYS-005(b) first fetch within 8 cycles of reset release -> relaxed to 40
  cycles: the register file is in BSRAM (saves ~1000 FF) and is cleared by a 32-cycle
  CLEAR state after reset (measured first fetch at cycle 31, SIMULATION). The bound
  was an unjustified guess; the trade-off favours area.
- REQ-TIM-005 (end-to-end latency including input load and CYCLE read) stays
  PARTIAL: the demo program does not load the 64 inputs; START->RESULT-read
  measured 2948 cycles, reset->TOHOST 5441 cycles (SIMULATION). Accepted for V1,
  listed as a limitation.
- Synthesis flow fixed to `synth_gowin -nowidelut` (5628 vs 6130 LUT4, worst Fmax
  47.46 vs 42.80 MHz, SIMULATION of P&R, 3 seeds).
