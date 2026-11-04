"""Unit tests of the RV32I reference assembler, disassembler and ISS (task SW-01b).

Three groups of checks:

1. Assembler encodings against KNOWN words derived by hand from the RISC-V
   Unprivileged ISA (RV32I v2.1) instruction formats.  Each case carries its
   derivation: the field values and how they are OR-ed together.
2. ISS semantics for every edge case listed in SW-01b (sign extension, SRA vs
   SRL, SLT/SLTU with 0x80000000, JALR bit 0, branches, x0, LUI/AUIPC, byte
   lanes, load-after-store, shift amounts, overflow wrap, traps, MMIO, TPU stub).
3. Round trip: disassemble -> re-assemble gives the same word, for a seeded
   random sample of 32-bit words and for every generated program; plus the
   consistency of the generated files in ``sim/data/cpu_tests/``.

Run with: ``.venv/bin/python -m pytest -q code/python/tests/test_rv32.py``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rv32 import gen_cpu_tests as gen  # noqa: E402
from rv32 import gen_soc_demo as demo  # noqa: E402
from rv32.asm import AsmError, assemble, assemble_line  # noqa: E402
from rv32.disasm import disassemble, roundtrip_mismatches  # noqa: E402
from rv32.iss import Iss, TpuStub, TrapCause, is_legal  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
CPU_TESTS = REPO / "sim" / "data" / "cpu_tests"
ROUNDTRIP_SEED = 20261104     # seed of the random-word round-trip sample
ROUNDTRIP_N = 20000

# ---------------------------------------------------------------------------
# 1. Known encodings (hand derived)
# ---------------------------------------------------------------------------
# Notation: imm<<20 etc. are the I/S/B/U/J field placements of spec 2.2/2.3.
KNOWN = [
    # (source, pc, expected words, derivation)
    ("addi x1, x0, 1", 0, [0x00100093],
     "I: imm=1<<20=0x00100000 | rs1=0 | f3=000 | rd=1<<7=0x80 | OP-IMM 0x13"),
    ("nop", 0, [0x00000013], "addi x0,x0,0: only the opcode 0x13 remains"),
    ("add x3, x1, x2", 0, [0x002081B3],
     "R: f7=0 | rs2=2<<20=0x200000 | rs1=1<<15=0x8000 | f3=0 | rd=3<<7=0x180 | OP 0x33"),
    ("sub x3, x1, x2", 0, [0x402081B3], "as add plus f7=0100000<<25=0x40000000"),
    ("sra x3, x1, x2", 0, [0x4020D1B3], "f7=0x40000000 | 0x200000 | 0x8000 | f3=101<<12=0x5000 | 0x180 | 0x33"),
    ("lui x5, 0x12345", 0, [0x123452B7], "U: 0x12345<<12=0x12345000 | rd=5<<7=0x280 | LUI 0x37"),
    ("auipc x5, 1", 0, [0x00001297], "U: 1<<12=0x1000 | 0x280 | AUIPC 0x17"),
    ("j .", 0, [0x0000006F], "jal x0, 0: all immediate bits 0 | JAL 0x6F"),
    ("jal x1, .+8", 0, [0x008000EF],
     "J: imm=8 -> imm[10:1]=4 at inst[30:21]: 4<<21=0x00800000 | rd=1<<7=0x80 | 0x6F"),
    ("jal x0, .-4", 0x100, [0xFFDFF06F],
     "J: imm=-4=0x1FFFFC: imm[20]=1->0x80000000, imm[10:1]=0x3FE<<21=0x7FC00000, "
     "imm[11]=1->1<<20=0x100000, imm[19:12]=0xFF<<12=0xFF000 | 0x6F"),
    ("ret", 0, [0x00008067], "jalr x0,0(x1): rs1=1<<15=0x8000 | JALR 0x67"),
    ("beq x1, x2, .+8", 0, [0x00208463],
     "B: imm=8 -> imm[4:1]=0100 at inst[11:8]=0x400 | rs2=0x200000 | rs1=0x8000 | f3=0 | 0x63"),
    ("bne x0, x0, .-4", 0x10, [0xFE001EE3],
     "B: imm=-4=0x1FFC: imm[12]->0x80000000, imm[10:5]=0x3F<<25=0x7E000000, "
     "imm[4:1]=0xE<<8=0xE00, imm[11]->1<<7=0x80 | f3=001<<12=0x1000 | 0x63"),
    ("lw x5, 8(x2)", 0, [0x00812283],
     "I: imm=8<<20=0x800000 | rs1=2<<15=0x10000 | f3=010<<12=0x2000 | rd=0x280 | LOAD 0x03"),
    ("lb x5, -1(x2)", 0, [0xFFF10283], "I: imm=0xFFF<<20=0xFFF00000 | 0x10000 | f3=0 | 0x280 | 0x03"),
    ("sw x5, 12(x2)", 0, [0x00512623],
     "S: imm[4:0]=12<<7=0x600 | rs2=5<<20=0x500000 | rs1=0x10000 | f3=010<<12=0x2000 | STORE 0x23"),
    ("sb x5, -1(x2)", 0, [0xFE510FA3],
     "S: imm=0xFFF: imm[11:5]=0x7F<<25=0xFE000000, imm[4:0]=0x1F<<7=0xF80 | 0x500000 | 0x10000 | 0x23"),
    ("srai x1, x2, 31", 0, [0x41F15093],
     "I-shift: imm[11:5]=0100000<<25=0x40000000 | shamt=31<<20=0x1F00000 | rs1=0x10000 | "
     "f3=101<<12=0x5000 | rd=0x80 | 0x13"),
    ("slli x1, x1, 1", 0, [0x00109093], "1<<20 | rs1=1<<15 | f3=001<<12 | rd=1<<7 | 0x13"),
    ("sltiu x1, x2, -1", 0, [0xFFF13093], "imm 0xFFF<<20 | rs1=0x10000 | f3=011<<12=0x3000 | 0x80 | 0x13"),
    ("ecall", 0, [0x00000073], "SYSTEM 0x73 with all other fields 0"),
    ("ebreak", 0, [0x00100073], "SYSTEM with imm=1: 1<<20 | 0x73"),
    ("fence", 0, [0x0FF0000F], "pred=iorw=0xF<<24, succ=0xF<<20 | MISC-MEM 0x0F"),
    ("li x1, 0x12345FFF", 0, [0x123460B7, 0xFFF08093],
     "low 12 bits 0xFFF are -1 for ADDI, so LUI gets 0x12345+1: "
     "lui x1,0x12346=0x12346000|0x80|0x37 ; addi x1,x1,-1=0xFFF00000|0x8000|0x80|0x13"),
    ("li x2, -2048", 0, [0x80000113], "fits ADDI: imm=0x800<<20=0x80000000 | rd=2<<7=0x100 | 0x13"),
]


@pytest.mark.parametrize("src,pc,words,why", KNOWN, ids=[k[0] for k in KNOWN])
def test_known_encoding(src, pc, words, why):
    """Assembler output equals the hand-derived spec encoding."""
    assert assemble_line(src, pc) == words, why


def test_known_encoding_count():
    """SW-01b requires at least 15 hand-computed encodings."""
    assert len(KNOWN) >= 15


@pytest.mark.parametrize("bad", [
    "addi x1, x0, 2048",        # I-immediate range -2048..2047
    "addi x1, x0, -2049",
    "slli x1, x1, 32",          # RV32I shamt 0..31
    "beq x0, x0, .+3",          # odd offset
    "beq x0, x0, .+4096",       # B range -4096..4094
    "jal x0, .+1048576",        # J range
    "lui x1, 0x100000",         # 20-bit field
    "lw x1, 0(x32)",            # bad register
    "frob x1, x2",              # unknown mnemonic
    "j nowhere",                # undefined label
    "add x1, x2",               # operand count
])
def test_assembler_rejects(bad):
    """Out-of-range / malformed statements raise AsmError (no silent truncation)."""
    with pytest.raises(AsmError):
        assemble(bad)


def test_labels_two_pass_and_abi_names():
    """Forward and backward labels resolve; ABI names map to the right numbers."""
    p = assemble("start: beq zero, ra, end\n  addi t0, sp, 1\nend: jal s11, start\n")
    assert p.words[0] == assemble_line("beq x0, x1, .+8")[0]
    assert p.words[4] == assemble_line("addi x5, x2, 1")[0]
    assert p.words[8] == assemble_line("jal x27, .-8", 8)[0]


def test_li_forward_reference_is_two_words():
    """li of a not-yet-defined symbol is sized as LUI+ADDI in pass 1."""
    p = assemble("li x1, lab\nlab: nop\n")
    assert sorted(p.words) == [0, 4, 8]
    assert Iss(p.image()).run(2).regs[1] == 8


def test_hex_file_format(tmp_path):
    """Hex image: exactly 1024 lines of 8 lowercase hex digits, zero padded."""
    p = assemble("addi x1, x0, 1\n.org 0x10\n.word 0xDEADBEEF\n")
    f = tmp_path / "t.hex"
    p.write_hex(f)
    lines = f.read_text().splitlines()
    assert len(lines) == 1024
    assert all(len(s) == 8 and s == s.lower() for s in lines)
    assert lines[0] == "00100093" and lines[4] == "deadbeef" and lines[1] == "00000000"


# ---------------------------------------------------------------------------
# 2. ISS semantics
# ---------------------------------------------------------------------------
def run(src: str, steps: int = 10_000, tpu: TpuStub | None = None):
    """Assemble ``src`` and run it on a fresh ISS."""
    return Iss(assemble(src).image(), tpu=tpu).run(steps)


@pytest.mark.parametrize("value", [0, 1, -1, 2047, -2048, 2048, -2049, 0x800, 0x7FF,
                                   0x12345FFF, 0x80000000, 0x7FFFFFFF, 0xFFFFF800,
                                   0x7FFFF800, 0xFFFFFFFF, 0x00001000, 0xABCDE800])
def test_li_values(value):
    """li loads every 32-bit value exactly (LUI/ADDI sign-carry handling)."""
    assert run(f"li x7, {value}").regs[7] == value & 0xFFFFFFFF


def test_li_random_values():
    """li on 2000 seeded random values (seed recorded in the test)."""
    rng = np.random.default_rng(7)
    vals = [int(v) for v in rng.integers(0, 1 << 32, size=2000)]
    for v in vals:
        assert run(f"li x9, {v:#x}", steps=3).regs[9] == v


def test_sign_extension_of_loads():
    """LB/LH sign-extend, LBU/LHU zero-extend, from every lane."""
    r = run("""
        lui x1, 0x1
        addi x1, x1, -2048
        lb  x2, 0(x1)
        lb  x3, 1(x1)
        lb  x4, 2(x1)
        lb  x5, 3(x1)
        lbu x6, 3(x1)
        lh  x7, 0(x1)
        lh  x8, 2(x1)
        lhu x9, 2(x1)
        lw  x10, 0(x1)
        ebreak
        .org 0x800
        .word 0x80FF7F01
    """)
    assert r.regs[2:11] == [0x01, 0x7F, 0xFFFFFFFF, 0xFFFFFF80, 0x80,
                            0x7F01, 0xFFFF80FF, 0x80FF, 0x80FF7F01]


def test_sra_vs_srl_and_shift_amounts():
    """SRA fills with the sign, SRL with 0; amounts 0 and 31; rs2[4:0] only."""
    r = run("""
        li x1, 0x80000000
        srai x2, x1, 31
        srli x3, x1, 31
        srai x4, x1, 0
        slli x5, x1, 31
        li x6, 0xFFFFFFE1      # low 5 bits = 1
        sra x7, x1, x6
        srl x8, x1, x6
        sll x9, x1, x6         # bit 31 shifted out
        ebreak
    """)
    assert r.regs[2:6] == [0xFFFFFFFF, 1, 0x80000000, 0]
    assert r.regs[7:10] == [0xC0000000, 0x40000000, 0]


def test_slt_sltu_with_int_min():
    """0x80000000 is the smallest signed and a large unsigned value."""
    r = run("""
        li x1, 0x80000000
        slt  x2, x1, x0        # 1
        sltu x3, x1, x0        # 0
        slti x4, x1, -1        # 1
        sltiu x5, x1, -1       # 1 (0x80000000 <u 0xFFFFFFFF)
        sltiu x6, x0, -2048    # 1 (0 <u 0xFFFFF800)
        ebreak
    """)
    assert r.regs[2:7] == [1, 0, 1, 1, 1]


def test_add_sub_wrap():
    """ADD/SUB/ADDI wrap modulo 2^32 and never trap."""
    r = run("""
        li x1, 0x7FFFFFFF
        addi x2, x1, 1
        sub x3, x0, x2
        li x4, 0xFFFFFFFF
        add x5, x4, x4
        ebreak
    """)
    assert r.trap_cause == TrapCause.EBREAK
    assert r.regs[2] == 0x80000000 and r.regs[3] == 0x80000000 and r.regs[5] == 0xFFFFFFFE


def test_jalr_clears_bit0_and_rd_equals_rs1():
    """JALR target = (rs1 + imm) & ~1, computed before rd (== rs1) is written."""
    p = assemble("""
        la   x5, tgt
        jalr x5, 1(x5)
        addi x6, x0, 1         # skipped
    tgt:
        ebreak
    """)
    r = Iss(p.image()).run(10)
    assert r.trap_cause == TrapCause.EBREAK and r.pc == p.symbols["tgt"]
    assert r.regs[5] == p.symbols["tgt"] - 4 and r.regs[6] == 0   # link = jalr pc + 4


def test_branches_forward_backward():
    """Taken/not-taken branches forward, and a backward loop."""
    r = run("""
        li x1, 0x80000000
        addi x2, x0, 1
        blt  x1, x2, f1        # taken (signed)
        addi x10, x0, 1
    f1: bltu x1, x2, f2        # not taken (unsigned)
        addi x11, x0, 1
    f2: addi x3, x0, 4
    lp: addi x12, x12, 1
        addi x3, x3, -1
        bne  x3, x0, lp        # backward taken 3x
        ebreak
    """)
    assert (r.regs[10], r.regs[11], r.regs[12]) == (0, 1, 4)


def test_x0_writes_discarded():
    """Every write to x0 is dropped."""
    r = run("""
        addi x0, x0, 1
        lui x0, 1
        jal x0, n
    n:  lw x0, 0(x0)
        add x1, x0, x0
        ebreak
    """)
    assert r.regs[0] == 0 and r.regs[1] == 0


def test_lui_auipc():
    """LUI places imm<<12; AUIPC adds it to its own PC (wraps)."""
    r = run("lui x1, 0xFFFFF\nauipc x2, 0\nauipc x3, 0xFFFFF\nebreak\n")
    assert r.regs[1:4] == [0xFFFFF000, 4, (8 - 0x1000) & 0xFFFFFFFF]


def test_store_lanes_and_load_after_store():
    """SB/SH write only their lanes; an immediately following load sees the data."""
    r = run("""
        lui x1, 0x1
        addi x1, x1, -2048
        li x2, 0x11223344
        sw x2, 0(x1)
        li x3, 0xAABBCCDD
        sb x3, 1(x1)
        lw x4, 0(x1)           # 0x1122DD44
        sh x3, 2(x1)
        lw x5, 0(x1)           # 0xCCDDDD44
        sb x3, 3(x1)
        lbu x6, 3(x1)          # 0xDD
        ebreak
    """)
    assert (r.regs[4], r.regs[5], r.regs[6]) == (0x1122DD44, 0xCCDDDD44, 0xDD)


@pytest.mark.parametrize("code,cause", [
    ("ecall", TrapCause.ECALL),
    ("ebreak", TrapCause.EBREAK),
    (".word 0x00000000", TrapCause.ILLEGAL),
    (".word 0xFFFFFFFF", TrapCause.ILLEGAL),
    (".word 0x30001073", TrapCause.ILLEGAL),        # csrrw: no CSRs
    (".word 0x0000100F", TrapCause.ILLEGAL),        # fence.i: not RV32I
    (".word 0x023100B3", TrapCause.ILLEGAL),        # mul
    (".word 0x02009093", TrapCause.ILLEGAL),        # slli with imm[11:5]=1 (shamt[5])
    ("lw x5, 2(x6)", TrapCause.MISALIGNED_LOAD),
    ("lhu x5, 1(x6)", TrapCause.MISALIGNED_LOAD),
    ("sh x5, 1(x6)", TrapCause.MISALIGNED_STORE),
    ("sw x5, 3(x6)", TrapCause.MISALIGNED_STORE),
    ("jalr x5, 2(x6)", TrapCause.MISALIGNED_FETCH),
    ("jal x5, .+6", TrapCause.MISALIGNED_FETCH),
    ("beq x0, x0, .+6", TrapCause.MISALIGNED_FETCH),
])
def test_traps_halt_precisely(code, cause):
    """Trap: halt, cause per INTERFACES.json, PC = trapping insn, no side effects."""
    p = assemble(f"""
        li x5, 0x5A5A5A5A
        li x6, 0x800
    t:  {code}
        addi x7, x0, 1
    """)
    r = Iss(p.image()).run(100)
    assert r.stop_reason == "trap" and r.trap_cause == cause
    assert r.pc == p.symbols["t"]
    assert r.regs[5] == 0x5A5A5A5A and r.regs[7] == 0
    assert r.word(0x800) == 0                          # no store performed
    assert r.instret == len([a for a in p.words if a < p.symbols["t"]])


def test_not_taken_misaligned_branch_does_not_trap():
    """Only a TAKEN branch to a misaligned target traps (spec 2.5)."""
    r = run("bne x0, x0, .+6\nebreak\n")
    assert r.trap_cause == TrapCause.EBREAK


def test_fence_is_nop_and_legal_variants():
    """FENCE with any fm/pred/succ/rs1/rd is a NOP (reserved fields ignored)."""
    r = run("fence\n.word 0x8330000F\naddi x1, x0, 3\nebreak\n")   # 0x8330000F = fence.tso
    assert r.trap_cause == TrapCause.EBREAK and r.regs[1] == 3 and r.instret == 3


def test_mmio_tohost_uart_led_cycle_unmapped():
    """Peripheral map, TOHOST stop, CYCLE = 0, unmapped bus_err, RAM aliasing."""
    p = assemble("""
        lui x1, 0x10000
        addi x2, x0, 0x7F
        sw x2, 0(x1)           # LED (6 bits)
        lw x3, 0(x1)
        addi x4, x0, 'A'
        sw x4, 4(x1)           # UART_TX
        lw x5, 8(x1)           # UART_STATUS = 0 (never busy)
        lw x6, 12(x1)          # CYCLE = 0 (not modelled)
        lui x7, 0x40000
        lw x8, 0(x7)           # unmapped -> 0, bus_err
        lui x9, 0x1            # 0x1000 aliases RAM address 0
        lw x10, 0(x9)
        addi x11, x0, 1
    st: sw x11, 0x10(x1)       # TOHOST
        addi x12, x0, 1        # not executed
    """)
    r = Iss(p.image()).run(100)
    assert r.stop_reason == "tohost" and r.tohost == 1 and r.pc == p.symbols["st"]
    assert r.regs[3] == 0x3F and r.led_writes == [0x3F] and r.uart == b"A"
    assert r.regs[5] == 0 and r.regs[6] == 0 and r.regs[8] == 0 and r.bus_err
    assert r.regs[10] == p.words[0] and r.regs[12] == 0


def test_tpu_stub():
    """Stub TPU: CONFIG clamp, START, BUSY polls then DONE, RESULT, CYCLES, PARAMS."""
    tpu = TpuStub(result=0x17, cycles=1234, busy_polls=2)
    r = run("""
        lui x1, 0x20000
        addi x2, x0, 0x7F      # LOG2_L=15 -> clamped to 10, ACT_SHIFT=7
        sw x2, 8(x1)
        lw x3, 8(x1)
        addi x2, x0, 1
        sw x2, 0(x1)
        lw x4, 4(x1)           # BUSY
        lw x5, 4(x1)           # BUSY
        lw x6, 4(x1)           # DONE
        lw x7, 12(x1)
        lw x8, 16(x1)
        lw x9, 20(x1)
        ebreak
    """, tpu=tpu)
    assert r.regs[3] == 0x7A and tpu.starts == 1
    assert r.regs[4:10] == [1, 1, 2, 7, 1234, 0x02020810]  # rev B PARAMS (mode 2, version 0x02)
    assert TpuStub(rng_mode=1, version=0x01).read(0x014) == 0x01010810  # rev A form still expressible


def test_soc_demo_on_iss():
    """The demo program behaves as specified for all RESULT values."""
    for s in (0, 5):
        prog = assemble(demo.demo_source(s))
        assert demo.check_on_iss(prog, s) == []
        assert roundtrip_mismatches(prog.words) == []


# ---------------------------------------------------------------------------
# 3. Round trip and generated programs
# ---------------------------------------------------------------------------
def test_roundtrip_random_words():
    """asm(disasm(w)) == w for ~48500 seeded random / opcode-biased words, and legality."""
    rng = np.random.default_rng(ROUNDTRIP_SEED)
    words = [int(w) for w in rng.integers(0, 1 << 32, size=ROUNDTRIP_N)]
    # Bias half of the sample toward valid opcodes (low 7 bits from the map).
    opcodes = [0x37, 0x17, 0x6F, 0x67, 0x63, 0x03, 0x23, 0x13, 0x33, 0x0F, 0x73]
    words += [(w & ~0x7F) | opcodes[i % len(opcodes)] for i, w in enumerate(words)]
    # Third batch: OP / OP-IMM with funct7 forced to 0000000 or 0100000 (so the
    # R-type and shift-immediate decoders are exercised), canonical FENCEs and
    # the exact ECALL / EBREAK words.
    words += [(w & 0x01FFFF80) | ((0x20 if i % 2 else 0) << 25) | (0x33 if i % 4 < 2 else 0x13)
              for i, w in enumerate(words[:8000])]
    words += [(w & 0x0FF00000) | 0x0F for w in words[:500]] + [0x00000073, 0x00100073]
    mism = roundtrip_mismatches({4 * i: w for i, w in enumerate(words)})
    assert mism == [], mism[:5]
    # Cross-check of two independent decoders: disasm prints .word iff the ISS
    # says illegal, except FENCE encodings with non-zero reserved fields
    # (ISS: NOP, disasm: .word so that the text re-assembles exactly).
    for w in words:
        raw = disassemble(w).startswith(".word")
        fence_variant = (w & 0x707F) == 0x000F
        if fence_variant:
            assert is_legal(w)
        else:
            assert raw == (not is_legal(w)), hex(w)


def test_every_generated_spec_roundtrips_and_checks():
    """Every directed/random/trap program assembles, round-trips and passes its checks."""
    for spec in gen.all_specs(n_random=3, base_seed=1000, n_body=200):
        prog, res, meta = gen.build(spec)
        assert meta["roundtrip_mismatches"] == 0


def test_generator_detects_wrong_expectation():
    """Mutation check: a wrong hand-derived value must make build() fail."""
    spec = gen.directed_tests()[0]
    spec.expect = dict(spec.expect)
    spec.expect[1] ^= 1
    with pytest.raises(gen.CheckError):
        gen.build(spec)


def test_random_programs_are_deterministic():
    """Same seed -> identical program text."""
    assert gen.random_test(1234).source == gen.random_test(1234).source
    assert gen.random_test(1234).source != gen.random_test(1235).source


@pytest.mark.skipif(not (CPU_TESTS / "index.txt").exists(), reason="run gen_cpu_tests.py first")
def test_generated_files_complete_and_consistent():
    """index.txt lists every test; each has hex/sig/meta/lst; sig matches the ISS."""
    names = (CPU_TESTS / "index.txt").read_text().split()
    assert len(names) == len(set(names)) >= 11 + 20 + 7
    assert sum(n.startswith("rand_") for n in names) == 20
    for n in names:
        hex_lines = (CPU_TESTS / f"{n}.hex").read_text().split()
        sig_lines = (CPU_TESTS / f"{n}.sig").read_text().split()
        meta = json.loads((CPU_TESTS / f"{n}.meta.json").read_text())
        assert (CPU_TESTS / f"{n}.lst").exists()
        assert len(hex_lines) == 1024 and len(sig_lines) == 32
        image = [int(h, 16) for h in hex_lines]
        r = Iss(image).run(gen.MAX_STEPS)
        assert [f"{w:08x}" for w in r.signature()] == sig_lines, n
        assert r.trap_cause == meta["expected_trap_cause"] and r.instret == meta["instret"]
        if meta["expected_halted"]:
            assert r.pc == int(meta["expected_halt_pc"], 16)
        else:
            assert r.tohost == 1 and r.pc == int(meta["tohost_pc"], 16)
        if n.startswith("rand_"):
            assert isinstance(meta["seed"], int)
    # Trap coverage: every non-zero cause appears at least once.
    causes = {json.loads((CPU_TESTS / f"{n}.meta.json").read_text())["expected_trap_cause"] for n in names}
    assert causes == {0, 1, 2, 3, 4, 5, 6}


@pytest.mark.skipif(not (REPO / "sim/data/soc_demo_prog.hex").exists(), reason="run gen_soc_demo.py first")
def test_soc_demo_file():
    """The committed demo hex is the image of the generated source (ACT_SHIFT from meta)."""
    meta = json.loads((REPO / "sim/data/soc_demo_prog.meta.json").read_text())
    lines = (REPO / "sim/data/soc_demo_prog.hex").read_text().split()
    assert len(lines) == 1024
    prog = assemble(demo.demo_source(meta["act_shift"]))
    assert [int(h, 16) for h in lines] == prog.image()
