#!/usr/bin/env python3
"""REV-01a: reviewer-written RV32I programs with HAND-DERIVED expectations.

The encoder below is written by the reviewer directly from the RV32I base
encoding tables (RISC-V Unprivileged ISA, ch. 2 / ch. 24 "RV32I Base
Instruction Set" listing); it does NOT use code/python/rv32/asm.py.
Expected register values are typed in by hand (derivation in comments and in
REVIEW_A_cpu_soc.md).  The script writes, per program, <name>.hex (1024 words),
<name>.sig (32 words at 0x0F00) and <name>.tbmeta.hex (layout of
scripts/cpu_meta_to_tb.py) for tests/cpu/tb_rv32i_core.v, and ALSO runs the
project ISS on the same image and reports any ISS-vs-hand mismatch.
"""
import sys
from pathlib import Path
OUT = Path(sys.argv[1]); OUT.mkdir(parents=True, exist_ok=True)

# ---------------- encoder (from the spec field layouts) -----------------------
def R(f7, rs2, rs1, f3, rd, op=0x33): return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op
def I(imm, rs1, f3, rd, op=0x13):     return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op
def S(imm, rs2, rs1, f3):             return (((imm >> 5) & 0x7F) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | ((imm & 0x1F) << 7) | 0x23
def B(imm, rs2, rs1, f3):             return (((imm >> 12) & 1) << 31) | (((imm >> 5) & 0x3F) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (((imm >> 1) & 0xF) << 8) | (((imm >> 11) & 1) << 7) | 0x63
def U(imm20, rd, op):                 return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | op
def J(imm, rd):                       return (((imm >> 20) & 1) << 31) | (((imm >> 1) & 0x3FF) << 21) | (((imm >> 11) & 1) << 20) | (((imm >> 12) & 0xFF) << 12) | (rd << 7) | 0x6F
LUI = lambda rd, i: U(i, rd, 0x37); AUIPC = lambda rd, i: U(i, rd, 0x17)
ADDI = lambda rd, rs1, i: I(i, rs1, 0, rd); SLTIU = lambda rd, rs1, i: I(i, rs1, 3, rd)
SRAI = lambda rd, rs1, sh: I(0x400 | sh, rs1, 5, rd)
SRA = lambda rd, rs1, rs2: R(0x20, rs2, rs1, 5, rd); SLT = lambda rd, a, b: R(0, b, a, 2, rd); SLTU = lambda rd, a, b: R(0, b, a, 3, rd)
SW = lambda rs2, off, rs1: S(off, rs2, rs1, 2); SH = lambda rs2, off, rs1: S(off, rs2, rs1, 1); SB = lambda rs2, off, rs1: S(off, rs2, rs1, 0)
LW = lambda rd, off, rs1: I(off, rs1, 2, rd, 0x03); LB = lambda rd, off, rs1: I(off, rs1, 0, rd, 0x03)
LH = lambda rd, off, rs1: I(off, rs1, 1, rd, 0x03); LHU = lambda rd, off, rs1: I(off, rs1, 5, rd, 0x03); LBU = lambda rd, off, rs1: I(off, rs1, 4, rd, 0x03)
JALR = lambda rd, rs1, off, f3=0: I(off, rs1, f3, rd, 0x67)
BEQ = lambda a, b, off: B(off, b, a, 0); BLTU = lambda a, b, off: B(off, b, a, 6)

def emit(name, words, sig, stop_pc, instret, trap=0):
    """words: dict byte address -> 32-bit word."""
    img = [0] * 1024
    for a, w in words.items(): img[a >> 2] = w & 0xFFFFFFFF
    (OUT / f"{name}.hex").write_text("".join(f"{w:08x}\n" for w in img))
    (OUT / f"{name}.sig").write_text("".join(f"{w & 0xFFFFFFFF:08x}\n" for w in sig))
    meta = [1 if trap else 0, trap, stop_pc, instret, 0 if trap else 1, 0 if trap else 1, 0, 0, 0] + [0] * 256
    (OUT / f"{name}.tbmeta.hex").write_text("".join(f"{w:08x}\n" for w in meta))
    return img

# ---------------- program H1: 14 hand-checked results -------------------------
P = {}
def at(a, w): P[a] = w
at(0x00, LUI(1, 0x80000))        # x1 = 0x80000000
at(0x04, SRAI(2, 1, 4))          # E1  x2 = 0x80000000 >>> 4 = 0xF8000000
at(0x08, ADDI(3, 0, 36))         # x3 = 36 (rs2[4:0] = 4)
at(0x0C, ADDI(4, 1, 16))         # x4 = 0x80000010
at(0x10, SRA(5, 4, 3))           # E2  x5 = 0x80000010 >>> (36 & 31 = 4) = 0xF8000001
at(0x14, ADDI(6, 0, -1))         # x6 = 0xFFFFFFFF
at(0x18, ADDI(7, 0, 1))          # x7 = 1
at(0x1C, SLT(8, 6, 7))           # E3  -1 < 1 signed  -> 1
at(0x20, SLTU(9, 6, 7))          # E4  0xFFFFFFFF <u 1 -> 0
at(0x24, SLTIU(10, 0, -1))       # E5  0 <u 0xFFFFFFFF (imm sign-extended) -> 1
at(0x28, ADDI(11, 0, -2048))     # E6  imm 0x800 sign-extended -> 0xFFFFF800
at(0x2C, AUIPC(12, 0xFFFFF))     # E7  0x2C + 0xFFFFF000 = 0xFFFFF02C
at(0x30, LUI(13, 0x1))           # 0x1000
at(0x34, ADDI(13, 13, -2048))    # x13 = 0x800
at(0x38, LUI(14, 0xABCD1))       # 0xABCD1000
at(0x3C, ADDI(14, 14, 0x234))    # x14 = 0xABCD1234
at(0x40, SW(0, 0, 13))           # [0x800] = 0
at(0x44, SH(14, 2, 13))          # [0x802..3] = 0x1234 -> word 0x12340000
at(0x48, ADDI(15, 0, 0x80))      # x15 = 0x80
at(0x4C, SB(15, 1, 13))          # [0x801] = 0x80 -> word 0x12348000
at(0x50, LW(16, 0, 13))          # E8  0x12348000
at(0x54, LB(17, 1, 13))          # E9  byte 0x80 sign-extended -> 0xFFFFFF80
at(0x58, LH(18, 0, 13))          # E10 half 0x8000 -> 0xFFFF8000
at(0x5C, LHU(19, 2, 13))         #     0x00001234
at(0x60, LBU(20, 1, 13))         #     0x00000080
at(0x64, AUIPC(21, 0))           # x21 = 0x64
at(0x68, JALR(22, 21, 13))       # E11 target (0x64+13)&~1 = 0x70; x22 = 0x6C
at(0x6C, ADDI(23, 0, 0x7FF))     #     skipped (x23 stays 0)
at(0x70, ADDI(24, 0, 0x24))      # x24 = 0x24
at(0x74, BEQ(0, 0, 0x804))       # E12 B-imm with bit 11 set: target 0x74 + 0x804 = 0x878
at(0x78, ADDI(25, 0, 1))         #     skipped (x25 stays 0)
at(0x878, ADDI(26, 0, 0x26))     # x26 = 0x26
at(0x87C, J(0x1008, 27))         # E13 J-imm bit 12 set: target 0x87C+0x1008 = 0x1884 (RAM alias of 0x884); x27 = 0x880
at(0x880, ADDI(25, 0, 2))        #     skipped
at(0x884, AUIPC(28, 0))          # E14 x28 = pc = 0x1884 (a wrong J-imm[19:12] would give 0x884)
at(0x888, ADDI(29, 0, 3))        # x29 = 3
at(0x88C, ADDI(30, 30, 1))       # loop: x30++
at(0x890, ADDI(29, 29, -1))      #       x29--
at(0x894, BLTU(0, 29, -8))       # E15 backward BLTU 0 <u x29: taken for x29 = 2, 1 -> x30 = 3, x29 = 0
at(0x898, LUI(31, 0x1))          # x31 = 0x1000 (signature base helper)
a = 0x89C
for k in range(1, 32):           # sw xk, (0xF00 + 4k - 0x1000)(x31)
    at(a, SW(k, 0xF00 + 4 * k - 0x1000, 31)); a += 4
at(a, LUI(31, 0x10000)); a += 4  # x31 = 0x1000_0000
at(a, ADDI(1, 0, 1)); a += 4     # x1 = 1
tohost_pc = a + 0x1000           # executing from the alias: pc = 0x1xxx
at(a, SW(1, 0x10, 31)); a += 4   # TOHOST <- 1
at(a, J(0, 0))                   # j .
exp = [0] * 32
exp[1] = 0x80000000; exp[2] = 0xF8000000; exp[3] = 36; exp[4] = 0x80000010; exp[5] = 0xF8000001
exp[6] = 0xFFFFFFFF; exp[7] = 1; exp[8] = 1; exp[9] = 0; exp[10] = 1; exp[11] = 0xFFFFF800
exp[12] = 0xFFFFF02C; exp[13] = 0x800; exp[14] = 0xABCD1234; exp[15] = 0x80; exp[16] = 0x12348000
exp[17] = 0xFFFFFF80; exp[18] = 0xFFFF8000; exp[19] = 0x1234; exp[20] = 0x80; exp[21] = 0x64
exp[22] = 0x6C; exp[23] = 0; exp[24] = 0x24; exp[25] = 0; exp[26] = 0x26; exp[27] = 0x880
exp[28] = 0x1884; exp[29] = 0; exp[30] = 3; exp[31] = 0x1000
# instret by hand: 0x00..0x68 = 27 insns, 0x70, 0x74 = 2, 0x878, 0x87C = 2, 0x884, 0x888 = 2,
# loop 3 x 3 = 9, 0x898 = 1, 31 stores, lui, addi, TOHOST sw = 3  -> 27+2+2+2+9+1+31+3 = 77
img = emit("hand_h1", P, exp, tohost_pc, 77)

# ---------------- trap programs (halt PC = trapping insn, rd unchanged) --------
traps = {
  "hand_lh_off3":  (LH(5, 3, 13), 5, "LH at 0x803 (halfword at byte offset 3) -> cause 5"),
  "hand_lhu_off1": (LHU(5, 1, 13), 5, "LHU at 0x801 -> cause 5"),
  "hand_lw_off1":  (LW(5, 1, 13), 5, "LW at 0x801 -> cause 5"),
  "hand_lw_off3":  (LW(5, 3, 13), 5, "LW at 0x803 -> cause 5"),
  "hand_sh_off3":  (SH(14, 3, 13), 6, "SH at 0x803 -> cause 6, memory unchanged"),
  "hand_sw_off1":  (SW(14, 1, 13), 6, "SW at 0x801 -> cause 6"),
  "hand_sw_off3":  (SW(14, 3, 13), 6, "SW at 0x803 -> cause 6"),
  "hand_fence_i":  (I(0, 0, 1, 0, 0x0F), 3, "FENCE.I (0x0000100F) -> illegal"),
  "hand_slli_f7":  (I(0x400 | 1, 1, 1, 5), 3, "SLLI with imm[11:5]=0100000 -> illegal"),
  "hand_srli_f7":  (I(0x200 | 1, 1, 5, 5), 3, "SRLI with imm[11:5]=0010000 (shamt[5]) -> illegal"),
  "hand_jalr_f3":  (JALR(5, 13, 0, f3=1), 3, "JALR with funct3=001 -> illegal"),
  "hand_br_f3":    (B(8, 0, 0, 2), 3, "BRANCH funct3=010 -> illegal"),
  "hand_ld_f3":    (I(0, 13, 3, 5, 0x03), 3, "LOAD funct3=011 (LD) -> illegal"),
  "hand_st_f3":    (S(0, 14, 13, 3), 3, "STORE funct3=011 (SD) -> illegal"),
  "hand_ecall_rs1":(I(0, 1, 0, 0, 0x73), 3, "ECALL encoding with rs1=1 -> illegal (strict)"),
}
for name, (w, cause, desc) in traps.items():
    Q = {0x00: LUI(13, 0x1), 0x04: ADDI(13, 13, -2048), 0x08: LUI(14, 0xABCD1), 0x0C: ADDI(5, 0, 0x55),
         0x10: w, 0x14: SW(5, 0x10, 0)}
    # sig: [0x0F00..] untouched -> zeros; x5 must stay 0x55 (not observable here except via no store)
    emit(name, Q, [0] * 32, 0x10, 4, trap=cause)

# ---------------- cross-check the project ISS against the hand values --------
sys.path.insert(0, "/home/user/tpu-e-cpu/code/python")
from rv32.iss import Iss
r = Iss(img).run(10000)
sig = r.signature(0x0F00, 32)
bad = [(k, hex(sig[k]), hex(exp[k])) for k in range(32) if sig[k] != exp[k]]
print(f"H1 ISS: stop={r.stop_reason} pc={r.pc:#x} (hand {tohost_pc:#x}) instret={r.instret} (hand 77) sig mismatches vs hand: {bad}")
for name, (w, cause, desc) in traps.items():
    img = [0] * 1024
    for a, ww in {0x00: LUI(13, 0x1), 0x04: ADDI(13, 13, -2048), 0x08: LUI(14, 0xABCD1), 0x0C: ADDI(5, 0, 0x55), 0x10: w, 0x14: SW(5, 0x10, 0)}.items():
        img[a >> 2] = ww
    r = Iss(img).run(100)
    ok = r.stop_reason == "trap" and r.trap_cause == cause and r.pc == 0x10 and r.instret == 4 and r.regs[5] == 0x55
    print(f"{name:16s} {w:08x} ISS cause={r.trap_cause} pc={r.pc:#x} instret={r.instret} x5={r.regs[5]:#x} -> {'AGREES' if ok else 'DISAGREES'} with hand ({desc})")
