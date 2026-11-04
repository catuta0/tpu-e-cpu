// =============================================================================
// File    : tests/tpu/tb_sc_lane_array.v
// Purpose : Self-checking unit testbench of design/rtl/tpu/sc_lane_array.v
//           (task RTL-TPU; spec ARCHITECTURE.md 5.2 / 5.3 step 1b [BIT-EXACT];
//           REQ-TPU-004 "unit test with forced r values").
//
// The random numbers are FORCED by the TB (no LFSR): r_x / r_w per lane are
// taken from the set {0, 1, 127, 128, 254, 255} (REQ-TPU-004), rotated over the
// lanes so that different lanes see different r in the same cycle.
//
//   TC1 SNG + XNOR + APC: for every pair (r_x set index a, r_w set index b)
//       (6 x 6) and every code c = 0..255 one stream cycle is applied with
//         x_i     = (c + 37 i) mod 256,           i = 0..7
//         W[j][i] = (3 c + 11 j + 5 i) mod 256,    j = 0..15
//       so every input lane and every weight sees all 256 codes against every
//       forced r. The reference (written here) computes
//         bx_i = (r_x(i) < x_i), bw_ji = (r_w(i) < W[j][i]),
//         inc_j = #{i : bx_i == bw_ji}
//       and the TB checks (a) the input SNG bits dut.bx == bx every cycle and
//       (b) acc_j == running sum of inc_j for all 16 neurons every cycle
//       (9216 cycles, acc reaches up to ~74k < 2^17: no wrap).
//   TC2 clr has priority over en; en = 0 holds the accumulators.
//   Codes 0 and 255: c = 0 gives b = 0 for every r; c = 255 gives b = 0 only
//   for r = 255 - both appear in TC1.
//
// Negative check: -DINJECT_FAULT uses AND instead of XNOR in the reference.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_sc_lane_array;

    localparam integer NL = 16, IL = 8, AW = 17;

    reg clk = 1'b0;
    always #5 clk <= ~clk;

    reg                clr = 1'b0, en = 1'b0;
    reg  [NL*IL*8-1:0] w_tile = 0;
    reg  [IL*8-1:0]    x_tile = 0, rx = 0, rw = 0;
    wire [NL*AW-1:0]   acc;

    sc_lane_array #(.NL(NL), .IL(IL), .AW(AW)) dut (
        .clk(clk), .clr(clr), .en(en), .w_tile(w_tile), .x_tile(x_tile),
        .rx(rx), .rw(rw), .acc(acc));

    reg [7:0] rset [0:5];
    integer ref_acc [0:NL-1];
    integer errors = 0, cycles = 0;
    integer a, b, c, i, j, inc, tmp;
    reg [7:0] xv, wv, rxv, rwv;
    reg       bxr, bwr, p;
    reg [IL-1:0] bx_ref;

    initial begin
        #(10_000_000);
        $display("FAIL: watchdog timeout");
        $display("TEST FAILED");
        $fatal(1, "watchdog");
    end

    task check_acc;
        input [8*24-1:0] where;
        begin
            for (j = 0; j < NL; j = j + 1)
                if (acc[AW*j +: AW] !== ref_acc[j][AW-1:0]) begin
                    if (errors < 10)
                        $display("FAIL: %0s neuron %0d acc %0d expected %0d", where, j, acc[AW*j +: AW], ref_acc[j]);
                    errors = errors + 1;
                end
        end
    endtask

    initial begin
        rset[0] = 8'd0;   rset[1] = 8'd1;   rset[2] = 8'd127;
        rset[3] = 8'd128; rset[4] = 8'd254; rset[5] = 8'd255;
        for (j = 0; j < NL; j = j + 1) ref_acc[j] = 0;

        // clear
        @(posedge clk); clr <= 1'b1; @(posedge clk); clr <= 1'b0; #1;
        check_acc("after clr");

        // ---------------- TC1 --------------------------------------------------
        for (a = 0; a < 6; a = a + 1)
            for (b = 0; b < 6; b = b + 1)
                for (c = 0; c < 256; c = c + 1) begin
                    // build operands (blocking, then applied before the edge)
                    for (i = 0; i < IL; i = i + 1) begin
                        rx[8*i +: 8]     = rset[(a + i) % 6];
                        rw[8*i +: 8]     = rset[(b + 2 * i) % 6];
                        tmp = (c + 37 * i) % 256;
                        x_tile[8*i +: 8] = tmp[7:0];
                        for (j = 0; j < NL; j = j + 1) begin
                            tmp = (3 * c + 11 * j + 5 * i) % 256;
                            w_tile[8*(j*IL + i) +: 8] = tmp[7:0];
                        end
                    end
                    en = 1'b1;
                    // reference
                    for (i = 0; i < IL; i = i + 1) begin
                        rxv = rx[8*i +: 8]; xv = x_tile[8*i +: 8];
                        bx_ref[i] = (rxv < xv);
                    end
                    #1;
                    if (dut.bx !== bx_ref) begin
                        if (errors < 10) $display("FAIL: input SNG bits %b expected %b (a %0d b %0d c %0d)", dut.bx, bx_ref, a, b, c);
                        errors = errors + 1;
                    end
                    for (j = 0; j < NL; j = j + 1) begin
                        inc = 0;
                        for (i = 0; i < IL; i = i + 1) begin
                            rwv = rw[8*i +: 8]; wv = w_tile[8*(j*IL + i) +: 8];
                            bxr = bx_ref[i];
                            bwr = (rwv < wv);
`ifdef INJECT_FAULT
                            p = bxr & bwr;
`else
                            p = ~(bxr ^ bwr);
`endif
                            inc = inc + {31'd0, p};
                        end
                        ref_acc[j] = ref_acc[j] + inc;
                    end
                    @(posedge clk); #1;
                    en = 1'b0;
                    cycles = cycles + 1;
                    check_acc("TC1");
                end
        if (errors == 0) $display("PASS: TC1 %0d stream cycles (6x6 forced r pairs x 256 codes), SNG bits and all 16 accumulators exact", cycles);
        else             $display("FAIL: TC1 errors=%0d", errors);

        // ---------------- TC2 ---------------------------------------------------
        repeat (5) @(posedge clk);
        #1; check_acc("TC2 hold (en=0)");
        en = 1'b1; clr = 1'b1;
        @(posedge clk); #1; en = 1'b0; clr = 1'b0;
        for (j = 0; j < NL; j = j + 1) ref_acc[j] = 0;
        check_acc("TC2 clr priority");
        if (errors == 0) $display("PASS: TC2 en=0 holds, clr has priority over en");

        if (errors == 0) begin
            $display("TEST PASSED");
            $finish;
        end else begin
            $display("errors=%0d", errors);
            $display("TEST FAILED");
            $fatal(1, "tb_sc_lane_array failed");
        end
    end

endmodule

`default_nettype wire
