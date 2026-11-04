// =============================================================================
// File      : design/rtl/tpu/sc_rng.v
// Module    : sc_rng
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Task      : RTL-TPU (fpga-engineer)
// Spec      : ARCHITECTURE.md rev A 5.3 [BIT-EXACT] (RNG, RNG_MODE),
//             INTERFACES.json tpu.lfsr / tpu.rng_modes, ADR-003, ADR-005.
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
//     0 SHARED      : one LFSR_X (seed 0xACE1) + one LFSR_W (seed 0x7A5C);
//                     every lane uses the same r_x / r_w.        (cheapest)
//     1 ROTATE      : same two LFSRs; lane i uses rotl8(r, i). A bit rotation
//                     is free wiring, keeps each r uniform, and changes the
//                     ordering relation between lanes (partial decorrelation).
//     2 INDEPENDENT : IL LFSR_X_i (seed 0xACE1 + 0x3C5A*i mod 2^16) and IL
//                     LFSR_W_i (seed 0x7A5C + 0x2B67*i mod 2^16).  (largest)
//   (Seeds for i = 0..15 are all non-zero, CALCULATION: X 0xACE1, 0xE93B,
//   0x2595, 0x61EF, 0x9E49, 0xDAA3, 0x16FD, 0x5357, 0x8FB1, 0xCC0B, 0x0865,
//   0x44BF, 0x8119, 0xBD73, 0xF9CD, 0x3627; W 0x7A5C, 0xA5C3, 0xD12A, 0xFC91,
//   0x27F8, 0x535F, 0x7EC6, 0xAA2D, 0xD594, 0x00FB, 0x2C62, 0x57C9, 0x8330,
//   0xAE97, 0xD9FE, 0x0565.)
//   In mode 1 the rotation amount is the LANE index i (0..IL-1), reading A1
//   of the golden model; for IL > 8 the rotation is taken mod 8 (rotl8 by 8
//   is the identity), identical to code/python/sctpu/model.py rotl8().
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
//   IL       : input lanes (8 in rev A; 4/16 only for the synthesis study)
//   RNG_MODE : 0, 1 or 2 as above (default 1, ADR-003)
// =============================================================================
`default_nettype none

module sc_rng #(
    parameter integer IL       = 8,
    parameter integer RNG_MODE = 1
) (
    input  wire            clk,
    input  wire            rst,
    input  wire            load,
    input  wire            adv,
    output wire [IL*8-1:0] rx,
    output wire [IL*8-1:0] rw
);

    // Seeds of spec 5.3 (modes 0/1 use lane 0's values only).
    localparam integer SEED_X      = 32'h0000_ACE1;
    localparam integer SEED_W      = 32'h0000_7A5C;
    localparam integer SEED_X_STEP = 32'h0000_3C5A;
    localparam integer SEED_W_STEP = 32'h0000_2B67;

    // Mode-2 seed of lane i: (seed + step*i) mod 2^16 (spec 5.3). Computed in
    // 32-bit integer arithmetic; the modulo is explicit and sc_lfsr8 uses
    // only bits [15:0] of its integer SEED parameter.
    function integer seed_x;
        input integer i;
        begin
            seed_x = (SEED_X + SEED_X_STEP * i) % 65536;
        end
    endfunction

    function integer seed_w;
        input integer i;
        begin
            seed_w = (SEED_W + SEED_W_STEP * i) % 65536;
        end
    endfunction

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
            for (i = 0; i < IL; i = i + 1) begin : g_lane
                wire [15:0] sx_unused, sw_unused;   // full states: debug only
                sc_lfsr8 #(.SEED(seed_x(i))) u_lfsr_x (
                    .clk(clk), .rst(rst), .load(load), .adv(adv),
                    .state(sx_unused), .r(rx[8*i +: 8]));
                sc_lfsr8 #(.SEED(seed_w(i))) u_lfsr_w (
                    .clk(clk), .rst(rst), .load(load), .adv(adv),
                    .state(sw_unused), .r(rw[8*i +: 8]));
            end
        end else begin : g_shared
            // ---------------- Modes 0/1: one LFSR_X + one LFSR_W --------------
            wire [7:0]  r_x, r_w;
            wire [15:0] sx_unused, sw_unused;       // full states: debug only
            sc_lfsr8 #(.SEED(SEED_X)) u_lfsr_x (
                .clk(clk), .rst(rst), .load(load), .adv(adv),
                .state(sx_unused), .r(r_x));
            sc_lfsr8 #(.SEED(SEED_W)) u_lfsr_w (
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
