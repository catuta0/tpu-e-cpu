`default_nettype none
`timescale 1ns / 1ps  // simulation only; keeps Icarus/Verilator timescale-consistent with the testbenches
// =============================================================================
// File        : design/rtl/cpu/rv32i_regfile.v
// Module      : rv32i_regfile
// Project     : SC-TPU + RV32I SoC on Sipeed Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Task        : RTL-CPU (RV32I multi-cycle CPU core)
// Author      : fpga-engineer (Claude Code specialist)
//
// PURPOSE
//   The 32 x 32-bit integer register file x0..x31 of the RV32I core, with two
//   read ports (rs1, rs2) and one write port (rd), implemented as INFERRED
//   BLOCK RAM (Gowin BSRAM) instead of 1024 flip-flops.
//
// IMPLEMENTATION CHOICE (area)  -- documented as required by RTL-CPU
//   A flip-flop register file would cost 992 DFF plus two 32-bit 32:1 read
//   multiplexers (~2 x 32 x 8 LUT4 + MUX2_LUT5..7 cells) plus a 5->32 write
//   decoder, i.e. roughly 10-15 % of the GW1NR-9 logic. Distributed RAM
//   (RAM16SDP4) would need 2 copies x 2 depth halves x 8 nibble slices = 32
//   RAM16SDP4 cells plus a depth mux. Block RAM costs ZERO LUTs/DFFs: two
//   18-kbit BSRAM blocks (out of 26 on the GW1NR-9), one per read port, each a
//   32-word x 32-bit simple-dual-port (SDP) RAM with identical write traffic.
//   (Each copy uses only 1 kbit of its 18-kbit block - BSRAM is plentiful on
//   this device, logic is not; see management/DECISIONS.md ADR-004.)
//
// READ LATENCY = 1 CLOCK (synchronous read, BSRAM output register)
//   rd1_data/rd2_data are the contents of the addressed registers sampled at
//   the rising edge on which rd_en = 1; they appear right after that edge and
//   are HELD (BSRAM clock-enable low) until the next edge with rd_en = 1.
//   The core asserts rd_en only in its DECODE state, so the operands stay
//   stable through EXECUTE / MEM / WRITEBACK (needed: rs2 is the store data
//   that must stay stable on mem_wdata while mem_valid && !mem_ready).
//
// READ-DURING-WRITE
//   The core never reads (DECODE) and writes (CLEAR / WRITEBACK) in the same
//   cycle, so the collision behaviour of the BSRAM is irrelevant. The
//   memory attribute no_rw_check tells Yosys so; without it Yosys emulates
//   read-first behaviour with bypass logic (measured: +72 DFF, ~130 LUT/MUX).
//   Mapped result (Yosys 0.70): 2 x SDPX9B, READ_MODE 0 (bypass = 1-cycle
//   latency), CEB = rd_en (output held while rd_en = 0), 0 LUT.
//
// x0 HANDLING
//   This module is a plain RAM: it does NOT know about x0. The core
//   (rv32i_core.v) guarantees x0 = 0 by (1) clearing all 32 entries, x0
//   included, after every reset (CLEAR state) and (2) never asserting wr_en
//   with wr_addr = 0 afterwards. Hence reading entry 0 always returns 0.
//
// RESET
//   A RAM cannot be reset in one cycle; the core's CLEAR state writes 0 into
//   all 32 entries during the 32 cycles that follow rst (ARCHITECTURE.md 6:
//   "registers reset to 0"). The `initial` block below only sets the
//   power-up / simulation start content to 0 as well (bitstream init).
//
// INTERFACES
//   clk      in   core clock (27 MHz)
//   rd_en    in   read enable: sample rd1_addr/rd2_addr at this edge
//   rd1_addr in   [4:0] rs1 index        rd1_data out [31:0] x[rs1] (1-cycle latency)
//   rd2_addr in   [4:0] rs2 index        rd2_data out [31:0] x[rs2] (1-cycle latency)
//   wr_en    in   write enable (x[wr_addr] <= wr_data at the rising edge)
//   wr_addr  in   [4:0] rd index
//   wr_data  in   [31:0] write data
//
// REQUIREMENT REFERENCES
//   ARCHITECTURE.md section 6 (RV32I, x0 hard-wired, registers reset to 0);
//   INTERFACES.json "cpu".
// =============================================================================

module rv32i_regfile (
    input  wire        clk,       // core clock
    input  wire        rd_en,     // read enable (DECODE state)
    input  wire [4:0]  rd1_addr,  // rs1 index
    input  wire [4:0]  rd2_addr,  // rs2 index
    output reg  [31:0] rd1_data,  // x[rs1], registered (BSRAM DO register)
    output reg  [31:0] rd2_data,  // x[rs2], registered (BSRAM DO register)
    input  wire        wr_en,     // write enable
    input  wire [4:0]  wr_addr,   // rd index
    input  wire [31:0] wr_data    // value to write
);

    // -------------------------------------------------------------------------
    // Two identical copies of the register array, one per read port. Both are
    // written with the same address/data, so they always hold the same values.
    // Attributes (Yosys memory_libmap):
    //   ram_style = "block" : map to block RAM (BSRAM). Without it Yosys picks
    //                         distributed RAM16SDP4 for such a small 1-kbit
    //                         memory (cost-based choice).
    //   no_rw_check         : read/write collisions on the same address never
    //                         happen (see header), so Yosys must NOT emulate
    //                         read-first behaviour. Verified during RTL-CPU:
    //                         without it Yosys adds 72 DFF + ~130 LUT/MUX of
    //                         bypass logic around the two SDPX9B cells; with it
    //                         the register file is exactly 2 SDPX9B, 0 LUT.
    //                         (Simulation semantics are unaffected.)
    // -------------------------------------------------------------------------
    (* ram_style = "block", no_rw_check *) reg [31:0] bank1 [0:31];
    (* ram_style = "block", no_rw_check *) reg [31:0] bank2 [0:31];

    // Power-up / simulation start content: all registers 0 (the CLEAR state of
    // the core re-establishes this after every reset).
    integer i;
    initial begin
        for (i = 0; i < 32; i = i + 1) begin
            bank1[i] = 32'd0;
            bank2[i] = 32'd0;
        end
        rd1_data = 32'd0;
        rd2_data = 32'd0;
    end

    // Write port (shared by both copies): one write per cycle at most.
    always @(posedge clk) begin
        if (wr_en) begin
            bank1[wr_addr] <= wr_data;
            bank2[wr_addr] <= wr_data;
        end
    end

    // Read ports: synchronous read with clock enable. Kept in a separate
    // always block from the write so Yosys treats a same-address collision as
    // "don't care" (it never happens, see header) and adds no bypass logic.
    always @(posedge clk) begin
        if (rd_en) begin
            rd1_data <= bank1[rd1_addr];
            rd2_data <= bank2[rd2_addr];
        end
    end

endmodule

`default_nettype wire
