"""RV32I disassembler used for the assembler round-trip self-check (SW-01b).

Design rule: for EVERY 32-bit word ``w`` and every word-aligned ``pc``::

    asm.assemble_line(disassemble(w), pc) == [w]

To guarantee this, the disassembler

* prints branch / JAL targets PC-relatively as ``.+N`` / ``.-N`` (the
  assembler's ``.`` is the address of the statement, so the text is position
  independent);
* prints only CANONICAL encodings as instructions: every field that the
  assembler cannot express (non-zero reserved fields, undefined funct3/funct7,
  FENCE with fm/rs1/rd != 0, SYSTEM words other than ECALL/EBREAK, ...) makes
  the word come out as ``.word 0x........``, which re-assembles to itself.

Decoding is written independently of ``iss.py`` (same spec, different code) so
that the two can be cross-checked: a word is printed as ``.word`` iff the ISS
treats it as an illegal instruction, except for non-canonical FENCE variants
that the ISS executes as NOP (see ``iss.py``).

Spec: RISC-V Unprivileged ISA, RV32I v2.1, base formats and opcode map.
"""

from __future__ import annotations

from .asm import ABI_NAMES, to_signed

_R = {  # (funct3, funct7) -> mnemonic
    (0, 0x00): "add", (0, 0x20): "sub", (1, 0x00): "sll", (2, 0x00): "slt",
    (3, 0x00): "sltu", (4, 0x00): "xor", (5, 0x00): "srl", (5, 0x20): "sra",
    (6, 0x00): "or", (7, 0x00): "and",
}
_I_ALU = {0: "addi", 2: "slti", 3: "sltiu", 4: "xori", 6: "ori", 7: "andi"}
_SHIFT = {(1, 0x00): "slli", (5, 0x00): "srli", (5, 0x20): "srai"}
_LOAD = {0: "lb", 1: "lh", 2: "lw", 4: "lbu", 5: "lhu"}
_STORE = {0: "sb", 1: "sh", 2: "sw"}
_BRANCH = {0: "beq", 1: "bne", 4: "blt", 5: "bge", 6: "bltu", 7: "bgeu"}


def _rel(off: int) -> str:
    """PC-relative target expression understood by the assembler."""
    return f".+{off}" if off >= 0 else f".-{-off}"


def _fence_set(bits: int) -> str:
    return "".join(c for c, b in zip("iorw", (8, 4, 2, 1)) if bits & b) or "0"


def disassemble(word: int, abi: bool = False) -> str:
    """Return assembler text for one 32-bit word (see module docstring)."""
    w = word & 0xFFFFFFFF
    reg = (lambda r: ABI_NAMES[r]) if abi else (lambda r: f"x{r}")
    opcode = w & 0x7F
    rd = (w >> 7) & 0x1F
    f3 = (w >> 12) & 0x7
    rs1 = (w >> 15) & 0x1F
    rs2 = (w >> 20) & 0x1F
    f7 = w >> 25
    imm_i = to_signed(w >> 20, 12)
    imm_s = to_signed(((w >> 25) << 5) | ((w >> 7) & 0x1F), 12)
    imm_b = to_signed((((w >> 31) & 1) << 12) | (((w >> 7) & 1) << 11)
                      | (((w >> 25) & 0x3F) << 5) | (((w >> 8) & 0xF) << 1), 13)
    imm_j = to_signed((((w >> 31) & 1) << 20) | (((w >> 12) & 0xFF) << 12)
                      | (((w >> 20) & 1) << 11) | (((w >> 21) & 0x3FF) << 1), 21)
    raw = f".word 0x{w:08x}"

    if opcode == 0b0110111:
        return f"lui {reg(rd)}, 0x{w >> 12:x}"
    if opcode == 0b0010111:
        return f"auipc {reg(rd)}, 0x{w >> 12:x}"
    if opcode == 0b1101111:
        return f"jal {reg(rd)}, {_rel(imm_j)}"
    if opcode == 0b1100111:
        return f"jalr {reg(rd)}, {imm_i}({reg(rs1)})" if f3 == 0 else raw
    if opcode == 0b1100011:
        m = _BRANCH.get(f3)
        return f"{m} {reg(rs1)}, {reg(rs2)}, {_rel(imm_b)}" if m else raw
    if opcode == 0b0000011:
        m = _LOAD.get(f3)
        return f"{m} {reg(rd)}, {imm_i}({reg(rs1)})" if m else raw
    if opcode == 0b0100011:
        m = _STORE.get(f3)
        return f"{m} {reg(rs2)}, {imm_s}({reg(rs1)})" if m else raw
    if opcode == 0b0010011:
        if f3 in (1, 5):
            m = _SHIFT.get((f3, f7))
            return f"{m} {reg(rd)}, {reg(rs1)}, {rs2}" if m else raw
        return f"{_I_ALU[f3]} {reg(rd)}, {reg(rs1)}, {imm_i}"
    if opcode == 0b0110011:
        m = _R.get((f3, f7))
        return f"{m} {reg(rd)}, {reg(rs1)}, {reg(rs2)}" if m else raw
    if opcode == 0b0001111:
        fm = w >> 28
        if f3 == 0 and fm == 0 and rd == 0 and rs1 == 0:
            return f"fence {_fence_set((w >> 24) & 0xF)}, {_fence_set((w >> 20) & 0xF)}"
        return raw
    if opcode == 0b1110011:
        if w == 0x00000073:
            return "ecall"
        if w == 0x00100073:
            return "ebreak"
        return raw
    return raw


def disassemble_image(words: dict[int, int] | list[int]) -> list[tuple[int, int, str]]:
    """Disassemble an image: list of (address, word, text)."""
    items = words.items() if isinstance(words, dict) else enumerate_words(words)
    return [(a, w, disassemble(w)) for a, w in sorted(items)]


def enumerate_words(image: list[int]):
    """(byte address, word) pairs of a flat image."""
    return ((4 * i, w) for i, w in enumerate(image))


def roundtrip_mismatches(words: dict[int, int]) -> list[tuple[int, int, str, list[int]]]:
    """Disassemble and re-assemble every word; return the mismatches.

    Each mismatch is (address, original word, disassembly, re-assembled words).
    An empty list means the round-trip self-check passed.
    """
    from .asm import assemble_line  # local import: avoid an import cycle at load
    bad = []
    for addr, w in sorted(words.items()):
        text = disassemble(w)
        again = assemble_line(text, pc=addr)
        if again != [w]:
            bad.append((addr, w, text, again))
    return bad
