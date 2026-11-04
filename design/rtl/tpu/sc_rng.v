// =============================================================================
// File      : design/rtl/tpu/sc_rng.v
// Module    : sc_rng
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Reqs      : requirements/REQUIREMENTS.md REQ-TPU-005, REQ-TPU-006 (RNG modes)
// Task      : RTL-TPU (rev A), RTL-SOC (rev B seed update) - fpga-engineer
// Spec      : ARCHITECTURE.md 5.3 [BIT-EXACT] (RNG, RNG_MODE) as amended by
//             section 11 (rev B, ADR-008: phase-spaced seeds, default mode 2);
//             INTERFACES.json rev B tpu.lfsr / tpu.rng_modes; ADR-003, ADR-005.
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
// SEEDS - REV B "PHASE-SPACED" (ARCHITECTURE.md 11, ADR-008)
//   All 16 LFSRs use the SAME primitive polynomial, so each of them walks the
//   SAME m-sequence of period 65535; a seed only selects the starting PHASE.
//   Two LFSRs started n single steps apart produce the same r values, n/8
//   stream cycles apart (one stream cycle = 8 steps). If n/8 is small, the
//   "independent" streams are in fact delayed copies of each other (rev A:
//   seeds 0xACE1 + 0x3C5A*i put X_0 and W_3 only 321 stream cycles apart,
//   SW-01a). Rev B therefore defines every seed as a point of the common
//   sequence:
//       S(n) = state of the LFSR started at 0xACE1 after n single steps
//       modes 0/1 : seed_x   = S(0)            = 0xACE1
//                   seed_w   = S(32768)        = 0xF9DE   (half a period)
//       mode 2    : seed_x_i = S(4096*i)
//                   seed_w_i = S(32768 + 4096*i)          (i = 0..7)
//   so the 16 mode-2 LFSRs sit at the 16 equally spaced phases 0, 4096, ...,
//   61440 of the period: any two are >= 4096 steps = 512 stream cycles apart
//   (4096 is a multiple of 8, so the spacing is an integer number of stream
//   cycles), and the multiplied pair X_i / W_i is 32768 steps = 4096 stream
//   cycles apart - longer than a whole inference at K <= 8
//   (10 tiles x 256 = 2560 stream cycles), so within one inference no
//   operand pair ever sees overlapping random numbers.
//   The tables below are EXPLICIT constants (not computed at elaboration).
//   Derivation (CALCULATION, reproducible): python3 -c "s=0xACE1
//   S=[]
//   for n in range(65535): S.append(s); s=((s<<1)|(((s>>15)^(s>>13)^(s>>12)^(s>>10))&1))&0xFFFF
//   print([hex(S[4096*i]) for i in range(8)], [hex(S[32768+4096*i]) for i in range(8)])"
//   and the values are re-derived by simulation in tests/tpu/tb_sc_lfsr8.v
//   (TC7: a 1-step reference LFSR is run from 0xACE1 and compared with every
//   instantiated seed of this module) and checked bit-exactly against the
//   golden RNG traces sim/data/tpu_rng_trace_mode<m>.txt (tb_sc_tpu R1).
//   All seeds are non-zero (0 is the LFSR lock-up state).
//
//   IL = 16 (synthesis study only, NOT part of the spec): lanes 8..15 use the
//   half-way phases S(4096*(i-8) + 2048) and S(32768 + 4096*(i-8) + 2048), so
//   all 32 LFSRs remain 2048 steps (256 stream cycles) apart and lanes 0..7
//   keep exactly the spec seeds.
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
//   RNG_MODE : 0, 1 or 2 as above (default 2 since rev B, ADR-008)
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

    // ---- Modes 0/1: the two shared LFSRs (ARCHITECTURE.md 11) ----------------
    localparam [15:0] SEED_X = 16'hACE1;   // S(0)
    localparam [15:0] SEED_W = 16'hF9DE;   // S(32768): half a period from X

    // ---- Mode 2: per-lane seeds = equally spaced phases of the m-sequence -----
    //   lane i     : 0       1       2       3       4       5       6       7
    //   phase n_x  : 0       4096    8192    12288   16384   20480   24576   28672
    //   phase n_w  : 32768   36864   40960   45056   49152   53248   57344   61440
    // Packed 16 bits per lane, lane i at [16i +: 16] (lane 0 rightmost).
    localparam [8*16-1:0] SEEDS_X_SPEC = {
        16'hC223, 16'hB617, 16'h70BC, 16'h0348,     // S(28672) S(24576) S(20480) S(16384)
        16'hEAD3, 16'h6F4D, 16'h357B, 16'hACE1 };   // S(12288) S( 8192) S( 4096) S(    0)
    localparam [8*16-1:0] SEEDS_W_SPEC = {
        16'h91AB, 16'h5D8E, 16'hF251, 16'h9DB1,     // S(61440) S(57344) S(53248) S(49152)
        16'h520B, 16'hAA39, 16'h71EC, 16'hF9DE };   // S(45056) S(40960) S(36864) S(32768)
    // IL = 16 study only (not spec): half-way phases 4096*(i-8) + 2048 (+32768 for W).
    localparam [8*16-1:0] SEEDS_X_EXT = {
        16'h0A33, 16'h3EC9, 16'hD08C, 16'h6B1C,     // S(30720) S(26624) S(22528) S(18432)
        16'h44BB, 16'h6F61, 16'h0F25, 16'hA932 };   // S(14336) S(10240) S( 6144) S( 2048)
    localparam [8*16-1:0] SEEDS_W_EXT = {
        16'hF26F, 16'hBCC8, 16'hD5B8, 16'hCFA4,     // S(63488) S(59392) S(55296) S(51200)
        16'hE90C, 16'h582E, 16'h89DF, 16'h2389 };   // S(47104) S(43008) S(38912) S(34816)
    localparam [16*16-1:0] SEEDS_X = {SEEDS_X_EXT, SEEDS_X_SPEC};
    localparam [16*16-1:0] SEEDS_W = {SEEDS_W_EXT, SEEDS_W_SPEC};

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
