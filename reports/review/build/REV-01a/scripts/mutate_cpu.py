#!/usr/bin/env python3
"""REV-01a: CPU mutation experiments on COPIES of design/rtl/cpu (never the originals).

Each mutant = one exact text replacement (must match exactly once) in one RTL
file copy under reports/review/build/REV-01a/mut/<id>/.  The full official CPU
suite (44 tests x configs ws0 ws1 ws3 rand) is run on tests/cpu/tb_rv32i_core.v
with the reviewer runner run_cpu_suite.sh.  KILLED = at least one run failed.
"""
import shutil, subprocess, sys
from pathlib import Path

ROOT = Path("/home/user/tpu-e-cpu")
B = ROOT / "reports/review/build/REV-01a"
SRC = ROOT / "design/rtl/cpu"
FILES = ["rv32i_core.v", "rv32i_decode.v", "rv32i_alu.v", "rv32i_regfile.v"]

MUTANTS = [
 ("C01", "SRA/SRAI fill with 0 (SRA behaves as SRL)", "rv32i_core.v",
  "wire       sh_fill   = ir[30] & alu_q[31];", "wire       sh_fill   = 1'b0;"),
 ("C02", "SRA sign fill only on 4-bit steps, 0 on 1-bit steps", "rv32i_core.v",
  "{sh_fill, alu_q[31:1]}", "{1'b0, alu_q[31:1]}"),
 ("C03", "JALR target bit 0 treated as misaligned (bit 0 not cleared)", "rv32i_core.v",
  "wire wb_trap_misf = is_jump & alu_q[1];", "wire wb_trap_misf = is_jump & (alu_q[1] | (d_jalr & alu_q[0]));"),
 ("C04", "BLTU/BGEU use the signed comparison", "rv32i_core.v",
  "(d_funct3[1] ? alu_ltu : alu_lt)", "(d_funct3[1] ? alu_lt : alu_lt)"),
 ("C05", "SB byte enable: lanes 1 and 2 swapped", "rv32i_core.v",
  "2'b00:   st_strb = 4'b0001 << ma_lo;", "2'b00:   st_strb = 4'b0001 << {ma_lo[0], ma_lo[1]};"),
 ("C06", "load byte lane 1 and 2 swapped", "rv32i_core.v",
  "2'b01:   ld_byte = mem_rdata[15:8];", "2'b01:   ld_byte = mem_rdata[23:16];"),
 ("C07", "LB zero-extends (byte sign forced 0)", "rv32i_core.v",
  "(d_funct3[0] ? ld_half[15] : ld_byte[7])", "(d_funct3[0] ? ld_half[15] : 1'b0)"),
 ("C08", "LH sign taken from bit 14", "rv32i_core.v",
  "(d_funct3[0] ? ld_half[15] : ld_byte[7])", "(d_funct3[0] ? ld_half[14] : ld_byte[7])"),
 ("C09", "SLT uses the unsigned flag", "rv32i_alu.v",
  "3'b010:  result = {31'd0, lt};", "3'b010:  result = {31'd0, ltu};"),
 ("C10", "x0 writable (rd != 0 guard removed)", "rv32i_core.v",
  "& d_writes_rd & (d_rd != 5'd0) &", "& d_writes_rd &"),
 ("C11", "halfword misalignment at byte offset 3 not detected (only offset 1)", "rv32i_core.v",
  "((d_funct3[1:0] == 2'b01) & ea_lo[0])", "((d_funct3[1:0] == 2'b01) & (ea_lo == 2'b01))"),
 ("C12", "word misalignment at byte offset 1 not detected", "rv32i_core.v",
  "((d_funct3[1:0] == 2'b10) & (ea_lo != 2'b00))", "((d_funct3[1:0] == 2'b10) & ea_lo[1])"),
 ("C13", "FENCE.I (MISC-MEM funct3 001) accepted as NOP", "rv32i_decode.v",
  "assign is_fence  = op_misc & (funct3 == 3'b000);", "assign is_fence  = op_misc & (funct3[2:1] == 2'b00);"),
 ("C14", "SLLI/SRLI/SRAI funct7 not checked", "rv32i_decode.v",
  "wire opimm_ok = (funct3 == 3'b001) ? f7_zero :\n                    (funct3 == 3'b101) ? (f7_zero | f7_alt) : 1'b1;",
  "wire opimm_ok = 1'b1;"),
 ("C15", "JALR funct3 not checked", "rv32i_decode.v",
  "assign is_jalr   = op_jalr & (funct3 == 3'b000);", "assign is_jalr   = op_jalr;"),
 ("C16", "not-taken branch with misaligned target traps", "rv32i_core.v",
  "if (br_taken & alu_q[1]) begin", "if (alu_q[1]) begin"),
 ("C17", "B-immediate bit 11 taken from ir[31] instead of ir[7]", "rv32i_decode.v",
  "imm = {{19{ir[31]}}, ir[31], ir[7], ir[30:25], ir[11:8], 1'b0};",
  "imm = {{19{ir[31]}}, ir[31], ir[31], ir[30:25], ir[11:8], 1'b0};"),
 ("C18", "J-immediate bit 11 taken from ir[31] instead of ir[20]", "rv32i_decode.v",
  "ir[19:12], ir[20], ir[30:21]", "ir[19:12], ir[31], ir[30:21]"),
 ("C19", "J-immediate bits 19:12 replaced by the sign", "rv32i_decode.v",
  "{{11{ir[31]}}, ir[31], ir[19:12], ir[20]", "{{11{ir[31]}}, ir[31], {8{ir[31]}}, ir[20]"),
 ("C20", "AUIPC/JAL/branch target uses pc+4 base", "rv32i_core.v",
  "(d_lui ? 32'd0 : pc)", "(d_lui ? 32'd0 : pc_plus4)"),
 ("C21", "store does not retire", "rv32i_core.v",
  "pc       <= pc_plus4;    // store complete\n                            retire_q <= 1'b1;",
  "pc       <= pc_plus4;    // store complete\n                            retire_q <= 1'b0;"),
 ("C22", "FETCH loads ir every cycle (samples rdata before mem_ready)", "rv32i_core.v",
  "                    if (mem_ready) begin\n                        ir    <= mem_rdata;\n                        state <= S_DECODE;\n                    end",
  "                    ir <= mem_rdata;\n                    if (mem_ready) begin\n                        state <= S_DECODE;\n                    end"),
 ("C23", "S-immediate bit 11 taken from ir[30]", "rv32i_decode.v",
  "imm = {{20{ir[31]}}, ir[31:25], ir[11:7]};", "imm = {{20{ir[31]}}, ir[30], ir[30:25], ir[11:7]};"),
 ("C24", "I-immediate bit 11 taken from ir[30] (sign ok)", "rv32i_decode.v",
  "imm = {{20{ir[31]}}, ir[31:20]};", "imm = {{20{ir[31]}}, ir[30], ir[30:20]};"),
 ("C25", "SLTIU compares signed", "rv32i_alu.v",
  "3'b011:  result = {31'd0, ltu};", "3'b011:  result = {31'd0, lt};"),
 ("C26", "shift amount uses only imm/rs2 bits [3:0]", "rv32i_core.v",
  "wire [4:0] shamt_new = alu_b[4:0];", "wire [4:0] shamt_new = {1'b0, alu_b[3:0]};"),
 ("C27", "ECALL/EBREAK cause codes swapped", "rv32i_core.v",
  "trap_q <= T_ECALL;   state <= S_HALT;", "trap_q <= T_EBREAK;   state <= S_HALT;"),
 ("C28", "LHU sign-extends", "rv32i_core.v",
  "wire        ld_sign = ~d_funct3[2] & (d_funct3[0] ? ld_half[15] : ld_byte[7]);",
  "wire        ld_sign = (d_funct3[2] & ~d_funct3[0]) ? 1'b0 : (d_funct3[0] ? ld_half[15] : ld_byte[7]);"),
 ("C29", "trapping JAL/JALR (misaligned target) still writes rd", "rv32i_core.v",
  "& (d_rd != 5'd0) & ~wb_trap_misf);", "& (d_rd != 5'd0));"),
 ("C30", "CLEAR state does not write the register file (no reset of x1..x31)", "rv32i_core.v",
  "wire rf_we = (state == S_CLEAR) |", "wire rf_we = 1'b0 |")
]

def main(sel):
    rows = []
    for mid, desc, fname, old, new in MUTANTS:
        if sel and mid not in sel: continue
        d = B / "mut" / mid
        if d.exists(): shutil.rmtree(d)
        (d / "rtl").mkdir(parents=True)
        for f in FILES: shutil.copy(SRC / f, d / "rtl" / f)
        p = d / "rtl" / fname
        txt = p.read_text()
        n = txt.count(old)
        if n != 1:
            rows.append((mid, desc, f"MUTATION NOT APPLIED ({n} matches)")); continue
        p.write_text(txt.replace(old, new))
        (d / "mutation.diff").write_text(subprocess.run(["diff", "-u", str(SRC / fname), str(p)],
                                          capture_output=True, text=True).stdout)
        r = subprocess.run([str(B / "scripts/run_cpu_suite.sh"), str(d / "sim"), "ws0 ws1 ws3 rand"]
                           + [str(d / "rtl" / f) for f in FILES], capture_output=True, text=True)
        out = r.stdout.strip().splitlines()
        runs = next((l for l in out if l.startswith("RUNS")), "RUNS ?")
        failed = next((l for l in out if l.startswith("FAILED:")), "FAILED: ?")[7:].split()
        tests = sorted({f.split(":")[0] for f in failed})
        status = "KILLED" if failed else ("SURVIVED" if runs.startswith("RUNS") and "?" not in runs else "ERROR " + r.stdout + r.stderr)
        rows.append((mid, desc, f"{status}; {runs}; failing tests ({len(tests)}): {' '.join(tests[:8])}{' ...' if len(tests) > 8 else ''}"))
        print(rows[-1], flush=True)
    with open(B / "mut" / "cpu_mutation_results.txt", "a") as fh:
        for r in rows: fh.write(" | ".join(r) + "\n")

if __name__ == "__main__":
    main(set(sys.argv[1:]))
