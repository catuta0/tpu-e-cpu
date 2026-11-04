// =============================================================================
// File    : tests/smoke/dsp/tb_dsp_smoke.v
// Purpose : Self-checking testbench of tests/smoke/dsp/dsp_smoke_mac.v
//           (task ST-FPGA-02).  The SAME testbench runs on
//             (a) the RTL, and
//             (b) the post-synthesis netlist written by Yosys synth_gowin
//                 (DSP-mapped: MULT9X9), simulated with Yosys' cells_sim.v
//                 and the MULT9X9 model tests/smoke/dsp/gowin_mult_models.v,
//           which proves that Yosys' DSP mapping keeps the signed semantics
//           (under the model ASSUMPTION documented in gowin_mult_models.v).
//           The DUT is instantiated WITHOUT parameter overrides (the netlist
//           has no parameters); ACC_W = 24 is the RTL default.
//
// TEST CASES (each prints PASS/FAIL; expected values computed in this TB with
// 32-bit `integer` arithmetic, independent of the DUT):
//   T1 known answers: (-128)(-128) = 16384 (the only product that needs the
//      full 16-bit range: +2^14), (-128)(127) = -16256 (most negative),
//      (127)(127) = 16129, (127)(-128) = -16256, (-1)(-1) = 1, (1)(-1) = -1,
//      (-128)(1) = -128, (0)(-128) = 0.  Checks p_q exactly 2 clocks after
//      the operands are applied (pipeline latency).
//   T2 exhaustive: all 65536 (a, b) pairs, one per clock, streamed; p_q is
//      compared with a*b two clocks later.
//   T3 accumulate: (i) 64 x (-128)(-128) -> acc = 64 * 2^14 = 2^20 = 1048576
//      (the DT-TPU layer-1 worst case); (ii) the sum over ALL 65536 pairs:
//      sum_a sum_b a*b = (sum_{a=-128..127} a)^2 = (-128)^2 = 16384 exactly;
//      (iii) clr restarts the sum (acc = last product only).
// Negative check: -DINJECT_FAULT corrupts one expected T1 value -> FAIL.
// Watchdog: 10 ms simulated time.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_dsp_smoke;

    reg clk = 1'b0;
    always #18.5 clk <= ~clk;        // 27 MHz
    reg        rst = 1'b1;
    reg        en  = 1'b0;
    reg        clr = 1'b0;
    reg  [7:0] a   = 8'd0;
    reg  [7:0] b   = 8'd0;
    wire [15:0] p_q;
    wire [23:0] acc;

    dsp_smoke_mac dut (.clk(clk), .rst(rst), .en(en), .clr(clr),
                       .a(a), .b(b), .p_q(p_q), .acc(acc));

    integer errors = 0;
    integer i, k, e;

    initial begin
        #(64'd10_000_000);
        $display("FAIL: watchdog");
        $display("TEST FAILED");
        $fatal(1, "watchdog");
    end

    // Signed product of two 8-bit codes, computed with 32-bit integers.
    function integer smul;
        input [7:0] x, y;
        integer xi, yi;
        begin
            xi = x; if (x[7]) xi = xi - 256;
            yi = y; if (y[7]) yi = yi - 256;
            smul = xi * yi;
        end
    endfunction

    // 16-bit signed register value -> integer.
    function integer s16;
        input [15:0] v;
        begin s16 = v; if (v[15]) s16 = s16 - 65536; end
    endfunction
    function integer s24;
        input [23:0] v;
        begin s24 = v; if (v[23]) s24 = s24 - 16777216; end
    endfunction

    // Apply one operand pair for one cycle and return p_q two edges later.
    task one;
        input [7:0] x, y;
        input integer exp;
        integer got;
        begin
            @(negedge clk); a = x; b = y; en = 1'b0;
            @(negedge clk);              // edge 1: operands registered
            @(negedge clk);              // edge 2: product registered
            got = s16(p_q);
            if (got !== exp) begin
                errors = errors + 1;
                $display("FAIL: T1 a=%0d b=%0d p=%0d exp=%0d", smul(x, 8'd1), smul(y, 8'd1), got, exp);
            end else
                $display("PASS: T1 a=%0d b=%0d p=%0d", smul(x, 8'd1), smul(y, 8'd1), got);
        end
    endtask

    // Expected-value pipeline for the streamed tests.
    reg [7:0] ha [0:2];
    reg [7:0] hb [0:2];
    integer   t2_err;

    initial begin
        repeat (3) @(negedge clk);
        rst = 1'b0;

        // ---- T1 known answers -------------------------------------------
`ifdef INJECT_FAULT
        one(8'h80, 8'h80, 16383);    // deliberately wrong expectation
`else
        one(8'h80, 8'h80, 16384);
`endif
        one(8'h80, 8'h7F, -16256);
        one(8'h7F, 8'h7F, 16129);
        one(8'h7F, 8'h80, -16256);
        one(8'hFF, 8'hFF, 1);
        one(8'h01, 8'hFF, -1);
        one(8'h80, 8'h01, -128);
        one(8'h00, 8'h80, 0);

        // ---- T2 exhaustive, streamed (one pair per clock) -----------------
        // At negedge n we apply pair n and check the product of pair n-2.
        t2_err = 0;
        for (k = 0; k < 65536 + 2; k = k + 1) begin
            @(negedge clk);
            if (k >= 2) begin
                e = smul(ha[1], hb[1]);   // pair k-2 (see shift below)
                if (s16(p_q) !== e) begin
                    t2_err = t2_err + 1;
                    if (t2_err <= 5)
                        $display("FAIL: T2 pair %0d p=%0d exp=%0d", k - 2, s16(p_q), e);
                end
            end
            ha[1] = ha[0]; hb[1] = hb[0];
            a = k[15:8]; b = k[7:0];
            ha[0] = a;   hb[0] = b;
        end
        if (t2_err == 0) $display("PASS: T2 exhaustive 65536 signed 8x8 products, 0 mismatches");
        else begin errors = errors + 1; $display("FAIL: T2 %0d mismatches", t2_err); end

        // ---- T3 (i) 64 x (-128 * -128) = 2^20 -----------------------------
        @(negedge clk); clr = 1'b1; en = 1'b0;     // clear: acc <= 0
        @(negedge clk); clr = 1'b0;
        repeat (3) @(negedge clk);
        for (i = 0; i < 64; i = i + 1) begin
            a = 8'h80; b = 8'h80; en = 1'b1;
            @(negedge clk);
        end
        en = 1'b0;
        repeat (3) @(negedge clk);
        if (s24(acc) === 1048576) $display("PASS: T3i 64 x 16384 = %0d", s24(acc));
        else begin errors = errors + 1; $display("FAIL: T3i acc=%0d exp 1048576", s24(acc)); end

        // ---- T3 (ii) sum over all pairs = 16384 ----------------------------
        @(negedge clk); clr = 1'b1;
        @(negedge clk); clr = 1'b0;
        repeat (3) @(negedge clk);
        for (k = 0; k < 65536; k = k + 1) begin
            a = k[15:8]; b = k[7:0]; en = 1'b1;
            @(negedge clk);
        end
        en = 1'b0;
        repeat (3) @(negedge clk);
        if (s24(acc) === 16384) $display("PASS: T3ii sum over all 65536 pairs = %0d", s24(acc));
        else begin errors = errors + 1; $display("FAIL: T3ii acc=%0d exp 16384", s24(acc)); end

        // ---- T3 (iii) clr together with a product: acc = that product ------
        a = 8'h85; b = 8'h7F; en = 1'b1; clr = 1'b1;  // (-123)(127) = -15621
        @(negedge clk); en = 1'b0; clr = 1'b0;
        repeat (3) @(negedge clk);
        if (s24(acc) === -15621) $display("PASS: T3iii clr+product acc = %0d", s24(acc));
        else begin errors = errors + 1; $display("FAIL: T3iii acc=%0d exp -15621", s24(acc)); end

        if (errors == 0) begin
            $display("TEST PASSED");
            $finish;
        end else begin
            $display("TEST FAILED (%0d errors)", errors);
            $fatal(1, "tb_dsp_smoke failed");
        end
    end

endmodule

`default_nettype wire
