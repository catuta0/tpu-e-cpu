# Project Definition — SC-TPU + RV32I SoC on Tang Nano 9K

Status: STARTING ASSUMPTION (not a verified specification). Collected 2026-11-04 (Phase A).

## Product / system
A small System-on-Chip for the Sipeed Tang Nano 9K board containing:
1. A **RISC-V RV32I multi-cycle CPU** (RTL, written from scratch).
2. A **stochastic-computing tensor processing unit (SC-TPU)**: a matrix-vector
   accelerator that performs multiply-accumulate using stochastic bitstreams
   (AND-gate multiplication / bipolar XNOR, counter-based accumulation),
   memory-mapped to the CPU.
3. A **mini AI workload**: an MLP 64-16-10 classifying the scikit-learn 8x8
   "digits" dataset, trained offline in Python, weights quantised and loaded
   into on-chip BSRAM; accuracy measured in simulation (bit-exact model vs RTL).

## Context
- Target: Sipeed Tang Nano 9K, Gowin GW1NR-LV9QN88PC6/I5 (values to be confirmed
  from datasheet and labelled SOURCE in SOURCES.md).
- Bench / hobby / research use, indoor lab environment. No special
  environmental requirements (temperature, vibration, radiation) — ASSUMPTION.
- Users: the author (research / education); readers of the scientific article.

## Hard constraints
- Must fit in GW1NR-9 resources (LUT4, FF, BSRAM, DSP) with margin.
- Must meet timing at the board 27 MHz oscillator clock (or a PLL-derived clock).
- No budget for paid tools; open-source toolchain only.
- No deadline stated.

## Bought-in parts / existing blocks not to redesign
- Tang Nano 9K board (as-is). Gowin primitives (rPLL, BSRAM) through open-source
  flow only.

## Toolchain
- Yosys (synth_gowin) + nextpnr-himbaechel (Gowin) + Apicula (gowin_pack) — via YoWASP / pip.
- Icarus Verilog and/or Verilator for simulation (apt).
- Python 3 (numpy, scikit-learn) for training, bit-exact golden model, analysis.
- LaTeX (IEEEtran) for the scientific article and engineering report (apt).

## Deliverables
- RTL (CPU, SC-TPU, SoC top, bus/peripherals) with **thorough comments**.
- Self-checking testbenches for every block; simulation results.
- Synthesis + place & route reports (utilisation, timing) for GW1NR-9.
- Python golden model + training + accuracy / error analysis.
- Scientific article in **English, IEEE style** (LaTeX source + PDF).
- Engineering report (LaTeX + PDF), requirement status matrix, release baseline.

## Specialists
systems-engineer, fpga-engineer, software-engineer, documentation-engineer,
independent-reviewer (always).

## Out of scope
- **No firmware** (no C/assembly application, drivers or bootloader). CPU test
  programs exist only as small instruction sequences embedded in testbenches /
  ROM init files generated for verification.
- No ordering parts, no flashing hardware, no powering up, no contacting anyone.
- Physical validation is planned (in the report) but not executed.

## Project folder
/home/user/tpu-e-cpu (git branch claude/awesome-lovelace-hu02o8)
