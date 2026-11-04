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
