`default_nettype none
`timescale 1ns / 1ps  // simulation only; keeps Icarus/Verilator timescale-consistent with the testbenches
// =============================================================================
// File        : design/rtl/cpu/rv32i_core.v
// Module      : rv32i_core
// Project     : SC-TPU + RV32I SoC on Sipeed Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Task        : RTL-CPU (RV32I multi-cycle CPU core)
// Author      : fpga-engineer (Claude Code specialist)
//
// PURPOSE
//   Small multi-cycle RV32I CPU that orchestrates the SC-TPU (ADR-004: the
//   multi-cycle micro-architecture leaves the most area for the TPU).
//   Implements the 37 RV32I base instructions + FENCE (as NOP); ECALL,
//   EBREAK, illegal instructions and misaligned fetch targets / loads /
//   stores HALT the core with a cause code. No CSRs, no interrupts.
//
// SUB-MODULES
//   rv32i_decode  (rv32i_decode.v)  combinational decoder of `ir`
//   rv32i_alu     (rv32i_alu.v)     combinational ALU (one adder, no shifter;
//                                   shifts are iterated in the SHIFT state)
//   rv32i_regfile (rv32i_regfile.v) 32x32 register file in 2 BSRAM blocks,
//                                   synchronous read, 1-cycle latency
//
// -----------------------------------------------------------------------------
// INTERFACES
//   clk, rst          27 MHz clock; synchronous active-high reset (from the
//                     2-FF synchroniser in the top level, ARCHITECTURE.md 2).
//   Native valid/ready memory bus (ARCHITECTURE.md 3, INTERFACES.json "bus"):
//   mem_valid  out    request active. Held high, with mem_instr/addr/wdata/
//                     wstrb STABLE, until mem_ready is seen; dropped in the
//                     cycle after mem_ready unless the next request starts
//                     right away (store -> next fetch).
//   mem_instr  out    1 = instruction fetch (debug only).
//   mem_addr   out    byte address. Fetches and word accesses are word
//                     aligned; byte/halfword accesses carry the true byte
//                     address (slaves decode addr[11:2] and use mem_wstrb).
//                     Misaligned accesses NEVER reach the bus: they are
//                     detected in EXECUTE and trap before MEM is entered.
//   mem_wdata  out    store data REPLICATED to all byte lanes (SB: 4 copies of
//                     the byte, SH: 2 copies of the half), so every enabled lane
//                     carries the right byte without a shifter.
//   mem_wstrb  out    byte enables; 0000 = read (fetch and loads).
//                     SB: 0001 << addr[1:0]; SH: addr[1] ? 1100 : 0011; SW: 1111.
//   mem_ready  in     one-cycle completion pulse (only while mem_valid).
//                     May be asserted in the FIRST cycle of mem_valid (zero
//                     wait states) or any number of cycles later.
//   mem_rdata  in     read data, sampled only when mem_ready = 1. Load data is
//                     extracted from the lane given by addr[1:0] and sign/zero
//                     extended (LB/LH/LBU/LHU), LW takes the whole word.
//   Debug (INTERFACES.json "cpu.debug_ports"):
//   halted     out    1 after a trap (stays 1 until rst).
//   trap_cause out    [3:0] 0 none, 1 ECALL, 2 EBREAK, 3 illegal, 4 misaligned
//                     fetch (taken branch / JAL / JALR target with bit 1 set),
//                     5 misaligned load, 6 misaligned store.
//   dbg_pc     out    [31:0] PC of the instruction being executed; after a trap
//                     it is the PC of the trapping instruction.
//   retire     out    one-cycle pulse (registered) in the cycle AFTER an
//                     instruction completed; a trapping instruction does not
//                     retire. Count of pulses = instructions executed.
//
// -----------------------------------------------------------------------------
// FSM (state register `state`)
//
//      rst
//       |
//       v
//   +-------+  32 cycles: x[ir[11:7]] <= 0, ir[11:7]++ (x0..x31 cleared)
//   | CLEAR |---+
//   +-------+   | ir[11:7] == 31
//               v
//   +-------+ !mem_ready (wait)    mem_valid=1 mem_instr=1 mem_addr=pc
//   | FETCH |<----------------+    on mem_ready: ir <= mem_rdata
//   +-------+                 |
//       | mem_ready           |
//       v                     |
//   +--------+  regfile read (rs1,rs2) issued; alu_q <= pc + imm (or 0 + imm
//   | DECODE |  for LUI). ECALL/EBREAK/illegal -------------------> HALT
//   +--------+-------------------------------+
//       | other                              | LUI, AUIPC, JAL, FENCE
//       v                                    |
//   +---------+  ALU on rs1/rs2/imm           |
//   | EXECUTE |-- BRANCH: pc <= taken ? alu_q : pc+4, retire ----> FETCH
//   +---------+   (taken target bit 1 set ------------------------> HALT 4)
//       |   |---- LOAD/STORE: alu_q <= rs1+imm; misaligned -------> HALT 5/6
//       |   |                                     else --> MEM
//       |   |---- SLL/SRL/SRA(I): alu_q <= rs1, shamt_q <= amount
//       |   |         amount 0 --------------------------------+
//       |   |         else --> SHIFT                           |
//       |   +---- other OP, OP-IMM, JALR: alu_q <= result -----+
//       |                                                      |
//       |   +-------+ alu_q shifted by 4 (shamt_q >= 4) or 1;  |
//       |   | SHIFT |<-+ shamt_q -= step; stay while > 0 ------+ (0 -> WB)
//       |   +-------+--+                                       |
//       v                                                    |
//   +-----+ !mem_ready (wait)  mem_valid=1 mem_addr=alu_q     |
//   | MEM |<---+               on mem_ready: LOAD alu_q <= load data -> WB
//   +-----+----+                             STORE pc <= pc+4, retire -> FETCH
//       | LOAD                                               |
//       v                                                    v
//   +----+  rd <= (JAL|JALR) ? pc+4 : alu_q  (if writes_rd and rd != 0)
//   | WB |  pc <= (JAL|JALR) ? {alu_q[31:1],0} : pc+4, retire -> FETCH
//   +----+  (JAL/JALR target with alu_q[1] = 1 --------------------> HALT 4)
//
//   +------+
//   | HALT |  terminal until rst; halted = 1, trap_cause holds the cause,
//   +------+  dbg_pc = PC of the trapping instruction, no bus activity.
//
// CYCLES PER INSTRUCTION (CALCULATION, zero bus wait states, i.e. mem_ready
// in the first mem_valid cycle; add the slave wait states of every access)
//   LUI AUIPC JAL FENCE : FETCH DECODE WB                  = 3
//   BRANCH (any outcome): FETCH DECODE EXECUTE             = 3
//   OP OP-IMM JALR      : FETCH DECODE EXECUTE WB          = 4  (non-shift)
//   SLL/SRL/SRA(I) by n : 4 + floor(n/4) + (n mod 4)         = 4 .. 14
//   STORE               : FETCH DECODE EXECUTE MEM         = 4
//   LOAD                : FETCH DECODE EXECUTE MEM WB      = 5
//   After reset: 32 CLEAR cycles before the first FETCH.
//
// -----------------------------------------------------------------------------
// DATAPATH REGISTERS
//   pc      [31:0] program counter; pc[1:0] is always 00 by construction
//                  (every target with bit 1 set traps, bit 0 is cleared).
//   ir      [31:0] instruction register (loaded at the end of FETCH); during
//                  CLEAR its rd field ir[11:7] doubles as the clear counter so
//                  the register-file write address needs no extra mux.
//   alu_q   [31:0] the one temporary register: branch/JAL target or AUIPC/LUI
//                  value (DECODE), ALU result or memory address (EXECUTE),
//                  load data (MEM), shifted operand (SHIFT). It feeds rd in
//                  WB, mem_addr in MEM and
//                  the jump target in WB/EXECUTE.
//   rs1_q, rs2_q   register-file read data (BSRAM output registers, held
//                  from the DECODE edge until the next DECODE).
//   shamt_q [4:0]  remaining shift amount in the SHIFT state.
//   state, trap_q, retire_q
//
// DESIGN DECISIONS (area / timing)
//   * Register file in BSRAM (see rv32i_regfile.v): 0 LUT, 0 DFF for the 1 kbit
//     of architectural state; costs the CLEAR state (32 cycles after reset)
//     because a RAM cannot be reset in one cycle.
//   * A single ALU adder computes everything; the branch target is computed
//     in DECODE (when the operands are still being read from the BSRAM) so
//     the compare in EXECUTE can reuse the same adder. Only pc+4 has its own
//     30-bit incrementer (needed in the same cycle as the ALU for JAL/JALR
//     links, branches and stores).
//   * Store data replicated to all lanes instead of shifted (no barrel mux).
//   * No barrel shifter: shifts are done in alu_q by 4 or 1 bit per cycle
//     (SHIFT state). A Yosys/Gowin barrel shifter costs ~450 LUT/MUX cells
//     (measured, see rv32i_alu.v); the iterative one ~3 LUT per bit, at the
//     price of up to 10 extra cycles per shift instruction.
//
// TIMING (27 MHz, 37.0 ns period)
//   Longest paths (by construction): rs1/rs2 BSRAM output -> operand-B mux
//   -> ALU (33-bit carry chain) -> alu_q / misalignment
//   check -> state; ir -> immediate mux -> ALU -> alu_q. The memory bus
//   outputs are driven by registers through one 2:1 mux (mem_addr) or
//   directly (wdata lanes, wstrb from alu_q[1:0] and funct3).
//   mem_rdata -> ir and mem_rdata -> load-extract -> alu_q are the only
//   paths from the bus inputs.
//
// PARAMETERS
//   none (reset PC fixed at 0x0000_0000 by INTERFACES.json "cpu.reset_pc").
//
// ASSUMPTIONS
//   * ECALL/EBREAK do not retire (they trap like an exception); dbg_pc points
//     at them. Same for every other trap.
//   * A taken branch / JAL / JALR whose target has bit 1 set traps with cause
//     4 (RISC-V: instruction-address-misaligned is raised by the jump/branch,
//     rd is NOT written). A not-taken branch never traps.
//   * FENCE with funct3 000 is a NOP whatever its other fields are; FENCE.I
//     (funct3 001, Zifencei) is not part of RV32I and is illegal.
//
// REQUIREMENT REFERENCES
//   ARCHITECTURE.md sections 2 (clock/reset), 3 (bus), 6 (CPU);
//   INTERFACES.json "bus" and "cpu".
// =============================================================================

module rv32i_core (
    input  wire        clk,         // 27 MHz core clock
    input  wire        rst,         // synchronous, active-high reset
    // ---- native valid/ready memory bus (CPU = master) --------------------------
    output wire        mem_valid,   // request active
    output wire        mem_instr,   // request is an instruction fetch
    output wire [31:0] mem_addr,    // byte address
    output wire [31:0] mem_wdata,   // store data, replicated to the byte lanes
    output wire [3:0]  mem_wstrb,   // byte write enables, 0000 = read
    input  wire        mem_ready,   // completion pulse
    input  wire [31:0] mem_rdata,   // read data (valid with mem_ready)
    // ---- debug ----------------------------------------------------------------
    output wire        halted,      // core stopped by a trap
    output wire [3:0]  trap_cause,  // 0 none 1 ecall 2 ebreak 3 illegal 4/5/6 misaligned
    output wire [31:0] dbg_pc,      // current / trapping PC
    output wire        retire       // 1-cycle pulse after each completed instruction
);

    // =========================================================================
    // State encoding (binary; Yosys may re-encode)
    // =========================================================================
    localparam [2:0] S_CLEAR  = 3'd0;   // clear x0..x31 after reset (32 cycles)
    localparam [2:0] S_FETCH  = 3'd1;   // bus read of the instruction at pc
    localparam [2:0] S_DECODE = 3'd2;   // regfile read, pc+imm, trap decode
    localparam [2:0] S_EXEC   = 3'd3;   // ALU, branch resolve, address + alignment
    localparam [2:0] S_MEM    = 3'd4;   // load / store bus access
    localparam [2:0] S_WB     = 3'd5;   // register write, pc update
    localparam [2:0] S_HALT   = 3'd6;   // trapped, terminal until reset
    localparam [2:0] S_SHIFT  = 3'd7;   // iterative shift of alu_q

    // Trap cause codes (INTERFACES.json "cpu.traps").
    localparam [3:0] T_NONE   = 4'd0;
    localparam [3:0] T_ECALL  = 4'd1;
    localparam [3:0] T_EBREAK = 4'd2;
    localparam [3:0] T_ILLEGAL= 4'd3;
    localparam [3:0] T_MISF   = 4'd4;   // misaligned fetch (jump/branch target)
    localparam [3:0] T_MISL   = 4'd5;   // misaligned load
    localparam [3:0] T_MISS   = 4'd6;   // misaligned store

    // =========================================================================
    // Registers
    // =========================================================================
    reg [2:0]  state;       // FSM state
    reg [31:0] pc;          // program counter (pc[1:0] always 00)
    reg [31:0] ir;          // instruction register / CLEAR counter in ir[11:7]
    reg [31:0] alu_q;       // temporary: target / result / address / load data
    reg [3:0]  trap_q;      // trap cause (0 until a trap)
    reg        retire_q;    // registered retire pulse
    reg [4:0]  shamt_q;     // remaining shift amount (SHIFT state)

    // =========================================================================
    // Decoder (combinational, from ir)
    // =========================================================================
    wire        d_lui, d_auipc, d_jal, d_jalr, d_branch, d_load, d_store;
    wire        d_fence, d_ecall, d_ebreak, d_illegal;
    wire [31:0] d_imm;
    wire        d_b_is_imm;
    wire [3:0]  d_alu_op;
    wire        d_writes_rd;
    wire [4:0]  d_rs1, d_rs2, d_rd;
    wire [2:0]  d_funct3;

    rv32i_decode u_decode (
        .ir        (ir),
        .is_lui    (d_lui),
        .is_auipc  (d_auipc),
        .is_jal    (d_jal),
        .is_jalr   (d_jalr),
        .is_branch (d_branch),
        .is_load   (d_load),
        .is_store  (d_store),
        .is_fence  (d_fence),
        .is_ecall  (d_ecall),
        .is_ebreak (d_ebreak),
        .illegal   (d_illegal),
        .imm       (d_imm),
        .b_is_imm  (d_b_is_imm),
        .alu_op    (d_alu_op),
        .writes_rd (d_writes_rd),
        .rs1       (d_rs1),
        .rs2       (d_rs2),
        .rd        (d_rd),
        .funct3    (d_funct3)
    );

    // JAL and JALR are the only instructions whose rd gets pc+4 and whose
    // target is applied in WB.
    wire is_jump = d_jal | d_jalr;

    // =========================================================================
    // Register file (BSRAM, 1-cycle synchronous read)
    // =========================================================================
    wire [31:0] rs1_q, rs2_q;   // operands, valid from EXECUTE on

    // Write port control:
    //   CLEAR : write 0 to x[ir[11:7]] (counter), x0 included.
    //   WB    : write rd if the instruction writes rd, rd != 0 (x0 hard-wired)
    //           and a JAL/JALR target is not misaligned (trapping jumps must
    //           leave rd unchanged).
    wire wb_trap_misf = is_jump & (alu_q[1] | (d_jalr & alu_q[0]));
    wire rf_we = (state == S_CLEAR) |
                 ((state == S_WB) & d_writes_rd & (d_rd != 5'd0) & ~wb_trap_misf);

    // pc + 4: dedicated incrementer (pc[1:0] = 00, so only bits 31:2 count).
    wire [31:0] pc_plus4 = {pc[31:2] + 30'd1, 2'b00};

    // Write data mux: 0 during CLEAR, the link pc+4 for JAL/JALR, else alu_q
    // (ALU result, LUI/AUIPC value or load data).
    wire [31:0] rf_wdata = (state == S_CLEAR) ? 32'd0 :
                           is_jump            ? pc_plus4 : alu_q;

    rv32i_regfile u_regfile (
        .clk      (clk),
        .rd_en    (state == S_DECODE),   // read only in DECODE -> outputs held
        .rd1_addr (d_rs1),
        .rd2_addr (d_rs2),
        .rd1_data (rs1_q),
        .rd2_data (rs2_q),
        .wr_en    (rf_we),
        .wr_addr  (d_rd),                // = ir[11:7]: rd in WB, counter in CLEAR
        .wr_data  (rf_wdata)
    );

    // =========================================================================
    // ALU and its operand multiplexers
    // =========================================================================
    // Operand A: DECODE -> pc (target / AUIPC) or 0 (LUI); EXECUTE -> rs1.
    // Operand B: DECODE -> imm;  EXECUTE -> imm or rs2 (decoder b_is_imm).
    // Operation: DECODE -> ADD;  EXECUTE -> decoder alu_op.
    wire        in_decode = (state == S_DECODE);
    wire [31:0] alu_a  = in_decode ? (d_lui ? 32'd0 : pc) : rs1_q;
    wire [31:0] alu_b  = (in_decode | d_b_is_imm) ? d_imm : rs2_q;
    wire [3:0]  alu_op = in_decode ? 4'b0000 : d_alu_op;
    wire [31:0] alu_y;
    wire        alu_eq, alu_lt, alu_ltu;

    rv32i_alu u_alu (
        .a      (alu_a),
        .b      (alu_b),
        .op     (alu_op),
        .result (alu_y),
        .eq     (alu_eq),
        .lt     (alu_lt),
        .ltu    (alu_ltu)
    );

    // Branch condition from funct3 (B-type):
    //   000 BEQ eq   001 BNE !eq   100 BLT lt   101 BGE !lt
    //   110 BLTU ltu 111 BGEU !ltu  (bit 0 inverts the base condition)
    wire br_base  = d_funct3[2] ? (d_funct3[1] ? alu_ltu : alu_lt) : alu_eq;
    wire br_taken = br_base ^ d_funct3[0];

    // =========================================================================
    // Load / store lane handling
    // =========================================================================
    // Access size from funct3[1:0]: 00 byte, 01 half, 10 word.
    // Alignment check on the EFFECTIVE ADDRESS while it is computed (EXECUTE,
    // alu_y = rs1 + imm), so a misaligned access traps BEFORE MEM and never
    // appears on the bus.
    wire [1:0] ea_lo      = alu_y[1:0];
    wire       misaligned = ((d_funct3[1:0] == 2'b01) & ea_lo[0]) |           // half
                            ((d_funct3[1:0] == 2'b10) & (ea_lo != 2'b00));     // word

    // In MEM the address is in alu_q; its low bits steer the lanes.
    wire [1:0] ma_lo = alu_q[1:0];

    // Store byte enables (only used in MEM for stores).
    reg [3:0] st_strb;
    always @(*) begin
        case (d_funct3[1:0])
            2'b00:   st_strb = 4'b0001 << ma_lo;                  // SB
            2'b01:   st_strb = ma_lo[1] ? 4'b1100 : 4'b0011;      // SH
            default: st_strb = 4'b1111;                           // SW
        endcase
    end

    // Store data replicated to the lanes (rs2 is held stable by the regfile):
    //   lane0 [7:0]  : rs2[7:0] always
    //   lane1 [15:8] : SB -> rs2[7:0]   else rs2[15:8]
    //   lane2 [23:16]: SW -> rs2[23:16] else rs2[7:0]   (SH lane2 = low byte of half)
    //   lane3 [31:24]: SB -> rs2[7:0]   SH -> rs2[15:8]  SW -> rs2[31:24]
    wire st_b = (d_funct3[1:0] == 2'b00);
    wire st_w = (d_funct3[1:0] == 2'b10);
    wire [31:0] st_data = {
        st_b ? rs2_q[7:0] : (st_w ? rs2_q[31:24] : rs2_q[15:8]),
        st_w ? rs2_q[23:16] : rs2_q[7:0],
        st_b ? rs2_q[7:0] : rs2_q[15:8],
        rs2_q[7:0]
    };

    // Load data extraction (MEM, valid with mem_ready):
    //   ld_byte : byte lane selected by addr[1:0]
    //   ld_half : half selected by addr[1] (alignment already guaranteed)
    //   sign    : MSB of the loaded byte/half, used unless funct3[2] (LBU/LHU)
    reg  [7:0]  ld_byte;
    always @(*) begin
        case (ma_lo)
            2'b00:   ld_byte = mem_rdata[7:0];
            2'b01:   ld_byte = mem_rdata[15:8];
            2'b10:   ld_byte = mem_rdata[23:16];
            default: ld_byte = mem_rdata[31:24];
        endcase
    end
    wire [15:0] ld_half = ma_lo[1] ? mem_rdata[31:16] : mem_rdata[15:0];
    wire        ld_is_b = (d_funct3[1:0] == 2'b00);
    wire        ld_is_w = (d_funct3[1:0] == 2'b10);
    wire        ld_sign = ~d_funct3[2] & (d_funct3[0] ? ld_half[15] : ld_byte[7]);
    // For LW, ld_half = mem_rdata[15:0] because addr[1] = 0 (aligned).
    wire [31:0] ld_data = {
        ld_is_w ? mem_rdata[31:16] : {16{ld_sign}},
        ld_is_b ? {8{ld_sign}} : ld_half[15:8],
        ld_is_b ? ld_byte : ld_half[7:0]
    };

    // =========================================================================
    // Iterative shifter (EXECUTE loads alu_q, SHIFT steps it)
    // =========================================================================
    // Shift instructions are OP / OP-IMM with funct3 = 001 (SLL) or 101
    // (SRL/SRA); in EXECUTE the ALU passes rs1 through (rv32i_alu.v) and the
    // amount is operand B [4:0] (imm[4:0] = shamt for the I-form, rs2[4:0]
    // for the R-form; the upper bits are ignored as RV32I requires).
    wire       is_shift  = (d_funct3[1:0] == 2'b01) & ~d_branch & ~d_load & ~d_store & ~is_jump;
    wire [4:0] shamt_new = alu_b[4:0];
    // Direction: funct3[2] = 0 left (SLL), 1 right. SRA: instr[30] = 1, the
    // vacated bits get the sign bit.
    wire       sh_right  = d_funct3[2];
    wire       sh_fill   = ir[30] & alu_q[31];
    wire       sh_by4    = (shamt_q[4:2] != 3'b000);           // >= 4 remaining
    wire [31:0] sh_step  = sh_right ?
                           (sh_by4 ? {{4{sh_fill}}, alu_q[31:4]} : {sh_fill, alu_q[31:1]}) :
                           (sh_by4 ? {alu_q[27:0], 4'b0000}      : {alu_q[30:0], 1'b0});
    wire [4:0] shamt_nxt = shamt_q - (sh_by4 ? 5'd4 : 5'd1);

    // =========================================================================
    // Bus outputs (combinational from registers; stable while waiting)
    // =========================================================================
    wire in_fetch = (state == S_FETCH);
    wire in_mem   = (state == S_MEM);
    assign mem_valid = in_fetch | in_mem;
    assign mem_instr = in_fetch;
    assign mem_addr  = in_fetch ? pc : alu_q;
    assign mem_wdata = st_data;   // don't care on reads (wstrb = 0)
    assign mem_wstrb = (in_mem & d_store) ? st_strb : 4'b0000;

    // =========================================================================
    // FSM and datapath register updates
    // =========================================================================
    always @(posedge clk) begin
        if (rst) begin
            state    <= S_CLEAR;
            pc       <= 32'd0;          // INTERFACES.json cpu.reset_pc
            ir       <= 32'd0;          // ir[11:7] = clear counter starts at 0
            alu_q    <= 32'd0;
            trap_q   <= T_NONE;
            retire_q <= 1'b0;
            shamt_q  <= 5'd0;
        end else begin
            retire_q <= 1'b0;           // default: no retire this cycle
            case (state)
                // -------------------------------------------------------------
                // CLEAR: x[ir[11:7]] <= 0 (via rf_we/rf_wdata); count 0..31.
                S_CLEAR: begin
                    ir[11:7] <= ir[11:7] + 5'd1;
                    if (ir[11:7] == 5'd31)
                        state <= S_FETCH;
                end
                // -------------------------------------------------------------
                // FETCH: wait for the instruction word.
                S_FETCH: begin
                    if (mem_ready) begin
                        ir    <= mem_rdata;
                        state <= S_DECODE;
                    end
                end
                // -------------------------------------------------------------
                // DECODE: the regfile read happens at this edge (rd_en); the
                // ALU computes pc+imm / 0+imm into alu_q; traps are detected.
                S_DECODE: begin
                    alu_q <= alu_y;
                    if (d_ecall) begin
                        trap_q <= T_ECALL;   state <= S_HALT;
                    end else if (d_ebreak) begin
                        trap_q <= T_EBREAK;  state <= S_HALT;
                    end else if (d_illegal) begin
                        trap_q <= T_ILLEGAL; state <= S_HALT;
                    end else if (d_lui | d_auipc | d_jal | d_fence) begin
                        state <= S_WB;       // value/target already in alu_q
                    end else begin
                        state <= S_EXEC;     // needs rs1/rs2 (JALR, BRANCH, LOAD, STORE, ALU)
                    end
                end
                // -------------------------------------------------------------
                // EXECUTE: operands rs1_q/rs2_q are valid now.
                S_EXEC: begin
                    if (d_branch) begin
                        // alu_q still holds the target from DECODE; the ALU
                        // output (rs1 - rs2) is used only for the flags.
                        if (br_taken & alu_q[1]) begin
                            trap_q <= T_MISF;  state <= S_HALT;
                        end else begin
                            pc       <= br_taken ? {alu_q[31:2], 2'b00} : pc_plus4;
                            retire_q <= 1'b1;
                            state    <= S_FETCH;
                        end
                    end else if (d_load | d_store) begin
                        alu_q <= alu_y;              // effective address
                        if (misaligned) begin
                            trap_q <= d_load ? T_MISL : T_MISS;
                            state  <= S_HALT;
                        end else begin
                            state  <= S_MEM;
                        end
                    end else if (is_shift) begin
                        alu_q   <= alu_y;            // = rs1 (ALU pass-through)
                        shamt_q <= shamt_new;
                        state   <= (shamt_new == 5'd0) ? S_WB : S_SHIFT;
                    end else begin
                        alu_q <= alu_y;              // OP / OP-IMM result, JALR target
                        state <= S_WB;
                    end
                end
                // -------------------------------------------------------------
                // SHIFT: one step of 4 or 1 bit(s) per cycle until done.
                S_SHIFT: begin
                    alu_q   <= sh_step;
                    shamt_q <= shamt_nxt;
                    if (shamt_nxt == 5'd0)
                        state <= S_WB;
                end
                // -------------------------------------------------------------
                // MEM: one load or store transaction at alu_q.
                S_MEM: begin
                    if (mem_ready) begin
                        if (d_load) begin
                            alu_q <= ld_data;        // written to rd in WB
                            state <= S_WB;
                        end else begin
                            pc       <= pc_plus4;    // store complete
                            retire_q <= 1'b1;
                            state    <= S_FETCH;
                        end
                    end
                end
                // -------------------------------------------------------------
                // WB: rd written by rf_we/rf_wdata at this edge; pc update.
                S_WB: begin
                    if (wb_trap_misf) begin
                        trap_q <= T_MISF;            // JAL/JALR target bit 1 set
                        state  <= S_HALT;
                    end else begin
                        // JALR: bit 0 of the target is cleared; bit 1 is 0 here.
                        pc       <= is_jump ? {alu_q[31:2], 2'b00} : pc_plus4;
                        retire_q <= 1'b1;
                        state    <= S_FETCH;
                    end
                end
                // -------------------------------------------------------------
                // HALT (S_HALT; all 8 encodings are used, so default = HALT):
                // stay, no bus activity.
                default: begin
                    state <= S_HALT;
                end
            endcase
        end
    end

    // =========================================================================
    // Debug outputs
    // =========================================================================
    assign halted     = (state == S_HALT);
    assign trap_cause = trap_q;
    assign dbg_pc     = pc;
    assign retire     = retire_q;

endmodule

`default_nettype wire
