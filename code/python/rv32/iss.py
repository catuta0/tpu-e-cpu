"""RV32I instruction-set simulator (ISS) - reference model for CPU verification.

Task SW-01b.  Models the architectural behaviour of the SoC CPU defined in
ARCHITECTURE.md sections 3, 4, 6 and INTERFACES.json (rev A, frozen):

* 32 x 32-bit registers, x0 hard-wired to 0, all registers 0 at reset
  (ARCHITECTURE.md 6: "registers reset to 0 (ASSUMPTION for determinism)");
* reset PC 0x0000_0000;
* RV32I base ISA semantics from the RISC-V Unprivileged ISA v2.1, chapter 2;
* little-endian memory, memory map decoded on addr[31:28]
  (0 = RAM, 1 = peripherals, 2 = SC-TPU, other = unmapped);
* traps per INTERFACES.json ``cpu.traps``: the CPU HALTS (no trap vector,
  no CSRs) and reports a cause 1..6.

Modelling decisions (all documented; the RTL must match them or the manager
must change the spec)
-------------------------------------------------------------------------
Traps (precise, no side effects)
    The trapping instruction does not retire: no register is written, no
    memory/peripheral write is performed, the PC stays at the address of the
    trapping instruction (``halt_pc``) and the retired-instruction counter
    does not count it.  This mirrors the RISC-V rule that exceptions are
    precise (mepc = address of the faulting instruction).
Misaligned fetch (cause 4)
    Following the RISC-V spec, the exception is raised by the JAL / JALR /
    TAKEN branch whose target is not 4-byte aligned (target[1:0] != 0 after
    JALR clears bit 0).  halt_pc = address of the jump/branch, rd unchanged.
    A NOT-taken branch with a misaligned target does not trap.
Misaligned load / store (causes 5 / 6)
    LH/LHU need addr[0] = 0, LW needs addr[1:0] = 0; SH / SW likewise.
    Checked before the address is decoded, for every region.
Illegal instruction (cause 3) - STRICT decoding
    Any word that is not one of the 37 RV32I instructions + FENCE + ECALL +
    EBREAK.  In particular: inst[1:0] != 11 (e.g. 0x00000000), unknown
    opcodes (e.g. 0xFFFFFFFF), JALR with funct3 != 0, undefined funct3 of
    BRANCH/LOAD/STORE, SLLI/SRLI/SRAI with imm[11:5] other than
    0000000/0100000 (SLLI: only 0000000), OP with funct7 other than
    0000000 (or 0100000 for SUB/SRA, e.g. M-extension words), every SYSTEM
    word other than exactly ECALL (0x00000073) and EBREAK (0x00100073)
    (no CSRs in rev A), MISC-MEM with funct3 != 000 (FENCE.I is Zifencei,
    not RV32I).
FENCE
    opcode MISC-MEM, funct3 000: NOP regardless of fm/pred/succ/rs1/rd
    (the spec says implementations ignore the reserved fields).
Peripherals (base 0x1000_0000, ARCHITECTURE.md 4.1)
    LED (0x00) RW, 6 bits; UART_TX (0x04) W, each write with byte lane 0
    enabled is recorded as one transmitted byte; UART_STATUS (0x08) reads 0:
    tx_busy is modelled as NEVER busy (the ISS has no notion of time).
    CYCLE (0x0C) reads 0: the ISS has no cycle model, so programs whose
    results depend on CYCLE must NOT be used for signature comparison.
    TOHOST (0x10) RW: a write stops the simulation (after the store retires)
    with ``stop_reason = 'tohost'``.  Other offsets: read 0, write ignored.
SC-TPU (base 0x2000_0000) - STUB for the SoC demo only
    See :class:`TpuStub`.  STATUS reads DONE=1 (after a configurable number
    of BUSY polls), RESULT / CYCLES return configurable values.
Unmapped addresses
    Read 0, write ignored, sticky ``bus_err`` flag set (ARCHITECTURE.md 4).
RAM aliasing
    Region 0 uses addr[11:2] only (ARCHITECTURE.md 4 ASSUMPTION), so RAM
    aliases every 4 KiB inside 0x0000_0000..0x0FFF_FFFF.
Byte / halfword accesses to peripherals and TPU
    Reads return the selected lanes of the 32-bit register, writes merge the
    enabled byte lanes (mem_wstrb semantics, ARCHITECTURE.md 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum

MASK32 = 0xFFFFFFFF
RAM_BYTES = 4096

PERIPH_BASE = 0x1000_0000
TPU_BASE = 0x2000_0000
LED_OFF, UART_TX_OFF, UART_STATUS_OFF, CYCLE_OFF, TOHOST_OFF = 0x00, 0x04, 0x08, 0x0C, 0x10
TOHOST_ADDR = PERIPH_BASE + TOHOST_OFF

# TPU register offsets (INTERFACES.json tpu.regs / ARCHITECTURE.md 5.4)
TPU_CTRL, TPU_STATUS, TPU_CONFIG, TPU_RESULT, TPU_CYCLES, TPU_PARAMS = 0x000, 0x004, 0x008, 0x00C, 0x010, 0x014


class TrapCause(IntEnum):
    """Trap causes, INTERFACES.json ``cpu.traps``."""
    NONE = 0
    ECALL = 1
    EBREAK = 2
    ILLEGAL = 3
    MISALIGNED_FETCH = 4
    MISALIGNED_LOAD = 5
    MISALIGNED_STORE = 6


def sext(value: int, bits: int) -> int:
    """Sign-extend the low ``bits`` bits of ``value`` to a Python int."""
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def s32(value: int) -> int:
    """32-bit word -> signed Python int."""
    return sext(value, 32)


# --------------------------------------------------------------------------
# SC-TPU stub
# --------------------------------------------------------------------------
@dataclass
class TpuStub:
    """Minimal register-level stand-in for the SC-TPU (NOT a golden model).

    Only what the SoC demo program needs:

    * CTRL (0x000) write with bit0 = 1 -> "START": counts ``starts`` and arms
      ``busy_polls`` STATUS reads that return BUSY=1, DONE=0.
    * STATUS (0x004) -> BUSY (0x1) while armed polls remain, else DONE (0x2).
      With the default ``busy_polls = 0`` STATUS always reads DONE=1, as
      requested in SW-01b.
    * CONFIG (0x008) RW: [3:0] LOG2_L (reset 8, clamped to 4..10 on write),
      [6:4] ACT_SHIFT (reset 0); other bits read 0 (INTERFACES.json).
    * RESULT (0x00C) -> ``result & 0xF``; CYCLES (0x010) -> ``cycles``.
    * PARAMS (0x014) -> NL=16, IL=8, RNG_MODE, version (rev B defaults: RNG_MODE 2,
      version 0x02 -> 0x02020810, ARCHITECTURE.md 11 / ADR-008; SW-02).
    * Every other offset of the 4 KiB window is plain read/write storage
      (stands in for INPUT/SCORE/HIDDEN/BIAS/WEIGHT; no inference is done).
    """
    result: int = 0
    cycles: int = 0
    busy_polls: int = 0
    rng_mode: int = 2              # rev B default RNG_MODE (ARCHITECTURE.md 11)
    version: int = 0x02            # PARAMS[31:24], rev B (was 0x01 in rev A)
    config: int = 0x08
    starts: int = 0
    config_writes: list[int] = field(default_factory=list)
    _polls_left: int = 0
    _store: bytearray = field(default_factory=lambda: bytearray(4096))

    def read(self, off: int) -> int:
        """32-bit read of the word at (word-aligned) offset ``off``."""
        if off == TPU_STATUS:
            if self._polls_left > 0:
                self._polls_left -= 1
                return 0x1          # BUSY
            return 0x2              # DONE
        if off == TPU_CONFIG:
            return self.config
        if off == TPU_RESULT:
            return self.result & 0xF
        if off == TPU_CYCLES:
            return self.cycles & MASK32
        if off == TPU_PARAMS:
            return ((self.version & 0xFF) << 24) | ((self.rng_mode & 3) << 16) | (8 << 8) | 16
        if off == TPU_CTRL:
            return 0                # CTRL is write-only
        return int.from_bytes(self._store[off:off + 4], "little")

    def write(self, off: int, data: int, strb: int) -> None:
        """Write the byte lanes enabled in ``strb`` of ``data``."""
        old = self.read(off) if off not in (TPU_STATUS, TPU_CTRL) else 0
        merged = _merge(old, data, strb)
        if off == TPU_CTRL:
            if merged & 1:
                self.starts += 1
                self._polls_left = self.busy_polls
        elif off == TPU_CONFIG:
            log2l = min(max(merged & 0xF, 4), 10)
            self.config = log2l | (merged & 0x70)
            self.config_writes.append(merged & MASK32)
        elif off in (TPU_STATUS, TPU_RESULT, TPU_CYCLES, TPU_PARAMS):
            pass                    # read-only registers: write ignored
        else:
            self._store[off:off + 4] = merged.to_bytes(4, "little")


def _merge(old: int, data: int, strb: int) -> int:
    """Byte-lane merge (mem_wstrb semantics)."""
    out = old
    for lane in range(4):
        if strb >> lane & 1:
            mask = 0xFF << (8 * lane)
            out = (out & ~mask) | (data & mask)
    return out & MASK32


# --------------------------------------------------------------------------
# Result container
# --------------------------------------------------------------------------
@dataclass
class IssResult:
    """Outcome of :meth:`Iss.run`.

    ``stop_reason``: 'tohost' (a store to TOHOST retired), 'trap' (CPU
    halted, see ``trap_cause``) or 'max_steps' (safety limit reached).
    ``pc``: for 'trap' the halt PC (address of the trapping instruction); for
    'tohost' the address of the store that wrote TOHOST.
    ``instret``: number of retired instructions (trapping one excluded,
    TOHOST store included).
    """
    stop_reason: str
    trap_cause: int
    pc: int
    instret: int
    regs: list[int]
    ram: bytes
    tohost: int | None
    uart: bytes
    led_writes: list[int]
    led: int
    bus_err: bool

    def word(self, addr: int) -> int:
        """RAM word at byte address ``addr`` (word aligned, < 4 KiB)."""
        return int.from_bytes(self.ram[addr:addr + 4], "little")

    def signature(self, base: int = 0x0F00, n: int = 32) -> list[int]:
        """``n`` RAM words starting at ``base`` (signature area, see gen_cpu_tests)."""
        return [self.word(base + 4 * k) for k in range(n)]


# --------------------------------------------------------------------------
# The simulator
# --------------------------------------------------------------------------
class Iss:
    """RV32I ISS.  ``image``: RAM contents as a list of 32-bit words (<= 1024)."""

    def __init__(self, image: list[int] | None = None, tpu: TpuStub | None = None):
        self.ram = bytearray(RAM_BYTES)
        for i, w in enumerate(image or []):
            self.ram[4 * i:4 * i + 4] = (w & MASK32).to_bytes(4, "little")
        self.regs = [0] * 32
        self.pc = 0
        self.instret = 0
        self.tpu = tpu if tpu is not None else TpuStub()
        self.led = 0
        self.led_writes: list[int] = []
        self.uart = bytearray()
        self.tohost: int | None = None
        self.bus_err = False
        self.halted = False
        self.trap_cause = TrapCause.NONE
        self.stop_reason: str | None = None

    # ---------------- bus (word granularity, like mem_* of ARCHITECTURE.md 3)
    def bus_read(self, addr: int) -> int:
        """32-bit read of the word containing ``addr`` (addr[1:0] ignored)."""
        addr &= MASK32 & ~3
        region = addr >> 28
        if region == 0x0:
            a = addr & 0xFFC                       # addr[11:2] only (aliasing)
            return int.from_bytes(self.ram[a:a + 4], "little")
        if region == 0x1:
            off = addr & 0xFFF
            if off == LED_OFF:
                return self.led
            if off == UART_STATUS_OFF:
                return 0                           # tx_busy never set (see docstring)
            if off == CYCLE_OFF:
                return 0                           # no cycle model (see docstring)
            if off == TOHOST_OFF:
                return self.tohost or 0
            return 0                               # UART_TX (W) and undefined offsets
        if region == 0x2:
            return self.tpu.read(addr & 0xFFF)
        self.bus_err = True                        # unmapped: read 0, sticky flag
        return 0

    def bus_write(self, addr: int, data: int, strb: int) -> None:
        """Write with byte enables ``strb`` (data already shifted to its lanes)."""
        addr &= MASK32 & ~3
        region = addr >> 28
        if region == 0x0:
            a = addr & 0xFFC
            old = int.from_bytes(self.ram[a:a + 4], "little")
            self.ram[a:a + 4] = _merge(old, data, strb).to_bytes(4, "little")
        elif region == 0x1:
            off = addr & 0xFFF
            if off == LED_OFF:
                self.led = _merge(self.led, data, strb) & 0x3F
                self.led_writes.append(self.led)
            elif off == UART_TX_OFF:
                if strb & 1:
                    self.uart.append(data & 0xFF)  # never busy -> never dropped
            elif off == TOHOST_OFF:
                self.tohost = _merge(self.tohost or 0, data, strb)
                self.stop_reason = "tohost"        # TB stops on any TOHOST write
            # UART_STATUS / CYCLE are read-only, other offsets undefined: ignored
        elif region == 0x2:
            self.tpu.write(addr & 0xFFF, data, strb)
        else:
            self.bus_err = True                    # unmapped: write ignored

    # ---------------- one instruction
    def _trap(self, cause: TrapCause) -> None:
        self.halted = True
        self.trap_cause = cause
        self.stop_reason = "trap"

    def step(self) -> None:
        """Execute one instruction (or take a trap).  No-op once stopped."""
        if self.stop_reason is not None:
            return
        pc = self.pc
        insn = self.bus_read(pc)
        opcode = insn & 0x7F
        rd = (insn >> 7) & 0x1F
        f3 = (insn >> 12) & 0x7
        rs1 = (insn >> 15) & 0x1F
        rs2 = (insn >> 20) & 0x1F
        f7 = insn >> 25
        x = self.regs
        a, b = x[rs1], x[rs2]
        # Immediates exactly as in spec figure "Types of immediate produced
        # by RISC-V instructions".
        imm_i = sext(insn >> 20, 12)
        imm_s = sext((f7 << 5) | rd, 12)
        imm_b = sext((((insn >> 31) & 1) << 12) | (((insn >> 7) & 1) << 11)
                     | (((insn >> 25) & 0x3F) << 5) | (((insn >> 8) & 0xF) << 1), 13)
        imm_u = insn & 0xFFFFF000
        imm_j = sext((((insn >> 31) & 1) << 20) | (((insn >> 12) & 0xFF) << 12)
                     | (((insn >> 20) & 1) << 11) | (((insn >> 21) & 0x3FF) << 1), 21)

        next_pc = (pc + 4) & MASK32
        result: int | None = None        # value for rd, None = no write

        if opcode == 0b0110111:                     # LUI
            result = imm_u
        elif opcode == 0b0010111:                   # AUIPC
            result = (pc + imm_u) & MASK32
        elif opcode == 0b1101111:                   # JAL
            target = (pc + imm_j) & MASK32
            if target & 3:
                return self._trap(TrapCause.MISALIGNED_FETCH)
            result, next_pc = (pc + 4) & MASK32, target
        elif opcode == 0b1100111:                   # JALR
            if f3 != 0:
                return self._trap(TrapCause.ILLEGAL)
            # Target computed from rs1 BEFORE rd is written (rd may == rs1);
            # the spec clears bit 0 of the sum.
            target = (a + imm_i) & MASK32 & ~1
            if target & 3:
                return self._trap(TrapCause.MISALIGNED_FETCH)
            result, next_pc = (pc + 4) & MASK32, target
        elif opcode == 0b1100011:                   # BRANCH
            if f3 == 0b000:
                taken = a == b                      # BEQ
            elif f3 == 0b001:
                taken = a != b                      # BNE
            elif f3 == 0b100:
                taken = s32(a) < s32(b)             # BLT  (signed)
            elif f3 == 0b101:
                taken = s32(a) >= s32(b)            # BGE  (signed)
            elif f3 == 0b110:
                taken = a < b                       # BLTU (unsigned)
            elif f3 == 0b111:
                taken = a >= b                      # BGEU (unsigned)
            else:
                return self._trap(TrapCause.ILLEGAL)
            if taken:
                target = (pc + imm_b) & MASK32
                if target & 3:
                    return self._trap(TrapCause.MISALIGNED_FETCH)
                next_pc = target
        elif opcode == 0b0000011:                   # LOAD
            if f3 not in (0, 1, 2, 4, 5):
                return self._trap(TrapCause.ILLEGAL)
            addr = (a + imm_i) & MASK32
            size = 1 << (f3 & 3)                    # 1, 2 or 4 bytes
            if addr & (size - 1):
                return self._trap(TrapCause.MISALIGNED_LOAD)
            word = self.bus_read(addr)
            raw = (word >> (8 * (addr & 3))) & ((1 << (8 * size)) - 1)
            if f3 == 0b000:
                result = sext(raw, 8) & MASK32      # LB  sign-extends
            elif f3 == 0b001:
                result = sext(raw, 16) & MASK32     # LH  sign-extends
            else:
                result = raw                        # LW, LBU, LHU zero-extend
        elif opcode == 0b0100011:                   # STORE
            if f3 not in (0, 1, 2):
                return self._trap(TrapCause.ILLEGAL)
            addr = (a + imm_s) & MASK32
            size = 1 << f3
            if addr & (size - 1):
                return self._trap(TrapCause.MISALIGNED_STORE)
            lane = addr & 3
            data = (b & ((1 << (8 * size)) - 1)) << (8 * lane)   # shifted to lanes
            strb = ((1 << size) - 1) << lane
            self.bus_write(addr, data, strb)
        elif opcode == 0b0010011:                   # OP-IMM
            if f3 == 0b000:
                result = (a + imm_i) & MASK32                      # ADDI
            elif f3 == 0b010:
                result = int(s32(a) < imm_i)                       # SLTI
            elif f3 == 0b011:
                result = int(a < (imm_i & MASK32))                 # SLTIU (imm sign-extended, compared unsigned)
            elif f3 == 0b100:
                result = (a ^ imm_i) & MASK32                      # XORI
            elif f3 == 0b110:
                result = (a | imm_i) & MASK32                      # ORI
            elif f3 == 0b111:
                result = (a & imm_i) & MASK32                      # ANDI
            elif f3 == 0b001:                                      # SLLI
                if f7 != 0:
                    return self._trap(TrapCause.ILLEGAL)
                result = (a << rs2) & MASK32
            else:                                                  # f3 == 0b101
                if f7 == 0x00:
                    result = a >> rs2                              # SRLI
                elif f7 == 0x20:
                    result = (s32(a) >> rs2) & MASK32              # SRAI
                else:
                    return self._trap(TrapCause.ILLEGAL)
        elif opcode == 0b0110011:                   # OP
            sh = b & 0x1F                           # only rs2[4:0] is used
            if f7 == 0x00:
                result = [
                    (a + b) & MASK32,               # ADD
                    (a << sh) & MASK32,             # SLL
                    int(s32(a) < s32(b)),           # SLT
                    int(a < b),                     # SLTU
                    a ^ b,                          # XOR
                    a >> sh,                        # SRL
                    a | b,                          # OR
                    a & b,                          # AND
                ][f3]
            elif f7 == 0x20 and f3 == 0b000:
                result = (a - b) & MASK32           # SUB
            elif f7 == 0x20 and f3 == 0b101:
                result = (s32(a) >> sh) & MASK32    # SRA
            else:
                return self._trap(TrapCause.ILLEGAL)
        elif opcode == 0b0001111:                   # MISC-MEM
            if f3 != 0:
                return self._trap(TrapCause.ILLEGAL)   # FENCE.I etc. not in RV32I
            # FENCE: single hart, in-order, no caches -> NOP.
        elif opcode == 0b1110011:                   # SYSTEM
            if insn == 0x00000073:
                return self._trap(TrapCause.ECALL)
            if insn == 0x00100073:
                return self._trap(TrapCause.EBREAK)
            return self._trap(TrapCause.ILLEGAL)    # CSR*, WFI, MRET...: no CSRs
        else:
            return self._trap(TrapCause.ILLEGAL)

        # ---- retire ----
        if result is not None and rd != 0:          # writes to x0 are discarded
            x[rd] = result & MASK32
        self.instret += 1
        if self.stop_reason is None:
            self.pc = next_pc
        else:                                       # TOHOST write retired: stop here
            self.pc = pc

    def run(self, max_steps: int = 200_000) -> IssResult:
        """Run until TOHOST write, trap or ``max_steps`` instructions."""
        for _ in range(max_steps):
            if self.stop_reason is not None:
                break
            self.step()
        if self.stop_reason is None:
            self.stop_reason = "max_steps"
        return IssResult(
            stop_reason=self.stop_reason, trap_cause=int(self.trap_cause),
            pc=self.pc, instret=self.instret, regs=list(self.regs),
            ram=bytes(self.ram), tohost=self.tohost, uart=bytes(self.uart),
            led_writes=list(self.led_writes), led=self.led, bus_err=self.bus_err)


def run_image(image: list[int], max_steps: int = 200_000, tpu: TpuStub | None = None) -> IssResult:
    """Convenience: build an :class:`Iss` on ``image`` and run it."""
    return Iss(image, tpu=tpu).run(max_steps)


def is_legal(word: int) -> bool:
    """True if the ISS would execute ``word`` without an ILLEGAL trap.

    Implemented by executing the word at PC 0 in a scratch ISS (registers 0,
    so loads/stores hit address 0 and jumps/branches stay aligned or trap
    with a non-illegal cause).
    """
    iss = Iss([word])
    iss.step()
    return iss.trap_cause != TrapCause.ILLEGAL
