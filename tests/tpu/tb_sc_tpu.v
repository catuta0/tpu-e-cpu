// =============================================================================
// File    : tests/tpu/tb_sc_tpu.v
// Purpose : System-level self-checking testbench of design/rtl/tpu/sc_tpu.v
//           (task RTL-TPU). A bus-functional model (BFM) drives the native
//           valid/ready bus exactly like the RV32I CPU would (ARCHITECTURE.md 3)
//           and uses only the register map of spec 5.4.
//
// Compile-time parameter : RNG_MODE (iverilog -P tb_sc_tpu.RNG_MODE=<m>), passed
//                          to the DUT; checked against the "mode" field of every
//                          vector.
// Plusargs               : +DATA=<dir>   directory of the SW-01a files (default
//                                        sim/data)
//                          +DIRECTED     run the directed tests D1..D9 first
//                          +VEC1=<file> .. +VEC6=<file>  golden vector files
//                                        (format: sim/data/README.md section 2)
//                          +CLAMP        re-run every K=4 / K=10 vector with an
//                                        out-of-range raw LOG2_L (0..3 / 11..15)
//
// BUS PROTOCOL CHECKER (always active, every cycle):
//   P1 mem_ready only while mem_valid (ARCHITECTURE.md 3, INTERFACES bus).
//   P2 mem_ready is a one-cycle pulse (never high in two consecutive cycles;
//      the BFM issues back-to-back transactions, so a second pulse would be
//      a protocol error / double completion).
//   P3 no hang: every transaction completes within 100 cycles.
//   P4 mem_rdata has no X/Z when mem_ready on a read.
//   P5 (design property of sc_tpu.v) mem_rdata = 0 when mem_ready = 0.
//
// DIRECTED TESTS (+DIRECTED), each prints PASS/FAIL:
//   D1 reset values (rev A.1): STATUS = 0, RESULT = 0, CYCLES = 0,
//      CONFIG = 0x08, SCORE[0..15] = HIDDEN[0..3] = 0, CTRL reads 0.
//   D2 PARAMS = {0x01, 6'b0, RNG_MODE, IL=8, NL=16}.
//   D3 CONFIG: write raw LOG2_L 0..15 with various ACT_SHIFT, read back the
//      clamped value (0..3 -> 4, 11..15 -> 10) and ACT_SHIFT unchanged.
//   D4 buffers: INPUT / BIAS / WEIGHT word writes, byte-strobe writes, read
//      back; BIAS read-back sign-extended; unmapped offsets read 0 and ignore
//      writes; read-only registers ignore writes.
//   D5 analytic, RNG-independent check: all weights and inputs = code 0 ->
//      every SNG bit is 0 -> every XNOR is 1 -> acc_j = 64 L exactly, D = 64 L.
//      Biases b_j = -8192 + d_j make Dp_j = floor(d_j L/128) small, so HIDDEN
//      exercises the floor and both clips; expected values computed here with
//      explicit floor division (independent of the RTL and of the Python model).
//   D6 inference A (pset 0, image of input.hex, K = 8, s = 0) - the FIRST
//      inference after reset: while BUSY, after layer 1 has written HIDDEN
//      internally, CPU reads of HIDDEN/SCORE return 0 (rev A.1 "0 until the
//      first inference completes"). STATUS reads BUSY=1, DONE=0 while busy.
//   D7 inference B = same data as A, with bus abuse while BUSY: START written
//      again (must be ignored: one BUSY pulse only, CYCLES unchanged), writes
//      to INPUT/BIAS/WEIGHT/CONFIG (ignored: read back after DONE unchanged,
//      results identical to A), reads of WEIGHT/INPUT/BIAS issued while the
//      controller owns the memory ports (stall, correct data).
//      Also: DONE cleared by START (STATUS read right after START = BUSY).
//   D8 CYCLES == number of cycles BUSY was 1 measured by this TB (hierarchical
//      probe dut.busy) == formula 10*2^K + 368 (sc_tpu_ctrl.v), for K=8.
//   D9 SCORE/HIDDEN readable after DONE (non-zero), RESULT in 0..9.
//
// VECTOR TESTS (+VECn): for every vector: (re)load WEIGHT/BIAS if the parameter
//   set changes (via the bus), write INPUT[0..15], CONFIG, START, poll STATUS
//   until DONE, read HIDDEN[0..3], SCORE[0..15], RESULT, CYCLES; compare
//   HIDDEN, SCORE, RESULT bit-exactly with the golden model and CYCLES with
//   the formula and the measured busy count. Mismatch counts per file.
//
// Negative check: -DINJECT_FAULT flips bit 0 of the expected SCORE[0] of every
// vector: the TB must report mismatches and TEST FAILED.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_sc_tpu;

    parameter integer RNG_MODE = 1;
    localparam integer NL = 16;
    localparam integer IL = 8;

    // ---------------------------------------------------------------- clock/reset
    reg clk = 1'b0;
    always #18.5 clk <= ~clk;       // 27.03 MHz (period 37 ns)
    reg rst = 1'b1;

    // ---------------------------------------------------------------- bus
    reg         mem_valid = 1'b0;
    reg  [11:0] mem_addr  = 12'd0;
    reg  [31:0] mem_wdata = 32'd0;
    reg  [3:0]  mem_wstrb = 4'd0;
    wire        mem_ready;
    wire [31:0] mem_rdata;

    sc_tpu #(.NL(NL), .IL(IL), .RNG_MODE(RNG_MODE)) dut (
        .clk(clk), .rst(rst),
        .mem_valid(mem_valid), .mem_addr(mem_addr), .mem_wdata(mem_wdata),
        .mem_wstrb(mem_wstrb), .mem_ready(mem_ready), .mem_rdata(mem_rdata));

    // ---------------------------------------------------------------- registers
    // Offsets as integers: address arithmetic in the TB is done in 32 bits and
    // the BFM takes the low 12 bits (the TPU window offset).
    localparam integer A_CTRL   = 32'h000, A_STATUS = 32'h004, A_CONFIG = 32'h008,
                       A_RESULT = 32'h00C, A_CYCLES = 32'h010, A_PARAMS = 32'h014,
                       A_INPUT  = 32'h040, A_SCORE  = 32'h080, A_HIDDEN = 32'h0C0,
                       A_BIAS   = 32'h100, A_WEIGHT = 32'h800;

    integer errors = 0;           // all failures (directed + vectors + protocol)
    integer proto_errors = 0;

    // ---------------------------------------------------------------- watchdog
    initial begin
        #(64'd40_000_000_000);    // 40 s simulated time
        $display("FAIL: watchdog timeout");
        $display("TEST FAILED");
        $fatal(1, "watchdog");
    end

    // =========================================================================
    // Bus protocol checker
    // =========================================================================
    reg     ready_q = 1'b0;
    integer wait_cnt = 0;
    integer max_wait = 0;          // longest valid->ready time observed (cycles)
    always @(posedge clk) begin
        if (!rst) begin
            if (mem_ready && !mem_valid) begin
                proto_errors = proto_errors + 1;
                $display("FAIL: P1 mem_ready without mem_valid at %0t", $time);
            end
            if (mem_ready && ready_q) begin
                proto_errors = proto_errors + 1;
                $display("FAIL: P2 mem_ready high for 2 consecutive cycles at %0t", $time);
            end
            if (mem_ready && mem_wstrb == 4'd0 && ((^mem_rdata) === 1'bx)) begin
                proto_errors = proto_errors + 1;
                $display("FAIL: P4 X/Z on mem_rdata at %0t", $time);
            end
            if (!mem_ready && mem_rdata !== 32'd0) begin
                proto_errors = proto_errors + 1;
                $display("FAIL: P5 mem_rdata != 0 outside mem_ready at %0t", $time);
            end
            if (mem_valid && !mem_ready) begin
                wait_cnt = wait_cnt + 1;
                if (wait_cnt == 100) begin
                    proto_errors = proto_errors + 1;
                    $display("FAIL: P3 transaction not completed within 100 cycles at %0t", $time);
                end
            end else if (mem_valid && mem_ready) begin
                if (wait_cnt + 1 > max_wait) max_wait = wait_cnt + 1;
                wait_cnt = 0;
            end else begin
                wait_cnt = 0;
            end
        end
        ready_q <= mem_ready;
    end

    // =========================================================================
    // BFM (PicoRV32-like): drive at a clock edge, hold until mem_ready is seen,
    // then either release mem_valid in the next cycle or (when the next task
    // is called immediately) start the next transaction back-to-back.
    // =========================================================================
    integer last_latency;          // cycles from request to mem_ready (incl.)

    task bus_xfer;
        input  integer addr;
        input  [31:0] wdata;
        input  [3:0]  wstrb;
        output [31:0] rdata;
        begin
            mem_valid <= 1'b1;
            mem_addr  <= addr[11:0];
            mem_wdata <= wdata;
            mem_wstrb <= wstrb;
            last_latency = 0;
            @(posedge clk);
            last_latency = 1;
            while (mem_ready !== 1'b1) begin
                @(posedge clk);
                last_latency = last_latency + 1;
            end
            rdata = mem_rdata;
            mem_valid <= 1'b0;     // overridden if another transfer follows at once
            mem_wstrb <= 4'd0;
        end
    endtask

    reg [31:0] dummy;
    task bus_write;
        input integer addr;
        input [31:0] data;
        begin
            bus_xfer(addr, data, 4'b1111, dummy);
        end
    endtask

    task bus_write_strb;
        input integer addr;
        input [31:0] data;
        input [3:0]  strb;
        begin
            bus_xfer(addr, data, strb, dummy);
        end
    endtask

    task bus_read;
        input  integer addr;
        output [31:0] data;
        begin
            bus_xfer(addr, 32'd0, 4'b0000, data);
        end
    endtask

    task idle;
        input integer n;
        begin
            repeat (n) @(posedge clk);
        end
    endtask

    // Read and compare with an expected value.
    reg [31:0] rd;
    task expect_read;
        input integer    addr;
        input [31:0]     exp;
        input [8*48-1:0] what;
        begin
            bus_read(addr, rd);
            if (rd !== exp) begin
                errors = errors + 1;
                $display("FAIL: %0s: read 0x%03h = 0x%08h, expected 0x%08h", what, addr, rd, exp);
            end
        end
    endtask

    // =========================================================================
    // Busy monitor: counts BUSY cycles of the current inference and BUSY pulses.
    // =========================================================================
    reg     busy_q = 1'b0;
    integer busy_cycles = 0;       // cycles with BUSY = 1 in the last/current pulse
    integer busy_pulses = 0;       // number of 0->1 transitions since last clear
    always @(posedge clk) begin
        if (dut.busy && !busy_q) begin
            busy_pulses = busy_pulses + 1;
            busy_cycles = 0;
        end
        if (dut.busy) busy_cycles = busy_cycles + 1;
        busy_q <= dut.busy;
    end

    // =========================================================================
    // Data: parameter sets (weights/bias files) and helpers
    // =========================================================================
    reg [8*256-1:0] data_dir;
    reg [8*256-1:0] fname;
    reg [31:0] pw [0:511];         // weight RAM image of the current pset
    reg [15:0] pb [0:31];          // biases of the current pset
    reg [31:0] img [0:15];         // input.hex
    integer cur_pset = -1;
    integer n;

    task load_pset;                // load weights + biases of pset p through the bus
        input integer p;
        begin
            if (p != cur_pset) begin
                if (p == 0) $sformat(fname, "%0s/weights.hex", data_dir);
                else        $sformat(fname, "%0s/corner/pset%0d_weights.hex", data_dir, p);
                $readmemh(fname, pw);
                if (p == 0) $sformat(fname, "%0s/bias.hex", data_dir);
                else        $sformat(fname, "%0s/corner/pset%0d_bias.hex", data_dir, p);
                $readmemh(fname, pb);
                for (n = 0; n < 512; n = n + 1) bus_write(A_WEIGHT + 4 * n, pw[n]);
                for (n = 0; n < 32; n = n + 1)  bus_write(A_BIAS + 4 * n, {16'd0, pb[n]});
                cur_pset = p;
            end
        end
    endtask

    // Run one inference: START, poll STATUS until DONE. Returns CYCLES read.
    reg [31:0] st;
    task run_inference;
        output [31:0] cyc;
        begin
            busy_pulses = 0;
            bus_write(A_CTRL, 32'd1);
            st = 32'd1;
            while (st[1] !== 1'b1) bus_read(A_STATUS, st);
            if (st[0] !== 1'b0) begin
                errors = errors + 1;
                $display("FAIL: STATUS 0x%08h: DONE with BUSY", st);
            end
            bus_read(A_CYCLES, cyc);
        end
    endtask

    function integer expected_cycles;
        input integer k;
        begin
            // sc_tpu_ctrl.v: (T1+T2)*(NL*IL/4 + 1 + L) + 2*(NL+3)
            expected_cycles = (64 / IL + 16 / IL) * (NL * IL / 4 + 1 + (1 << k)) + 2 * (NL + 3);
        end
    endfunction

    function signed [63:0] floor_div;   // floor(a/b), b > 0 (independent of RTL)
        input signed [63:0] a;
        input signed [63:0] b;
        reg   signed [63:0] q;
        begin
            q = a / b;
            if ((a % b) != 0 && a < 0) q = q - 1;
            floor_div = q;
        end
    endfunction

    // =========================================================================
    // Directed tests
    // =========================================================================
    reg  [31:0] cyc_a, cyc_b, v, res_a;
    reg  [31:0] hid_a [0:3];
    reg  [31:0] sco_a [0:15];
    integer e0, j, raw, sh, k_eff, lat, d5_k, d5_s;
    reg signed [63:0] L64, Bj, Dpj, uj, hj, j64;
    integer bint;
    reg  [7:0]  exp_code;
    reg  [15:0] b16;

    task directed_tests;
        begin
            // ---------------- D1 reset values ---------------------------------
            e0 = errors;
            expect_read(A_STATUS, 32'd0, "D1 STATUS reset");
            expect_read(A_RESULT, 32'd0, "D1 RESULT reset");
            expect_read(A_CYCLES, 32'd0, "D1 CYCLES reset");
            expect_read(A_CONFIG, 32'h08, "D1 CONFIG reset");
            expect_read(A_CTRL,   32'd0, "D1 CTRL reads 0");
            for (n = 0; n < 16; n = n + 1) expect_read(A_SCORE + 4 * n, 32'd0, "D1 SCORE reset");
            for (n = 0; n < 4; n = n + 1)  expect_read(A_HIDDEN + 4 * n, 32'd0, "D1 HIDDEN reset");
            if (errors == e0) $display("PASS: D1 reset values STATUS/RESULT/CYCLES/SCORE/HIDDEN = 0, CONFIG = 0x08, CTRL reads 0");
            else              $display("FAIL: D1 reset values");

            // ---------------- D2 PARAMS ----------------------------------------
            e0 = errors;
            v = {8'h01, 6'd0, RNG_MODE[1:0], 8'd8, 8'd16};
            expect_read(A_PARAMS, v, "D2 PARAMS");
            if (errors == e0) $display("PASS: D2 PARAMS = 0x%08h (NL=16, IL=8, RNG_MODE=%0d, version 0x01)", v, RNG_MODE);
            else              $display("FAIL: D2 PARAMS");

            // ---------------- D3 CONFIG clamp ----------------------------------
            e0 = errors;
            for (raw = 0; raw < 16; raw = raw + 1) begin
                sh = raw % 8;
                bus_write(A_CONFIG, {25'd0, sh[2:0], raw[3:0]});
                k_eff = (raw < 4) ? 4 : (raw > 10) ? 10 : raw;
                expect_read(A_CONFIG, {25'd0, sh[2:0], k_eff[3:0]}, "D3 CONFIG clamp");
            end
            bus_write(A_CONFIG, 32'h0000_0008);
            if (errors == e0) $display("PASS: D3 CONFIG LOG2_L raw 0..15 read back clamped to 4..10, ACT_SHIFT kept");
            else              $display("FAIL: D3 CONFIG clamp");

            // ---------------- D4 buffers, strobes, unmapped, read-only ----------
            e0 = errors;
            for (n = 0; n < 16; n = n + 1) bus_write(A_INPUT + 4 * n, 32'h0101_0101 * n + 32'h1020_3040);
            for (n = 0; n < 16; n = n + 1) expect_read(A_INPUT + 4 * n, 32'h0101_0101 * n + 32'h1020_3040, "D4 INPUT word");
            bus_write_strb(A_INPUT + 32'h008, 32'hAABB_CCDD, 4'b0101);    // bytes 0 and 2
            expect_read(A_INPUT + 32'h008, (32'h0202_0202 + 32'h1020_3040) & 32'hFF00_FF00 | 32'h00BB_00DD, "D4 INPUT byte strobes");
            bus_write(A_BIAS + 32'h004, 32'h1234_8001);                    // bits [31:16] not stored
            expect_read(A_BIAS + 32'h004, 32'hFFFF_8001, "D4 BIAS sign-extended");
            bus_write(A_BIAS + 32'h07C, 32'h0000_7FFF);
            expect_read(A_BIAS + 32'h07C, 32'h0000_7FFF, "D4 BIAS[31]");
            bus_write_strb(A_BIAS + 32'h07C, 32'h0000_8000, 4'b0010);      // high byte only
            expect_read(A_BIAS + 32'h07C, 32'hFFFF_80FF, "D4 BIAS byte strobe");
            bus_write(A_WEIGHT + 32'h000, 32'hDEAD_BEEF);
            bus_write(A_WEIGHT + 32'h7FC, 32'h0123_4567);
            bus_write_strb(A_WEIGHT + 32'h7FC, 32'hFFFF_FFFF, 4'b1000);
            expect_read(A_WEIGHT + 32'h000, 32'hDEAD_BEEF, "D4 WEIGHT[0]");
            expect_read(A_WEIGHT + 32'h7FC, 32'hFF23_4567, "D4 WEIGHT[511] byte strobe");
            // unmapped offsets inside the window: read 0, writes ignored, no hang
            bus_write(32'h018, 32'hFFFF_FFFF); expect_read(32'h018, 32'd0, "D4 unmapped 0x018");
            bus_write(32'h03C, 32'hFFFF_FFFF); expect_read(32'h03C, 32'd0, "D4 unmapped 0x03C");
            bus_write(32'h0D0, 32'hFFFF_FFFF); expect_read(32'h0D0, 32'd0, "D4 unmapped 0x0D0");
            bus_write(32'h0FC, 32'hFFFF_FFFF); expect_read(32'h0FC, 32'd0, "D4 unmapped 0x0FC");
            bus_write(32'h180, 32'hFFFF_FFFF); expect_read(32'h180, 32'd0, "D4 unmapped 0x180");
            bus_write(32'h7FC, 32'hFFFF_FFFF); expect_read(32'h7FC, 32'd0, "D4 unmapped 0x7FC");
            // read-only registers ignore writes
            bus_write(A_STATUS, 32'hFFFF_FFFF); expect_read(A_STATUS, 32'd0, "D4 STATUS is read-only");
            bus_write(A_RESULT, 32'hFFFF_FFFF); expect_read(A_RESULT, 32'd0, "D4 RESULT is read-only");
            bus_write(A_CYCLES, 32'hFFFF_FFFF); expect_read(A_CYCLES, 32'd0, "D4 CYCLES is read-only");
            bus_write(A_PARAMS, 32'hFFFF_FFFF); expect_read(A_PARAMS, {8'h01, 6'd0, RNG_MODE[1:0], 8'd8, 8'd16}, "D4 PARAMS is read-only");
            bus_write(A_SCORE,  32'hFFFF_FFFF); expect_read(A_SCORE, 32'd0, "D4 SCORE is read-only");
            bus_write(A_HIDDEN, 32'hFFFF_FFFF); expect_read(A_HIDDEN, 32'd0, "D4 HIDDEN is read-only");
            expect_read(A_STATUS, 32'd0, "D4 no START from other writes");
            if (errors == e0) $display("PASS: D4 INPUT/BIAS/WEIGHT read-back incl. byte strobes, BIAS sign-extension, unmapped = 0, read-only regs");
            else              $display("FAIL: D4 buffers/strobes");

            // ---------------- D5/D6 inference A (first inference) ------------------
            // D6 needs the very first inference: pset 0, image = input.hex, K=8, s=0.
            e0 = errors;
            load_pset(0);
            $sformat(fname, "%0s/input.hex", data_dir);
            $readmemh(fname, img);
            for (n = 0; n < 16; n = n + 1) bus_write(A_INPUT + 4 * n, img[n]);
            bus_write(A_CONFIG, 32'h0000_0008);
            busy_pulses = 0;
            bus_write(A_CTRL, 32'd1);
            expect_read(A_STATUS, 32'h1, "D6 STATUS while busy (BUSY=1, DONE=0)");
            // wait until layer 1 has written HIDDEN internally
            while (dut.u_ctrl.layer2 !== 1'b1) @(posedge clk);
            if (dut.hidden === 128'd0) begin
                errors = errors + 1;
                $display("FAIL: D6 precondition: internal HIDDEN still 0 after layer 1");
            end
            for (n = 0; n < 4; n = n + 1)  expect_read(A_HIDDEN + 4 * n, 32'd0, "D6 HIDDEN = 0 before first DONE");
            for (n = 0; n < 16; n = n + 1) expect_read(A_SCORE + 4 * n, 32'd0, "D6 SCORE = 0 before first DONE");
            st = 32'd1;
            while (st[1] !== 1'b1) bus_read(A_STATUS, st);
            bus_read(A_CYCLES, cyc_a);
            bus_read(A_RESULT, res_a);
            for (n = 0; n < 4; n = n + 1)  bus_read(A_HIDDEN + 4 * n, hid_a[n]);
            for (n = 0; n < 16; n = n + 1) bus_read(A_SCORE + 4 * n, sco_a[n]);
            if (errors == e0) $display("PASS: D6 first inference: BUSY=1/DONE=0 while busy, HIDDEN/SCORE read 0 until first DONE (internal HIDDEN already written)");
            else              $display("FAIL: D6 first inference");

            // ---------------- D8 CYCLES ------------------------------------------
            e0 = errors;
            if (cyc_a != busy_cycles || cyc_a != expected_cycles(8) || busy_pulses != 1) begin
                errors = errors + 1;
                $display("FAIL: D8 CYCLES reg %0d, measured busy cycles %0d, formula %0d, busy pulses %0d",
                         cyc_a, busy_cycles, expected_cycles(8), busy_pulses);
            end else
                $display("PASS: D8 CYCLES = %0d = measured BUSY cycles %0d = formula 10*2^8+368 (K=8)", cyc_a, busy_cycles);

            // ---------------- D9 results present ---------------------------------
            if (res_a > 9 || (hid_a[0] | hid_a[1] | hid_a[2] | hid_a[3]) == 32'd0) begin
                errors = errors + 1;
                $display("FAIL: D9 RESULT %0d / HIDDEN all zero after DONE", res_a);
            end else
                $display("PASS: D9 after DONE: RESULT = %0d, HIDDEN[0] = 0x%08h, SCORE[0] = 0x%08h", res_a, hid_a[0], sco_a[0]);

            // ---------------- D7 inference B with bus abuse while BUSY -----------
            e0 = errors;
            busy_pulses = 0;
            bus_write(A_CTRL, 32'd1);
            expect_read(A_STATUS, 32'h1, "D7 DONE cleared by START");
            // reads of the shared memories while the controller owns the ports
            while (dut.port_busy !== 1'b1) @(posedge clk);
            bus_read(A_WEIGHT + 4 * 37, v); lat = last_latency;
            if (v !== pw[37]) begin errors = errors + 1; $display("FAIL: D7 WEIGHT read while busy 0x%08h exp 0x%08h", v, pw[37]); end
            while (dut.port_busy !== 1'b1) @(posedge clk);
            expect_read(A_INPUT + 4 * 5, img[5], "D7 INPUT read while busy");
            while (dut.port_busy !== 1'b1) @(posedge clk);
            expect_read(A_BIAS + 4 * 3, {{16{pb[3][15]}}, pb[3]}, "D7 BIAS read while busy");
            // writes that must be ignored
            bus_write(A_CTRL, 32'd1);                    // START while BUSY
            for (n = 0; n < 16; n = n + 1) bus_write(A_INPUT + 4 * n, 32'hFFFF_FFFF);
            for (n = 0; n < 32; n = n + 1) bus_write(A_BIAS + 4 * n, 32'h0000_7FFF);
            for (n = 0; n < 512; n = n + 37) bus_write(A_WEIGHT + 4 * n, 32'h0000_0000);
            bus_write(A_CONFIG, 32'h0000_0074);
            bus_write(A_CTRL, 32'd1);                    // START while BUSY again
            if (dut.busy !== 1'b1) begin                 // the abuse must happen while BUSY
                errors = errors + 1;
                $display("FAIL: D7 precondition: inference finished before the bus abuse sequence");
            end
            st = 32'd1;
            while (st[1] !== 1'b1) bus_read(A_STATUS, st);
            bus_read(A_CYCLES, cyc_b);
            expect_read(A_RESULT, res_a, "D7 RESULT identical to A");
            for (n = 0; n < 4; n = n + 1)  expect_read(A_HIDDEN + 4 * n, hid_a[n], "D7 HIDDEN identical to A");
            for (n = 0; n < 16; n = n + 1) expect_read(A_SCORE + 4 * n, sco_a[n], "D7 SCORE identical to A");
            expect_read(A_CONFIG, 32'h0000_0008, "D7 CONFIG write while busy ignored");
            for (n = 0; n < 16; n = n + 1) expect_read(A_INPUT + 4 * n, img[n], "D7 INPUT write while busy ignored");
            for (n = 0; n < 32; n = n + 1) expect_read(A_BIAS + 4 * n, {{16{pb[n][15]}}, pb[n]}, "D7 BIAS write while busy ignored");
            for (n = 0; n < 512; n = n + 37) expect_read(A_WEIGHT + 4 * n, pw[n], "D7 WEIGHT write while busy ignored");
            if (cyc_b != cyc_a || busy_pulses != 1 || cyc_b != busy_cycles) begin
                errors = errors + 1;
                $display("FAIL: D7 START while busy: CYCLES %0d vs %0d, busy pulses %0d", cyc_b, cyc_a, busy_pulses);
            end
            if (lat <= 3) begin
                errors = errors + 1;
                $display("FAIL: D7 weight read during port use did not stall (latency %0d)", lat);
            end
            if (errors == e0) $display("PASS: D7 DONE cleared by START; START/INPUT/BIAS/WEIGHT/CONFIG writes while BUSY ignored (1 busy pulse, CYCLES %0d unchanged, results identical); memory reads while busy stall (%0d cycles) and return correct data", cyc_b, lat);
            else              $display("FAIL: D7 busy behaviour");

            // ---------------- D5 analytic zero-code test --------------------------
            // weights = inputs = code 0 -> every SNG bit 0 -> XNOR = 1 -> acc = 64 L.
            e0 = errors;
            for (n = 0; n < 512; n = n + 1) bus_write(A_WEIGHT + 4 * n, 32'd0);
            for (n = 0; n < 16; n = n + 1)  bus_write(A_INPUT + 4 * n, 32'd0);
            for (j = 0; j < 16; j = j + 1) begin
                bint = -8192 + (j - 8) * 3;          // b = -8192 + d_j, d_j = 3(j-8)
                b16  = bint[15:0];
                bus_write(A_BIAS + 4 * j, {16'd0, b16});
            end
            cur_pset = -1;                           // RAM no longer holds a pset
            for (d5_k = 4; d5_k <= 10; d5_k = d5_k + 3)
                for (d5_s = 0; d5_s <= 7; d5_s = d5_s + 7) begin
                    bus_write(A_CONFIG, {25'd0, d5_s[2:0], d5_k[3:0]});
                    run_inference(v);
                    L64 = 64'sd1 <<< d5_k;
                    for (j = 0; j < 16; j = j + 1) begin
                        j64 = {{32{j[31]}}, j};
                        Bj  = floor_div((-64'sd8192 + (j64 - 64'sd8) * 64'sd3) * L64, 64'sd128);
                        Dpj = 64 * L64 + Bj;                       // D = 64 L exactly
                        uj  = floor_div(Dpj * (64'sd1 <<< (d5_s + 7)), L64);
                        hj  = (uj < 0) ? 0 : (uj > 127) ? 127 : uj;
                        exp_code = 8'd128 + hj[7:0];
                        bus_read(A_HIDDEN + 4 * (j / 4), rd);
                        if (rd[8 * (j % 4) +: 8] !== exp_code) begin
                            errors = errors + 1;
                            $display("FAIL: D5 K=%0d s=%0d HIDDEN[%0d] = 0x%02h, expected 0x%02h (Dp=%0d)",
                                     d5_k, d5_s, j, rd[8 * (j % 4) +: 8], exp_code, Dpj);
                        end
                    end
                end
            if (errors == e0) $display("PASS: D5 analytic zero-code test (acc = 64L, Dp = floor(d_j L/128)), K = 4/7/10, s = 0/7, 16 neurons each");
            else              $display("FAIL: D5 analytic zero-code test");
            bus_write(A_CONFIG, 32'h0000_0008);
        end
    endtask

    // =========================================================================
    // Golden vector runner
    // =========================================================================
    integer fd, c, r, w;
    reg [8*1024-1:0] line;
    reg [31:0] f_pset, f_k, f_s, f_mode, f_idx, f_label, f_result;
    reg [31:0] f_in  [0:15];
    reg [31:0] f_hid [0:3];
    reg [31:0] f_sco [0:15];
    integer tot_vec = 0, tot_bad = 0, tot_fields = 0, tot_clamp = 0;
    integer do_clamp;

    task apply_vector;                       // run the current vector with raw LOG2_L
        input  integer rawk;
        output integer bad_fields;
        reg [31:0] cyc, got;
        integer q;
        begin
            bad_fields = 0;
            load_pset(f_pset);
            for (q = 0; q < 16; q = q + 1) bus_write(A_INPUT + 4 * q, f_in[q]);
            bus_write(A_CONFIG, {25'd0, f_s[2:0], rawk[3:0]});
            run_inference(cyc);
            for (q = 0; q < 4; q = q + 1) begin
                bus_read(A_HIDDEN + 4 * q, got);
                if (got !== f_hid[q]) begin
                    bad_fields = bad_fields + 1;
                    if (tot_bad < 20) $display("FAIL: vec pset %0d idx %0d K %0d s %0d: HIDDEN[%0d] 0x%08h exp 0x%08h",
                                               f_pset, f_idx, f_k, f_s, q, got, f_hid[q]);
                end
            end
            for (q = 0; q < 16; q = q + 1) begin
                bus_read(A_SCORE + 4 * q, got);
`ifdef INJECT_FAULT
                if (q == 0) got = got ^ 32'd1;
`endif
                if (got !== f_sco[q]) begin
                    bad_fields = bad_fields + 1;
                    if (tot_bad < 20) $display("FAIL: vec pset %0d idx %0d K %0d s %0d: SCORE[%0d] 0x%08h exp 0x%08h",
                                               f_pset, f_idx, f_k, f_s, q, got, f_sco[q]);
                end
            end
            bus_read(A_RESULT, got);
            if (got !== f_result) begin
                bad_fields = bad_fields + 1;
                if (tot_bad < 20) $display("FAIL: vec pset %0d idx %0d: RESULT %0d exp %0d", f_pset, f_idx, got, f_result);
            end
            if (cyc != expected_cycles(f_k) || cyc != busy_cycles || busy_pulses != 1) begin
                bad_fields = bad_fields + 1;
                if (tot_bad < 20) $display("FAIL: vec pset %0d idx %0d: CYCLES %0d, measured %0d, formula %0d",
                                           f_pset, f_idx, cyc, busy_cycles, expected_cycles(f_k));
            end
        end
    endtask

    task run_vector_file;
        input [8*256-1:0] vf;
        integer nvec, nbad, nfields, bf, rk, nclamp;
        begin
            nvec = 0; nbad = 0; nfields = 0; nclamp = 0;
            fd = $fopen(vf, "r");
            if (fd == 0) begin
                errors = errors + 1;
                $display("FAIL: cannot open vector file %0s", vf);
            end else begin
                c = $fgetc(fd);
                while (c != -1) begin
                    if (c == "#") begin
                        r = $fgets(line, fd);
                    end else if (c == "\n" || c == " " || c == "\r") begin
                        // skip blank
                    end else begin
                        r = $ungetc(c, fd);
                        r = $fscanf(fd, "%h %h %h %h %h %h", f_pset, f_k, f_s, f_mode, f_idx, f_label);
                        for (w = 0; w < 16; w = w + 1) r = $fscanf(fd, "%h", f_in[w]);
                        for (w = 0; w < 4;  w = w + 1) r = $fscanf(fd, "%h", f_hid[w]);
                        for (w = 0; w < 16; w = w + 1) r = $fscanf(fd, "%h", f_sco[w]);
                        r = $fscanf(fd, "%h", f_result);
                        if (r != 1) begin
                            errors = errors + 1;
                            $display("FAIL: parse error in %0s after vector %0d", vf, nvec);
                        end
                        if (f_mode != RNG_MODE) begin
                            errors = errors + 1;
                            $display("FAIL: vector mode %0d but DUT RNG_MODE %0d (%0s)", f_mode, RNG_MODE, vf);
                        end
                        apply_vector(f_k, bf);
                        nvec = nvec + 1;
                        nfields = nfields + bf;
                        if (bf != 0) nbad = nbad + 1;
                        // Clamp re-run: raw LOG2_L outside 4..10 must give identical results.
                        if ((do_clamp != 0) && (f_k == 4 || f_k == 10)) begin
                            rk = (f_k == 4) ? (nvec % 4) : (11 + nvec % 5);
                            apply_vector(rk, bf);
                            nclamp = nclamp + 1;
                            nfields = nfields + bf;
                            if (bf != 0) nbad = nbad + 1;
                        end
                    end
                    c = $fgetc(fd);
                end
                $fclose(fd);
                $display("%0s: VECFILE %0s : vectors %0d (+%0d clamp re-runs), mismatching inferences %0d, mismatching fields %0d",
                         (nfields == 0 && nvec > 0) ? "PASS" : "FAIL", vf, nvec, nclamp, nbad, nfields);
                if (nvec == 0) errors = errors + 1;
                tot_vec = tot_vec + nvec; tot_bad = tot_bad + nbad;
                tot_fields = tot_fields + nfields; tot_clamp = tot_clamp + nclamp;
                errors = errors + nfields;
            end
        end
    endtask

    // =========================================================================
    // Main
    // =========================================================================
    reg [8*256-1:0] vfile;
    initial begin
        if (!$value$plusargs("DATA=%s", data_dir)) data_dir = "sim/data";
        do_clamp = $test$plusargs("CLAMP");
        $display("INFO: tb_sc_tpu RNG_MODE=%0d DATA=%0s", RNG_MODE, data_dir);
        repeat (4) @(posedge clk);
        rst <= 1'b0;
        @(posedge clk);

        if ($test$plusargs("DIRECTED")) directed_tests;

        if ($value$plusargs("VEC1=%s", vfile)) run_vector_file(vfile);
        if ($value$plusargs("VEC2=%s", vfile)) run_vector_file(vfile);
        if ($value$plusargs("VEC3=%s", vfile)) run_vector_file(vfile);
        if ($value$plusargs("VEC4=%s", vfile)) run_vector_file(vfile);
        if ($value$plusargs("VEC5=%s", vfile)) run_vector_file(vfile);
        if ($value$plusargs("VEC6=%s", vfile)) run_vector_file(vfile);

        idle(5);
        errors = errors + proto_errors;
        $display("INFO: golden vectors total %0d (+%0d clamp re-runs), mismatching inferences %0d, mismatching fields %0d",
                 tot_vec, tot_clamp, tot_bad, tot_fields);
        $display("INFO: bus protocol errors %0d, longest valid->ready %0d cycles", proto_errors, max_wait);
        if (errors == 0) begin
            $display("TEST PASSED");
            $finish;
        end else begin
            $display("errors=%0d", errors);
            $display("TEST FAILED");
            $fatal(1, "tb_sc_tpu failed");
        end
    end

endmodule

`default_nettype wire
