// =============================================================================
// File    : tests/soc/tb_soc_bfm.v
// Purpose : Directed, self-checking testbench of the SoC fabric INSIDE the
//           real soc_top (soc_bus + soc_ram + soc_periph + sc_tpu + LED
//           inversion + pins). The CPU's bus outputs are overridden with
//           Verilog `force` by a bus-functional model (BFM), so every
//           register / memory / error case can be exercised directly,
//           without a CPU program (the project has no firmware; CPU programs
//           come only from the Python assembler, task SW-01b). Everything
//           downstream of the CPU is the unmodified synthesisable RTL.
// Task    : RTL-SOC (fpga-engineer)
// Reqs    : acceptance criteria of REQ-SYS-006 (reset values), REQ-SYS-007
//           (ready within 4 cycles, single pulse), REQ-SYS-008 (byte lanes),
//           REQ-SYS-009 (map, first/last words, aliases), REQ-SYS-010
//           (unmapped: 0x3000_0000 and 0xF000_0000), REQ-SYS-011 (registers,
//           CYCLE difference, UART_TX ignored while busy), REQ-SYS-012 (bytes
//           0x00, 0x55, 0xA5, 0xFF; 234 clocks per bit; 2340 per frame),
//           REQ-SYS-013 (LED values 0x00, 0x3F, 0x15, 0x2A on led_n).
//
// BFM (native valid/ready, ARCHITECTURE.md 3): signals are driven at the
//   falling clock edge, mem_valid is held with a stable request until
//   mem_ready is seen (sampled at the falling edge, i.e. mid-cycle), and
//   dropped right after the rising edge that completes the transaction.
//   Latency = number of cycles mem_valid was high, incl. the ready cycle;
//   every access must complete within 4 cycles (REQ-SYS-007).
//
// TESTS (each prints PASS/FAIL)
//   T1 reset values through the bus: LED 0, UART_STATUS 0, TOHOST 0;
//      TPU STATUS 0, RESULT 0, CYCLES 0, CONFIG 0x08, PARAMS 0x02020810
//      (rev B: version 2, RNG_MODE 2, IL 8, NL 16); led_n = 6'b111111.
//   T2 LED: 0x00, 0x3F, 0x15, 0x2A -> read-back and led_n = ~value; 0xFF
//      reads back 0x3F (6-bit register); a write without byte-0 strobe is
//      ignored.
//   T3 TOHOST: word write / read-back, byte-lane write (wstrb 0100).
//   T4 CYCLE: two reads N cycles apart (N measured by the BFM between the
//      accepting edges) differ by exactly N; a write to CYCLE is ignored.
//   T5 peripheral reserved offsets 0x14 / 0xFFC read 0 and ignore writes;
//      alias 0x1234_5000 reads LED (addr[27:12] not decoded).
//   T6 RAM: first / last word 0x000 / 0xFFC; byte lanes (SB/SH strobe
//      patterns with replicated data, like the CPU); aliases 0x0000_1100 ->
//      0x100 and 0x0FFF_FFFC -> 0xFFC.
//   T7 TPU window: WEIGHT 0x2000_0800 / 0x2000_0FFC, CONFIG and INPUT
//      write / read-back through the SoC decoder.
//   T8 unmapped: bus_err 0 before; reads of 0x3000_0000 and 0xF000_0000 = 0
//      within 4 cycles; a write to 0x3000_0000 changes nothing (RAM word 0,
//      LED, TOHOST); bus_err = 1 afterwards, still 1 after 200 cycles and
//      further mapped accesses; cleared by a button reset.
//   T9 UART: bytes 0x00, 0x55, 0xA5, 0xFF sent by polling UART_STATUS;
//      UART_STATUS = 1 right after a write; a UART_TX write while busy (0x12)
//      is ignored. The real-time receiver on the uart_tx pin must decode
//      exactly 0x00 0x55 0xA5 0xFF; every line edge on a multiple of 234
//      clocks; tx_busy exactly 2340 clocks per frame.
//   T10 every BFM access completed within 4 cycles; mem_ready never without
//      mem_valid; never two consecutive ready cycles.
// Negative run: -DINJECT_FAULT expects the LED pins NON-inverted in T2 ->
//   must end in TEST FAILED.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_soc_bfm;

    localparam integer EXP_DIV = 234;
    localparam real    BIT_NS  = 1.0e9 / 115200.0;

    reg clk = 1'b0;
    always #18.519 clk <= ~clk;          // 27 MHz

    reg  btn_rst_n = 1'b0;
    wire [5:0] led_n;
    wire       uart_tx;

    soc_top dut (
        .clk(clk), .btn_rst_n(btn_rst_n), .led_n(led_n),
        .uart_tx(uart_tx), .uart_rx(1'b1));

    // ---- BFM drives the CPU-side bus nets (CPU outputs overridden) ------------
    reg        bv = 1'b0;
    reg [31:0] ba = 32'd0, bd = 32'd0;
    reg [3:0]  bs = 4'd0;
    initial begin
        force dut.mem_valid = bv;
        force dut.mem_instr = 1'b0;
        force dut.mem_addr  = ba;
        force dut.mem_wdata = bd;
        force dut.mem_wstrb = bs;
    end

    integer errors = 0, lat_max = 0, n_acc = 0, cyc = 0, viol = 0;
    always @(posedge clk) cyc <= cyc + 1;

    // ready checks (T10)
    reg rdy_q = 1'b0;
    always @(posedge clk) begin
        if (!dut.rst) begin
            if (dut.mem_ready && !dut.mem_valid) begin viol = viol + 1; $display("FAIL: mem_ready without mem_valid"); end
            if (dut.mem_ready && rdy_q)          begin viol = viol + 1; $display("FAIL: two consecutive ready cycles"); end
        end
        rdy_q <= dut.mem_ready;
    end

    task fail;
        input [8*120-1:0] msg;
        begin errors = errors + 1; $display("FAIL: %0s", msg); end
    endtask

    // One bus transaction. Returns read data, latency and the cycle number of
    // the first (accepting, for the 1-wait-state slaves) cycle.
    reg [31:0] rd;
    integer    lat, acc_cyc;
    task xfer;
        input [31:0] a;
        input [31:0] d;
        input [3:0]  s;
        begin
            @(negedge clk);
            bv = 1'b1; ba = a; bd = d; bs = s;
            lat = 1; acc_cyc = cyc;
            while (dut.mem_ready !== 1'b1 && lat < 50) begin
                @(negedge clk);
                lat = lat + 1;
            end
            rd = dut.mem_rdata;
            @(posedge clk); #1;
            bv = 1'b0; bs = 4'd0;
            n_acc = n_acc + 1;
            if (lat > lat_max) lat_max = lat;
            if (lat > 4) begin
                errors = errors + 1;
                $display("FAIL: access to 0x%08h took %0d cycles (> 4)", a, lat);
            end
        end
    endtask

    task wr;   input [31:0] a; input [31:0] d; begin xfer(a, d, 4'b1111); end endtask
    task wrs;  input [31:0] a; input [31:0] d; input [3:0] s; begin xfer(a, d, s); end endtask
    task rdw;  input [31:0] a; begin xfer(a, 32'h0, 4'b0000); end endtask
    task expect_rd;
        input [31:0] a;
        input [31:0] e;
        input [8*60-1:0] what;
        begin
            rdw(a);
            if (rd !== e) begin
                errors = errors + 1;
                $display("FAIL: %0s: read 0x%08h = 0x%08h, expected 0x%08h", what, a, rd, e);
            end
        end
    endtask

    // ---- UART receiver on the pin (real time, as in tb_soc.v) ------------------
    reg  [7:0] rxb [0:15];
    integer    n_rx = 0, frame_err = 0, b;
    reg  [7:0] rx_byte;
    reg        s25, s50, s75;
    always begin
        @(negedge uart_tx);
        if (!dut.rst) begin
            rx_byte = 8'd0;
            for (b = 0; b < 10; b = b + 1) begin
                if (b == 0) #(BIT_NS * 0.25); else #(BIT_NS * 0.5);
                s25 = uart_tx; #(BIT_NS * 0.25);
                s50 = uart_tx; #(BIT_NS * 0.25);
                s75 = uart_tx;
                if (s25 !== s50 || s50 !== s75) frame_err = frame_err + 1;
                if (b == 0 && s50 !== 1'b0) frame_err = frame_err + 1;
                if (b >= 1 && b <= 8) rx_byte[b - 1] = s50;
                if (b == 9 && s50 !== 1'b1) frame_err = frame_err + 1;
            end
            rxb[n_rx[3:0]] = rx_byte;
            n_rx = n_rx + 1;
            $display("INFO: UART RX byte 0x%02h", rx_byte);
        end
    end

    // ---- bit-timing checker ----------------------------------------------------
    integer t0 = -1, bstart = -1, n_frames = 0, terr = 0;
    reg     txp = 1'b1, bsy_p = 1'b0;
    always @(posedge clk) begin
        if (!dut.rst) begin
            if (uart_tx !== txp) begin
                if (t0 < 0) begin if (uart_tx === 1'b0) t0 = cyc; else terr = terr + 1; end
                else if ((cyc - t0) % EXP_DIV != 0) terr = terr + 1;
            end
            if (t0 >= 0 && cyc - t0 == 10 * EXP_DIV - 1) t0 = -1;
            if (dut.u_periph.tx_busy && !bsy_p) bstart = cyc;
            if (!dut.u_periph.tx_busy && bsy_p) begin
                n_frames = n_frames + 1;
                if (cyc - bstart != 10 * EXP_DIV) begin
                    terr = terr + 1;
                    $display("FAIL: tx_busy %0d cycles", cyc - bstart);
                end
            end
        end
        txp   <= dut.rst ? 1'b1 : uart_tx;
        bsy_p <= dut.rst ? 1'b0 : dut.u_periph.tx_busy;
    end

    // ---- watchdog -------------------------------------------------------------
    initial begin
        #(37.038 * 200000.0);
        $display("FAIL: watchdog"); $display("TEST FAILED"); $fatal(1, "watchdog");
    end

    localparam [31:0] P = 32'h1000_0000, T = 32'h2000_0000;
    integer e0, i, c1, c2, a1, a2, n;
    reg [31:0] v;
    reg [5:0]  led_exp;
    reg [7:0]  ub [0:3];

    task reset_button;
        begin
            @(negedge clk); btn_rst_n = 1'b0;
            repeat (10) @(posedge clk);
            @(negedge clk); btn_rst_n = 1'b1;
            while (dut.rst !== 1'b0) @(posedge clk);
            repeat (2) @(posedge clk);
        end
    endtask

    initial begin
        reset_button;

        // ---------------- T1 reset values ----------------------------------------
        e0 = errors;
        if (led_n !== 6'b111111) fail("T1 led_n not all-off after reset");
        expect_rd(P + 32'h00, 32'd0, "T1 LED reset");
        expect_rd(P + 32'h08, 32'd0, "T1 UART_STATUS reset");
        expect_rd(P + 32'h10, 32'd0, "T1 TOHOST reset");
        expect_rd(T + 32'h004, 32'd0, "T1 TPU STATUS reset");
        expect_rd(T + 32'h00C, 32'd0, "T1 TPU RESULT reset");
        expect_rd(T + 32'h010, 32'd0, "T1 TPU CYCLES reset");
        expect_rd(T + 32'h008, 32'h08, "T1 TPU CONFIG reset");
        expect_rd(T + 32'h014, 32'h0202_0810, "T1 TPU PARAMS rev B");
        if (errors == e0) $display("PASS: T1 reset values: LED/UART_STATUS/TOHOST = 0, TPU STATUS/RESULT/CYCLES = 0, CONFIG = 0x08, PARAMS = 0x02020810, led_n = 6'b111111");

        // ---------------- T2 LED --------------------------------------------------
        e0 = errors;
        for (i = 0; i < 4; i = i + 1) begin
            case (i) 0: v = 32'h00; 1: v = 32'h3F; 2: v = 32'h15; default: v = 32'h2A; endcase
            wr(P + 32'h00, v);
            expect_rd(P + 32'h00, v, "T2 LED read-back");
`ifdef INJECT_FAULT
            led_exp = v[5:0];                 // wrong polarity on purpose
`else
            led_exp = ~v[5:0];
`endif
            if (led_n !== led_exp) begin
                errors = errors + 1;
                $display("FAIL: T2 LED 0x%02h: led_n = 6'b%06b, expected 6'b%06b", v, led_n, led_exp);
            end
        end
        wr(P + 32'h00, 32'hFF);
        expect_rd(P + 32'h00, 32'h3F, "T2 LED is 6 bits");
        wrs(P + 32'h00, 32'h0000_1500, 4'b0010);    // byte 1 only: no effect
        expect_rd(P + 32'h00, 32'h3F, "T2 LED needs byte-0 strobe");
        if (errors == e0) $display("PASS: T2 LED values 0x00/0x3F/0x15/0x2A read back and led_n = ~value; 6-bit register; byte-0 strobe required");

        // ---------------- T3 TOHOST ------------------------------------------------
        e0 = errors;
        wr(P + 32'h10, 32'hDEAD_BEEF);
        expect_rd(P + 32'h10, 32'hDEAD_BEEF, "T3 TOHOST word");
        wrs(P + 32'h10, 32'h1111_1111, 4'b0100);
        expect_rd(P + 32'h10, 32'hDE11_BEEF, "T3 TOHOST byte lane 2");
        if (errors == e0) $display("PASS: T3 TOHOST word and byte-lane writes");

        // ---------------- T4 CYCLE -------------------------------------------------
        e0 = errors;
        rdw(P + 32'h0C); c1 = rd; a1 = acc_cyc;
        repeat (1000) @(posedge clk);
        wr(P + 32'h0C, 32'h0);                       // ignored (read-only)
        rdw(P + 32'h0C); c2 = rd; a2 = acc_cyc;
        if (c2 - c1 !== a2 - a1) begin
            errors = errors + 1;
            $display("FAIL: T4 CYCLE difference %0d, BFM-measured %0d", c2 - c1, a2 - a1);
        end
        if (errors == e0) $display("PASS: T4 CYCLE read twice %0d cycles apart differs by exactly %0d; write ignored", a2 - a1, c2 - c1);

        // ---------------- T5 reserved / alias --------------------------------------
        e0 = errors;
        wr(P + 32'h00, 32'h15);
        wr(P + 32'h14, 32'hFFFF_FFFF);
        wr(P + 32'hFFC, 32'hFFFF_FFFF);
        expect_rd(P + 32'h14, 32'd0, "T5 reserved 0x14");
        expect_rd(P + 32'hFFC, 32'd0, "T5 reserved 0xFFC");
        expect_rd(P + 32'h04, 32'd0, "T5 UART_TX reads 0");
        expect_rd(32'h1234_5000, 32'h15, "T5 alias 0x12345000 = LED");
        expect_rd(P + 32'h10, 32'hDE11_BEEF, "T5 TOHOST unchanged");
        if (errors == e0) $display("PASS: T5 reserved peripheral offsets read 0 / ignore writes; alias 0x12345000 reads LED");

        // ---------------- T6 RAM ----------------------------------------------------
        e0 = errors;
        wr(32'h0000_0000, 32'hA5A5_0001);  expect_rd(32'h0000_0000, 32'hA5A5_0001, "T6 RAM first word");
        wr(32'h0000_0FFC, 32'h5A5A_0FFC);  expect_rd(32'h0000_0FFC, 32'h5A5A_0FFC, "T6 RAM last word");
        wr(32'h0000_0100, 32'h0000_0000);
        wrs(32'h0000_0100, 32'h1111_1111, 4'b0001);   // SB lane 0
        wrs(32'h0000_0101, 32'h2222_2222, 4'b0010);   // SB lane 1
        wrs(32'h0000_0102, 32'h3333_3333, 4'b0100);   // SB lane 2
        wrs(32'h0000_0103, 32'h4444_4444, 4'b1000);   // SB lane 3
        expect_rd(32'h0000_0100, 32'h4433_2211, "T6 RAM byte lanes (little-endian)");
        wrs(32'h0000_0102, 32'hBEEF_BEEF, 4'b1100);   // SH upper half
        expect_rd(32'h0000_0100, 32'hBEEF_2211, "T6 RAM halfword lane");
        expect_rd(32'h0000_1100, 32'hBEEF_2211, "T6 RAM alias 0x1100 -> 0x100");
        expect_rd(32'h0FFF_FFFC, 32'h5A5A_0FFC, "T6 RAM alias 0x0FFFFFFC -> 0xFFC");
        if (errors == e0) $display("PASS: T6 RAM first/last word, byte and halfword lanes (little-endian), aliases");

        // ---------------- T7 TPU window ------------------------------------------
        e0 = errors;
        wr(T + 32'h800, 32'h0123_4567);  expect_rd(T + 32'h800, 32'h0123_4567, "T7 WEIGHT first word");
        wr(T + 32'hFFC, 32'h89AB_CDEF);  expect_rd(T + 32'hFFC, 32'h89AB_CDEF, "T7 WEIGHT last word");
        wr(T + 32'h008, 32'h35);         expect_rd(T + 32'h008, 32'h35, "T7 CONFIG");
        wr(T + 32'h040, 32'hCAFE_F00D);  expect_rd(T + 32'h040, 32'hCAFE_F00D, "T7 INPUT word 0");
        if (errors == e0) $display("PASS: T7 TPU WEIGHT first/last word, CONFIG, INPUT through the SoC decoder");

        // ---------------- T8 unmapped -----------------------------------------------
        e0 = errors;
        if (dut.bus_err !== 1'b0) fail("T8 bus_err set before any unmapped access");
        expect_rd(32'h3000_0000, 32'd0, "T8 unmapped 0x30000000 reads 0");
        n = lat;
        expect_rd(32'hF000_0000, 32'd0, "T8 unmapped 0xF0000000 reads 0");
        if (lat > n) n = lat;
        wr(32'h3000_0000, 32'hFFFF_FFFF);
        expect_rd(32'h0000_0000, 32'hA5A5_0001, "T8 RAM word 0 unchanged by unmapped write");
        expect_rd(P + 32'h00, 32'h15, "T8 LED unchanged");
        expect_rd(P + 32'h10, 32'hDE11_BEEF, "T8 TOHOST unchanged");
        if (dut.bus_err !== 1'b1) fail("T8 bus_err not set");
        repeat (200) @(posedge clk);
        rdw(32'h0000_0004);
        if (dut.bus_err !== 1'b1) fail("T8 bus_err not sticky");
        reset_button;
        if (dut.bus_err !== 1'b0) fail("T8 bus_err not cleared by reset");
        if (errors == e0) $display("PASS: T8 unmapped 0x30000000/0xF00000000 read 0 in %0d cycles, write ignored, bus_err sticky until reset", n);

        // ---------------- T9 UART -----------------------------------------------------
        e0 = errors;
        ub[0] = 8'h00; ub[1] = 8'h55; ub[2] = 8'hA5; ub[3] = 8'hFF;
        for (i = 0; i < 4; i = i + 1) begin
            rdw(P + 32'h08);
            while (rd[0] == 1'b1) rdw(P + 32'h08);
            wrs(P + 32'h04, {4{ub[i]}}, 4'b0001);
            rdw(P + 32'h08);
            if (rd !== 32'd1) fail("T9 UART_STATUS not 1 right after a write");
            if (i == 1) wrs(P + 32'h04, 32'h12, 4'b0001);   // while busy: must be ignored
        end
        rdw(P + 32'h08);
        while (rd[0] == 1'b1) rdw(P + 32'h08);
        repeat (3 * EXP_DIV) @(posedge clk);
        if (n_rx != 4) begin errors = errors + 1; $display("FAIL: T9 received %0d bytes, expected 4", n_rx); end
        for (i = 0; i < 4 && i < n_rx; i = i + 1)
            if (rxb[i] !== ub[i]) begin errors = errors + 1; $display("FAIL: T9 byte %0d = 0x%02h expected 0x%02h", i, rxb[i], ub[i]); end
        if (frame_err != 0 || terr != 0 || n_frames != 4) begin
            errors = errors + 1;
            $display("FAIL: T9 frame errors %0d, timing errors %0d, frames %0d", frame_err, terr, n_frames);
        end
        if (errors == e0) $display("PASS: T9 UART bytes 0x00 0x55 0xA5 0xFF decoded on the pin (real-time 115200 8N1 receiver); write while busy ignored; %0d frames, edges on multiples of 234 clocks, tx_busy 2340 clocks each", n_frames);

        // ---------------- T10 ---------------------------------------------------------
        if (viol == 0 && lat_max <= 4) $display("PASS: T10 %0d BFM accesses, max latency %0d cycles (<= 4), ready protocol clean", n_acc, lat_max);
        else fail("T10 latency / ready protocol");

        if (errors == 0) begin
            $display("TEST PASSED");
            $finish;
        end else begin
            $display("errors=%0d", errors);
            $display("TEST FAILED");
            $fatal(1, "tb_soc_bfm failed");
        end
    end

endmodule

`default_nettype wire
