`default_nettype none
`timescale 1ns / 1ps  // simulation only; keeps Icarus/Verilator timescale-consistent with the testbenches
// =============================================================================
// File        : design/rtl/cpu/rv32i_decode.v
// Module      : rv32i_decode
// Project     : SC-TPU + RV32I SoC on Sipeed Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Task        : RTL-CPU (RV32I multi-cycle CPU core)
// Author      : fpga-engineer (Claude Code specialist)
//
// PURPOSE
//   Purely combinational instruction decoder of the RV32I core. Input is the
//   instruction register `ir` (held constant from the end of FETCH until the
//   next FETCH completes). Outputs are the instruction class, the sign-
//   extended immediate, the ALU operation for the EXECUTE state, the
//   register-write flag and the trap classification (illegal / ECALL /
//   EBREAK).
//
// INSTRUCTION FIELDS (RISC-V Unprivileged ISA v2.1, section 2.2/2.3)
//
//    31        25 24   20 19   15 14  12 11        7 6      0
//   +------------+-------+-------+------+-----------+--------+
//   |  funct7    |  rs2  |  rs1  |funct3|    rd     | opcode | R-type (OP)
//   |     imm[11:0]      |  rs1  |funct3|    rd     | opcode | I-type (OP-IMM, LOAD, JALR, FENCE, SYSTEM)
//   | imm[11:5]  |  rs2  |  rs1  |funct3| imm[4:0]  | opcode | S-type (STORE)
//   |imm[12|10:5]|  rs2  |  rs1  |funct3|imm[4:1|11]| opcode | B-type (BRANCH)
//   |           imm[31:12]              |    rd     | opcode | U-type (LUI, AUIPC)
//   |     imm[20|10:1|11|19:12]         |    rd     | opcode | J-type (JAL)
//   +------------+-------+-------+------+-----------+--------+
//   ir[1:0] must be 2'b11 (32-bit encoding); anything else is illegal.
//
// OPCODE MAP USED (ir[6:2], ir[1:0] = 11)      (spec table "RV32I Base")
//   01101 LUI      00101 AUIPC    11011 JAL      11001 JALR (funct3 000)
//   11000 BRANCH   (funct3 000 BEQ 001 BNE 100 BLT 101 BGE 110 BLTU 111 BGEU)
//   00000 LOAD     (funct3 000 LB 001 LH 010 LW 100 LBU 101 LHU)
//   01000 STORE    (funct3 000 SB 001 SH 010 SW)
//   00100 OP-IMM   (000 ADDI 010 SLTI 011 SLTIU 100 XORI 110 ORI 111 ANDI,
//                   001 SLLI funct7=0000000, 101 SRLI 0000000 / SRAI 0100000)
//   01100 OP       (funct7 0000000: all funct3; funct7 0100000: SUB 000, SRA 101)
//   00011 MISC-MEM (funct3 000 FENCE -> executed as a NOP; other fields ignored
//                   as the spec reserves them for future use)
//   11100 SYSTEM   (exactly 0x00000073 ECALL, 0x00100073 EBREAK)
//   Everything else (incl. FENCE.I funct3 001, CSR instructions, a zero word,
//   RV32I shifts with shamt[5] = 1) is ILLEGAL -> trap_cause 3.
//
// IMMEDIATES (all sign-extended from ir[31])
//   I: {20{ir31}, ir[31:20]}
//   S: {20{ir31}, ir[31:25], ir[11:7]}
//   B: {19{ir31}, ir31, ir7, ir[30:25], ir[11:8], 0}
//   U: {ir[31:12], 12'b0}
//   J: {11{ir31}, ir31, ir[19:12], ir20, ir[30:21], 0}
//
// REQUIREMENT REFERENCES
//   ARCHITECTURE.md section 6 (ISA list, trap causes); INTERFACES.json "cpu".
// =============================================================================

module rv32i_decode (
    input  wire [31:0] ir,          // instruction register
    // ---- instruction class (one-hot among legal instructions) --------------
    output wire        is_lui,      // LUI      rd = imm_u
    output wire        is_auipc,    // AUIPC    rd = pc + imm_u
    output wire        is_jal,      // JAL      rd = pc + 4, pc = pc + imm_j
    output wire        is_jalr,     // JALR     rd = pc + 4, pc = (rs1 + imm_i) & ~1
    output wire        is_branch,   // Bxx      pc = cond ? pc + imm_b : pc + 4
    output wire        is_load,     // Lx       rd = mem[rs1 + imm_i]
    output wire        is_store,    // Sx       mem[rs1 + imm_s] = rs2
    output wire        is_fence,    // FENCE    NOP (single-hart, in-order, no caches)
    output wire        is_ecall,    // ECALL    trap 1
    output wire        is_ebreak,   // EBREAK   trap 2
    output wire        illegal,     // none of the above -> trap 3
    // ---- operands / control -------------------------------------------------
    output reg  [31:0] imm,         // sign-extended immediate of the format
    output wire        b_is_imm,    // EXECUTE: ALU operand B = imm (else rs2)
    output wire [3:0]  alu_op,      // EXECUTE: ALU operation (rv32i_alu table)
    output wire        writes_rd,   // instruction writes rd (if rd != 0)
    output wire [4:0]  rs1,         // ir[19:15]
    output wire [4:0]  rs2,         // ir[24:20]
    output wire [4:0]  rd,          // ir[11:7]
    output wire [2:0]  funct3       // ir[14:12] (branch condition, load/store size)
);

    // ---- Raw fields ---------------------------------------------------------------
    wire [4:0] opc    = ir[6:2];        // major opcode (ir[1:0] checked separately)
    wire [6:0] funct7 = ir[31:25];      // R-type funct7 / shift-type in OP-IMM
    wire       len32  = (ir[1:0] == 2'b11); // 32-bit instruction encoding
    assign funct3 = ir[14:12];
    assign rs1    = ir[19:15];
    assign rs2    = ir[24:20];
    assign rd     = ir[11:7];

    // ---- Major opcode match (before funct checks) --------------------------------
    wire op_lui    = len32 & (opc == 5'b01101);
    wire op_auipc  = len32 & (opc == 5'b00101);
    wire op_jal    = len32 & (opc == 5'b11011);
    wire op_jalr   = len32 & (opc == 5'b11001);
    wire op_branch = len32 & (opc == 5'b11000);
    wire op_load   = len32 & (opc == 5'b00000);
    wire op_store  = len32 & (opc == 5'b01000);
    wire op_opimm  = len32 & (opc == 5'b00100);
    wire op_op     = len32 & (opc == 5'b01100);
    wire op_misc   = len32 & (opc == 5'b00011);

    // ---- funct3 / funct7 legality per opcode ------------------------------------
    // BRANCH: funct3 010 and 011 are reserved.
    wire br_ok    = (funct3[2:1] != 2'b01);
    // LOAD: 000 LB, 001 LH, 010 LW, 100 LBU, 101 LHU are defined.
    wire ld_ok    = (funct3 == 3'b000) | (funct3 == 3'b001) | (funct3 == 3'b010) |
                    (funct3 == 3'b100) | (funct3 == 3'b101);
    // STORE: 000 SB, 001 SH, 010 SW.
    wire st_ok    = (funct3 == 3'b000) | (funct3 == 3'b001) | (funct3 == 3'b010);
    // OP-IMM shifts: SLLI needs funct7 0000000; SRLI/SRAI need 0000000/0100000.
    // (In RV32I a set shamt[5] = ir[25] is reserved -> covered by funct7.)
    wire f7_zero  = (funct7 == 7'b0000000);
    wire f7_alt   = (funct7 == 7'b0100000);
    wire opimm_ok = (funct3 == 3'b001) ? f7_zero :
                    (funct3 == 3'b101) ? (f7_zero | f7_alt) : 1'b1;
    // OP: funct7 0000000 for all funct3, 0100000 only for SUB (000) and SRA (101).
    wire op_ok    = f7_zero | (f7_alt & ((funct3 == 3'b000) | (funct3 == 3'b101)));

    // OP / OP-IMM (rd = rs1 op rs2|imm). Internal only: the core treats every
    // legal instruction that is not one of the other classes as an ALU op.
    wire is_alu;

    // ---- Final classes -------------------------------------------------------------
    assign is_lui    = op_lui;
    assign is_auipc  = op_auipc;
    assign is_jal    = op_jal;
    assign is_jalr   = op_jalr & (funct3 == 3'b000);
    assign is_branch = op_branch & br_ok;
    assign is_load   = op_load & ld_ok;
    assign is_store  = op_store & st_ok;
    assign is_alu    = (op_opimm & opimm_ok) | (op_op & op_ok);
    assign is_fence  = op_misc & (funct3 == 3'b000);
    assign is_ecall  = (ir == 32'h0000_0073);
    assign is_ebreak = (ir == 32'h0010_0073);
    assign illegal   = ~(is_lui | is_auipc | is_jal | is_jalr | is_branch | is_load |
                         is_store | is_alu | is_fence | is_ecall | is_ebreak);

    // ---- Immediate generator (one mux on the format) ---------------------------------
    // The format is selected from the major opcode only; for opcodes without an
    // immediate (OP) or illegal words the value is irrelevant (default I).
    always @(*) begin
        if (op_lui | op_auipc)
            imm = {ir[31:12], 12'd0};                                      // U
        else if (op_jal)
            imm = {{11{ir[31]}}, ir[31], {8{ir[31]}}, ir[20], ir[30:21], 1'b0}; // J
        else if (op_branch)
            imm = {{19{ir[31]}}, ir[31], ir[7], ir[30:25], ir[11:8], 1'b0};   // B
        else if (op_store)
            imm = {{20{ir[31]}}, ir[31:25], ir[11:7]};                       // S
        else
            imm = {{20{ir[31]}}, ir[31:20]};                                 // I
    end

    // ---- EXECUTE-state ALU control ----------------------------------------------------
    // Operand B: immediate for OP-IMM, LOAD, STORE, JALR; rs2 for OP and BRANCH.
    assign b_is_imm = op_opimm | op_load | op_store | op_jalr;

    // alu_op = {instr[30], funct3} for OP; for OP-IMM instr[30] is part of the
    // immediate and only means "arithmetic" for SRAI (funct3 101), so it is
    // masked otherwise (ADDI with a negative immediate must NOT subtract).
    // Branches subtract (1000) to get eq/lt/ltu; loads, stores, JALR add (0000).
    assign alu_op = op_op     ? {ir[30], funct3} :
                    op_opimm  ? {ir[30] & (funct3 == 3'b101), funct3} :
                    op_branch ? 4'b1000 :
                                4'b0000;

    // ---- Register write ------------------------------------------------------------------
    assign writes_rd = is_lui | is_auipc | is_jal | is_jalr | is_load | is_alu;

endmodule

`default_nettype wire
