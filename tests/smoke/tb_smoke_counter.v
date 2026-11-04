`default_nettype none
`timescale 1ns / 1ps
// =============================================================================
// File        : tests/smoke/tb_smoke_counter.v
// Testbench   : tb_smoke_counter
// DUT         : design/rtl/common/smoke_counter.v
// Task        : ST-FPGA-01 (toolchain smoke test with a KNOWN answer)
//
// PURPOSE
//   Self-checking testbench. Every check prints a "PASS: ..." or "FAIL: ..."
//   line; the run ends with "TEST PASSED" or "TEST FAILED". On any failure it
//   calls $fatal(1) so the calling script gets a non-zero exit status.
//
// DUTs
//   u_dut24 : default instance, WIDTH=24, NUM_LEDS=6 (the synthesised design).
//   u_dut4  : WIDTH=4, NUM_LEDS=4, used to observe wrap-around 15 -> 0 in a
//             handful of cycles (the 24-bit one would need 2**24 cycles).
//
// STIMULUS CONVENTIONS (avoid races)
//   * 27 MHz clock: period 37.037 ns, modelled as 37.000 ns (half period
//     18.5 ns). The exact period is irrelevant for a cycle-based check.
//   * The button input is changed ONLY right after a FALLING clock edge, i.e.
//     half a period away from the rising edge where the DUT samples it. This
//     models a well-defined asynchronous event without setup/hold ambiguity.
//   * Edges are counted by the task `tick(n)`, which waits for n rising edges
//     and then for the following falling edge, so all register outputs have
//     settled when they are checked.
//
// KNOWN ANSWER (derived by hand - see also the header of smoke_counter.v)
//   Synchroniser = 2 flip-flops (sync_ff1 -> sync_ff2), counter reset is
//   synchronous on sync_ff2. Number the rising edges after the release, 1..N:
//     edge 1: sync_ff1 <- 0, sync_ff2 <- 1 (old ff1), counter sees rst=1 -> 0
//     edge 2: sync_ff2 <- 0, counter still sees old rst=1             -> 0
//     edge 3: counter sees rst=0                                      -> 1
//     edge k: count = k - 2  (k >= 2)
//   => after N = 1000 edges: count = 998 = 24'h0003E6, and since bits 23..18
//      of 998 are all 0, led_n = ~6'b000000 = 6'b111111 (all LEDs off).
//   Additional known answers checked:
//   * N = 2**18 + 2 edges after release: count = 2**18 = 24'h040000, so bit 18
//     (the lowest LED bit) is 1 -> led_n = 6'b111110 (LED1 on). One edge
//     earlier count = 24'h03FFFF -> led_n = 6'b111111. This proves the LED
//     bit mapping (top 6 bits, inverted).
//   * 4-bit instance: 17 edges after release -> count = 15 (4'hF),
//     led_n = 4'b0000; 18 edges -> count = 0 (wrap-around), led_n = 4'b1111.
//   * Reset assertion latency: press the button with count = c; on the next
//     2 edges the counter still increments (c+1, c+2), on the 3rd it is 0.
// =============================================================================

module tb_smoke_counter;

    // -------------------------------------------------------------------------
    // Parameters of the test
    // -------------------------------------------------------------------------
    localparam real    T_HALF_NS  = 18.5;   // half period of the 27 MHz clock (approx.)
    localparam integer SYNC_LAT   = 2;      // synchroniser latency (edges), see header
    localparam integer N_KNOWN    = 1000;   // the edge count requested by ST-FPGA-01
`ifdef INJECT_FAULT
    // Negative self-test of the testbench itself: a deliberately WRONG
    // expected value (999) must make the run end in TEST FAILED + $fatal.
    // Used once by scripts/smoke_fpga.sh to prove the checker can fail.
    localparam [23:0]  EXP_KNOWN  = N_KNOWN[23:0] - SYNC_LAT[23:0] + 24'd1;
`else
    localparam [23:0]  EXP_KNOWN  = N_KNOWN[23:0] - SYNC_LAT[23:0];   // = 998 (CALCULATION)
`endif

    // -------------------------------------------------------------------------
    // Clock, stimulus and DUT outputs
    // -------------------------------------------------------------------------
    reg        clk      = 1'b0;
    reg        btn24_n  = 1'b0;   // S1 for the 24-bit DUT; start PRESSED (reset)
    reg        btn4_n   = 1'b0;   // S1 for the 4-bit DUT;  start PRESSED (reset)
    wire [5:0] led24_n;
    wire [3:0] led4_n;

    integer errors = 0;           // number of failed checks
    integer checks = 0;           // number of checks executed

    // Free-running clock (non-blocking update: no race with DUT processes).
    always #(T_HALF_NS) clk <= ~clk;

    // Default configuration = what is synthesised for the board.
    smoke_counter #(.WIDTH(24), .NUM_LEDS(6)) u_dut24 (
        .clk      (clk),
        .btn_rst_n (btn24_n),
        .led_n    (led24_n)
    );

    // Small instance to observe wrap-around quickly.
    smoke_counter #(.WIDTH(4), .NUM_LEDS(4)) u_dut4 (
        .clk      (clk),
        .btn_rst_n (btn4_n),
        .led_n    (led4_n)
    );

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------
    // Wait for n rising edges, then the following falling edge (outputs settled,
    // and we are at the safe point to change the button input).
    task tick;
        input integer n;
        integer i;
        begin
            for (i = 0; i < n; i = i + 1)
                @(posedge clk);
            @(negedge clk);
        end
    endtask

    // Compare a 24-bit observed value with the expected one and log the result.
    task check24;
        input [511:0] name;   // label (packed string, up to 64 chars)
        input [23:0]  got;
        input [23:0]  exp;
        begin
            checks = checks + 1;
            if (got === exp)
                $display("PASS: %0s : got 0x%06h (%0d), expected 0x%06h (%0d)",
                         name, got, got, exp, exp);
            else begin
                $display("FAIL: %0s : got 0x%06h (%0d), expected 0x%06h (%0d)",
                         name, got, got, exp, exp);
                errors = errors + 1;
            end
        end
    endtask

    // -------------------------------------------------------------------------
    // Watchdog: the whole test needs ~2.7e5 cycles (~10 ms simulated). Abort
    // well after that so a hung test cannot run forever.
    // -------------------------------------------------------------------------
    initial begin
        #(50_000_000.0);  // 50 ms simulated
        $display("FAIL: watchdog timeout");
        $display("TEST FAILED");
        $fatal(1, "watchdog timeout");
    end

    // -------------------------------------------------------------------------
    // Test sequence
    // -------------------------------------------------------------------------
    initial begin
        $display("tb_smoke_counter: ST-FPGA-01 known-answer test start");

        // ---------------------------------------------------------------
        // TC0: hold both buttons pressed for 5 edges -> both counters 0.
        // Expected: count == 0 while reset is applied (and after the
        // synchroniser has filled with 1s).
        // ---------------------------------------------------------------
        tick(5);
        check24("TC0 24-bit count held in reset", u_dut24.count, 24'd0);
        check24("TC0 4-bit count held in reset",  {20'd0, u_dut4.count}, 24'd0);
        check24("TC0 24-bit LEDs all off in reset", {18'd0, led24_n}, {18'd0, 6'b111111});

        // ---------------------------------------------------------------
        // TC1 (the KNOWN ANSWER): release S1 of the 24-bit DUT just after a
        // falling edge, then count exactly N_KNOWN = 1000 rising edges.
        // Expected count = 1000 - 2 = 998 (synchroniser latency 2 edges).
        // Also check the edge-by-edge start: 0, 0, 1 after edges 1, 2, 3.
        // ---------------------------------------------------------------
        btn24_n = 1'b1;                        // release (we are at a negedge)
        tick(1);
        check24("TC1 edge 1 after release (sync stage 1)", u_dut24.count, 24'd0);
        tick(1);
        check24("TC1 edge 2 after release (sync stage 2)", u_dut24.count, 24'd0);
        tick(1);
        check24("TC1 edge 3 after release (first increment)", u_dut24.count, 24'd1);
        tick(N_KNOWN - 3);                     // total edges since release = 1000
        check24("TC1 KNOWN ANSWER: count after 1000 edges", u_dut24.count, EXP_KNOWN);
        check24("TC1 LEDs after 1000 edges (top bits 0 -> all off)",
                {18'd0, led24_n}, {18'd0, 6'b111111});

        // ---------------------------------------------------------------
        // TC2: LED mapping. Continue to 2**18 + 2 - 1 edges since release
        // (count = 0x03FFFF, LEDs still off) and then one more edge
        // (count = 0x040000 -> bit 18 = 1 -> led_n[0] = 0).
        // ---------------------------------------------------------------
        tick((1 << 18) + 2 - 1 - N_KNOWN);
        check24("TC2 count at 2^18+1 edges", u_dut24.count, 24'h03FFFF);
        check24("TC2 LEDs at 0x03FFFF (all off)", {18'd0, led24_n}, {18'd0, 6'b111111});
        tick(1);
        check24("TC2 count at 2^18+2 edges", u_dut24.count, 24'h040000);
        check24("TC2 LEDs at 0x040000 (LED1 = led_n[0] on)",
                {18'd0, led24_n}, {18'd0, 6'b111110});

        // ---------------------------------------------------------------
        // TC3: reset assertion latency on the 24-bit DUT. Press S1 with
        // count = c = 0x040000; expected c+1, c+2, then 0 on the 3rd edge,
        // and 0 again on the 4th (still pressed).
        // ---------------------------------------------------------------
        btn24_n = 1'b0;                        // press
        tick(1);
        check24("TC3 edge 1 after press (still counting)", u_dut24.count, 24'h040001);
        tick(1);
        check24("TC3 edge 2 after press (still counting)", u_dut24.count, 24'h040002);
        tick(1);
        check24("TC3 edge 3 after press (cleared)", u_dut24.count, 24'h000000);
        tick(1);
        check24("TC3 edge 4 after press (held)", u_dut24.count, 24'h000000);

        // ---------------------------------------------------------------
        // TC4: wrap-around on the 4-bit DUT. Release, then after
        // 17 edges count = 17-2 = 15 (all LEDs on: led_n = 4'b0000),
        // after 18 edges count = 0 (wrapped, led_n = 4'b1111),
        // after 19 edges count = 1.
        // ---------------------------------------------------------------
        btn4_n = 1'b1;                         // release
        tick(17);
        check24("TC4 4-bit count after 17 edges (=15)", {20'd0, u_dut4.count}, 24'd15);
        check24("TC4 4-bit LEDs at 15 (all on)", {20'd0, led4_n}, {20'd0, 4'b0000});
        tick(1);
        check24("TC4 4-bit WRAP 15 -> 0 after 18 edges", {20'd0, u_dut4.count}, 24'd0);
        check24("TC4 4-bit LEDs at 0 (all off)", {20'd0, led4_n}, {20'd0, 4'b1111});
        tick(1);
        check24("TC4 4-bit count after 19 edges (=1)", {20'd0, u_dut4.count}, 24'd1);

        // ---------------------------------------------------------------
        // Summary
        // ---------------------------------------------------------------
        $display("tb_smoke_counter: %0d checks, %0d errors", checks, errors);
        if (errors == 0) begin
            $display("TEST PASSED");
            $finish;
        end else begin
            $display("TEST FAILED");
            $fatal(1, "%0d check(s) failed", errors);
        end
    end

endmodule

`default_nettype wire
