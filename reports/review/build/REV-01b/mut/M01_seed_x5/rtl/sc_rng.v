// =============================================================================
// File      : design/rtl/tpu/sc_rng.v
// Module    : sc_rng
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Reqs      : requirements/REQUIREMENTS.md REQ-TPU-005, REQ-TPU-006 (RNG modes)
// Task      : RTL-TPU (rev A), RTL-SOC (rev B, then rev C seed update) - fpga-engineer
// Spec      : ARCHITECTURE.md 5.3 [BIT-EXACT] (RNG, RNG_MODE) as amended by
//             section 12 (REV C, ADR-010: CURRENT seed tables, default mode 2;
//             supersedes the seed text of 5.3 and of section 11 / rev B);
//             INTERFACES.json rev C tpu.lfsr / tpu.rng_modes; ADR-003, ADR-005.
//
// PURPOSE
//   Random-number source of the SC-TPU. Produces, for every input lane
//   i = 0..IL-1, the 8-bit random number r_x(i) used by the INPUT-side
//   stochastic number generator (SNG) of lane i, and r_w(i) used by ALL the
//   weight-side SNGs of column i (weights W[j][i], j = 0..NL-1).
//
// THEORY: why there are three modes (ADR-003)
//   Bipolar SC multiplication p = XNOR(b_x, b_w) is unbiased only if the two
//   streams are statistically independent: E[p] = (1 + v_x v_w)/2 requires
//   P(b_x = 1, b_w = 1) = P(b_x = 1) P(b_w = 1). Therefore x and w ALWAYS use
//   different LFSRs (LFSR_X / LFSR_W). Across lanes, the APC sums IL products;
//   if every lane uses the same r, the lane errors are fully correlated and do
//   not average out. The three modes trade area for decorrelation:
//     0 SHARED      : one LFSR_X + one LFSR_W; every lane uses the same
//                     r_x / r_w.                                  (cheapest)
//     1 ROTATE      : same two LFSRs; lane i uses rotl8(r, i). A bit rotation
//                     is free wiring, keeps each r uniform, and changes the
//                     ordering relation between lanes (partial decorrelation).
//     2 INDEPENDENT : IL LFSR_X_i and IL LFSR_W_i.     (largest; REV B DEFAULT)
//   In mode 1 the rotation amount is the LANE index i (0..IL-1), reading A1
//   of the golden model; for IL > 8 the rotation is taken mod 8 (rotl8 by 8
//   is the identity), identical to code/python/sctpu/model.py rotl8().
//
// SEEDS - REV C (ARCHITECTURE.md 12, ADR-010; CURRENT)
//   All 16 LFSRs use the SAME primitive polynomial, so each of them walks the
//   SAME m-sequence of period 65535; a seed only selects the starting PHASE.
//   Two LFSRs started n single steps apart produce the same r values n/8
//   stream cycles apart (one stream cycle = 8 steps).
//   History (why the table is what it is):
//     rev A : mode 2 seed_x_i = 0xACE1 + 0x3C5A*i, seed_w_i = 0x7A5C + 0x2B67*i
//             (mod 2^16), modes 0/1 X = 0xACE1, W = 0x7A5C.
//     rev B : maximally phase-spaced seeds S(4096 i) / S(32768 + 4096 i)
//             (ADR-008). SW-02 then showed that equal spacing makes the
//             operand-pair streams of different lanes TRANSLATES of each
//             other (lag_x(i)-lag_x(j) == lag_w(i)-lag_w(j)), a structural
//             correlation that cost accuracy at K = 9.
//     rev C : seed rules R1 (no two lanes' operand-pair streams are
//             translates) and R2 (no direct or swapped shared-bit lag between
//             operand pairs); among 5 candidate sets the rev A mode-2 seeds had
//             the best worst-case validation accuracy (SW-03,
//             reports/sw/seed_selection_revC.md). Modes 0/1 keep the rev B
//             pair X = 0xACE1 = S(0), W = 0xF9DE = S(32768) (half a period).
//   Rev C values (lane 0..7), CALCULATION (mod 2^16):
//       seed_x_i = 0xACE1 + 0x3C5A*i : ACE1 E93B 2595 61EF 9E49 DAA3 16FD 5357
//       seed_w_i = 0x7A5C + 0x2B67*i : 7A5C A5C3 D12A FC91 27F8 535F 7EC6 AA2D
//   (minimum pairwise lag on the common sequence: 321 stream cycles, X0-W3).
//   The tables below are EXPLICIT constants (not computed at elaboration);
//   tests/tpu/tb_sc_lfsr8.v TC7 re-derives them from the formulas and checks
//   every instantiated LFSR, and tb_sc_tpu R1 checks the r values against the
//   golden RNG traces sim/data/tpu_rng_trace_mode<m>.txt (spec_rev C).
//   All seeds are non-zero (0 is the LFSR lock-up state).
//
//   IL = 16 (synthesis study only, NOT part of the spec): lanes 8..15 use the
//   SAME formulas continued to i = 8..15 (0xACE1 + 0x3C5A*i, 0x7A5C +
//   0x2B67*i, mod 2^16; all non-zero), so lanes 0..7 keep exactly the spec
//   seeds.
//
// INTERFACE / TIMING
//   load : START accepted -> every LFSR re-loaded (look-ahead seed, see
//          sc_lfsr8.v). adv : stream cycle -> every LFSR advances 8 steps.
//   rx   : {r_x(IL-1), ..., r_x(0)}, 8 bits per lane, lane i at [8i+7:8i]
//   rw   : {r_w(IL-1), ..., r_w(0)}, same packing.
//   All outputs come straight from flip-flops (plus wiring for the rotation),
//   so they add no logic depth to the SNG comparators. Latency 0.
//
// PARAMETERS
//   IL       : input lanes (8 in the spec; 4/16 only for the synthesis study)
//   RNG_MODE : 0, 1 or 2 as above (default 2 since rev B, ADR-008; kept in rev C)
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module sc_rng #(
    parameter integer IL       = 8,
    parameter integer RNG_MODE = 2
) (
    input  wire            clk,
    input  wire            rst,
    input  wire            load,
    input  wire            adv,
    output wire [IL*8-1:0] rx,
    output wire [IL*8-1:0] rw
);

    // =========================================================================
    // SEED TABLES - the ONLY place where LFSR seeds are defined in the RTL.
    // A future seed revision changes only the constants in this block (and
    // PARAMS.version in sc_tpu.v); tests/tpu/tb_sc_lfsr8.v TC7 re-derives the
    // rev C rule and must be updated together with it.
    // =========================================================================
    // ---- Modes 0/1: the two shared LFSRs (ARCHITECTURE.md 12, = rev B) -------
    localparam [15:0] SEED_X = 16'hACE1;   // S(0)
    localparam [15:0] SEED_W = 16'hF9DE;   // S(32768): half a period from X

    // ---- Mode 2 (rev C): seed_x_i = 0xACE1 + 0x3C5A*i, seed_w_i = 0x7A5C + 0x2B67*i
    // Packed 16 bits per lane, lane i at [16i +: 16] (lane 0 rightmost).
    localparam [8*16-1:0] SEEDS_X_SPEC = {
        16'h5357, 16'h16FD, 16'hDAA2, 16'h9E49,     // lanes 7 6 5 4
        16'h61EF, 16'h2595, 16'hE93B, 16'hACE1 };   // lanes 3 2 1 0
    localparam [8*16-1:0] SEEDS_W_SPEC = {
        16'hAA2D, 16'h7EC6, 16'h535F, 16'h27F8,     // lanes 7 6 5 4
        16'hFC91, 16'hD12A, 16'hA5C3, 16'h7A5C };   // lanes 3 2 1 0
    // IL = 16 study only (not spec): the same formulas for i = 8..15.
    localparam [8*16-1:0] SEEDS_X_EXT = {
        16'h3627, 16'hF9CD, 16'hBD73, 16'h8119,     // lanes 15 14 13 12
        16'h44BF, 16'h0865, 16'hCC0B, 16'h8FB1 };   // lanes 11 10  9  8
    localparam [8*16-1:0] SEEDS_W_EXT = {
        16'h0565, 16'hD9FE, 16'hAE97, 16'h8330,     // lanes 15 14 13 12
        16'h57C9, 16'h2C62, 16'h00FB, 16'hD594 };   // lanes 11 10  9  8
    localparam [16*16-1:0] SEEDS_X = {SEEDS_X_EXT, SEEDS_X_SPEC};
    localparam [16*16-1:0] SEEDS_W = {SEEDS_W_EXT, SEEDS_W_SPEC};
    // ======================== end of the seed tables ===========================

    // 8-bit rotate left by n (0..7): pure wiring when n is a constant.
    function [7:0] rotl8;
        input [7:0]   v;
        input integer n;
        begin
            if (n == 0) rotl8 = v;
            else        rotl8 = (v << n) | (v >> (8 - n));
        end
    endfunction

    genvar i;
    generate
        if (RNG_MODE == 2) begin : g_indep
            // ---------------- Mode 2: IL independent LFSR pairs ----------------
            // Lane i (i < 16) takes its seeds from the tables above.
            for (i = 0; i < IL; i = i + 1) begin : g_lane
                wire [15:0] sx_unused, sw_unused;   // full states: debug only
                sc_lfsr8 #(.SEED({16'd0, SEEDS_X[16*i +: 16]})) u_lfsr_x (
                    .clk(clk), .rst(rst), .load(load), .adv(adv),
                    .state(sx_unused), .r(rx[8*i +: 8]));
                sc_lfsr8 #(.SEED({16'd0, SEEDS_W[16*i +: 16]})) u_lfsr_w (
                    .clk(clk), .rst(rst), .load(load), .adv(adv),
                    .state(sw_unused), .r(rw[8*i +: 8]));
            end
        end else begin : g_shared
            // ---------------- Modes 0/1: one LFSR_X + one LFSR_W --------------
            wire [7:0]  r_x, r_w;
            wire [15:0] sx_unused, sw_unused;       // full states: debug only
            sc_lfsr8 #(.SEED({16'd0, SEED_X})) u_lfsr_x (
                .clk(clk), .rst(rst), .load(load), .adv(adv),
                .state(sx_unused), .r(r_x));
            sc_lfsr8 #(.SEED({16'd0, SEED_W})) u_lfsr_w (
                .clk(clk), .rst(rst), .load(load), .adv(adv),
                .state(sw_unused), .r(r_w));
            for (i = 0; i < IL; i = i + 1) begin : g_lane
                if (RNG_MODE == 1) begin : g_rot
                    // Mode 1 ROTATE: lane i sees rotl8(r, i mod 8).
                    assign rx[8*i +: 8] = rotl8(r_x, i % 8);
                    assign rw[8*i +: 8] = rotl8(r_w, i % 8);
                end else begin : g_same
                    // Mode 0 SHARED: every lane sees the same r.
                    assign rx[8*i +: 8] = r_x;
                    assign rw[8*i +: 8] = r_w;
                end
            end
        end
    endgenerate

endmodule

`default_nettype wire
