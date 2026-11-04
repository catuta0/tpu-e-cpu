// =============================================================================
// File    : tests/tpu/tb_sc_postproc.v
// Purpose : Self-checking unit testbench of design/rtl/tpu/sc_postproc.v
//           (task RTL-TPU; spec ARCHITECTURE.md 5.3 step 1c [BIT-EXACT]).
//
// Reference model (written here independently of the RTL): it uses 64-bit
// signed integer arithmetic and an explicit FLOOR division built from
// Verilog's truncating '/' and '%' (q = a/b; if a%b != 0 and a < 0: q = q-1),
// i.e. it does NOT use shifts like the RTL does:
//     L  = 2^K, N_in = 64 (layer 1) or 16 (layer 2)
//     D  = 2*acc - N_in*L
//     B  = floor(bias * L / 128)
//     Dp = D + B
//     u  = floor(Dp * 2^(s+7) / L);  h = clip(u, 0, 127);  code = 128 + h
//
// Test cases (one input per clock, results checked 2 clocks later):
//   TC1 DIRECTED GRID: both layers x every K = 4..10 x every s = 0..7 x
//       acc in {0, 1, N_in*L/2 - 1, N_in*L/2, N_in*L/2 + 1, N_in*L - 1,
//       N_in*L} x bias in {-32768, -32767, -1025, -129, -128, -127, -65, -1,
//       0, 1, 63, 127, 128, 129, 32767}. Contains every corner: floor of
//       negative biases (e.g. bias = -1 -> B = -1, not 0), Dp most negative
//       / most positive, u exactly at 0 / 127 / 128, clip low and clip high.
//   TC2 NEAR-THRESHOLD: for every (layer, K, s), acc values around the Dp
//       that gives u = 127/128 and u = 0/1 (bias 0), to hit the exact clip
//       boundary and the floor of the positive shift-right case.
//   TC3 RANDOM: 40000 uniformly random (layer, K, s, acc in 0..N_in*L,
//       bias int16) vectors, fixed seed (deterministic).
//   Coverage counters are printed (negative-floor cases where trunc != floor,
//   clip-low, clip-high, in-range) so that the log shows the corners were hit.
//
// Negative check: -DINJECT_FAULT makes the reference use TRUNCATING division
// for B; the TB must then fail (TEST FAILED, non-zero exit).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_sc_postproc;

    localparam integer AW  = 17;
    localparam integer DPW = 20;

    reg clk = 1'b0;
    always #5 clk <= ~clk;
    reg rst = 1'b1;

    reg            in_valid  = 1'b0;
    reg            in_layer2 = 1'b0;
    reg  [3:0]     in_idx    = 4'd0;
    reg  [3:0]     in_k      = 4'd4;
    reg  [2:0]     in_s      = 3'd0;
    reg  [AW-1:0]  in_acc    = {AW{1'b0}};
    reg  [15:0]    in_bias   = 16'd0;
    wire           out_valid, out_layer2;
    wire [3:0]     out_idx;
    wire [DPW-1:0] out_dp;
    wire [7:0]     out_hcode;

    sc_postproc #(.AW(AW), .DPW(DPW)) dut (
        .clk(clk), .rst(rst), .in_valid(in_valid), .in_layer2(in_layer2),
        .in_idx(in_idx), .in_k(in_k), .in_s(in_s), .in_acc(in_acc), .in_bias(in_bias),
        .out_valid(out_valid), .out_layer2(out_layer2), .out_idx(out_idx),
        .out_dp(out_dp), .out_hcode(out_hcode));

    // ---------------- independent reference -----------------------------------
    function signed [63:0] floor_div;      // floor(a / b), b > 0
        input signed [63:0] a;
        input signed [63:0] b;
        reg   signed [63:0] q;
        begin
            q = a / b;                      // Verilog: truncates towards zero
`ifdef INJECT_FAULT
            floor_div = q;                  // deliberately wrong (truncation)
`else
            if ((a % b) != 0 && a < 0) q = q - 1;
            floor_div = q;
`endif
        end
    endfunction

    function signed [63:0] floor_div_ok;   // always-correct copy for the u term
        input signed [63:0] a;
        input signed [63:0] b;
        reg   signed [63:0] q;
        begin
            q = a / b;
            if ((a % b) != 0 && a < 0) q = q - 1;
            floor_div_ok = q;
        end
    endfunction

    // Expected-result queue (the DUT has a fixed 2-cycle latency; a queue
    // makes the checker independent of that number anyway).
    localparam integer QN = 65536;
    reg signed [63:0] q_dp   [0:QN-1];
    reg        [7:0]  q_code [0:QN-1];
    reg        [3:0]  q_idx  [0:QN-1];
    reg               q_l2   [0:QN-1];
    integer wr_ptr = 0, rd_ptr = 0;
    integer errors = 0, checked = 0;
    integer cov_floor_neg = 0, cov_clip_lo = 0, cov_clip_hi = 0, cov_mid = 0;
    integer cov_u127 = 0, cov_u128 = 0, cov_u0 = 0;

    // Push one vector: compute expected values, drive the DUT for one cycle.
    task push;
        input        layer2;
        input integer k;
        input integer s;
        input integer acc;
        input integer bias;
        reg signed [63:0] L, nin, D, B, Dp, u, h, bt;
        integer idx_i;
        begin
            L   = 64'sd1 <<< k;
            nin = layer2 ? 64'sd16 : 64'sd64;
            D   = 2 * acc - nin * L;
            B   = floor_div(bias * L, 128);
            bt  = (bias * L) / 128;                         // truncation, coverage only
            if (bt != floor_div_ok(bias * L, 128)) cov_floor_neg = cov_floor_neg + 1;
            Dp  = D + B;
            u   = floor_div_ok(Dp * (64'sd1 <<< (s + 7)), L);
            if (u < 0)        begin h = 0;   cov_clip_lo = cov_clip_lo + 1; end
            else if (u > 127) begin h = 127; cov_clip_hi = cov_clip_hi + 1; end
            else              begin h = u;   cov_mid     = cov_mid + 1;     end
            if (u == 127) cov_u127 = cov_u127 + 1;
            if (u == 128) cov_u128 = cov_u128 + 1;
            if (u == 0)   cov_u0   = cov_u0 + 1;
            q_dp[wr_ptr % QN]   = Dp;
            q_code[wr_ptr % QN] = 8'd128 + h[7:0];
            idx_i = wr_ptr % 16;
            q_idx[wr_ptr % QN]  = idx_i[3:0];
            q_l2[wr_ptr % QN]   = layer2;
            // drive
            in_valid  <= 1'b1;
            in_layer2 <= layer2;
            in_idx    <= idx_i[3:0];
            in_k      <= k[3:0];
            in_s      <= s[2:0];
            in_acc    <= acc[AW-1:0];
            in_bias   <= bias[15:0];
            wr_ptr = wr_ptr + 1;
            @(posedge clk);
            in_valid  <= 1'b0;
        end
    endtask

    // Checker: every out_valid must match the oldest queued expectation.
    reg signed [63:0] got_dp;
    always @(posedge clk) begin
        if (!rst && out_valid) begin
            got_dp = {{(64-DPW){out_dp[DPW-1]}}, out_dp};
            if (rd_ptr >= wr_ptr) begin
                errors = errors + 1;
                $display("FAIL: unexpected out_valid");
            end else if (got_dp !== q_dp[rd_ptr % QN] || out_hcode !== q_code[rd_ptr % QN] ||
                         out_idx !== q_idx[rd_ptr % QN] || out_layer2 !== q_l2[rd_ptr % QN]) begin
                if (errors < 20)
                    $display("FAIL: vec %0d dp got %0d exp %0d | code got %0d exp %0d | idx %0d/%0d l2 %0d/%0d",
                             rd_ptr, got_dp, q_dp[rd_ptr % QN], out_hcode, q_code[rd_ptr % QN],
                             out_idx, q_idx[rd_ptr % QN], out_layer2, q_l2[rd_ptr % QN]);
                errors = errors + 1;
            end
            rd_ptr  = rd_ptr + 1;
            checked = checked + 1;
        end
    end

    initial begin
        #(50_000_000);
        $display("FAIL: watchdog timeout");
        $display("TEST FAILED");
        $fatal(1, "watchdog");
    end

    integer l2, k, s, a, b, nin, L, n, seed, e0, acc0, t, thr;
    integer acc_list [0:6];
    integer bias_list [0:14];

    initial begin
        bias_list[0] = -32768; bias_list[1] = -32767; bias_list[2] = -1025;
        bias_list[3] = -129;   bias_list[4] = -128;   bias_list[5] = -127;
        bias_list[6] = -65;    bias_list[7] = -1;     bias_list[8] = 0;
        bias_list[9] = 1;      bias_list[10] = 63;    bias_list[11] = 127;
        bias_list[12] = 128;   bias_list[13] = 129;   bias_list[14] = 32767;

        repeat (3) @(posedge clk);
        rst <= 1'b0;
        @(posedge clk);

        // ---------------- TC1: directed grid --------------------------------------
        e0 = errors;
        for (l2 = 0; l2 < 2; l2 = l2 + 1)
            for (k = 4; k <= 10; k = k + 1)
                for (s = 0; s <= 7; s = s + 1) begin
                    nin = (l2 != 0) ? 16 : 64;
                    L   = 1 << k;
                    acc_list[0] = 0;               acc_list[1] = 1;
                    acc_list[2] = nin * L / 2 - 1; acc_list[3] = nin * L / 2;
                    acc_list[4] = nin * L / 2 + 1; acc_list[5] = nin * L - 1;
                    acc_list[6] = nin * L;
                    for (a = 0; a < 7; a = a + 1)
                        for (b = 0; b < 15; b = b + 1)
                            push(l2[0], k, s, acc_list[a], bias_list[b]);
                end
        repeat (4) @(posedge clk);
        if (errors == e0) $display("PASS: TC1 DIRECTED GRID %0d vectors (2 layers x K 4..10 x s 0..7 x 7 acc x 15 bias)", rd_ptr);
        else              $display("FAIL: TC1 DIRECTED GRID errors=%0d", errors - e0);

        // ---------------- TC2: near the clip thresholds ----------------------------
        // With bias 0: Dp = 2 acc - N_in L. u = 128 when Dp = 128 * L / 2^(s+7)
        // = L / 2^s (if integer), so test acc giving Dp around thr = max(L>>s,1)*{0,1}.
        e0 = errors; n = rd_ptr;
        for (l2 = 0; l2 < 2; l2 = l2 + 1)
            for (k = 4; k <= 10; k = k + 1)
                for (s = 0; s <= 7; s = s + 1) begin
                    nin  = (l2 != 0) ? 16 : 64;
                    L    = 1 << k;
                    acc0 = nin * L / 2;           // Dp = 0
                    thr  = (L >> s) / 2;          // acc offset giving Dp ~ L/2^s
                    for (t = -3; t <= 3; t = t + 1) begin
                        push(l2[0], k, s, acc0 + t, 0);              // u around 0
                        if (acc0 + thr + t <= nin * L && acc0 + thr + t >= 0)
                            push(l2[0], k, s, acc0 + thr + t, 0);    // u around 128
                    end
                end
        repeat (4) @(posedge clk);
        if (errors == e0) $display("PASS: TC2 NEAR-THRESHOLD %0d vectors", rd_ptr - n);
        else              $display("FAIL: TC2 NEAR-THRESHOLD errors=%0d", errors - e0);

        // ---------------- TC3: random --------------------------------------------
        e0 = errors; n = rd_ptr; seed = 32'h5C7A_0001;
        for (t = 0; t < 40000; t = t + 1) begin
            l2  = $unsigned($random(seed)) % 2;
            k   = 4 + $unsigned($random(seed)) % 7;
            s   = $unsigned($random(seed)) % 8;
            nin = (l2 != 0) ? 16 : 64;
            L   = 1 << k;
            a   = $unsigned($random(seed)) % (nin * L + 1);
            b   = ($unsigned($random(seed)) % 65536) - 32768;
            push(l2[0], k, s, a, b);
        end
        repeat (4) @(posedge clk);
        if (errors == e0) $display("PASS: TC3 RANDOM %0d vectors", rd_ptr - n);
        else              $display("FAIL: TC3 RANDOM errors=%0d", errors - e0);

        // ---------------- summary --------------------------------------------------
        $display("INFO: coverage: B floor!=trunc (negative non-integer) %0d, clip-low %0d, clip-high %0d, in-range %0d, u==0 %0d, u==127 %0d, u==128 %0d",
                 cov_floor_neg, cov_clip_lo, cov_clip_hi, cov_mid, cov_u0, cov_u127, cov_u128);
        if (checked != wr_ptr) begin
            errors = errors + 1;
            $display("FAIL: %0d vectors pushed, %0d results checked", wr_ptr, checked);
        end
        $display("INFO: vectors checked = %0d, mismatches = %0d", checked, errors);
        if (errors == 0 && cov_floor_neg > 0 && cov_clip_lo > 0 && cov_clip_hi > 0 && cov_u127 > 0 && cov_u128 > 0) begin
            $display("TEST PASSED");
            $finish;
        end else begin
            $display("TEST FAILED");
            $fatal(1, "tb_sc_postproc failed");
        end
    end

endmodule

`default_nettype wire
