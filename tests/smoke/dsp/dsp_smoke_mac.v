// =============================================================================
// File      : tests/smoke/dsp/dsp_smoke_mac.v
// Module    : dsp_smoke_mac   (smoke-test vehicle, NOT product RTL)
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Task      : ST-FPGA-02 (CR-001 plan step 1) - fpga-engineer
// Reqs      : CR-001 risk "open-source DSP support for GW1N-9C must be
//             smoke-tested first"; prepares REQ-RES-003 (DSP use) for rev D.
//
// PURPOSE
//   The smallest circuit that exercises exactly the arithmetic the DT-TPU
//   needs: a REGISTERED SIGNED 8 x 8 -> 16-bit multiply followed by an
//   accumulate.  It answers three toolchain questions:
//     1. Does Yosys 0.70 `synth_gowin` infer a Gowin DSP primitive
//        (MULT9X9 / MULT18X18 / MULTALU*) for `$signed(a) * $signed(b)`?
//     2. Does nextpnr-himbaechel-gowin place and route that primitive on the
//        GW1N-9C and time it?
//     3. Does Apicula gowin_pack accept the routed DSP cell (bitstream)?
//   Bit-exactness of the inferred netlist is checked by running the same
//   testbench on the post-synthesis netlist with a behavioural MULT9X9 model
//   (tests/smoke/dsp/gowin_mult_models.v) - see tests/smoke/dsp/run_dsp_smoke.sh.
//
// PIPELINE (one result per clock, latency 3 clocks from a/b to acc)
//   edge 0 : a_q <= a, b_q <= b, v1 <= en           (operand registers)
//   edge 1 : p_q <= a_q * b_q (signed, 16 bit), v2 <= v1
//   edge 2 : acc <= (clr ? 0 : acc) + (v2 ? p_q : 0)
//   The operand and product registers are deliberately SEPARATE flops in the
//   RTL: Yosys' Gowin DSP mapping (+/gowin/dsp_map.v) instantiates the
//   multiplier combinationally (AREG = BREG = OUT_REG = 0), so these flops
//   stay as fabric DFFs around the DSP and the timing report shows the
//   register -> DSP -> register path.
//
// ARITHMETIC
//   a, b in -128..127 (int8 two's complement).  Product range:
//   min = -128 * 127 = -16256, max = (-128) * (-128) = +16384 = 2^14, so a
//   16-bit signed product (range -32768..32767) is exact.  The accumulator is
//   ACC_W bits (default 24): it is exact for up to
//   floor((2^23 - 1) / 2^14) = 511 maximal products.
//
// PARAMETERS
//   ACC_W  accumulator width (>= 16).
// ASSUMPTIONS
//   Synchronous active-high reset `rst` (ARCHITECTURE.md 2).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module dsp_smoke_mac #(
    parameter integer ACC_W = 24
) (
    input  wire              clk,
    input  wire              rst,
    input  wire              en,     // a/b valid this cycle -> accumulate it
    input  wire              clr,    // clear acc (applied together with the
                                     // product that reaches acc in that cycle)
    input  wire signed [7:0] a,
    input  wire signed [7:0] b,
    output reg  signed [15:0] p_q,   // registered product (latency 2)
    output reg  signed [ACC_W-1:0] acc // running sum (latency 3)
);

    // Operand registers: isolate the DSP from the input logic so the measured
    // path is FF -> multiplier -> FF (the same structure the DT-TPU uses).
    reg signed [7:0] a_q, b_q;
    reg              v1, v2;         // valid flags travelling with the data
    reg              c1, c2;         // clear flags travelling with the data

    always @(posedge clk) begin
        if (rst) begin
            a_q <= 8'sd0;  b_q <= 8'sd0;
            v1  <= 1'b0;   c1  <= 1'b0;
        end else begin
            a_q <= a;      b_q <= b;
            v1  <= en;     c1  <= clr;
        end
    end

    // Product register.  `a_q * b_q` with both operands declared signed is a
    // signed multiplication in Verilog-2005 (both operands signed -> signed
    // context); the 16-bit result width is exact (see ARITHMETIC).
    always @(posedge clk) begin
        if (rst) begin
            p_q <= 16'sd0;
            v2  <= 1'b0;
            c2  <= 1'b0;
        end else begin
            p_q <= a_q * b_q;
            v2  <= v1;
            c2  <= c1;
        end
    end

    // Accumulator: the product is sign-extended to ACC_W bits explicitly
    // ({{..{p_q[15]}}, p_q}) so the width extension cannot silently become a
    // zero-extension if a signed/unsigned mix is introduced later.
    wire signed [ACC_W-1:0] p_ext = {{(ACC_W-16){p_q[15]}}, p_q};
    wire signed [ACC_W-1:0] acc_base = c2 ? {ACC_W{1'b0}} : acc;

    always @(posedge clk) begin
        if (rst)     acc <= {ACC_W{1'b0}};
        else if (v2) acc <= acc_base + p_ext;
        else         acc <= acc_base;
    end

endmodule

`default_nettype wire
