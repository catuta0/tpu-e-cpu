"""rv32 - host-side RV32I reference tools for CPU verification (task SW-01b).

This package is the Python reference for the RV32I multi-cycle CPU of the
SC-TPU + RV32I SoC (ARCHITECTURE.md section 6 and section 8).  Everything here
runs on the HOST.  The only code that ever runs on the target CPU are the small
verification instruction sequences produced by the assembler below; they are
testbench stimuli, NOT firmware (PROJECT_DEFINITION.md, "No firmware").

Modules
-------
asm
    Two-pass assembler for RV32I (+ FENCE/ECALL/EBREAK, labels, a few
    pseudo-instructions and directives).  Produces 32-bit words, a 1024-line
    ``$readmemh`` hex image of the 4 KiB RAM and a listing.
disasm
    Disassembler producing text that ``asm`` re-assembles to the same word
    (round-trip self-check).  Undecodable words are printed as ``.word``.
iss
    Instruction-set simulator: 32 registers, 4 KiB RAM at address 0, the
    peripheral map of ARCHITECTURE.md 4.1, a stub SC-TPU and the trap/halt
    behaviour of INTERFACES.json ``cpu.traps``.
gen_cpu_tests
    Generates the directed / random / trap CPU verification programs into
    ``sim/data/cpu_tests/`` together with their ISS-derived expected
    signatures and metadata.
gen_soc_demo
    Generates the SoC demo program ``sim/data/soc_demo_prog.hex`` (+ listing).

Specification sources: RISC-V Unprivileged ISA, RV32I Base Integer Instruction
Set, version 2.1 (instruction formats, immediate encodings, semantics), and the
frozen project interface ``management/INTERFACES.json`` (rev A).
"""

__all__ = ["asm", "disasm", "iss"]
