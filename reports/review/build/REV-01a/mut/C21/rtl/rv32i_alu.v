`default_nettype none
`timescale 1ns / 1ps  // simulation only; keeps Icarus/Verilator timescale-consistent with the testbenches
// =============================================================================
// File        : design/rtl/cpu/rv32i_alu.v
// Module      : rv32i_alu
// Project     : SC-TPU + RV32I SoC on Sipeed Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Task        : RTL-CPU (RV32I multi-cycle CPU core)
// Author      : fpga-engineer (Claude Code specialist)
//
// PURPOSE
//   Purely combinational 32-bit integer ALU of the RV32I core. It is the ONLY
//   arithmetic unit of the core besides the PC+4 incrementer; the multi-cycle
//   FSM time-shares it for
//     DECODE : pc + imm  (branch / JAL target, AUIPC)  or  0 + imm  (LUI)
//     EXECUTE: rs1 OP rs2 / rs1 OP imm (OP, OP-IMM), rs1 + imm (load/store
//              address, JALR target), rs1 - rs2 (branch compare flags).
//
// OPERATION ENCODING  op[3:0] = {instr[30], funct3}  (chosen so that the core
// can pass the instruction bits through almost unchanged for OP / OP-IMM)
//   op    | result                         | RV32I instructions
//   ------+--------------------------------+---------------------------------
//   0000  | a + b                          | ADD ADDI, addresses, targets
//   1000  | a - b                          | SUB, branch compare
//   x001  | a  (pass-through, see SHIFTS)  | SLL SLLI
//   x010  | (signed a < signed b) ? 1 : 0  | SLT SLTI
//   x011  | (a < b unsigned) ? 1 : 0       | SLTU SLTIU
//   x100  | a ^ b                          | XOR XORI
//   x101  | a  (pass-through, see SHIFTS)  | SRL SRLI SRA SRAI
//   x110  | a | b                          | OR ORI
//   x111  | a & b                          | AND ANDI
//   (x = don't care; the decoder only produces op[3]=1 for SUB and SRA.)
//
// SHIFTS (area decision, RTL-CPU)
//   This ALU contains NO barrel shifter. For SLL/SRL/SRA it passes operand A
//   through; the core loads it into alu_q and shifts it iteratively in its
//   SHIFT state (4 bits per cycle while >= 4 remain, then 1 bit per cycle,
//   like PicoRV32's TWO_STAGE_SHIFT option). Measured during RTL-CPU with
//   Yosys 0.70 synth_gowin: a 33-bit 5-level barrel shifter alone maps to
//   ~283 LUT + 164 MUX2_LUTx cells and the ALU with it to ~1000 LUT/MUX
//   cells; the iterative shifter needs ~3 LUT per bit in the core.
//
// FLAG OUTPUTS (valid for any op, but only meaningful when the adder
// subtracts, i.e. op = 1000 SUB, x010 SLT, x011 SLTU)
//   eq  : a == b                  (BEQ/BNE)  - from a ^ b, independent of op
//   lt  : signed   a < b          (BLT/BGE, SLT)
//   ltu : unsigned a < b          (BLTU/BGEU, SLTU)
//
// IMPLEMENTATION NOTES (area on GW1NR-9)
//   * ONE adder for add and subtract: a + (b ^ {32{sub}}) + sub. The carry-in
//     is injected through an extra LSB ({a,1} + {b',sub}) so that Yosys maps
//     the whole thing onto a single 33-bit Gowin ALU carry chain.
//   * No shifter (see SHIFTS).
//   * Unsigned less-than = NOT carry-out of a - b; signed less-than corrects
//     it with the operand sign bits (no second comparator).
//
// TIMING
//   Combinational, no state. In the core the worst path is
//   BSRAM output (rs1/rs2) -> operand mux -> this ALU (33-bit carry chain)
//   -> alu_q / FSM.
//
// REQUIREMENT REFERENCES
//   ARCHITECTURE.md section 6 (RV32I base ISA); RISC-V Unprivileged ISA v2.1,
//   chapter 2 (integer computational instructions, conditional branches).
// =============================================================================

module rv32i_alu (
    input  wire [31:0] a,       // operand A (rs1, pc or 0)
    input  wire [31:0] b,       // operand B (rs2 or immediate); unused for shifts
    input  wire [3:0]  op,      // operation, see table in the header
    output reg  [31:0] result,  // operation result
    output wire        eq,      // a == b
    output wire        lt,      // signed a < b   (valid when subtracting)
    output wire        ltu      // unsigned a < b (valid when subtracting)
);

    // ---- Adder / subtractor --------------------------------------------------
    // sub = 1 for SUB (op 1000) and for the set-less-than ops (x010, x011),
    // which need a - b to derive the comparison.
    wire sub = (op == 4'b1000) | (op[2:1] == 2'b01);

    // b inverted for subtraction (two's complement = ~b + 1, the +1 is the
    // carry-in injected below).
    wire [31:0] b_x = b ^ {32{sub}};

    // 34-bit trick: the extra LSB pair (1 + sub) produces a carry INTO bit 1
    // exactly when sub = 1, i.e. it acts as the carry-in of the 32-bit add.
    // sum34[33] is the carry-out of the 32-bit operation.
    wire [33:0] sum34 = {1'b0, a, 1'b1} + {1'b0, b_x, sub};
    wire [31:0] sum   = sum34[32:1];    // a + b  or  a - b
    wire        cout  = sum34[33];      // carry-out (for a - b: 1 = no borrow)

    // Unsigned a < b  <=>  a - b borrows  <=>  carry-out = 0.
    assign ltu = ~cout;
    // Signed a < b: if the signs differ, a < b exactly when a is negative;
    // if the signs are equal, a - b cannot overflow, so the sign of the
    // difference decides.
    assign lt  = (a[31] ^ b[31]) ? a[31] : sum[31];

    // ---- Logic ops -------------------------------------------------------------
    wire [31:0] x_xor = a ^ b;
    assign eq = (x_xor == 32'd0);       // shared with XOR: equality = no bit differs

    // ---- Result multiplexer (selected by funct3 = op[2:0]) ------------------------
    always @(*) begin
        case (op[2:0])
            3'b000:  result = sum;                  // ADD / SUB
            3'b001:  result = a;                    // SLL: operand to the core shifter
            3'b010:  result = {31'd0, lt};          // SLT
            3'b011:  result = {31'd0, ltu};         // SLTU
            3'b100:  result = x_xor;                // XOR
            3'b101:  result = a;                    // SRL/SRA: operand to the core shifter
            3'b110:  result = a | b;                // OR
            default: result = a & b;                // AND (3'b111)
        endcase
    end

    // Intentionally unused bits, collected in a wire whose name matches
    // the default --unused-regexp "*unused*" of the Verilator linter (an idiom, no
    // lint_off pragma needed):
    //   sum34[0]   : the LSB of the carry-in trick (carries no result)
    wire alu_unused = &{1'b0, sum34[0]};

endmodule

`default_nettype wire
