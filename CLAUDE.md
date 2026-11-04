# SC-TPU + RV32I SoC on Tang Nano 9K — project rules

The main session is the ENGINEERING MANAGER. Specialists live in `.claude/agents/`
(systems-engineer, fpga-engineer, software-engineer, documentation-engineer,
independent-reviewer) and cannot delegate.

## Rules
- Honesty: never invent results. Label numbers SOURCE / CALCULATION / SIMULATION /
  MEASUREMENT / ASSUMPTION. Status only PASS / PARTIAL / FAIL / BLOCKED / NOT RUN.
  Simulation is not test; synthesis/P&R passing is not hardware validation.
- All files, code, comments and reports in English. Comment everything thoroughly.
- No firmware (no target C/asm application); CPU stimuli live only in testbenches.
- No flashing hardware, no ordering, no contacting anyone.
- One writer per file (`management/locks/`). Frozen interfaces: `management/INTERFACES.json`.
- Tools: `source .venv/bin/activate` (yowasp-yosys, yowasp-nextpnr-himbaechel-gowin,
  gowin_pack); iverilog, verilator, latexmk on PATH. See `management/TOOLCHAIN.md`.
- Releases in `releases/` are immutable.

## Documents
[Definition](management/PROJECT_DEFINITION.md) · [State](management/PROJECT_STATE.md) ·
[Tasks](management/TASK_BOARD.md) · [Requirements](requirements/REQUIREMENTS.md) ·
[Interfaces](management/INTERFACES.json) · [Architecture spec](design/architecture/ARCHITECTURE.md) ·
[Risks](management/RISKS.md) · [Decisions](management/DECISIONS.md) ·
[Toolchain](management/TOOLCHAIN.md) · [Sources](management/SOURCES.md) ·
[Metrics](management/metrics.json) · [Resume](management/RESUME.md)
