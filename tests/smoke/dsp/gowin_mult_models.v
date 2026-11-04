// =============================================================================
// File      : tests/smoke/dsp/gowin_mult_models.v
// Purpose   : Behavioural SIMULATION model of the Gowin MULT9X9 primitive, for
//             post-synthesis (gate-level) simulation of netlists produced by
//             Yosys `synth_gowin` (tasks ST-FPGA-02, RTL-DET-1).
//             yowasp-yosys ships MULT9X9 only as a black-box stub
//             (share/gowin/cells_xtra_gw1n.v: ports + parameters, no body),
//             so a gate-level simulation needs this hand-written model
//             (rtl-gowin-flow lesson RTL-CPU: "No behavioural BSRAM model
//             ships with yowasp-yosys").
//
// MODELLED BEHAVIOUR (ASSUMPTION - from the port/parameter names of the stub
// and the way +/gowin/dsp_map.v drives them; NOT validated against the Gowin
// silicon or the vendor simulation library):
//   * ASEL = 0 selects port A, ASEL = 1 the shift-in SIA (same for B/BSEL).
//   * ASIGN / BSIGN = 1: the operand is a 9-bit two's-complement number,
//     0: unsigned.  DOUT = full 18-bit product (exact for every 9x9 input).
//   * AREG/BREG/OUT_REG/PIPE_REG/ASIGN_REG/BSIGN_REG/SOA_REG = 0 (the only
//     configuration dsp_map.v generates): the primitive is purely
//     combinational and CLK/CE/RESET are unused.  Any other configuration is
//     NOT modelled: the model stops the simulation with $fatal so that a
//     netlist using internal registers can never pass silently.
//   * SOA/SOB (shift-out, cascade) = the selected A/B operand.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module MULT9X9 (A, SIA, B, SIB, ASIGN, BSIGN, ASEL, BSEL, CE, CLK, RESET, DOUT, SOA, SOB);
    input  wire [8:0]  A, SIA;
    input  wire [8:0]  B, SIB;
    input  wire        ASIGN, BSIGN;
    input  wire        ASEL, BSEL;
    input  wire        CE;
    input  wire        CLK;
    input  wire        RESET;
    output wire [17:0] DOUT;
    output wire [8:0]  SOA, SOB;
    parameter AREG = 1'b0;
    parameter BREG = 1'b0;
    parameter OUT_REG = 1'b0;
    parameter PIPE_REG = 1'b0;
    parameter ASIGN_REG = 1'b0;
    parameter BSIGN_REG = 1'b0;
    parameter SOA_REG = 1'b0;
    parameter MULT_RESET_MODE = "SYNC";

    initial begin
        if (AREG || BREG || OUT_REG || PIPE_REG || ASIGN_REG || BSIGN_REG || SOA_REG)
            $fatal(1, "MULT9X9 model: internal registers are not modelled (%m)");
    end

    wire [8:0] a_sel = ASEL ? SIA : A;
    wire [8:0] b_sel = BSEL ? SIB : B;
    // 10-bit extension: sign bit replicated when signed, 0 when unsigned, so
    // one signed 10x10 multiplication covers all four sign combinations.
    wire signed [9:0]  a_ext = {ASIGN & a_sel[8], a_sel};
    wire signed [9:0]  b_ext = {BSIGN & b_sel[8], b_sel};
    wire signed [19:0] prod  = a_ext * b_ext;
    assign DOUT = prod[17:0];
    assign SOA  = a_sel;
    assign SOB  = b_sel;

    // Unused in the combinational configuration (kept for port compatibility).
    wire unused_ok = &{1'b0, CE, CLK, RESET};
endmodule

`default_nettype wire
