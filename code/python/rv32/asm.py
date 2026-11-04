"""Two-pass RV32I reference assembler (task SW-01b, ARCHITECTURE.md section 8).

Purpose
-------
Turns small, generated verification programs (testbench stimuli, NOT firmware)
into 32-bit instruction words, a ``$readmemh`` image of the 4 KiB RAM
(1024 lines x 8 lowercase hex digits, zero padded; INTERFACES.json
``memory_map.RAM`` / ``init_files.prog.hex``) and a human-readable listing.

Specification
-------------
Encodings are written from the RISC-V Unprivileged ISA, chapter "RV32I Base
Integer Instruction Set, Version 2.1":

* base formats (R/I/S/B/U/J) and the position of every immediate bit
  (spec section 2.2 / 2.3, figures "RISC-V base instruction formats" and
  "Types of immediate produced by RISC-V instructions");
* opcode / funct3 / funct7 values from the RV32I opcode map
  (spec chapter "RV32/64G Instruction Set Listings", table RV32I).

Supported syntax (one statement per line)
-----------------------------------------
* Comments: ``#`` or ``//`` to end of line (outside character literals).
* Labels: ``name:`` (several may precede a statement on the same line).
* Registers: ``x0``..``x31`` and the standard ABI names (``zero ra sp gp tp
  t0-t6 s0-s11 fp a0-a7``).
* Expressions: integer literals (decimal, ``0x`` hex, ``0b`` binary, ``_``
  separators allowed), character literals (``'A'``, ``'\\n'``), symbols, ``.``
  (address of the current statement), unary ``- + ~``, binary ``+ - *``,
  parentheses, and the relocation operators ``%hi(expr)`` / ``%lo(expr)``.
* Instructions: all 37 RV32I instructions that the CPU implements plus
  FENCE, ECALL, EBREAK (ARCHITECTURE.md section 6):
  ``lui auipc jal jalr beq bne blt bge bltu bgeu lb lh lw lbu lhu sb sh sw
  addi slti sltiu xori ori andi slli srli srai add sub sll slt sltu xor srl
  sra or and fence ecall ebreak``.
  Branch / JAL targets are ABSOLUTE address expressions (labels, or ``.+8``);
  the assembler subtracts the statement address, exactly like GNU as.
* Pseudo-instructions: ``li la mv nop j ret beqz bnez`` (required by SW-01b)
  plus ``not neg seqz snez jr``, ``jal target`` (rd = ra) and ``jalr rs``.
* Directives: ``.word e1, e2, ...``, ``.org addr``, ``.align n`` (2**n bytes),
  ``.space n`` / ``.zero n`` (n multiple of 4), ``.equ name, expr``.

Two-pass algorithm
------------------
Pass 1 walks the source, assigns an address to every statement and defines
labels.  The size of every statement must be known in pass 1; only ``li``
has a variable size: it is 1 instruction when the (already known) value fits
a single ADDI or LUI, otherwise 2 (LUI + ADDI).  If ``li`` refers to a symbol
that is not yet defined (forward reference) it is conservatively sized as 2.
Pass 2 evaluates every expression with the complete symbol table and encodes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------
# Constants from the frozen interface (INTERFACES.json memory_map.RAM)
# --------------------------------------------------------------------------
RAM_BYTES = 4096          # 4 KiB RAM at address 0 (ARCHITECTURE.md 4)
RAM_WORDS = RAM_BYTES // 4  # 1024 lines in prog.hex (ARCHITECTURE.md 5.6)
MASK32 = 0xFFFFFFFF

# --------------------------------------------------------------------------
# Registers: numeric and ABI names (RISC-V psABI / spec table "Assembler
# mnemonics for RISC-V integer registers").
# --------------------------------------------------------------------------
ABI_NAMES = [
    "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
    "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
    "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
]
REGISTERS: dict[str, int] = {f"x{i}": i for i in range(32)}
REGISTERS.update({name: i for i, name in enumerate(ABI_NAMES)})
REGISTERS["fp"] = 8  # fp is an alias of s0

# --------------------------------------------------------------------------
# Opcodes (spec RV32I opcode map, inst[6:0]).
# --------------------------------------------------------------------------
OP_LUI = 0b0110111
OP_AUIPC = 0b0010111
OP_JAL = 0b1101111
OP_JALR = 0b1100111
OP_BRANCH = 0b1100011
OP_LOAD = 0b0000011
OP_STORE = 0b0100011
OP_IMM = 0b0010011
OP_OP = 0b0110011
OP_MISC_MEM = 0b0001111
OP_SYSTEM = 0b1110011

# funct3 / funct7 tables (spec RV32I instruction listing).
R_TYPE = {  # mnemonic: (funct3, funct7)
    "add": (0b000, 0b0000000), "sub": (0b000, 0b0100000),
    "sll": (0b001, 0b0000000), "slt": (0b010, 0b0000000),
    "sltu": (0b011, 0b0000000), "xor": (0b100, 0b0000000),
    "srl": (0b101, 0b0000000), "sra": (0b101, 0b0100000),
    "or": (0b110, 0b0000000), "and": (0b111, 0b0000000),
}
I_ALU = {"addi": 0b000, "slti": 0b010, "sltiu": 0b011,
         "xori": 0b100, "ori": 0b110, "andi": 0b111}
SHIFT_IMM = {  # mnemonic: (funct3, imm[11:5])
    "slli": (0b001, 0b0000000), "srli": (0b101, 0b0000000),
    "srai": (0b101, 0b0100000),
}
LOADS = {"lb": 0b000, "lh": 0b001, "lw": 0b010, "lbu": 0b100, "lhu": 0b101}
STORES = {"sb": 0b000, "sh": 0b001, "sw": 0b010}
BRANCHES = {"beq": 0b000, "bne": 0b001, "blt": 0b100,
            "bge": 0b101, "bltu": 0b110, "bgeu": 0b111}

# FENCE predecessor / successor set bits: inst[27:24] = PI PO PR PW,
# inst[23:20] = SI SO SR SW (spec section "Memory Ordering Instructions").
FENCE_BITS = {"i": 8, "o": 4, "r": 2, "w": 1}

ECALL_WORD = 0x00000073   # imm=0, rs1=0, funct3=0, rd=0, SYSTEM
EBREAK_WORD = 0x00100073  # imm=1, rs1=0, funct3=0, rd=0, SYSTEM

#: Every mnemonic the assembler accepts (used by tests / documentation).
BASE_MNEMONICS = (["lui", "auipc", "jal", "jalr"] + list(BRANCHES) + list(LOADS)
                  + list(STORES) + list(I_ALU) + list(SHIFT_IMM) + list(R_TYPE)
                  + ["fence", "ecall", "ebreak"])
PSEUDO_MNEMONICS = ["li", "la", "mv", "nop", "j", "ret", "beqz", "bnez",
                    "not", "neg", "seqz", "snez", "jr"]


class AsmError(Exception):
    """Assembly error with the offending source line attached."""

    def __init__(self, msg: str, line_no: int | None = None, text: str = ""):
        where = f"line {line_no}: " if line_no is not None else ""
        super().__init__(f"{where}{msg}" + (f"   [{text.strip()}]" if text else ""))
        self.line_no = line_no


class _Undefined(Exception):
    """Raised by the expression evaluator for a not-yet-defined symbol."""


# --------------------------------------------------------------------------
# Small numeric helpers
# --------------------------------------------------------------------------
def to_signed(value: int, bits: int) -> int:
    """Interpret the low ``bits`` bits of ``value`` as two's complement."""
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def fits_signed(value: int, bits: int) -> bool:
    """True if ``value`` is representable as a ``bits``-bit signed integer."""
    return -(1 << (bits - 1)) <= value < (1 << (bits - 1))


def hi20(value: int) -> int:
    """Upper 20 bits for a LUI/AUIPC + ADDI pair (``%hi``).

    ADDI sign-extends its 12-bit immediate, so when bit 11 of the value is 1
    the low part is negative and the upper part must be incremented by one
    ("sign carry"): hi = (value + 0x800) >> 12.
    """
    return ((value + 0x800) >> 12) & 0xFFFFF


def lo12(value: int) -> int:
    """Signed low 12 bits for a LUI/AUIPC + ADDI pair (``%lo``)."""
    return to_signed(value & 0xFFF, 12)


# --------------------------------------------------------------------------
# Instruction-format encoders (spec section 2.2, "Base Instruction Formats").
# Each one range-checks its fields so that a bad program fails loudly.
# --------------------------------------------------------------------------
def _chk_reg(r: int) -> int:
    if not 0 <= r < 32:
        raise AsmError(f"register number {r} out of range")
    return r


def enc_r(opcode: int, funct3: int, funct7: int, rd: int, rs1: int, rs2: int) -> int:
    """R-type: funct7[31:25] rs2[24:20] rs1[19:15] funct3[14:12] rd[11:7] opcode."""
    return ((funct7 << 25) | (_chk_reg(rs2) << 20) | (_chk_reg(rs1) << 15)
            | (funct3 << 12) | (_chk_reg(rd) << 7) | opcode)


def enc_i(opcode: int, funct3: int, rd: int, rs1: int, imm: int) -> int:
    """I-type: imm[11:0] -> inst[31:20]; imm is a signed 12-bit value."""
    if not fits_signed(imm, 12):
        raise AsmError(f"I-type immediate {imm} outside -2048..2047")
    return (((imm & 0xFFF) << 20) | (_chk_reg(rs1) << 15) | (funct3 << 12)
            | (_chk_reg(rd) << 7) | opcode)


def enc_s(opcode: int, funct3: int, rs1: int, rs2: int, imm: int) -> int:
    """S-type: imm[11:5] -> inst[31:25], imm[4:0] -> inst[11:7]."""
    if not fits_signed(imm, 12):
        raise AsmError(f"S-type offset {imm} outside -2048..2047")
    imm &= 0xFFF
    return (((imm >> 5) << 25) | (_chk_reg(rs2) << 20) | (_chk_reg(rs1) << 15)
            | (funct3 << 12) | ((imm & 0x1F) << 7) | opcode)


def enc_b(opcode: int, funct3: int, rs1: int, rs2: int, offset: int) -> int:
    """B-type: offset is a multiple of 2 in -4096..4094.

    Bit scattering (spec figure "B-type immediate"):
    inst[31] = imm[12], inst[30:25] = imm[10:5], inst[11:8] = imm[4:1],
    inst[7] = imm[11].
    """
    if offset % 2:
        raise AsmError(f"branch offset {offset} is odd")
    if not fits_signed(offset, 13):
        raise AsmError(f"branch offset {offset} outside -4096..4094")
    o = offset & 0x1FFF
    return ((((o >> 12) & 1) << 31) | (((o >> 5) & 0x3F) << 25)
            | (_chk_reg(rs2) << 20) | (_chk_reg(rs1) << 15) | (funct3 << 12)
            | (((o >> 1) & 0xF) << 8) | (((o >> 11) & 1) << 7) | opcode)


def enc_u(opcode: int, rd: int, imm20: int) -> int:
    """U-type: imm[31:12] -> inst[31:12]; operand is the 20-bit field value."""
    if not 0 <= imm20 <= 0xFFFFF:
        raise AsmError(f"U-type immediate {imm20:#x} outside 0..0xfffff")
    return (imm20 << 12) | (_chk_reg(rd) << 7) | opcode


def enc_j(opcode: int, rd: int, offset: int) -> int:
    """J-type: offset multiple of 2 in -1 MiB..+1 MiB-2.

    Bit scattering (spec figure "J-type immediate"):
    inst[31] = imm[20], inst[30:21] = imm[10:1], inst[20] = imm[11],
    inst[19:12] = imm[19:12].
    """
    if offset % 2:
        raise AsmError(f"jump offset {offset} is odd")
    if not fits_signed(offset, 21):
        raise AsmError(f"jump offset {offset} outside +-1 MiB")
    o = offset & 0x1FFFFF
    return ((((o >> 20) & 1) << 31) | (((o >> 1) & 0x3FF) << 21)
            | (((o >> 11) & 1) << 20) | (((o >> 12) & 0xFF) << 12)
            | (_chk_reg(rd) << 7) | opcode)


# --------------------------------------------------------------------------
# Expression evaluator (recursive descent)
# --------------------------------------------------------------------------
_TOKEN_RE = re.compile(r"""
    \s*(?:
      (?P<num>0[xX][0-9a-fA-F_]+|0[bB][01_]+|[0-9][0-9_]*)
    | (?P<chr>'(?:\\.|[^\\'])')
    | (?P<rel>%hi|%lo)
    | (?P<sym>[A-Za-z_$][\w.$]*|\.[A-Za-z_$][\w.$]*)
    | (?P<dot>\.)
    | (?P<op>[-+*~()])
    )""", re.VERBOSE)

_ESCAPES = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, "'": 39, '"': 34}


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens, pos = [], 0
    text = text.rstrip()
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m or m.end() == pos:
            raise AsmError(f"cannot parse expression near '{text[pos:]}'")
        kind = m.lastgroup
        tokens.append((kind, m.group(kind)))
        pos = m.end()
    return tokens


def _char_value(lit: str) -> int:
    body = lit[1:-1]
    if body.startswith("\\"):
        if body[1] not in _ESCAPES:
            raise AsmError(f"unknown escape {lit}")
        return _ESCAPES[body[1]]
    return ord(body)


def evaluate(text: str, symbols: dict[str, int], dot: int) -> int:
    """Evaluate an assembler expression.

    ``dot`` is the value of ``.`` (address of the current statement).
    Raises :class:`_Undefined` for unknown symbols (pass 1 uses this to size
    forward-referencing ``li``) and :class:`AsmError` for syntax errors.
    """
    tokens = _tokenize(text)
    if not tokens:
        raise AsmError("empty expression")
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else (None, None)

    def take(expected=None):
        nonlocal pos
        tok = peek()
        if tok[0] is None or (expected is not None and tok[1] != expected):
            raise AsmError(f"expected '{expected}' in expression '{text}'")
        pos += 1
        return tok

    def expr():
        val = term()
        while peek()[1] in ("+", "-"):
            op = take()[1]
            rhs = term()
            val = val + rhs if op == "+" else val - rhs
        return val

    def term():
        val = unary()
        while peek()[1] == "*":
            take()
            val *= unary()
        return val

    def unary():
        kind, tok = peek()
        if tok == "-":
            take(); return -unary()
        if tok == "+":
            take(); return unary()
        if tok == "~":
            take(); return ~unary()
        return primary()

    def primary():
        kind, tok = take()
        if kind == "num":
            return int(tok.replace("_", ""), 0)
        if kind == "chr":
            return _char_value(tok)
        if kind == "dot":
            return dot
        if kind == "sym":
            if tok in REGISTERS:
                raise AsmError(f"register '{tok}' used where a number is expected")
            if tok not in symbols:
                raise _Undefined(tok)
            return symbols[tok]
        if kind == "rel":
            take("(")
            v = expr()
            take(")")
            return hi20(v) if tok == "%hi" else lo12(v)
        if tok == "(":
            v = expr()
            take(")")
            return v
        raise AsmError(f"unexpected token '{tok}' in expression '{text}'")

    value = expr()
    if pos != len(tokens):
        raise AsmError(f"trailing characters in expression '{text}'")
    return value


# --------------------------------------------------------------------------
# Source-line parsing helpers
# --------------------------------------------------------------------------
_LABEL_RE = re.compile(r"^\s*([A-Za-z_$.][\w.$]*)\s*:(?!:)")
_MEM_RE = re.compile(r"^(.*)\(\s*([A-Za-z0-9]+)\s*\)\s*$")


def _strip_comment(line: str) -> str:
    """Remove ``#`` / ``//`` comments that are not inside a character literal."""
    out, i, in_chr = [], 0, False
    while i < len(line):
        c = line[i]
        if in_chr:
            out.append(c)
            if c == "\\" and i + 1 < len(line):
                out.append(line[i + 1]); i += 2; continue
            if c == "'":
                in_chr = False
        else:
            if c == "'":
                in_chr = True
            elif c == "#" or line.startswith("//", i):
                break
            out.append(c)
        i += 1
    return "".join(out)


def _split_operands(text: str) -> list[str]:
    """Split on commas that are outside parentheses and character literals."""
    ops, depth, cur, in_chr, i = [], 0, [], False, 0
    while i < len(text):
        c = text[i]
        if in_chr:
            cur.append(c)
            if c == "\\" and i + 1 < len(text):
                cur.append(text[i + 1]); i += 2; continue
            if c == "'":
                in_chr = False
        elif c == "'":
            in_chr = True; cur.append(c)
        elif c == "(":
            depth += 1; cur.append(c)
        elif c == ")":
            depth -= 1; cur.append(c)
        elif c == "," and depth == 0:
            ops.append("".join(cur).strip()); cur = []
        else:
            cur.append(c)
        i += 1
    if cur or ops:
        ops.append("".join(cur).strip())
    return ops


def parse_reg(text: str) -> int:
    """Register name (``x5`` or ``t0``) -> number."""
    name = text.strip().lower()
    if name not in REGISTERS:
        raise AsmError(f"unknown register '{text}'")
    return REGISTERS[name]


def _parse_fence_set(text: str) -> int:
    """FENCE set string (subset of ``iorw`` in that order, or ``0``) -> 4 bits."""
    t = text.strip().lower()
    if t == "0":
        return 0
    if not t or any(c not in FENCE_BITS for c in t) or list(t) != sorted(t, key="iorw".index) \
            or len(set(t)) != len(t):
        raise AsmError(f"bad fence set '{text}' (use a subset of 'iorw' in order)")
    return sum(FENCE_BITS[c] for c in t)


# --------------------------------------------------------------------------
# Program container
# --------------------------------------------------------------------------
@dataclass
class ListingLine:
    """One line of the listing: address, encoded words, source line."""
    addr: int
    words: list[int]
    line_no: int
    text: str
    is_data: bool = False


@dataclass
class Program:
    """Result of :func:`assemble`.

    ``words`` maps a byte address (multiple of 4) to a 32-bit word.  Addresses
    that are not present are zero in the RAM image.
    """
    words: dict[int, int]
    symbols: dict[str, int]
    listing: list[ListingLine]
    data_addrs: set[int] = field(default_factory=set)

    @property
    def end(self) -> int:
        """One past the highest occupied byte address."""
        return max(self.words) + 4 if self.words else 0

    def image(self, n_words: int = RAM_WORDS) -> list[int]:
        """Flat list of ``n_words`` 32-bit words starting at address 0."""
        img = [0] * n_words
        for addr, w in self.words.items():
            if addr // 4 >= n_words or addr < 0:
                raise AsmError(f"word at {addr:#x} does not fit the {n_words*4}-byte image")
            img[addr // 4] = w
        return img

    def write_hex(self, path: str | Path, n_words: int = RAM_WORDS) -> None:
        """Write the RAM image as ``$readmemh`` text (see :func:`write_hex`)."""
        write_hex(path, self.image(n_words))

    def listing_text(self, title: str = "") -> str:
        """Listing: ``address  word  source``; labels/comments kept verbatim."""
        out = []
        if title:
            out.append(f"// {title}")
        out.append("// address   word      line  source")
        for ln in self.listing:
            if not ln.words:
                out.append(f"//                     {ln.line_no:4d}  {ln.text}")
                continue
            for k, w in enumerate(ln.words):
                src = ln.text if k == 0 else "    (cont.)"
                out.append(f"{ln.addr + 4*k:08x}    {w:08x}  {ln.line_no:4d}  {src}")
        if self.symbols:
            out.append("//")
            out.append("// symbols:")
            for name, val in sorted(self.symbols.items(), key=lambda kv: (kv[1], kv[0])):
                out.append(f"//   {val & MASK32:08x}  {name}")
        return "\n".join(out) + "\n"


def write_hex(path: str | Path, image: list[int]) -> None:
    """Write one 32-bit word per line, 8 lowercase hex digits, no ``0x``.

    Format required by the python-model-flow skill and ARCHITECTURE.md 5.6
    (prog.hex: 1024 x 32-bit).  No header line is written so that the file
    has exactly ``len(image)`` lines.
    """
    Path(path).write_text("".join(f"{w & MASK32:08x}\n" for w in image))


# --------------------------------------------------------------------------
# The assembler
# --------------------------------------------------------------------------
@dataclass
class _Stmt:
    line_no: int
    text: str        # original source line (for listing / errors)
    addr: int
    mnem: str
    ops: list[str]
    size: int        # bytes


def _li_words(value: int) -> int:
    """Number of instructions ``li`` needs for a known value (1 or 2)."""
    v = to_signed(value & MASK32, 32)
    if fits_signed(v, 12):
        return 1            # addi rd, x0, v
    if lo12(v) == 0:
        return 1            # lui rd, hi20(v)
    return 2                # lui + addi with sign carry


def assemble(source: str, origin: int = 0) -> Program:
    """Assemble ``source`` (text) starting at byte address ``origin``.

    Returns a :class:`Program`.  Raises :class:`AsmError` on any error.
    """
    lines = source.splitlines()
    symbols: dict[str, int] = {}
    stmts: list[_Stmt] = []
    labels_only: list[tuple[int, int, str]] = []  # (index into stmts, line_no, text)
    pc = origin

    # ---------------- pass 1: addresses, labels, sizes ----------------
    for line_no, raw in enumerate(lines, start=1):
        text = _strip_comment(raw).strip()
        # Leading labels.
        while True:
            m = _LABEL_RE.match(text)
            if not m:
                break
            name = m.group(1)
            if name in symbols:
                raise AsmError(f"duplicate label '{name}'", line_no, raw)
            if name.lower() in REGISTERS or name == ".":
                raise AsmError(f"label '{name}' is reserved", line_no, raw)
            symbols[name] = pc
            text = text[m.end():].strip()
        if not text:
            labels_only.append((len(stmts), line_no, raw))
            continue
        parts = text.split(None, 1)
        mnem = parts[0].lower()
        ops = _split_operands(parts[1]) if len(parts) > 1 else []
        try:
            size = _pass1_size(mnem, ops, symbols, pc)
            if mnem == ".org":
                new_pc = evaluate(ops[0], symbols, pc)
                if new_pc < pc or new_pc % 4:
                    raise AsmError(f".org {new_pc:#x} goes backwards or is not word aligned")
                stmts.append(_Stmt(line_no, raw, pc, mnem, ops, 0))
                pc = new_pc
                continue
            if mnem == ".equ":
                if len(ops) != 2:
                    raise AsmError(".equ needs 'name, value'")
                symbols[ops[0]] = evaluate(ops[1], symbols, pc)
                stmts.append(_Stmt(line_no, raw, pc, mnem, ops, 0))
                continue
        except AsmError as e:
            raise AsmError(str(e), line_no, raw) from None
        except _Undefined as u:
            raise AsmError(f"symbol '{u}' must be defined before this directive", line_no, raw) from None
        stmts.append(_Stmt(line_no, raw, pc, mnem, ops, size))
        pc += size

    # ---------------- pass 2: encode ----------------
    words: dict[int, int] = {}
    data_addrs: set[int] = set()
    listing: list[ListingLine] = []
    label_iter = iter(labels_only)
    pending = next(label_iter, None)
    for idx, st in enumerate(stmts):
        while pending is not None and pending[0] <= idx:
            listing.append(ListingLine(st.addr, [], pending[1], pending[2]))
            pending = next(label_iter, None)
        try:
            enc = _encode(st, symbols)
        except _Undefined as u:
            raise AsmError(f"undefined symbol '{u}'", st.line_no, st.text) from None
        except AsmError as e:
            raise AsmError(str(e), st.line_no, st.text) from None
        if len(enc) * 4 != st.size and st.mnem not in (".org", ".align", ".space", ".zero"):
            raise AsmError("internal error: size changed between passes", st.line_no, st.text)
        for k, w in enumerate(enc):
            a = st.addr + 4 * k
            if a in words:
                raise AsmError(f"address {a:#x} written twice", st.line_no, st.text)
            words[a] = w & MASK32
            if st.mnem == ".word":
                data_addrs.add(a)
        listing.append(ListingLine(st.addr, enc, st.line_no, st.text, st.mnem == ".word"))
    while pending is not None:
        listing.append(ListingLine(pc, [], pending[1], pending[2]))
        pending = next(label_iter, None)
    return Program(words, symbols, listing, data_addrs)


def assemble_line(text: str, pc: int = 0) -> list[int]:
    """Assemble a single statement located at ``pc``; return its words."""
    prog = assemble(text, origin=pc)
    return [prog.words[a] for a in sorted(prog.words)]


def _pass1_size(mnem: str, ops: list[str], symbols: dict[str, int], pc: int) -> int:
    """Size in bytes of a statement, decided in pass 1."""
    if mnem == ".word":
        if not ops:
            raise AsmError(".word needs at least one value")
        return 4 * len(ops)
    if mnem in (".org", ".equ"):
        return 0
    if mnem == ".align":
        n = evaluate(ops[0], symbols, pc)
        a = 1 << n
        return (-pc) % a if a >= 4 else 0
    if mnem in (".space", ".zero"):
        n = evaluate(ops[0], symbols, pc)
        if n < 0 or n % 4:
            raise AsmError(f"{mnem} size must be a non-negative multiple of 4")
        return n
    if mnem.startswith("."):
        raise AsmError(f"unknown directive '{mnem}'")
    if mnem == "li":
        if len(ops) != 2:
            raise AsmError("li needs 'rd, value'")
        try:
            return 4 * _li_words(evaluate(ops[1], symbols, pc))
        except _Undefined:
            return 8   # forward reference: always LUI + ADDI
    if mnem == "la":
        return 8       # AUIPC + ADDI
    if mnem in BASE_MNEMONICS or mnem in PSEUDO_MNEMONICS:
        return 4
    raise AsmError(f"unknown mnemonic '{mnem}'")


def _nops(ops: list[str], n: int, mnem: str) -> None:
    if len(ops) != n:
        raise AsmError(f"'{mnem}' expects {n} operand(s), got {len(ops)}")


def _mem_operand(text: str, symbols: dict[str, int], pc: int) -> tuple[int, int]:
    """Parse ``offset(reg)`` (offset may be empty) -> (offset, reg)."""
    m = _MEM_RE.match(text.strip())
    if not m or m.group(2).lower() not in REGISTERS:
        raise AsmError(f"expected 'offset(reg)', got '{text}'")
    off_txt = m.group(1).strip()
    off = evaluate(off_txt, symbols, pc) if off_txt else 0
    return off, parse_reg(m.group(2))


def _encode(st: _Stmt, symbols: dict[str, int]) -> list[int]:
    """Encode one statement (pass 2).  Returns a list of 32-bit words."""
    m, ops, pc = st.mnem, st.ops, st.addr
    ev = lambda t: evaluate(t, symbols, pc)  # noqa: E731

    # ---- directives ----
    if m == ".word":
        out = []
        for o in ops:
            v = ev(o)
            if not -(1 << 31) <= v <= MASK32:
                raise AsmError(f".word value {v} does not fit 32 bits")
            out.append(v & MASK32)
        return out
    if m in (".org", ".equ"):
        return []
    if m in (".align", ".space", ".zero"):
        return [0] * (st.size // 4)

    # ---- pseudo-instructions (expanded to base instructions) ----
    if m == "nop":
        _nops(ops, 0, m); return [enc_i(OP_IMM, 0, 0, 0, 0)]          # addi x0,x0,0
    if m == "mv":
        _nops(ops, 2, m); return [enc_i(OP_IMM, 0, parse_reg(ops[0]), parse_reg(ops[1]), 0)]
    if m == "not":
        _nops(ops, 2, m); return [enc_i(OP_IMM, 0b100, parse_reg(ops[0]), parse_reg(ops[1]), -1)]
    if m == "neg":
        _nops(ops, 2, m); return [enc_r(OP_OP, 0, 0b0100000, parse_reg(ops[0]), 0, parse_reg(ops[1]))]
    if m == "seqz":
        _nops(ops, 2, m); return [enc_i(OP_IMM, 0b011, parse_reg(ops[0]), parse_reg(ops[1]), 1)]
    if m == "snez":
        _nops(ops, 2, m); return [enc_r(OP_OP, 0b011, 0, parse_reg(ops[0]), 0, parse_reg(ops[1]))]
    if m == "j":
        _nops(ops, 1, m); return [enc_j(OP_JAL, 0, ev(ops[0]) - pc)]
    if m == "jr":
        _nops(ops, 1, m); return [enc_i(OP_JALR, 0, 0, parse_reg(ops[0]), 0)]
    if m == "ret":
        _nops(ops, 0, m); return [enc_i(OP_JALR, 0, 0, 1, 0)]          # jalr x0, 0(ra)
    if m in ("beqz", "bnez"):
        _nops(ops, 2, m)
        f3 = BRANCHES["beq" if m == "beqz" else "bne"]
        return [enc_b(OP_BRANCH, f3, parse_reg(ops[0]), 0, ev(ops[1]) - pc)]
    if m == "li":
        rd = parse_reg(ops[0])
        v = ev(ops[1])
        if not -(1 << 31) <= v <= MASK32:
            raise AsmError(f"li value {v} does not fit 32 bits")
        v = to_signed(v & MASK32, 32)
        if st.size == 4:
            if fits_signed(v, 12):
                return [enc_i(OP_IMM, 0, rd, 0, v)]
            return [enc_u(OP_LUI, rd, hi20(v))]
        # LUI + ADDI: lui loads hi20 (sign carry included), addi adds lo12.
        return [enc_u(OP_LUI, rd, hi20(v)), enc_i(OP_IMM, 0, rd, rd, lo12(v))]
    if m == "la":
        _nops(ops, 2, m)
        rd = parse_reg(ops[0])
        delta = to_signed((ev(ops[1]) - pc) & MASK32, 32)
        # PC-relative: auipc adds hi20<<12 to its own address, addi adds lo12.
        return [enc_u(OP_AUIPC, rd, hi20(delta)), enc_i(OP_IMM, 0, rd, rd, lo12(delta))]

    # ---- base instructions ----
    if m in R_TYPE:
        _nops(ops, 3, m)
        f3, f7 = R_TYPE[m]
        return [enc_r(OP_OP, f3, f7, parse_reg(ops[0]), parse_reg(ops[1]), parse_reg(ops[2]))]
    if m in I_ALU:
        _nops(ops, 3, m)
        return [enc_i(OP_IMM, I_ALU[m], parse_reg(ops[0]), parse_reg(ops[1]), ev(ops[2]))]
    if m in SHIFT_IMM:
        _nops(ops, 3, m)
        f3, f7 = SHIFT_IMM[m]
        sh = ev(ops[2])
        if not 0 <= sh <= 31:   # RV32I: shamt[5] must be 0 (spec 2.4)
            raise AsmError(f"shift amount {sh} outside 0..31")
        return [enc_r(OP_IMM, f3, f7, parse_reg(ops[0]), parse_reg(ops[1]), sh)]
    if m in LOADS:
        _nops(ops, 2, m)
        off, rs1 = _mem_operand(ops[1], symbols, pc)
        return [enc_i(OP_LOAD, LOADS[m], parse_reg(ops[0]), rs1, off)]
    if m in STORES:
        _nops(ops, 2, m)
        off, rs1 = _mem_operand(ops[1], symbols, pc)
        return [enc_s(OP_STORE, STORES[m], rs1, parse_reg(ops[0]), off)]
    if m in BRANCHES:
        _nops(ops, 3, m)
        return [enc_b(OP_BRANCH, BRANCHES[m], parse_reg(ops[0]), parse_reg(ops[1]), ev(ops[2]) - pc)]
    if m == "jal":
        if len(ops) == 1:            # pseudo: jal target  (rd = ra)
            return [enc_j(OP_JAL, 1, ev(ops[0]) - pc)]
        _nops(ops, 2, m)
        return [enc_j(OP_JAL, parse_reg(ops[0]), ev(ops[1]) - pc)]
    if m == "jalr":
        if len(ops) == 1:            # pseudo: jalr rs  (rd = ra, offset 0)
            return [enc_i(OP_JALR, 0, 1, parse_reg(ops[0]), 0)]
        if len(ops) == 2:            # jalr rd, offset(rs1)
            off, rs1 = _mem_operand(ops[1], symbols, pc)
            return [enc_i(OP_JALR, 0, parse_reg(ops[0]), rs1, off)]
        _nops(ops, 3, m)             # jalr rd, rs1, offset
        return [enc_i(OP_JALR, 0, parse_reg(ops[0]), parse_reg(ops[1]), ev(ops[2]))]
    if m in ("lui", "auipc"):
        _nops(ops, 2, m)
        return [enc_u(OP_LUI if m == "lui" else OP_AUIPC, parse_reg(ops[0]), ev(ops[1]))]
    if m == "fence":
        if not ops:                  # plain 'fence' = fence iorw, iorw
            pred = succ = 0xF
        else:
            _nops(ops, 2, m)
            pred, succ = _parse_fence_set(ops[0]), _parse_fence_set(ops[1])
        # fm = 0000 (normal fence), rs1 = rd = 0, funct3 = 000.
        return [(pred << 24) | (succ << 20) | OP_MISC_MEM]
    if m == "ecall":
        _nops(ops, 0, m); return [ECALL_WORD]
    if m == "ebreak":
        _nops(ops, 0, m); return [EBREAK_WORD]
    raise AsmError(f"unknown mnemonic '{m}'")
