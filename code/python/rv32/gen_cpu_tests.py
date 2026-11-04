"""Generator of the RV32I CPU verification programs (task SW-01b).

These programs are TESTBENCH STIMULI, not firmware (PROJECT_DEFINITION.md
"No firmware", ARCHITECTURE.md section 8).  They are produced by the reference
assembler (:mod:`rv32.asm`), self-checked by disassembly round trip
(:mod:`rv32.disasm`) and executed on the reference ISS (:mod:`rv32.iss`),
which provides the expected results for the RTL testbench.

Usage (from the repository root)::

    .venv/bin/python code/python/rv32/gen_cpu_tests.py            # defaults
    .venv/bin/python code/python/rv32/gen_cpu_tests.py --n-random 20 --base-seed 1000

Output directory ``sim/data/cpu_tests/`` (one set of files per test):

``<name>.hex``
    RAM image, 1024 lines x 8 lowercase hex digits (``$readmemh``), zero
    padded, word i = bytes 4i..4i+3 little-endian (ARCHITECTURE.md 5.6).
``<name>.sig``
    Expected signature, 32 lines x 8 hex digits = RAM words 0x0F00..0x0F7C at
    the end of the run (see "Signature convention").
``<name>.meta.json``
    Expected stop reason, trap cause, halt PC, retired-instruction count,
    seed (random tests), final registers, UART/LED/bus_err expectations.
``<name>.lst``
    Assembler listing (address, word, source) for debugging.
``index.txt``
    Every test name, one per line, in run order (directed, random, trap).

Memory layout used by every program (byte addresses)
----------------------------------------------------
* ``0x000 .. 0x7FB`` code (checked: the code below the data area must end
  below the scratch word);
* ``0x7FC``          scratch word used by the signature dump (reachable as
  ``0x7FC(x0)`` because I-type offsets are limited to +2047);
* ``0x800 .. 0x9FF`` data area (initialised data / load-store target);
* ``0x900 / 0xA00 ..`` tests that own a data area place their signature-dump
  code after it (``dir_loads``, ``dir_x0``: 0x900; random tests: 0xA00);
* ``0x0E00``         (SoC demo only: TPU CYCLES);
* ``0x0F00 .. 0x0F7F`` signature area (checked: never occupied by the image).

Signature convention (exact)
----------------------------
At label ``sig_dump`` every non-trap program stores its architectural
registers so that **word k at address 0x0F00 + 4*k holds xk for k = 1..31,
and the word at 0x0F00 holds 0** (x0).  The values are those of the
registers at the moment execution reaches ``sig_dump``.  Because
0x0F00 is not reachable from x0 with a 12-bit offset, the dump first parks
x1 at 0x7FC, sets x1 = 0x1000 and uses negative offsets
(0x0F00 + 4k - 0x1000), then recovers the original x1 through x2 (already
saved).  After the dump the program writes 1 (= pass) to TOHOST
(0x1000_0010) and parks in a ``j .`` loop.  The ``.sig`` file therefore has
32 lines: line k (0-based) = word at 0x0F00 + 4k.

Trap programs dump the signature too (WITHOUT the TOHOST write), then
execute the trapping instruction.  If the CPU fails to trap it falls through
into a TOHOST write of 3 (an odd fail code, ARCHITECTURE.md 4.1).  The
expected trap cause and halt PC (address of the trapping instruction) are in
the meta file; misaligned-store targets lie inside the signature area so that
a store that is wrongly performed corrupts the signature.

CYCLE (0x1000_000C) is never read by these programs: the ISS models it as 0
(see iss.py), so CYCLE-dependent values must not enter a signature.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

if __package__ in (None, ""):          # allow "python code/python/rv32/gen_cpu_tests.py"
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "rv32"               # noqa: A001

from rv32.asm import BASE_MNEMONICS, BRANCHES, I_ALU, LOADS, R_TYPE, STORES, Program, assemble, write_hex  # noqa: E402
from rv32.disasm import disassemble, roundtrip_mismatches  # noqa: E402
from rv32.iss import Iss, IssResult, TrapCause  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
DEFAULT_OUT = REPO / "sim" / "data" / "cpu_tests"

SIG_BASE = 0x0F00          # signature area (SW-01b)
SIG_WORDS = 32             # 0x0F00 (x0 = 0) + x1..x31
SCRATCH = 0x7FC            # x1 parking word used by the dump
DATA_BASE = 0x800          # data area for loads / stores
DATA_BYTES = 0x200         # 512 bytes
TOHOST_FAIL_NO_TRAP = 3    # odd fail code written if an expected trap does not happen
MAX_STEPS = 100_000        # ISS safety limit (no generated program comes close)

TRAP_NAMES = {c.value: c.name.lower() for c in TrapCause}


# --------------------------------------------------------------------------
# Program fragments
# --------------------------------------------------------------------------
def signature_dump(tohost: bool = True) -> str:
    """Assembly of the signature dump (+ TOHOST pass write when ``tohost``)."""
    out = [
        "# ---------------- signature dump (generated, see gen_cpu_tests.py) ----------------",
        "sig_dump:",
        f"    sw   x1, {SCRATCH:#x}(x0)          # park x1 in the scratch word 0x7FC",
        "    lui  x1, 0x1                 # x1 = 0x1000: offsets 0xF00+4k-0x1000 are negative",
    ]
    for k in range(2, 32):
        out.append(f"    sw   x{k}, {SIG_BASE + 4 * k - 0x1000}(x1)          # [0x{SIG_BASE + 4 * k:04x}] <- x{k}")
    out += [
        f"    lw   x2, {SCRATCH:#x}(x0)          # x2 <- original x1 (x2 is already saved)",
        f"    sw   x2, {SIG_BASE + 4 - 0x1000}(x1)          # [0x0f04] <- x1",
        f"    sw   x0, {SIG_BASE - 0x1000}(x1)          # [0x0f00] <- x0 = 0",
    ]
    if tohost:
        out += [
            "    lui  x1, 0x10000             # x1 = 0x1000_0000 peripheral base",
            "    addi x2, x0, 1               # 1 = pass",
            "tohost_store:",
            "    sw   x2, 0x10(x1)            # TOHOST <- 1: the ISS / testbench stop here",
            "halt_loop:",
            "    j    halt_loop               # park forever",
        ]
    return "\n".join(out) + "\n"


def tohost_fail(code: int = TOHOST_FAIL_NO_TRAP) -> str:
    """Fall-through code after a trapping instruction: report failure."""
    return (f"    # reached only if the CPU did NOT trap: report fail code {code}\n"
            "    lui  x1, 0x10000\n"
            f"    addi x2, x0, {code}\n"
            "    sw   x2, 0x10(x1)            # TOHOST <- fail code\n"
            "no_trap_loop:\n"
            "    j    no_trap_loop\n")


# --------------------------------------------------------------------------
# Test description
# --------------------------------------------------------------------------
Expect = dict[int, "int | Callable[[dict[str, int]], int]"]


@dataclass
class TestSpec:
    """One verification program.

    ``expect``: hand-derived expected register values at ``sig_dump``
    (registers not listed must be 0) - an ISS-independent check for directed
    tests.  Values may be callables of the symbol table (link addresses).
    ``trap``: (expected cause, label of the trapping instruction) for trap
    tests.
    """
    name: str
    kind: str
    description: str
    source: str
    seed: int | None = None
    expect: Expect | None = None
    trap: tuple[TrapCause, str] | None = None
    expect_bus_err: bool = False
    requires: list[str] = field(default_factory=lambda: ["ram", "tohost"])


# --------------------------------------------------------------------------
# Directed tests (one per instruction class).  Expected values are derived by
# hand from the RV32I v2.1 semantics; the comments show the derivation.
# --------------------------------------------------------------------------
def directed_tests() -> list[TestSpec]:
    """Return the directed test programs."""
    tests: list[TestSpec] = []

    # ---------------------------------------------------------------- LUI / AUIPC / li
    tests.append(TestSpec(
        "dir_lui_auipc", "directed",
        "LUI (incl. 0, 0xFFFFF, 0x80000), AUIPC at known PCs incl. wrap-around, "
        "li expansion with sign carry", """
    lui   x1, 0x12345          # x1 = 0x12345000
    lui   x2, 0xFFFFF          # x2 = 0xFFFFF000
    lui   x3, 0x80000          # x3 = 0x80000000
    lui   x4, 0                # x4 = 0
    auipc x5, 0                # @0x10: x5 = 0x00000010
    auipc x6, 1                # @0x14: x6 = 0x14 + 0x1000 = 0x00001014
    auipc x7, 0xFFFFF          # @0x18: x7 = 0x18 - 0x1000 = 0xFFFFF018 (wraps)
    auipc x8, 0x80000          # @0x1c: x8 = 0x8000001C
    lui   x9, 0x1
    addi  x9, x9, -1           # x9 = 0x1000 - 1 = 0x00000FFF
    li    x10, 0x12345FFF      # lui 0x12346 + addi -1 (sign carry) = 0x12345FFF
    li    x11, -1              # single addi: 0xFFFFFFFF
    li    x12, 0x80000000      # single lui (low part 0)
    li    x13, 0x7FFFF800      # lui 0x80000 + addi -2048 -> 0x7FFFF800 (wraps)
    li    x14, 2047            # addi: 0x7FF
    li    x15, -2048           # addi: 0xFFFFF800
    li    x16, 0x800           # lui 0x1 + addi -2048 = 0x800
""" + signature_dump(),
        expect={1: 0x12345000, 2: 0xFFFFF000, 3: 0x80000000, 4: 0, 5: 0x10, 6: 0x1014,
                7: 0xFFFFF018, 8: 0x8000001C, 9: 0xFFF, 10: 0x12345FFF, 11: 0xFFFFFFFF,
                12: 0x80000000, 13: 0x7FFFF800, 14: 0x7FF, 15: 0xFFFFF800, 16: 0x800}))

    # ---------------------------------------------------------------- OP-IMM
    tests.append(TestSpec(
        "dir_alu_imm", "directed",
        "ADDI/SLTI/SLTIU/XORI/ORI/ANDI: sign-extended immediates, wrap, "
        "SLTIU with imm -1 (= 0xFFFFFFFF unsigned), 0x80000000 operands", """
    addi  x1, x0, 1            # 1
    addi  x2, x0, -1           # 0xFFFFFFFF
    addi  x3, x2, 1            # 0xFFFFFFFF + 1 = 0 (wrap)
    li    x4, 0x7FFFFFFF
    addi  x5, x4, 1            # 0x80000000 (signed overflow wraps, no trap)
    addi  x6, x5, -1           # 0x7FFFFFFF
    addi  x7, x0, 2047         # 0x7FF (largest positive immediate)
    addi  x8, x0, -2048        # 0xFFFFF800 (most negative immediate)
    slti  x9, x2, 0            # -1 < 0 -> 1
    slti  x10, x1, -1          # 1 < -1 -> 0
    sltiu x11, x2, -1          # 0xFFFFFFFF <u 0xFFFFFFFF -> 0
    sltiu x12, x1, -1          # 1 <u 0xFFFFFFFF -> 1 (imm sign-extended, then unsigned)
    sltiu x13, x0, 1           # 0 <u 1 -> 1 (seqz)
    slti  x14, x5, 0           # 0x80000000 is negative -> 1
    xori  x15, x4, -1          # ~0x7FFFFFFF = 0x80000000
    ori   x16, x0, -2048       # 0xFFFFF800
    andi  x17, x2, 0x7FF       # 0x000007FF
    andi  x18, x4, -16         # 0x7FFFFFF0
    xori  x19, x1, 0x555       # 0x554
    ori   x20, x1, 0x0F0       # 0x0F1
    sltiu x21, x5, 2047        # 0x80000000 <u 0x7FF -> 0
    slti  x22, x0, 2047        # 0 < 2047 -> 1
    slti  x23, x5, -2048       # -2^31 < -2048 -> 1
""" + signature_dump(),
        expect={1: 1, 2: 0xFFFFFFFF, 3: 0, 4: 0x7FFFFFFF, 5: 0x80000000, 6: 0x7FFFFFFF,
                7: 0x7FF, 8: 0xFFFFF800, 9: 1, 10: 0, 11: 0, 12: 1, 13: 1, 14: 1,
                15: 0x80000000, 16: 0xFFFFF800, 17: 0x7FF, 18: 0x7FFFFFF0, 19: 0x554,
                20: 0xF1, 21: 0, 22: 1, 23: 1}))

    # ---------------------------------------------------------------- OP
    tests.append(TestSpec(
        "dir_alu_reg", "directed",
        "ADD/SUB overflow wrap, SLT/SLTU with 0x80000000/0x7FFFFFFF/-1, XOR/OR/AND", """
    li    x1, 0x7FFFFFFF
    li    x2, 0x80000000
    li    x3, -1
    li    x4, 1
    add   x5, x1, x4           # 0x7FFFFFFF + 1 = 0x80000000 (wrap)
    add   x6, x3, x4           # 0xFFFFFFFF + 1 = 0
    add   x7, x2, x2           # 0x80000000 * 2 = 0 (carry out discarded)
    sub   x8, x2, x4           # 0x80000000 - 1 = 0x7FFFFFFF
    sub   x9, x0, x4           # 0 - 1 = 0xFFFFFFFF
    sub   x10, x0, x2          # -(-2^31) = 0x80000000
    slt   x11, x2, x0          # -2^31 < 0 -> 1
    slt   x12, x0, x2          # 0 < -2^31 -> 0
    sltu  x13, x2, x0          # 0x80000000 <u 0 -> 0
    sltu  x14, x0, x2          # 0 <u 0x80000000 -> 1
    slt   x15, x2, x1          # -2^31 < 2^31-1 -> 1
    sltu  x16, x2, x1          # 0x80000000 <u 0x7FFFFFFF -> 0
    slt   x17, x3, x4          # -1 < 1 -> 1
    sltu  x18, x3, x4          # 0xFFFFFFFF <u 1 -> 0
    slt   x19, x1, x1          # equal -> 0
    sltu  x20, x0, x4          # 0 <u 1 -> 1 (snez)
    xor   x21, x1, x3          # 0x7FFFFFFF ^ 0xFFFFFFFF = 0x80000000
    or    x22, x2, x4          # 0x80000001
    and   x23, x1, x3          # 0x7FFFFFFF
    li    x24, 0x0F0F0F0F
    li    x25, 0x00FF00FF
    xor   x26, x24, x25        # 0x0FF00FF0
    or    x27, x24, x25        # 0x0FFF0FFF
    and   x28, x24, x25        # 0x000F000F
    sub   x29, x24, x25        # 0x0E100E10
    add   x30, x24, x25        # 0x100E100E
    sltu  x31, x25, x24        # 0x00FF00FF <u 0x0F0F0F0F -> 1
""" + signature_dump(),
        expect={1: 0x7FFFFFFF, 2: 0x80000000, 3: 0xFFFFFFFF, 4: 1, 5: 0x80000000, 6: 0, 7: 0,
                8: 0x7FFFFFFF, 9: 0xFFFFFFFF, 10: 0x80000000, 11: 1, 12: 0, 13: 0, 14: 1,
                15: 1, 16: 0, 17: 1, 18: 0, 19: 0, 20: 1, 21: 0x80000000, 22: 0x80000001,
                23: 0x7FFFFFFF, 24: 0x0F0F0F0F, 25: 0x00FF00FF, 26: 0x0FF00FF0,
                27: 0x0FFF0FFF, 28: 0x000F000F, 29: 0x0E100E10, 30: 0x100E100E, 31: 1}))

    # ---------------------------------------------------------------- shifts
    tests.append(TestSpec(
        "dir_shifts", "directed",
        "SLL/SRL/SRA and immediate forms: amounts 0, 1, 31, register amounts use "
        "only rs2[4:0] (33 -> 1, -32 -> 0), SRA vs SRL on negative values", """
    li    x1, 0x80000001
    li    x2, 0x12345678
    slli  x3, x1, 0            # 0x80000001 (shift 0)
    slli  x4, x1, 1            # 0x00000002 (bit 31 shifted out)
    slli  x5, x1, 31           # 0x80000000
    srli  x6, x1, 0            # 0x80000001
    srli  x7, x1, 1            # 0x40000000 (zero fill)
    srli  x8, x1, 31           # 0x00000001
    srai  x9, x1, 0            # 0x80000001
    srai  x10, x1, 1           # 0xC0000000 (sign fill)
    srai  x11, x1, 31          # 0xFFFFFFFF
    srai  x12, x2, 4           # 0x01234567 (positive: same as srl)
    addi  x13, x0, 31
    addi  x14, x0, 33          # amount 33 -> rs2[4:0] = 1
    li    x15, -32             # 0xFFFFFFE0 -> rs2[4:0] = 0
    sll   x16, x1, x13         # 0x80000000
    srl   x17, x1, x13         # 0x00000001
    sra   x18, x1, x13         # 0xFFFFFFFF
    sll   x19, x2, x14         # 0x12345678 << 1 = 0x2468ACF0
    srl   x20, x1, x14         # 0x40000000
    sra   x21, x1, x14         # 0xC0000000
    sll   x22, x2, x15         # amount 0 -> 0x12345678
    sra   x23, x1, x15         # amount 0 -> 0x80000001
    srl   x24, x1, x0          # amount 0 -> 0x80000001
    li    x25, -8              # 0xFFFFFFF8
    srai  x26, x25, 2          # -8 >> 2 = -2 = 0xFFFFFFFE
    srli  x27, x25, 2          # 0x3FFFFFFE
    sra   x28, x25, x14        # -8 >> 1 = 0xFFFFFFFC
    srl   x29, x25, x14        # 0x7FFFFFFC
    slli  x30, x25, 28         # 0x80000000
""" + signature_dump(),
        expect={1: 0x80000001, 2: 0x12345678, 3: 0x80000001, 4: 2, 5: 0x80000000, 6: 0x80000001,
                7: 0x40000000, 8: 1, 9: 0x80000001, 10: 0xC0000000, 11: 0xFFFFFFFF,
                12: 0x01234567, 13: 31, 14: 33, 15: 0xFFFFFFE0, 16: 0x80000000, 17: 1,
                18: 0xFFFFFFFF, 19: 0x2468ACF0, 20: 0x40000000, 21: 0xC0000000,
                22: 0x12345678, 23: 0x80000001, 24: 0x80000001, 25: 0xFFFFFFF8,
                26: 0xFFFFFFFE, 27: 0x3FFFFFFE, 28: 0xFFFFFFFC, 29: 0x7FFFFFFC, 30: 0x80000000}))

    # ---------------------------------------------------------------- branches
    # Forward cases: x29 collects one bit per case (MSB = case 0), 1 = taken;
    # x28 counts not-taken cases.  Values: x1=0x80000000, x2=0x7FFFFFFF,
    # x3=-1, x4=x5=1.
    cases = [  # (mnemonic, rs1, rs2, taken?)   derivation
        ("beq", 4, 5, 1),    # 1 == 1
        ("beq", 4, 3, 0),    # 1 != -1
        ("bne", 4, 3, 1),
        ("bne", 4, 5, 0),
        ("blt", 1, 2, 1),    # -2^31 < 2^31-1 (signed)
        ("blt", 2, 1, 0),
        ("blt", 3, 4, 1),    # -1 < 1
        ("bge", 2, 1, 1),    # 2^31-1 >= -2^31
        ("bge", 1, 2, 0),
        ("bge", 4, 5, 1),    # equal -> taken
        ("bltu", 2, 1, 1),   # 0x7FFFFFFF <u 0x80000000
        ("bltu", 1, 2, 0),
        ("bltu", 4, 3, 1),   # 1 <u 0xFFFFFFFF
        ("bgeu", 1, 2, 1),   # 0x80000000 >=u 0x7FFFFFFF
        ("bgeu", 4, 3, 0),   # 1 >=u 0xFFFFFFFF false
        ("bgeu", 0, 0, 1),   # equal -> taken
    ]
    body = ["    li    x1, 0x80000000", "    li    x2, 0x7FFFFFFF", "    li    x3, -1",
            "    addi  x4, x0, 1", "    addi  x5, x0, 1"]
    pattern = 0
    for n, (mn, r1, r2, tk) in enumerate(cases):
        body += [f"    # case {n}: {mn} x{r1}, x{r2} -> {'taken' if tk else 'not taken'}",
                 "    slli  x29, x29, 1",
                 f"    {mn:5s} x{r1}, x{r2}, BT{n}      # forward branch",
                 "    addi  x28, x28, 1          # not-taken path",
                 f"    jal   x0, BE{n}",
                 f"BT{n}: ori   x29, x29, 1          # taken path",
                 f"BE{n}:"]
        pattern = (pattern << 1) | tk
    body += [
        "    # long forward branch over 512 bytes of zero words (would trap if executed)",
        "    beq   x0, x0, long_fwd",
        "    .space 0x200",
        "long_fwd:",
        "    addi  x27, x0, 0x27",
        "    # backward branches (loops), one per condition; each ends not-taken",
        "    addi  x10, x0, 5",
        "Lb1: addi  x11, x11, 1",
        "    addi  x10, x10, -1",
        "    bne   x10, x0, Lb1         # taken 4x backward -> x11 = 5, x10 = 0",
        "    addi  x12, x0, -3",
        "    addi  x13, x0, 2",
        "Lb2: addi  x14, x14, 1",
        "    addi  x12, x12, 1",
        "    blt   x12, x13, Lb2        # x12 = -2,-1,0,1,2 -> 5 iterations, signed across 0",
        "    addi  x15, x0, 3",
        "Lb3: addi  x16, x16, 1",
        "    addi  x15, x15, -1",
        "    bgeu  x15, x5, Lb3         # x15 = 2,1 taken, 0 not -> x16 = 3",
        "    addi  x19, x0, 4",
        "Lb4: addi  x17, x17, 1",
        "    bltu  x17, x19, Lb4        # x17 = 1,2,3 taken, 4 not -> x17 = 4",
        "    addi  x20, x0, 3",
        "Lb5: addi  x21, x21, 1",
        "    addi  x20, x20, -1",
        "    bge   x20, x0, Lb5         # x20 = 2,1,0 taken, -1 not -> x21 = 4",
        "Lb6: addi  x22, x22, 1",
        "    slti  x23, x22, 3",
        "    beq   x23, x5, Lb6         # x22 = 1,2 taken, 3 not -> x22 = 3, x23 = 0",
    ]
    assert pattern == 0xAB6D  # hand-derived: T N T N | T N T T | N T T N | T T N T
    tests.append(TestSpec(
        "dir_branches", "directed",
        "All six branches taken / not-taken forward, signed vs unsigned with "
        "0x80000000, long forward branch (0x204), backward loops for every condition",
        "\n".join(body) + "\n" + signature_dump(),
        expect={1: 0x80000000, 2: 0x7FFFFFFF, 3: 0xFFFFFFFF, 4: 1, 5: 1, 10: 0, 11: 5,
                12: 2, 13: 2, 14: 5, 15: 0, 16: 3, 17: 4, 19: 4, 20: 0xFFFFFFFF, 21: 4,
                22: 3, 23: 0, 27: 0x27, 28: 6, 29: 0xAB6D}))

    # ---------------------------------------------------------------- jumps
    tests.append(TestSpec(
        "dir_jumps", "directed",
        "JAL/JALR forward and backward, link values, JALR clears bit 0 of the "
        "target, JALR with rd == rs1, negative JALR offset, x0 link discarded, "
        "long JAL over 1 KiB", """
    jal   x1, sub1             # call: x1 = ret1
ret1:
    addi  x10, x10, 1          # executed once, after the return
    jal   x0, over             # j: link to x0 is discarded
sub1:
    addi  x11, x0, 0x11
    jalr  x0, 0(x1)            # ret
over:
    la    x5, target_odd
    jalr  x2, 1(x5)            # target = (x5 + 1) & ~1 = target_odd (bit 0 cleared)
skip1:
    addi  x12, x0, 0x7FF       # skipped
target_odd:
    addi  x13, x0, 0x13
    la    x6, back_tgt
    jal   x0, fwd2
back_tgt:
    addi  x14, x0, 0x14        # reached by the backward jalr below
    jal   x0, after_back
fwd2:
    jalr  x7, 0(x6)            # backward jalr, x7 = skip2
skip2:
    addi  x15, x0, 0x7FF       # skipped
after_back:
    la    x8, tgt3
    jalr  x8, 0(x8)            # rd == rs1: target uses the OLD x8, then x8 = skip3
skip3:
    addi  x16, x0, 0x7FF       # skipped
tgt3:
    addi  x17, x0, 2
loop_j:
    addi  x17, x17, -1
    beq   x17, x0, done_j
    jal   x18, loop_j          # backward jal, x18 = done_j
done_j:
    la    x19, after_neg
    addi  x19, x19, 8          # x19 = after_neg + 8
    jalr  x20, -8(x19)         # negative offset -> after_neg, x20 = skip4
skip4:
    addi  x21, x0, 0x7FF       # skipped
after_neg:
    addi  x22, x0, 0x22
    jal   x23, far             # long forward jal over 1 KiB of zero words
    .space 0x400
far:
    addi  x24, x0, 0x24
""" + signature_dump(),
        expect={1: lambda s: s["ret1"], 2: lambda s: s["skip1"], 5: lambda s: s["target_odd"],
                6: lambda s: s["back_tgt"], 7: lambda s: s["skip2"], 8: lambda s: s["skip3"],
                10: 1, 11: 0x11, 13: 0x13, 14: 0x14, 17: 0, 18: lambda s: s["done_j"],
                19: lambda s: s["after_neg"] + 8, 20: lambda s: s["skip4"], 22: 0x22,
                23: lambda s: s["far"] - 0x400, 24: 0x24}))

    # ---------------------------------------------------------------- loads
    tests.append(TestSpec(
        "dir_loads", "directed",
        "LB/LBU/LH/LHU/LW from every byte / halfword lane, sign extension of "
        "0x80/0xFF/0x8000, negative offsets, rd == rs1", """
    lui   x1, 0x1
    addi  x1, x1, -2048        # x1 = 0x800 (data)
    lb    x2, 0(x1)            # byte 0 = 0x7F -> 0x0000007F
    lb    x3, 1(x1)            # byte 1 = 0xFF -> 0xFFFFFFFF
    lb    x4, 2(x1)            # byte 2 = 0x40 -> 0x00000040
    lb    x5, 3(x1)            # byte 3 = 0x80 -> 0xFFFFFF80
    lbu   x6, 1(x1)            # 0x000000FF
    lbu   x7, 3(x1)            # 0x00000080
    lh    x8, 4(x1)            # half 0x8000 -> 0xFFFF8000
    lh    x9, 6(x1)            # half 0x7FFF -> 0x00007FFF
    lhu   x10, 4(x1)           # 0x00008000
    lhu   x11, 2(x1)           # upper half of word 0 = 0x8040
    lh    x12, 2(x1)           # 0xFFFF8040
    lh    x13, 0(x1)           # 0xFF7F -> 0xFFFFFF7F
    lw    x14, 8(x1)           # 0xFFFFFFFF
    lw    x15, 12(x1)          # 0x12345678
    addi  x16, x1, 16          # x16 = 0x810
    lw    x17, -4(x16)         # 0x12345678
    lbu   x18, -1(x16)         # byte 0x80F = 0x12
    lb    x19, -2(x16)         # byte 0x80E = 0x34
    lhu   x20, -2(x16)         # 0x1234
    lhu   x21, -8(x16)         # 0xFFFF
    lw    x22, 16(x1)          # 0x00000000 (zero-initialised word)
    lw    x23, 0(x1)           # 0x8040FF7F
    lw    x1, 0(x1)            # rd == rs1: x1 = 0x8040FF7F
    jal   x0, sig_dump         # jump over the data area
.org 0x800
data:
    .word 0x8040FF7F           # bytes (little-endian) 7F FF 40 80
    .word 0x7FFF8000           # halves 0x8000 (low), 0x7FFF (high)
    .word 0xFFFFFFFF
    .word 0x12345678
.org 0x900                     # signature dump code placed after the data
""" + signature_dump(),
        expect={1: 0x8040FF7F, 2: 0x7F, 3: 0xFFFFFFFF, 4: 0x40, 5: 0xFFFFFF80, 6: 0xFF, 7: 0x80,
                8: 0xFFFF8000, 9: 0x7FFF, 10: 0x8000, 11: 0x8040, 12: 0xFFFF8040,
                13: 0xFFFFFF7F, 14: 0xFFFFFFFF, 15: 0x12345678, 16: 0x810, 17: 0x12345678,
                18: 0x12, 19: 0x34, 20: 0x1234, 21: 0xFFFF, 22: 0, 23: 0x8040FF7F}))

    # ---------------------------------------------------------------- stores
    tests.append(TestSpec(
        "dir_stores", "directed",
        "SB into each byte lane, SH into each half, SW; load immediately after "
        "store; upper rs2 bits ignored; negative offsets; rs2 == rs1", """
    lui   x1, 0x1
    addi  x1, x1, -1792        # x1 = 0x900
    li    x2, 0x11223344
    sw    x0, 0(x1)
    sb    x2, 0(x1)            # lane 0 <- 0x44 (rs2[31:8] ignored)
    lw    x4, 0(x1)            # load-after-store: 0x00000044
    sb    x2, 1(x1)            # lane 1 <- 0x44
    lw    x5, 0(x1)            # 0x00004444
    addi  x6, x0, 0xAB
    sb    x6, 2(x1)            # lane 2
    sb    x6, 3(x1)            # lane 3
    lw    x7, 0(x1)            # 0xABAB4444
    lb    x8, 3(x1)            # 0xFFFFFFAB
    li    x9, 0xCAFE8001
    sw    x0, 4(x1)
    sh    x9, 4(x1)            # low half <- 0x8001
    lw    x10, 4(x1)           # 0x00008001
    sh    x9, 6(x1)            # high half <- 0x8001
    lw    x11, 4(x1)           # 0x80018001
    lh    x12, 6(x1)           # 0xFFFF8001
    lhu   x13, 4(x1)           # 0x00008001
    sw    x2, 8(x1)
    lw    x14, 8(x1)           # 0x11223344
    sb    x0, 9(x1)            # clear lane 1 -> 0x11220044
    lw    x15, 8(x1)
    sh    x0, 10(x1)           # clear upper half -> 0x00000044
    lw    x16, 8(x1)
    sw    x9, -4(x1)           # negative offset: [0x8FC] <- 0xCAFE8001
    lw    x17, -4(x1)          # 0xCAFE8001
    sw    x2, 12(x1)
    lbu   x18, 13(x1)          # 0x33
    lhu   x19, 14(x1)          # 0x1122
    lb    x20, 12(x1)          # 0x44
    sw    x1, 16(x1)           # rs2 == rs1: stores 0x900
    lw    x21, 16(x1)          # 0x00000900
    sb    x6, 20(x1)
    sb    x2, 20(x1)           # second store to the same byte wins: 0x44
    lw    x22, 20(x1)          # 0x00000044
    lw    x23, 0(x1)           # re-read the first word: 0xABAB4444
""" + signature_dump(),
        expect={1: 0x900, 2: 0x11223344, 4: 0x44, 5: 0x4444, 6: 0xAB, 7: 0xABAB4444,
                8: 0xFFFFFFAB, 9: 0xCAFE8001, 10: 0x8001, 11: 0x80018001, 12: 0xFFFF8001,
                13: 0x8001, 14: 0x11223344, 15: 0x11220044, 16: 0x44, 17: 0xCAFE8001,
                18: 0x33, 19: 0x1122, 20: 0x44, 21: 0x900, 22: 0x44, 23: 0xABAB4444}))

    # ---------------------------------------------------------------- x0
    tests.append(TestSpec(
        "dir_x0", "directed",
        "Writes to x0 by every instruction class are discarded; x0 reads 0", """
    addi  x0, x0, 5
    lui   x0, 0x12345
    auipc x0, 1
    addi  x1, x0, 7            # x1 = 7: x0 still reads 0
    add   x0, x1, x1
    sub   x0, x0, x1
    slli  x0, x1, 3
    lui   x2, 0x1
    addi  x2, x2, -2048        # x2 = 0x800
    lw    x0, 0(x2)            # load of 0xDEADBEEF into x0: discarded
    jal   x0, l1               # link discarded
l1:
    la    x3, l2
    jalr  x0, 0(x3)            # link discarded
l2:
    add   x4, x0, x1           # 7
    addi  x5, x0, 0            # 0
    sltu  x6, x0, x0           # 0
    or    x7, x0, x0           # 0
    sw    x0, 4(x2)            # store x0 (=0) over 0xFFFFFFFF
    lw    x8, 4(x2)            # 0
    sub   x9, x0, x1           # -7 = 0xFFFFFFF9
    lw    x10, 0(x2)           # 0xDEADBEEF (the load to x0 did not change memory)
    jal   x0, sig_dump
.org 0x800
    .word 0xDEADBEEF, 0xFFFFFFFF
.org 0x900
""" + signature_dump(),
        expect={1: 7, 2: 0x800, 3: lambda s: s["l2"], 4: 7, 9: 0xFFFFFFF9, 10: 0xDEADBEEF}))

    # ---------------------------------------------------------------- fence / nop
    tests.append(TestSpec(
        "dir_fence_nop", "directed",
        "FENCE (several pred/succ sets) and NOP behave as no-ops", """
    addi  x1, x0, 1
    fence                      # fence iorw, iorw
    addi  x1, x1, 1
    fence rw, rw
    nop
    fence w, r
    addi  x1, x1, 1            # x1 = 3
    lui   x2, 0x1
    addi  x2, x2, -2048        # 0x800
    sw    x1, 0(x2)
    fence                      # store then fence then load: value unchanged
    lw    x3, 0(x2)            # 3
""" + signature_dump(),
        expect={1: 3, 2: 0x800, 3: 3}))

    # ---------------------------------------------------------------- MMIO
    tests.append(TestSpec(
        "dir_mmio", "directed",
        "Peripheral access: LED write/read-back, UART_STATUS reads 0 when idle, "
        "unmapped region reads 0 / ignores writes (sets sticky bus_err)", """
    lui   x1, 0x10000          # x1 = 0x1000_0000 peripheral base
    addi  x2, x0, 0x2A
    sw    x2, 0(x1)            # LED <- 0x2A (6-bit register)
    lw    x3, 0(x1)            # LED read-back: 0x2A
    lw    x4, 8(x1)            # UART_STATUS: 0 (nothing transmitted yet)
    lui   x5, 0x30000          # 0x3000_0000: unmapped
    sw    x2, 0(x5)            # ignored (bus_err)
    lw    x6, 0(x5)            # 0
""" + signature_dump(),
        expect={1: 0x10000000, 2: 0x2A, 3: 0x2A, 4: 0, 5: 0x30000000, 6: 0},
        expect_bus_err=True,
        requires=["ram", "tohost", "led", "uart_status", "unmapped_bus"]))
    return tests


# --------------------------------------------------------------------------
# Random tests
# --------------------------------------------------------------------------
SPECIAL_VALUES = [0, 1, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF, 0x7FF, 0x800,
                  0xFFFFF800, 0x0000FFFF, 0xFFFF0000, 0x55555555, 0xAAAAAAAA]
SPECIAL_IMM = [0, 1, -1, 2047, -2048, 0x7F, 0x80, -0x80]


def random_test(seed: int, n_body: int = 200, name: str | None = None) -> TestSpec:
    """Random ALU / load / store / branch / jump program with seed ``seed``.

    * Prologue: every register x1..x31 gets a random value (25 % chosen from
      SPECIAL_VALUES), except one randomly chosen BASE register = 0x800.
    * Body: ``n_body`` slots, each exactly ONE instruction, so branch
      targets are known by slot index.  Control flow is forward-only
      (branches skip 0..6 slots, JAL 0..4, an AUIPC+JALR gadget with an odd
      offset skips 0..4 slots), therefore every program terminates.  BASE is
      never written; loads / stores use aligned offsets inside the 512-byte
      data area, which is pre-filled with random words.
    * Epilogue: signature dump + TOHOST.
    """
    rng = np.random.default_rng(seed)
    ri = lambda lo, hi: int(rng.integers(lo, hi))  # noqa: E731  [lo, hi)
    base = ri(1, 32)
    writable = [r for r in range(32) if r != base]          # x0 allowed as rd
    srcs = list(range(32))

    def rand_u32() -> int:
        if rng.random() < 0.25:
            return SPECIAL_VALUES[ri(0, len(SPECIAL_VALUES))]
        return int(rng.integers(0, 1 << 32))

    def rand_imm() -> int:
        if rng.random() < 0.25:
            return SPECIAL_IMM[ri(0, len(SPECIAL_IMM))]
        return ri(-2048, 2048)

    lines = [f"# random test, numpy default_rng seed = {seed}, base register x{base} = {DATA_BASE:#x}"]
    for r in range(1, 32):
        lines.append(f"    li    x{r}, {DATA_BASE:#x}" if r == base else f"    li    x{r}, {rand_u32():#010x}")

    slots: list[str] = [""] * n_body
    labels: dict[int, str] = {}         # slot index -> label placed before it
    targets: set[int] = set()           # slot indices that are jump targets
    gadget_second: set[int] = set()     # JALR slots that must not be entered directly
    r_ops, i_ops, l_ops, s_ops, b_ops = list(R_TYPE), list(I_ALU), list(LOADS), list(STORES), list(BRANCHES)
    pick = lambda seq: seq[ri(0, len(seq))]  # noqa: E731

    def target_label(t: int) -> str:
        targets.add(t)
        return labels.setdefault(t, f"L{t:03d}")

    i = 0
    while i < n_body:
        u = rng.random()
        rd = pick(writable)
        if u < 0.30:                                        # R-type
            slots[i] = f"    {pick(r_ops):5s} x{rd}, x{pick(srcs)}, x{pick(srcs)}"
        elif u < 0.52:                                      # I-type ALU
            slots[i] = f"    {pick(i_ops):5s} x{rd}, x{pick(srcs)}, {rand_imm()}"
        elif u < 0.60:                                      # shift immediate
            sh = pick([0, 31, ri(0, 32), ri(0, 32)])
            slots[i] = f"    {pick(['slli', 'srli', 'srai']):5s} x{rd}, x{pick(srcs)}, {sh}"
        elif u < 0.65:                                      # LUI / AUIPC
            slots[i] = f"    {pick(['lui', 'auipc']):5s} x{rd}, {ri(0, 1 << 20):#x}"
        elif u < 0.78:                                      # load
            op = pick(l_ops)
            size = {"lb": 1, "lbu": 1, "lh": 2, "lhu": 2, "lw": 4}[op]
            off = ri(0, DATA_BYTES // size) * size
            slots[i] = f"    {op:5s} x{rd}, {off}(x{base})"
        elif u < 0.88:                                      # store
            op = pick(s_ops)
            size = {"sb": 1, "sh": 2, "sw": 4}[op]
            off = ri(0, DATA_BYTES // size) * size
            slots[i] = f"    {op:5s} x{pick(srcs)}, {off}(x{base})"
        elif u < 0.97:                                      # forward branch
            t = min(i + 1 + ri(0, 7), n_body)
            if t in gadget_second:
                t += 1
            r1 = pick(srcs)
            r2 = r1 if rng.random() < 0.2 else pick(srcs)   # some equal operands
            slots[i] = f"    {pick(b_ops):5s} x{r1}, x{r2}, {target_label(t)}"
        elif u < 0.99 or i + 1 >= n_body or (i + 1) in targets:   # forward JAL
            t = min(i + 1 + ri(0, 5), n_body)
            if t in gadget_second:
                t += 1
            slots[i] = f"    jal   x{rd}, {target_label(t)}"
        else:                                               # AUIPC + JALR gadget
            rt = pick([r for r in writable if r != 0])
            k = ri(0, min(5, n_body - (i + 2) + 1))
            t = i + 2 + k
            odd = ri(0, 2)                                  # bit 0 must be cleared by JALR
            slots[i] = f"    auipc x{rt}, 0                # gadget: x{rt} = pc"
            slots[i + 1] = (f"    jalr  x{rd}, {4 * (2 + k) + odd}(x{rt})     "
                            f"# -> slot {t} (offset bit0={odd} cleared)")
            gadget_second.add(i + 1)
            targets.add(t)
            i += 2
            continue
        i += 1
    assert not (targets & gadget_second), "a jump target hits the middle of a gadget"
    assert all(slots), "every body slot must hold one instruction"

    lines.append("# ---- random body ----")
    for idx, s in enumerate(slots):
        if idx in labels:
            lines.append(f"{labels[idx]}:")
        lines.append(s)
    if n_body in labels:
        lines.append(f"{labels[n_body]}:")
    lines.append("    jal   x0, sig_dump        # skip over the data area")
    lines.append(f".org {DATA_BASE:#x}")
    lines.append("rand_data:")
    for w in range(0, DATA_BYTES // 4, 8):
        lines.append("    .word " + ", ".join(f"{int(rng.integers(0, 1 << 32)):#010x}" for _ in range(8)))
    lines.append(f".org {DATA_BASE + DATA_BYTES:#x}")
    src = "\n".join(lines) + "\n" + signature_dump()
    return TestSpec(name or f"rand_{seed}", "random",
                    f"random program, seed {seed}, {n_body} body instructions, base x{base}",
                    src, seed=seed)


# --------------------------------------------------------------------------
# Trap tests
# --------------------------------------------------------------------------
_TRAP_PRE = """
    li    x5, 0x5A5A5A5A       # marker: must survive the trap (rd of trapping insns)
    li    x6, 0x800
    li    x7, 0xDEADBEEF       # store data for the misaligned stores
    li    x31, 0x31313131
"""


def trap_tests() -> list[TestSpec]:
    """Trap programs: (name, description, cause, code placed after the dump)."""
    defs = [
        ("trap_ecall", "ECALL halts with cause 1", TrapCause.ECALL,
         "trap_here:\n    ecall\n"),
        ("trap_ebreak", "EBREAK halts with cause 2", TrapCause.EBREAK,
         "trap_here:\n    ebreak\n"),
        ("trap_illegal_zero", "all-zero word 0x00000000 is illegal (inst[1:0] = 00)",
         TrapCause.ILLEGAL, "trap_here:\n    .word 0x00000000\n"),
        ("trap_illegal_ones", "all-ones word 0xFFFFFFFF is illegal", TrapCause.ILLEGAL,
         "trap_here:\n    .word 0xFFFFFFFF\n"),
        ("trap_illegal_csr", "CSRRW x0, 0x300, x0 (0x30001073) is illegal: no CSRs in rev A",
         TrapCause.ILLEGAL, "trap_here:\n    .word 0x30001073      # csrrw x0, mstatus, x0\n"),
        ("trap_illegal_funct7", "OP with funct7 = 0000001 (MUL x1,x2,x3 = 0x023100B3) is illegal in RV32I",
         TrapCause.ILLEGAL, "trap_here:\n    .word 0x023100B3      # mul x1, x2, x3 (M extension)\n"),
        ("trap_misaligned_lw", "LW from 0x802 halts with cause 5; rd (x5) unchanged",
         TrapCause.MISALIGNED_LOAD, "trap_here:\n    lw    x5, 2(x6)          # 0x802\n"),
        ("trap_misaligned_lh", "LH from 0x801 halts with cause 5; rd (x5) unchanged",
         TrapCause.MISALIGNED_LOAD, "trap_here:\n    lh    x5, 1(x6)          # 0x801\n"),
        ("trap_misaligned_sh", "SH to 0xF41 (inside the signature) halts with cause 6; memory unchanged",
         TrapCause.MISALIGNED_STORE, "trap_here:\n    sh    x7, -191(x1)       # x1 = 0x1000 -> 0xF41\n"),
        ("trap_misaligned_sw", "SW to 0xF42 (inside the signature) halts with cause 6; memory unchanged",
         TrapCause.MISALIGNED_STORE, "trap_here:\n    sw    x7, -190(x1)       # x1 = 0x1000 -> 0xF42\n"),
        ("trap_misaligned_jalr", "JALR to target+2 halts with cause 4 at the JALR; rd (x5) unchanged",
         TrapCause.MISALIGNED_FETCH,
         "    la    x8, jtarget\ntrap_here:\n    jalr  x5, 2(x8)          # (jtarget+2) & ~1 is not 4-aligned\n"
         "jtarget:\n    nop\n"),
        ("trap_misaligned_jal", "JAL with offset +6 halts with cause 4 at the JAL; rd (x5) unchanged",
         TrapCause.MISALIGNED_FETCH, "trap_here:\n    jal   x5, .+6\n    nop\n    nop\n"),
        ("trap_misaligned_branch",
         "not-taken BNE to .+6 must NOT trap; taken BEQ to .+6 halts with cause 4 at the BEQ",
         TrapCause.MISALIGNED_FETCH,
         "    bne   x0, x0, .+6        # not taken: no trap\n"
         "trap_here:\n    beq   x0, x0, .+6        # taken, misaligned target\n    nop\n    nop\n"),
    ]
    out = []
    for name, desc, cause, code in defs:
        src = (f"# trap test: {desc}\n" + _TRAP_PRE + signature_dump(tohost=False)
               + "    # ---- trapping instruction ----\n" + code + tohost_fail())
        out.append(TestSpec(name, "trap", desc, src, trap=(cause, "trap_here"),
                            expect={5: 0x5A5A5A5A, 6: 0x800, 7: 0xDEADBEEF, 31: 0x31313131}))
    return out


# --------------------------------------------------------------------------
# Build / check / write
# --------------------------------------------------------------------------
class CheckError(Exception):
    """A self-check of the generator failed."""


def regs_at(image: list[int], pc_stop: int) -> list[int]:
    """Registers at the first time execution reaches ``pc_stop`` (ISS)."""
    iss = Iss(image)
    for _ in range(MAX_STEPS):
        if iss.pc == pc_stop or iss.stop_reason is not None:
            break
        iss.step()
    if iss.pc != pc_stop:
        raise CheckError(f"execution never reached {pc_stop:#x}")
    return list(iss.regs)


def retired_mnemonics(image: list[int]) -> Counter:
    """Count retired instructions per base mnemonic (coverage evidence)."""
    iss, cov = Iss(image), Counter()
    for _ in range(MAX_STEPS):
        if iss.stop_reason is not None:
            break
        pc, word, before = iss.pc, iss.bus_read(iss.pc), iss.instret
        iss.step()
        if iss.instret != before:
            mnem = disassemble(word).split()[0]
            cov[mnem] += 1
            if mnem in BRANCHES:   # taken / not-taken statistics
                cov["(branch next_pc!=pc+4)" if iss.pc != pc + 4 else "(branch next_pc==pc+4)"] += 1
    return cov


def build(spec: TestSpec) -> tuple[Program, IssResult, dict]:
    """Assemble, self-check and simulate one test.  Returns (prog, result, meta)."""
    prog = assemble(spec.source)
    errs: list[str] = []
    # Layout checks: code + data must not touch the scratch word or the signature.
    if SCRATCH in prog.words:
        errs.append("program occupies the scratch word 0x7FC")
    if any(SIG_BASE <= a < SIG_BASE + 4 * SIG_WORDS for a in prog.words):
        errs.append("program occupies the signature area")
    code_end = max(a for a in prog.words if a < DATA_BASE) + 4
    if code_end > SCRATCH:
        errs.append(f"code ends at {code_end:#x} > scratch 0x7FC")
    # Round-trip self-check: disassemble every word and re-assemble it.
    rt = roundtrip_mismatches(prog.words)
    if rt:
        errs.append(f"{len(rt)} round-trip mismatches, first {rt[0]}")
    image = prog.image()
    res = Iss(image).run(MAX_STEPS)
    sig = res.signature(SIG_BASE, SIG_WORDS)
    sym = prog.symbols

    if spec.trap is None:
        if res.stop_reason != "tohost" or res.tohost != 1:
            errs.append(f"expected TOHOST=1 stop, got {res.stop_reason} tohost={res.tohost} "
                        f"cause={res.trap_cause} pc={res.pc:#x}")
        if res.pc != sym["tohost_store"]:
            errs.append(f"stopped at {res.pc:#x}, expected tohost_store {sym['tohost_store']:#x}")
    else:
        cause, label = spec.trap
        if res.stop_reason != "trap" or res.trap_cause != cause or res.pc != sym[label]:
            errs.append(f"expected trap {cause.name} at {sym[label]:#x}, got {res.stop_reason} "
                        f"cause={res.trap_cause} pc={res.pc:#x}")
    if res.bus_err != spec.expect_bus_err:
        errs.append(f"bus_err = {res.bus_err}, expected {spec.expect_bus_err}")
    # Signature == registers at sig_dump (independent re-run that stops there).
    snap = regs_at(image, sym["sig_dump"])
    if sig != [0] + snap[1:]:
        errs.append("signature in RAM differs from the register snapshot at sig_dump")
    # Hand-derived expectations (directed and trap tests).
    if spec.expect is not None:
        for k in range(1, 32):
            exp = spec.expect.get(k, 0)
            exp = exp(sym) if callable(exp) else exp
            if spec.trap is not None and k not in spec.expect:
                continue                   # trap tests: only listed registers checked
            if sig[k] != exp & 0xFFFFFFFF:
                errs.append(f"x{k} = {sig[k]:#010x}, hand-derived {exp & 0xFFFFFFFF:#010x}")
        if spec.trap is not None:          # rd of the trapping insn must be unchanged
            for k in spec.expect:
                if k not in (1, 2) and res.regs[k] != spec.expect[k]:
                    errs.append(f"after trap x{k} = {res.regs[k]:#x}, expected {spec.expect[k]:#x}")
    if errs:
        raise CheckError(f"{spec.name}: " + "; ".join(errs))

    meta = {
        "name": spec.name,
        "kind": spec.kind,
        "description": spec.description,
        "seed": spec.seed,
        "rng": "numpy.random.default_rng" if spec.seed is not None else None,
        "requires": spec.requires,
        "expected_stop": res.stop_reason,
        "expected_halted": res.stop_reason == "trap",
        "expected_trap_cause": res.trap_cause,
        "expected_trap_name": TRAP_NAMES[res.trap_cause],
        "expected_halt_pc": f"0x{res.pc:08x}" if res.stop_reason == "trap" else None,
        "tohost_pc": f"0x{res.pc:08x}" if res.stop_reason == "tohost" else None,
        "expected_tohost": res.tohost,
        "instret": res.instret,
        "instret_note": "retired instructions; trapping instruction not counted, TOHOST store counted",
        "signature_base": f"0x{SIG_BASE:08x}",
        "signature_words": SIG_WORDS,
        "signature_layout": "word k at 0x0F00+4k = xk at label sig_dump (k=1..31); 0x0F00 = 0",
        "sig_dump_pc": f"0x{sym['sig_dump']:08x}",
        "expected_bus_err": res.bus_err,
        "expected_uart": res.uart.decode("latin-1"),
        "expected_led": res.led,
        "final_regs": [f"0x{v:08x}" for v in res.regs],
        "final_regs_note": "ISS registers at the stop point (x1/x2 are clobbered by the dump; "
                           "for trap tests rd of the trapping instruction must be unchanged)",
        "code_bytes": max(a for a in prog.words if a < DATA_BASE) + 4,
        "image_words_nonzero": sum(1 for w in image if w),
        "roundtrip_mismatches": len(rt),
    }
    return prog, res, meta


def write_test(out_dir: Path, spec: TestSpec, prog: Program, res: IssResult, meta: dict) -> None:
    """Write <name>.hex / .sig / .meta.json / .lst."""
    write_hex(out_dir / f"{spec.name}.hex", prog.image())
    write_hex(out_dir / f"{spec.name}.sig", res.signature(SIG_BASE, SIG_WORDS))
    meta = dict(meta)
    meta["hex_sha256"] = hashlib.sha256((out_dir / f"{spec.name}.hex").read_bytes()).hexdigest()
    meta["sig_sha256"] = hashlib.sha256((out_dir / f"{spec.name}.sig").read_bytes()).hexdigest()
    (out_dir / f"{spec.name}.meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    (out_dir / f"{spec.name}.lst").write_text(prog.listing_text(
        f"{spec.name}: {spec.description} (generated by code/python/rv32/gen_cpu_tests.py)"))


def all_specs(n_random: int, base_seed: int, n_body: int) -> list[TestSpec]:
    """Directed, random (seeds base_seed + i) and trap tests, in index order."""
    specs = directed_tests()
    specs += [random_test(base_seed + i, n_body, name=f"rand_{i:02d}") for i in range(n_random)]
    specs += trap_tests()
    return specs


def git_revision() -> str:
    """``git rev-parse --short HEAD`` plus ``-dirty`` when the tree is dirty."""
    try:
        rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                               capture_output=True, text=True, check=True).stdout.strip()
        return rev + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point.  Returns 0 if every self-check passed."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="output directory")
    ap.add_argument("--n-random", type=int, default=20, help="number of random programs")
    ap.add_argument("--base-seed", type=int, default=1000, help="seed of rand_00 (rand_i uses base+i)")
    ap.add_argument("--body", type=int, default=200, help="random body length (instructions)")
    ap.add_argument("--summary", type=Path, default=REPO / "reports" / "sw" / "cpu_tests_summary.json")
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    rev = git_revision()
    print(f"gen_cpu_tests: revision {rev}, n_random={args.n_random}, base_seed={args.base_seed}, "
          f"body={args.body}, out={args.out}")
    names, rows, failures, coverage = [], [], [], Counter()
    for spec in all_specs(args.n_random, args.base_seed, args.body):
        try:
            prog, res, meta = build(spec)
        except CheckError as e:
            failures.append(str(e))
            print(f"FAIL {e}")
            continue
        write_test(args.out, spec, prog, res, meta)
        coverage += retired_mnemonics(prog.image())
        names.append(spec.name)
        rows.append({k: meta[k] for k in ("name", "kind", "seed", "expected_stop", "expected_trap_cause",
                                          "expected_halt_pc", "tohost_pc", "instret", "code_bytes",
                                          "roundtrip_mismatches")})
        print(f"PASS {spec.name:24s} kind={spec.kind:8s} seed={str(spec.seed):5s} "
              f"stop={res.stop_reason:6s} cause={res.trap_cause} pc=0x{res.pc:08x} "
              f"instret={res.instret:5d} code={meta['code_bytes']:5d}B roundtrip_mismatch=0")
    (args.out / "index.txt").write_text("".join(n + "\n" for n in names))
    summary = {"generator": "code/python/rv32/gen_cpu_tests.py", "revision": rev,
               "n_random": args.n_random, "base_seed": args.base_seed, "body": args.body,
               "random_seeds": {f"rand_{i:02d}": args.base_seed + i for i in range(args.n_random)},
               "retired_per_mnemonic": dict(sorted(coverage.items())),
               "base_mnemonics_never_retired": [m for m in BASE_MNEMONICS
                                                if m not in coverage and m not in ("ecall", "ebreak")],
               "coverage_note": "ecall/ebreak never retire (they trap); see trap tests",
               "tests": rows, "n_tests": len(names), "n_failures": len(failures), "failures": failures,
               "label": "SIMULATION (Python reference ISS, not RTL)"}
    args.summary.parent.mkdir(parents=True, exist_ok=True)
    args.summary.write_text(json.dumps(summary, indent=2) + "\n")
    print("retired instructions per mnemonic (all tests): "
          + ", ".join(f"{k}={v}" for k, v in sorted(coverage.items())))
    print(f"base mnemonics never retired: {summary['base_mnemonics_never_retired']}")
    print(f"wrote {len(names)} tests + index.txt to {args.out}; failures: {len(failures)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
