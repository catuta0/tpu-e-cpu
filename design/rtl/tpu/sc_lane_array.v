// =============================================================================
// File      : design/rtl/tpu/sc_lane_array.v
// Module    : sc_lane_array
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Task      : RTL-TPU (fpga-engineer)
// Spec      : ARCHITECTURE.md rev A 5.1, 5.2 [BIT-EXACT], 5.3 step 1b
//             [BIT-EXACT]; INTERFACES.json tpu.sng / tpu.mult / tpu.accumulate;
//             ADR-001 (bipolar SC, XNOR + APC), ADR-002 (16x8 weight-stationary).
//
// PURPOSE
//   The stochastic multiply-accumulate array: NL neuron lanes x IL input lanes
//   (16 x 8 = 128 stochastic multipliers in rev A). Every stream cycle it
//   evaluates, for every neuron j,
//       acc_j += sum_{i=0}^{IL-1} XNOR( r_x(i) < x_i , r_w(i) < W[j][i] )
//   which is spec 5.3 step 1b literally.
//
// THEORY
//   1. Number format (5.2): code c in 0..255 <-> bipolar value
//      v = (c - 128)/128 in [-1, 127/128].
//   2. Stochastic number generator (SNG): b = (r < c) with r uniform on
//      0..255 gives P(b = 1) = c/256 = (v + 1)/2. One 8-bit magnitude
//      comparator per operand. The INPUT comparators (IL of them) are shared
//      by all NL neuron lanes (x_i is the same for every neuron: broadcast);
//      the WEIGHT comparators are one per weight (NL*IL of them) because each
//      weight is a different operand. Weights are "stationary": held in
//      registers for the L stream cycles of a tile (ADR-002).
//   3. Bipolar multiplication: for independent streams
//      P(XNOR = 1) = p_x p_w + (1 - p_x)(1 - p_w) = (1 + v_x v_w)/2,
//      so the XNOR of two bipolar streams is a bipolar stream of the product.
//   4. Accumulative parallel counter (APC): instead of a (lossy) stochastic
//      adder (MUX), the IL product bits of a neuron are counted exactly every
//      cycle (popcount, 0..IL) and accumulated in a binary register acc_j.
//      After L cycles over all tiles of a layer
//          E[2 acc_j - N_in L] = L * sum_i v(x_i) v(W_ji),
//      which the post-processor (sc_postproc.v) turns into the neuron output.
//
// INTERFACE / TIMING (all synchronous to clk, no reset needed: see clr)
//   clr    : 1 -> every acc_j <= 0 at the next edge (spec 5.3 step 1a; issued
//            by the controller at the start of each layer). Priority over en.
//   en     : 1 -> stream cycle: acc_j <= acc_j + popcount_j at the next edge.
//   w_tile : NL*IL weight codes; W[j][i] at bits [8*(j*IL+i) +: 8], which is
//            exactly the byte order of one tile in the weight RAM (5.5:
//            tile byte offset = j*IL + i), so the controller can shift words
//            in without any reordering.
//   x_tile : IL input codes, x_i at bits [8*i +: 8].
//   rx, rw : random numbers per input lane (from sc_rng.v), lane i at [8i+:8].
//   acc    : NL accumulators, acc_j at [AW*j +: AW], registered outputs.
//   Combinational depth per stream cycle (the TPU critical path candidate):
//     rw flop -> 8-bit compare (ALU carry chain) -> XNOR -> popcount
//     -> AW-bit add (ALU carry chain) -> acc flop. No internal pipeline:
//     the result of stream cycle k is in acc after its clock edge.
//
// PARAMETERS
//   NL : neuron lanes (16), IL : input lanes (8; 4 and 16 for the synthesis
//        study, must be a multiple of 4), AW : accumulator width. acc_j is at
//        most N_in*L = 64 * 2^10 = 65536 (CALCULATION, 5.3 with K <= 10), so
//        AW = 17 bits suffices and never wraps.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module sc_lane_array #(
    parameter integer NL = 16,
    parameter integer IL = 8,
    parameter integer AW = 17
) (
    input  wire               clk,
    input  wire               clr,
    input  wire               en,
    input  wire [NL*IL*8-1:0] w_tile,
    input  wire [IL*8-1:0]    x_tile,
    input  wire [IL*8-1:0]    rx,
    input  wire [IL*8-1:0]    rw,
    output wire [NL*AW-1:0]   acc
);

    // Popcount width: 0..IL needs clog2(IL+1) bits; 5 bits covers IL <= 31.
    localparam integer PW = 5;

    // -------------------------------------------------------------------------
    // popcount4: exact number of ones in 4 bits written as pure logic (no '+'),
    // so it maps to LUT4s and not to a chain of ALU carry cells. Wider
    // popcounts are built as a sum of these 4-bit chunks (IL/4 - 1 adders:
    // one 3-bit adder for IL = 8).
    // -------------------------------------------------------------------------
    function [2:0] popcount4;
        input [3:0] v;
        begin
            case (v)
                4'b0000:                                         popcount4 = 3'd0;
                4'b0001, 4'b0010, 4'b0100, 4'b1000:              popcount4 = 3'd1;
                4'b0011, 4'b0101, 4'b0110, 4'b1001, 4'b1010,
                4'b1100:                                         popcount4 = 3'd2;
                4'b0111, 4'b1011, 4'b1101, 4'b1110:              popcount4 = 3'd3;
                default:                                         popcount4 = 3'd4; // 4'b1111
            endcase
        end
    endfunction

    function [PW-1:0] popcount;
        input [IL-1:0] v;
        integer c;
        begin
            popcount = {PW{1'b0}};
            for (c = 0; c < IL / 4; c = c + 1)
                popcount = popcount + {{(PW-3){1'b0}}, popcount4(v[4*c +: 4])};
        end
    endfunction

    // -------------------------------------------------------------------------
    // Input-side SNGs: one comparator per input lane, broadcast to all
    // neuron lanes. bx[i] = (r_x(i) < x_i)   (spec 5.2 / 5.3 step 1b).
    // -------------------------------------------------------------------------
    wire [IL-1:0] bx;
    genvar i, j;
    generate
        for (i = 0; i < IL; i = i + 1) begin : g_xsng
            assign bx[i] = (rx[8*i +: 8] < x_tile[8*i +: 8]);
        end
    endgenerate

    // -------------------------------------------------------------------------
    // Per neuron lane j: IL weight SNGs, IL XNOR multipliers, one APC.
    // -------------------------------------------------------------------------
    generate
        for (j = 0; j < NL; j = j + 1) begin : g_neuron
            wire [IL-1:0] bw;    // weight stream bits of row j
            wire [IL-1:0] p;     // bipolar products (XNOR)
            reg  [AW-1:0] acc_r; // binary accumulator of the APC

            for (i = 0; i < IL; i = i + 1) begin : g_mult
                // Weight SNG: bw = (r_w(i) < W[j][i]); W[j][i] = tile byte j*IL+i.
                assign bw[i] = (rw[8*i +: 8] < w_tile[8*(j*IL + i) +: 8]);
                // Bipolar multiply: XNOR of the two streams (1 when equal).
                assign p[i]  = ~(bx[i] ^ bw[i]);
            end

            // APC: exact popcount of the IL products, accumulated in binary.
            // clr has priority so that a layer always starts from acc_j = 0
            // (spec 5.3 step 1a). acc_r has no reset: it is cleared by clr at
            // the start of every layer before it is ever read.
            always @(posedge clk) begin
                if (clr)
                    acc_r <= {AW{1'b0}};
                else if (en)
                    acc_r <= acc_r + {{(AW-PW){1'b0}}, popcount(p)};
            end

            assign acc[AW*j +: AW] = acc_r;
        end
    endgenerate

endmodule

`default_nettype wire
