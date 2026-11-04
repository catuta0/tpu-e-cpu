// =============================================================================
// File      : design/rtl/tpu/sc_postproc.v
// Module    : sc_postproc
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Reqs      : requirements/REQUIREMENTS.md REQ-TPU-008 (post-processing exactness and widths), REQ-TPU-013
// Task      : RTL-TPU (fpga-engineer)
// Spec      : ARCHITECTURE.md rev A 5.3 step 1c [BIT-EXACT];
//             INTERFACES.json tpu.postproc.
//
// PURPOSE
//   Converts one APC accumulator value acc_j into the neuron output of spec
//   5.3 step 1c. One instance is time-shared by the 16 neurons of a layer
//   (one neuron per clock, 16 cycles per layer): area is negligible and the
//   arithmetic is exact integer arithmetic.
//
// THEORY / FORMULAS (all [BIT-EXACT], "floor" = round towards minus infinity)
//   L = 2^K stream cycles per tile, N_in = 64 (layer 1) or 16 (layer 2).
//   D  = 2*acc - N_in*L        Bipolar decoding of the APC count: each XNOR
//                              bit p in {0,1} represents the bipolar value
//                              2p - 1, so the sum of N_in*L bipolar products
//                              is 2*acc - N_in*L. E[D] = L * sum v_x v_w.
//   B  = floor(bias * 2^K / 128)
//                              The bias is an int16 in units of 1/128 (same
//                              scale as one code step); it is rescaled to the
//                              L-cycle scale of D. Implemented exactly as
//                              (sign_extend(bias) << K) >>> 7: the left shift
//                              is exact and the ARITHMETIC right shift by 7 is
//                              floor division by 128 also for negative values
//                              (e.g. bias = -1, K = 4: -16 >>> 7 = -1, while a
//                              truncating division would give 0).
//   Dp = D + B
//   layer 1: u = floor(Dp * 2^(s+7) / 2^K) = (Dp << (s+7)) >>> K  (exact);
//            h = clip(u, 0, 127);  HIDDEN code = 128 + h (a clipped ReLU in
//            code space: h/128 = clip(2^s Dp/L, 0, 127/128)).
//   layer 2: SCORE = Dp (signed, sign-extended to 32 bits by the bus slave).
//
// WIDTHS (CALCULATION, K <= 10, |bias| <= 2^15)
//   acc <= 65536 (17 bit); D in [-65536, 65536] (18 bit signed);
//   B in [-262144, 262136] (19 bit signed); Dp in [-327680, 327672] -> DPW =
//   20 bit signed (2^19 = 524288). u = Dp * 2^(s+7) needs 20 + 14 = 34 bits
//   before the right shift: worst case |Dp * 2^(s+7)| = 327680 * 2^14 =
//   5 368 709 120 (2^32.3) < 2^33, so a 34-bit SIGNED intermediate holds every
//   legal value (ARCHITECTURE.md 10 rev A.2 bound |Dp*2^(s+7)| < 2^34;
//   REQ-TPU-008). The shifter is 34 bits wide, no intermediate value is ever
//   truncated and no early saturation is used: the hardware is a literal
//   transcription of the formula (proved by tests/tpu/tb_sc_postproc.v over
//   every K, s and the extreme acc/bias values).
//
// INTERFACE / TIMING: 2-stage pipeline, latency 2 clocks, throughput 1/clock
//   cycle n   : in_valid, in_* presented
//   edge n    : stage 1 registers Dp (D + B)                  [v1, dp1, ...]
//   edge n+1  : stage 2 registers out_dp = Dp and out_hcode   [out_*]
//   cycle n+2 : out_valid = 1, outputs valid for exactly one cycle per input
//   in_k must already be clamped to 4..10 (done at the CONFIG write, sc_tpu.v);
//   in_s is 0..7 (3-bit field). in_idx / in_layer2 are carried along so the
//   consumer knows which neuron / layer the result belongs to.
//   rst clears only the valid flags (datapath flops need no reset).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module sc_postproc #(
    parameter integer AW  = 17,   // accumulator width (see sc_lane_array.v)
    parameter integer DPW = 20    // width of D, B, Dp (signed)
) (
    input  wire                  clk,
    input  wire                  rst,
    // ---- stage-0 inputs ----------------------------------------------------
    input  wire                  in_valid,
    input  wire                  in_layer2,  // 0: layer 1 (N_in=64), 1: layer 2 (N_in=16)
    input  wire [3:0]            in_idx,     // neuron index j (carried along)
    input  wire [3:0]            in_k,       // K = log2(L), 4..10
    input  wire [2:0]            in_s,       // ACT_SHIFT s, 0..7
    input  wire [AW-1:0]         in_acc,     // acc_j (unsigned)
    input  wire [15:0]           in_bias,    // bias_j (signed int16)
    // ---- stage-2 outputs ---------------------------------------------------
    output reg                   out_valid,
    output reg                   out_layer2,
    output reg  [3:0]            out_idx,
    output reg  [DPW-1:0]        out_dp,     // Dp_j (signed two's complement)
    output reg  [7:0]            out_hcode   // 128 + clip(u,0,127) (layer 1 meaning)
);

    // =========================================================================
    // Stage 1: D, B, Dp
    // =========================================================================
    // N_in * L = 2^(log2(N_in) + K): 2^(K+6) for layer 1, 2^(K+4) for layer 2.
    // The shift amount is 5 bits wide: K + 6 reaches 16, which would wrap to 0
    // in a 4-bit self-determined sum.
    wire [4:0]     nl_log2 = in_layer2 ? 5'd4 : 5'd6;
    wire [4:0]     nl_sh   = {1'b0, in_k} + nl_log2;
    wire [DPW-1:0] nl      = {{(DPW-1){1'b0}}, 1'b1} << nl_sh;

    // D = 2*acc - N_in*L, computed modulo 2^DPW (the true value fits, so the
    // two's-complement result is exact).
    wire [DPW-1:0] two_acc = {{(DPW-AW-1){1'b0}}, in_acc, 1'b0};
    wire [DPW-1:0] d       = two_acc - nl;

    // B = floor(bias * 2^K / 128): sign-extend to 26 bits (16 + K_max), shift
    // left by K (exact), then drop 7 LSBs (= arithmetic shift right by 7).
    wire [25:0]    bias_x  = {{10{in_bias[15]}}, in_bias};
    wire [25:0]    bias_sh = bias_x << in_k;
    wire [DPW-1:0] b       = {{(DPW-19){bias_sh[25]}}, bias_sh[25:7]};
    // bias_sh[6:0] are the fraction bits discarded by the floor: intentionally
    // unused (Verilator idiom: a signal whose name contains "unused").
    wire           unused_bias_frac = &{1'b0, bias_sh[6:0]};

    reg            v1, layer2_1;
    reg  [3:0]     idx1, k1;
    reg  [2:0]     s1;
    reg  [DPW-1:0] dp1;

    always @(posedge clk) begin
        if (rst) v1 <= 1'b0;
        else     v1 <= in_valid;
        // Datapath: captured every cycle (only meaningful when v1 = 1).
        layer2_1 <= in_layer2;
        idx1     <= in_idx;
        k1       <= in_k;
        s1       <= in_s;
        dp1      <= d + b;            // Dp = D + B
    end

    // =========================================================================
    // Stage 2: u = floor(Dp * 2^(s+7) / 2^K), h = clip(u, 0, 127)
    // =========================================================================
    // Sign-extend Dp to 34 bits and multiply by 2^(s+7) (exact: 20 + 14 bits).
    wire [3:0]  up_sh = {1'b0, s1} + 4'd7;                   // s + 7 = 7..14
    wire [33:0] wide  = {{(34-DPW){dp1[DPW-1]}}, dp1} << up_sh;
    // Floor division by 2^K = arithmetic right shift ($signed + >>>).
    wire [33:0] u     = wide >> k1;
    // Clip to 0..127: negative -> 0 (u[33] is the sign), >= 128 -> 127.
    wire        u_neg = u[33];
    wire        u_big = |u[32:7];
    wire [6:0]  h     = u_neg ? 7'd0 : (u_big ? 7'd127 : u[6:0]);

    always @(posedge clk) begin
        if (rst) out_valid <= 1'b0;
        else     out_valid <= v1;
        out_layer2 <= layer2_1;
        out_idx    <= idx1;
        out_dp     <= dp1;
        out_hcode  <= {1'b1, h};      // 128 + h, h <= 127
    end

endmodule

`default_nettype wire
