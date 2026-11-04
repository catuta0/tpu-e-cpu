// =============================================================================
// File    : tests/soc/tb_soc.v
// Purpose : Self-checking system testbench of the complete SoC
//           design/rtl/soc/soc_top.v = real rv32i_core + soc_bus + soc_ram +
//           soc_periph + real sc_tpu (rev B, RNG_MODE 2), driven ONLY through
//           the board pins (clk, btn_rst_n) - the CPU executes a program from
//           the RAM init file, exactly as on the Tang Nano 9K.
// Task    : RTL-SOC (fpga-engineer)
// Reqs    : REQ-SYS-005 (reset synchroniser latency, first fetch), REQ-SYS-006
//           (reset values on the pins), REQ-SYS-007 (bus protocol), REQ-SYS-010
//           (bus_err), REQ-SYS-012 (UART frames), REQ-SYS-013 (LED pins),
//           REQ-SYS-016 (end-to-end demo), REQ-TIM-005 (end-to-end cycles),
//           REQ-TPU-013/014 (bit-exact results and CYCLES inside the SoC).
//
// COMPILE-TIME PARAMETERS (iverilog -P tb_soc.<name>=<value>)
//   PROG_HEX  RAM image for soc_top.INIT_FILE (default: the SoC demo
//             program sim/data/soc_demo_prog.hex; for CPU-suite runs
//             sim/data/cpu_tests/<test>.hex).
//   UART_DIV  divider passed to the DUT (default 234). The TB's own
//             expectations always use 234 (INTERFACES.json uart), so a
//             different value is a deliberate fault (negative run).
// PLUSARGS
//   +MODE=demo   SoC demo program checks (default)
//        cpu     CPU verification program checks (SW-01b suite)
//   +EXP=<file>  demo: sim/soc/build/soc_expected.hex, made by
//                scripts/sim_soc.sh from sim/data/soc_expected.json (SW-02);
//                layout below.
//   +META=<f> +SIG=<f>   cpu: <test>.tbmeta.hex (scripts/cpu_meta_to_tb.py)
//                and <test>.sig (32-word signature at 0x0F00).
//   +MAXCYC=<n>  watchdog in clock cycles after reset release (default 200000,
//                the REQ-SYS-016 bound).
//
// SEQUENCE
//   1. Power-up: btn_rst_n = 1. rst_sync powers up as 11, so rst = 1 for the
//      first 2 edges, then 0 (power-up reset). R1: rst falls on edge 2.
//   2. Button pressed (btn_rst_n = 0, mid-cycle): R2 rst rises on the 2nd edge
//      (REQ-SYS-005a: 2nd or 3rd). Held 20 cycles: R3 led_n = 6'b111111 and
//      uart_tx = 1 during reset (REQ-SYS-006).
//   3. Button released (mid-cycle): R4 rst falls on the 2nd edge. From here
//      "cycle 0" = first cycle with rst = 0; every cycle count is relative to it.
//      R5 the first bus request is a fetch (mem_instr = 1) of 0x0000_0000;
//      its delay is reported (the CPU's 32-cycle CLEAR state comes first).
//   4. The program runs. Monitors (always on):
//      - BUS PROTOCOL CHECKER on the CPU bus inside soc_top (rules below);
//      - TRANSACTION MONITOR: counts per slave, CPU-observed TPU RESULT read
//        data, START write, LED / UART_TX / TOHOST writes;
//      - UART RECEIVER MODEL on the uart_tx PIN: an independent decoder that
//        knows only "115200 Bd, 8N1" and REAL TIME (bit = 8680.56 ns). It
//        samples each of the 10 bits at 25 %, 50 % and 75 % of the nominal
//        bit window; all three must agree (the bit is really there for most
//        of its window), start must be 0, stop must be 1;
//      - UART BIT-TIMING CHECKER: every transition of uart_tx inside a frame
//        happens an exact multiple of 234 clocks after the start edge, and
//        tx_busy lasts exactly 10 * 234 = 2340 clocks (REQ-SYS-012);
//      - TPU BUSY counter (cycles with sc_tpu.busy = 1).
//   5. Stop point: demo/cpu tohost stop = completion of the TOHOST write;
//      cpu trap stop = halted. The TB continues until the expected number of
//      UART bytes has been received (the demo's last byte is still on the
//      wire when TOHOST is written), plus 8 cycles, then checks.
//
// DEMO CHECKS (+MODE=demo; expectation = SW-02 golden model, SIMULATION)
//   D1 TOHOST == 1 and written at the tohost_store PC 0x68.
//   D2 CPU-observed RESULT: read data of the CPU's load from TPU 0x00C
//      ([3:0]) == golden RESULT; sc_tpu RESULT register == golden.
//   D3 TPU storage: sc_tpu.hidden (16 codes) == golden HIDDEN words and
//      sc_tpu.score (16 x Dp, sign-extended) == golden SCORE words (bit-exact).
//   D4 LED pins: led_n == ~{2'b00, RESULT} (active-low) and LED register.
//   D5 UART: exactly the bytes "0"+RESULT, "\n" decoded on the pin.
//   D6 CYCLES: RAM word 0x0E00 (stored by the program from TPU CYCLES) ==
//      TPU formula 10 * 2^K + 368 (sc_tpu_ctrl.v, K = 8 -> 2928) == TB-measured
//      BUSY cycles == sc_tpu CYCLES register.
//   D7 bus_err == 0, CPU not halted, 0 protocol violations, every
//      transaction completed within 4 cycles (REQ-SYS-007 bound).
// CPU-SUITE CHECKS (+MODE=cpu; expectation = SW-01b ISS, SIMULATION)
//   C1 stop kind / trap cause / stop PC; C2 instret; C3 TOHOST value;
//   C4 signature 0x0F00..0x0F7C == <test>.sig; C5 bus_err; C6 LED pins;
//   C7 UART bytes; C8 0 protocol violations.
//
// BUS PROTOCOL CHECKER (ARCHITECTURE.md 3, REQ-SYS-007), every cycle out of reset:
//   P1 while mem_valid && !mem_ready: next cycle mem_valid stays 1 and
//      addr / wdata / wstrb / instr are unchanged;
//   P2 mem_ready only while mem_valid;
//   P3 mem_ready never high in two consecutive cycles (single pulse; all
//      SoC slaves need >= 2 cycles per transaction);
//   P4 no X/Z on mem_valid / mem_ready; on addr / wstrb while valid; on
//      mem_rdata when a read completes;
//   P5 slave selects one-hot and only with mem_valid; at most one slave
//      ready per cycle and only while its own select is active;
//   P6 latency (cycles from first mem_valid to mem_ready, inclusive) <= 4;
//   P7 no request while the CPU is halted.
//
// NEGATIVE RUNS (scripts/sim_soc.sh, must end in TEST FAILED):
//   -DINJECT_FAULT : bit 0 of the expected SCORE[0] is flipped -> D3 fails.
//   -P tb_soc.UART_DIV=240 : DUT UART 2.5 % slow -> bit-timing checker fails.
//   -DINJECT_PROTO_FAULT : mem_ready forced high for one cycle without
//                          mem_valid -> protocol checker P2 fails.
//
// Output: PASS/FAIL per check, INFO lines with measurements, final
//   "TEST PASSED" or "TEST FAILED" + $fatal(1).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module tb_soc;

    parameter         PROG_HEX = "sim/data/soc_demo_prog.hex";
    parameter integer UART_DIV = 234;

    localparam integer EXP_DIV    = 234;          // INTERFACES.json uart divider
    localparam real    BIT_NS     = 1.0e9 / 115200.0;   // 8680.556 ns, real baud
    localparam integer META_WORDS = 9 + 256;      // scripts/cpu_meta_to_tb.py
    localparam integer EXP_WORDS  = 32;           // soc_expected.hex length
    localparam integer LAT_MAX    = 4;            // REQ-SYS-007 bound (cycles)

    // ---------------------------------------------------------------- clock
    // 27 MHz: half period 18.519 ns (period 37.038 ns = 26.9994 MHz).
    reg clk = 1'b0;
    always #18.519 clk <= ~clk;

    reg  btn_rst_n = 1'b1;
    wire [5:0] led_n;
    wire       uart_tx;
    reg        uart_rx = 1'b1;    // idle; unused by the DUT

    soc_top #(
        .INIT_FILE (PROG_HEX),
        .UART_DIV  (UART_DIV)
    ) dut (
        .clk       (clk),
        .btn_rst_n (btn_rst_n),
        .led_n     (led_n),
        .uart_tx   (uart_tx),
        .uart_rx   (uart_rx)
    );

    // ---------------------------------------------------------------- probes
    wire        rst       = dut.rst;
    wire        mem_valid = dut.mem_valid;
    wire        mem_instr = dut.mem_instr;
    wire [31:0] mem_addr  = dut.mem_addr;
    wire [31:0] mem_wdata = dut.mem_wdata;
    wire [3:0]  mem_wstrb = dut.mem_wstrb;
    wire        mem_ready = dut.mem_ready;
    wire [31:0] mem_rdata = dut.mem_rdata;

    // ---------------------------------------------------------------- state
    integer errors = 0;
    integer cyc = -1;             // cycles since reset release (-1 = in reset)
    reg [8*16-1:0]  mode;
    reg [8*512-1:0] exp_file, meta_file, sig_file;
    integer maxcyc;
    reg [31:0] expv [0:EXP_WORDS-1];
    reg [31:0] meta [0:META_WORDS-1];
    reg [31:0] sig  [0:31];

    task fail;
        input [8*160-1:0] msg;
        begin
            errors = errors + 1;
            $display("FAIL: %0s", msg);
        end
    endtask

    // =========================================================================
    // Cycle counter (relative to reset release)
    // =========================================================================
    always @(posedge clk) begin
        if (rst) cyc <= -1;
        else     cyc <= cyc + 1;
    end

    // =========================================================================
    // Bus protocol checker
    // =========================================================================
    integer viol = 0;
    reg         pend = 1'b0, rdy_q = 1'b0;
    reg [31:0]  p_addr, p_wdata;
    reg [3:0]   p_wstrb;
    reg         p_instr;
    integer     lat = 0, lat_max = 0;
    integer     lat_max_slave [0:3];      // 0 RAM, 1 periph, 2 TPU, 3 unmapped
    integer     n_tr [0:3];
    integer     n_viol_print = 0;
    integer     si;
    initial for (si = 0; si < 4; si = si + 1) begin lat_max_slave[si] = 0; n_tr[si] = 0; end

    task pviol;
        input [8*100-1:0] msg;
        begin
            viol = viol + 1;
            if (n_viol_print < 10) begin
                n_viol_print = n_viol_print + 1;
                $display("PROTOCOL VIOLATION #%0d at cycle %0d: %0s (addr 0x%08h)", viol, cyc, msg, mem_addr);
            end
        end
    endtask

    function integer slave_of;
        input [31:0] a;
        begin
            case (a[31:28])
                4'h0: slave_of = 0;
                4'h1: slave_of = 1;
                4'h2: slave_of = 2;
                default: slave_of = 3;
            endcase
        end
    endfunction

    always @(posedge clk) begin
        if (!rst) begin
            // P4 (control signals)
            if (^{mem_valid, mem_ready} === 1'bx) pviol("P4 X/Z on mem_valid/mem_ready");
            if (mem_valid === 1'b1 && (^mem_addr === 1'bx || ^mem_wstrb === 1'bx)) pviol("P4 X/Z on addr/wstrb");
            if (mem_valid && mem_ready && mem_wstrb == 4'd0 && ^mem_rdata === 1'bx) pviol("P4 X/Z on read data");
            // P1 (request held stable until ready)
            if (pend) begin
                if (mem_valid !== 1'b1)                     pviol("P1 mem_valid dropped before mem_ready");
                else if (mem_addr !== p_addr || mem_wdata !== p_wdata ||
                         mem_wstrb !== p_wstrb || mem_instr !== p_instr)
                                                            pviol("P1 request changed while waiting for mem_ready");
            end
            // P2, P3
            if (mem_ready && !mem_valid) pviol("P2 mem_ready without mem_valid");
            if (mem_ready && rdy_q)      pviol("P3 mem_ready high in two consecutive cycles");
            // P5 one-hot selects / readies, each ready only with its own select
            if ((dut.ram_valid + dut.per_valid + dut.tpu_valid) > 1) pviol("P5 several slave selects");
            if ((dut.ram_valid || dut.per_valid || dut.tpu_valid) && !mem_valid) pviol("P5 slave select without mem_valid");
            if ((dut.ram_ready + dut.per_ready + dut.tpu_ready + dut.u_bus.un_ready_q) > 1) pviol("P5 several slave readies");
            if ((dut.ram_ready && !dut.ram_valid) || (dut.per_ready && !dut.per_valid) ||
                (dut.tpu_ready && !dut.tpu_valid)) pviol("P5 slave ready without its select");
            // P6 latency
            if (mem_valid) begin
                if (mem_ready) begin
                    si = slave_of(mem_addr);
                    n_tr[si] = n_tr[si] + 1;
                    if (lat + 1 > lat_max_slave[si]) lat_max_slave[si] = lat + 1;
                    if (lat + 1 > lat_max) lat_max = lat + 1;
                    if (lat + 1 > LAT_MAX) pviol("P6 transaction latency > 4 cycles");
                    lat = 0;
                end else begin
                    lat = lat + 1;
                end
            end
            // P7
            if (dut.cpu_halted && mem_valid) pviol("P7 request while halted");
        end else begin
            lat = 0;
        end
        pend    <= !rst && mem_valid && !mem_ready;
        rdy_q   <= !rst && mem_ready;
        p_addr  <= mem_addr;  p_wdata <= mem_wdata;
        p_wstrb <= mem_wstrb; p_instr <= mem_instr;
    end

`ifdef INJECT_PROTO_FAULT
    // Negative run of the protocol checker: 2000 cycles after reset release,
    // pulse mem_ready for one cycle in a cycle without mem_valid (P2).
    initial begin
        wait (cyc == 2000);
        while (mem_valid !== 1'b0) @(negedge clk);
        @(negedge clk);
        if (mem_valid === 1'b0) begin
            force dut.mem_ready = 1'b1;
            @(negedge clk);
            release dut.mem_ready;
            $display("NOTE: INJECT_PROTO_FAULT: mem_ready forced for one cycle without mem_valid");
        end
    end
`endif

    // =========================================================================
    // Transaction monitor (completed transactions only)
    // =========================================================================
    reg        tohost_seen = 1'b0;
    reg [31:0] tohost_val = 0, tohost_pc = 0;
    integer    tohost_cyc = -1;
    reg        result_seen = 1'b0;
    reg [31:0] cpu_result = 0;
    integer    start_cyc = -1, result_cyc = -1, n_status_polls = 0;
    integer    first_req_cyc = -1;
    reg        first_req_fetch = 1'b0;
    reg [31:0] first_req_addr = 32'hFFFF_FFFF;
    integer    n_led_wr = 0, n_uart_wr = 0, n_uart_status = 0;
    reg [5:0]  led_wr_val = 0;

    always @(posedge clk) begin
        if (!rst && mem_valid && first_req_cyc < 0) begin
            first_req_cyc   = cyc;
            first_req_fetch = mem_instr;
            first_req_addr  = mem_addr;
        end
        if (!rst && mem_valid && mem_ready) begin
            // TPU accesses (region 0x2)
            if (mem_addr[31:28] == 4'h2) begin
                if (mem_wstrb != 0 && mem_addr[11:0] == 12'h000 && mem_wdata[0]) start_cyc = cyc;
                if (mem_wstrb == 0 && mem_addr[11:0] == 12'h004) n_status_polls = n_status_polls + 1;
                if (mem_wstrb == 0 && mem_addr[11:0] == 12'h00C && !result_seen) begin
                    result_seen = 1'b1;
                    cpu_result  = mem_rdata;
                    result_cyc  = cyc;
                end
            end
            // peripheral accesses (region 0x1)
            if (mem_addr[31:28] == 4'h1) begin
                if (mem_wstrb != 0 && mem_addr[11:0] == 12'h000) begin n_led_wr = n_led_wr + 1; led_wr_val = mem_wdata[5:0]; end
                if (mem_wstrb != 0 && mem_addr[11:0] == 12'h004) n_uart_wr = n_uart_wr + 1;
                if (mem_wstrb == 0 && mem_addr[11:0] == 12'h008) n_uart_status = n_uart_status + 1;
                if (mem_wstrb != 0 && mem_addr[11:0] == 12'h010 && !tohost_seen) begin
                    tohost_seen = 1'b1;
                    tohost_val  = mem_wdata;
                    tohost_pc   = dut.cpu_dbg_pc;
                    tohost_cyc  = cyc;
                end
            end
        end
    end

    // Retired instructions (registered pulse, counted until the stop point + 2).
    integer instret = 0;
    integer stop_cyc = -1;
    always @(posedge clk)
        if (!rst && dut.cpu_retire && (stop_cyc < 0 || cyc <= stop_cyc + 2)) instret = instret + 1;

    // TPU BUSY cycles (rising edges with BUSY = 1, ARCHITECTURE.md 10 definition).
    integer busy_cycles = 0;
    always @(posedge clk)
        if (!rst && dut.u_tpu.busy) busy_cycles = busy_cycles + 1;

    // =========================================================================
    // UART receiver model on the pin (real-time, independent of the DUT divider)
    // =========================================================================
    reg  [7:0] uart_rx_bytes [0:255];
    integer    n_uart_rx = 0, uart_frame_err = 0;
    reg        rx_en = 1'b0;
    reg  [7:0] rx_byte;
    reg        s25, s50, s75;
    integer    b;
    always begin
        @(negedge uart_tx);
        if (rx_en) begin
            rx_byte = 8'd0;
            for (b = 0; b < 10; b = b + 1) begin
                // sample points at 25 / 50 / 75 % of nominal bit b (from the edge)
                if (b == 0) #(BIT_NS * 0.25); else #(BIT_NS * 0.5);
                s25 = uart_tx;
                #(BIT_NS * 0.25);
                s50 = uart_tx;
                #(BIT_NS * 0.25);
                s75 = uart_tx;
                if (s25 !== s50 || s50 !== s75) begin
                    uart_frame_err = uart_frame_err + 1;
                    $display("FAIL: UART RX bit %0d of byte %0d not stable over its window (%b%b%b) at %0t",
                             b, n_uart_rx, s25, s50, s75, $time);
                end
                if (b == 0 && s50 !== 1'b0) begin
                    uart_frame_err = uart_frame_err + 1;
                    $display("FAIL: UART RX start bit not 0 at %0t", $time);
                end
                if (b >= 1 && b <= 8) rx_byte[b - 1] = s50;   // LSB first
                if (b == 9 && s50 !== 1'b1) begin
                    uart_frame_err = uart_frame_err + 1;
                    $display("FAIL: UART RX stop bit not 1 (framing error) at %0t", $time);
                end
            end
            // We are at 9.75 bit times: the line is in the stop bit (high), so
            // the next @(negedge) is the next start bit.
            uart_rx_bytes[n_uart_rx[7:0]] = rx_byte;
            n_uart_rx = n_uart_rx + 1;
            $display("INFO: UART RX byte %0d = 0x%02h ('%s') at cycle %0d", n_uart_rx - 1, rx_byte,
                     (rx_byte >= 8'h20 && rx_byte < 8'h7F) ? rx_byte : 8'h2E, cyc);
        end
    end

    // =========================================================================
    // UART bit-timing checker (exact divider, REQ-SYS-012)
    // =========================================================================
    integer tx_start_cyc = -1, busy_start = -1, n_frames = 0, uart_timing_err = 0;
    reg     tx_prev = 1'b1, busy_prev = 1'b0;
    always @(posedge clk) begin
        if (!rst) begin
            if (uart_tx !== tx_prev) begin
                if (tx_start_cyc < 0) begin
                    if (uart_tx === 1'b0) tx_start_cyc = cyc;       // start edge
                    else begin
                        uart_timing_err = uart_timing_err + 1;
                        $display("FAIL: UART line rose outside a frame at cycle %0d", cyc);
                    end
                end else if ((cyc - tx_start_cyc) % EXP_DIV != 0) begin
                    uart_timing_err = uart_timing_err + 1;
                    if (uart_timing_err < 5)
                        $display("FAIL: UART edge %0d cycles after the start edge (not a multiple of %0d)",
                                 cyc - tx_start_cyc, EXP_DIV);
                end
            end
            // frame end: 10 bit times after the start edge
            if (tx_start_cyc >= 0 && cyc - tx_start_cyc == 10 * EXP_DIV - 1) tx_start_cyc = -1;
            // tx_busy duration
            if (dut.u_periph.tx_busy && !busy_prev) busy_start = cyc;
            if (!dut.u_periph.tx_busy && busy_prev) begin
                n_frames = n_frames + 1;
                if (cyc - busy_start != 10 * EXP_DIV) begin
                    uart_timing_err = uart_timing_err + 1;
                    $display("FAIL: tx_busy lasted %0d cycles (expected %0d)", cyc - busy_start, 10 * EXP_DIV);
                end
            end
        end
        tx_prev   <= rst ? 1'b1 : uart_tx;
        busy_prev <= rst ? 1'b0 : dut.u_periph.tx_busy;
    end

    // =========================================================================
    // Watchdog (simulation time): 2 x the cycle bound + margin
    // =========================================================================
    initial begin
        #(37.038 * 1000000.0);
        $display("FAIL: watchdog (simulation time limit)");
        $display("TEST FAILED");
        $fatal(1, "watchdog");
    end

    // =========================================================================
    // Helpers
    // =========================================================================
    integer edges, i, k_exp, cyc_formula, n_uart_exp;
    reg [31:0] w, sc_exp, sc_got;
    reg [19:0] dp;
    reg        stop_trap;

    task wait_edges_until_rst;   // count rising edges until rst == val
        input val;
        begin
            edges = 0;
            while (rst !== val && edges < 10) begin
                @(posedge clk); #1;
                edges = edges + 1;
            end
        end
    endtask

    function [31:0] ram_word;
        input [31:0] byte_addr;
        begin
            ram_word = dut.u_ram.mem[byte_addr[11:2]];
        end
    endfunction

    // =========================================================================
    // Main sequence
    // =========================================================================
    initial begin
        if (!$value$plusargs("MODE=%s", mode)) mode = "demo";
        if (!$value$plusargs("MAXCYC=%d", maxcyc)) maxcyc = 200000;
        $display("INFO: tb_soc MODE=%0s PROG_HEX=%0s UART_DIV(DUT)=%0d expected divider %0d",
                 mode, PROG_HEX, UART_DIV, EXP_DIV);
        if (mode == "demo") begin
            if (!$value$plusargs("EXP=%s", exp_file)) begin $display("FAIL: +EXP missing"); $fatal(1); end
            $readmemh(exp_file, expv);
`ifdef INJECT_FAULT
            expv[8] = expv[8] ^ 32'h1;
            $display("NOTE: INJECT_FAULT active (expected SCORE[0] bit 0 flipped)");
`endif
        end else begin
            if (!$value$plusargs("META=%s", meta_file)) begin $display("FAIL: +META missing"); $fatal(1); end
            if (!$value$plusargs("SIG=%s", sig_file))   begin $display("FAIL: +SIG missing");  $fatal(1); end
            $readmemh(meta_file, meta);
            $readmemh(sig_file, sig);
        end

        // ---- 1. power-up reset (rst_sync powers up as 11) ---------------------
        #1;
        if (rst !== 1'b1) fail("R1 rst not asserted at power-up");
        wait_edges_until_rst(1'b0);
        if (edges == 2) $display("PASS: R1 power-up reset: rst released on rising edge %0d after configuration", edges);
        else            fail("R1 power-up reset release not on the 2nd edge");

        // ---- 2. button press -------------------------------------------------
        repeat (3) @(posedge clk);
        #(10.0);                         // mid-cycle, asynchronous to clk
        btn_rst_n = 1'b0;
        wait_edges_until_rst(1'b1);
        if (edges == 2 || edges == 3) $display("PASS: R2 button press -> rst asserted on rising edge %0d (2..3 required)", edges);
        else begin $display("INFO: edges=%0d", edges); fail("R2 reset assertion latency"); end
        repeat (20) @(posedge clk);
        #1;
        if (led_n === 6'b111111 && uart_tx === 1'b1)
            $display("PASS: R3 during reset led_n = 6'b111111 (all LEDs off), uart_tx = 1 (idle)");
        else fail("R3 pin values during reset");

        // ---- 3. button release -----------------------------------------------
        #(10.0);
        btn_rst_n = 1'b1;
        wait_edges_until_rst(1'b0);
        if (edges == 2 || edges == 3) $display("PASS: R4 button release -> rst released on rising edge %0d (2..3 required)", edges);
        else fail("R4 reset release latency");
        rx_en = 1'b1;

        // ---- 4. run until the stop point ---------------------------------------
        stop_trap = 1'b0;
        while (!tohost_seen && !dut.cpu_halted && cyc < maxcyc) @(posedge clk);
        if (dut.cpu_halted && !tohost_seen) stop_trap = 1'b1;
        stop_cyc = cyc;
        if (mode == "demo") n_uart_exp = expv[24];
        else                n_uart_exp = meta[8];
        // wait for the expected UART bytes (or the cycle bound)
        while (n_uart_rx < n_uart_exp && cyc < maxcyc + 4 * 10 * EXP_DIV) @(posedge clk);
        // let a possible extra byte start (it would be an error) and settle
        repeat (3 * EXP_DIV) @(posedge clk);
        #1;

        // ---- 5. reset-release checks -------------------------------------------
        if (first_req_fetch === 1'b1 && first_req_addr === 32'd0)
            $display("PASS: R5 first bus request after reset release is a fetch of 0x00000000 (at cycle %0d after rst fell; CPU CLEAR state = 32 cycles)", first_req_cyc);
        else fail("R5 first bus request is not a fetch of 0x00000000");

        if (mode == "demo") begin : demo_checks
            // D1
            if (tohost_seen && tohost_val == expv[1] && tohost_pc == 32'h68)
                $display("PASS: D1 TOHOST = %0d written by the store at PC 0x%08h, cycle %0d after reset release", tohost_val, tohost_pc, tohost_cyc);
            else fail("D1 TOHOST");
            // D2
            if (result_seen && cpu_result[3:0] == expv[0][3:0] && cpu_result[31:4] == 28'd0 && dut.u_tpu.result == expv[0][3:0])
                $display("PASS: D2 CPU-observed RESULT (load from 0x2000000C) = 0x%08h = golden class %0d; TPU RESULT register = %0d",
                         cpu_result, expv[0], dut.u_tpu.result);
            else begin
                $display("INFO: cpu_result=0x%08h seen=%0d tpu.result=%0d expected=%0d", cpu_result, result_seen, dut.u_tpu.result, expv[0]);
                fail("D2 RESULT");
            end
            // D3 HIDDEN + SCORE storage
            begin : d3
                integer bad;
                bad = 0;
                for (i = 0; i < 4; i = i + 1) begin
                    w = dut.u_tpu.hidden[32*i +: 32];
                    if (w !== expv[4 + i]) begin
                        bad = bad + 1;
                        $display("FAIL: D3 HIDDEN word %0d = 0x%08h expected 0x%08h", i, w, expv[4 + i]);
                    end
                end
                for (i = 0; i < 16; i = i + 1) begin
                    dp = dut.u_tpu.score[20*i +: 20];
                    sc_got = {{12{dp[19]}}, dp};
                    sc_exp = expv[8 + i];
                    if (sc_got !== sc_exp) begin
                        bad = bad + 1;
                        $display("FAIL: D3 SCORE[%0d] = 0x%08h (%0d) expected 0x%08h (%0d)", i, sc_got, $signed(sc_got), sc_exp, $signed(sc_exp));
                    end
                end
                if (bad == 0) $display("PASS: D3 TPU storage bit-exact vs golden: HIDDEN[0..15] (4 words) and SCORE[0..15] (16 words), e.g. SCORE[%0d] = %0d",
                                       expv[0], $signed(expv[8 + expv[0]]));
                else begin errors = errors + 1; $display("FAIL: D3 %0d mismatching words", bad); end
            end
            // D4 LEDs
            if (led_n === ~{2'b00, expv[2][3:0]} && dut.u_periph.led_q == expv[2][5:0] && n_led_wr == 1)
                $display("PASS: D4 led_n = 6'b%06b = ~LED (LED register %0d = class), 1 LED write", led_n, dut.u_periph.led_q);
            else fail("D4 LED pins");
            // D5 UART
            begin : d5
                reg okb;
                okb = (n_uart_rx == expv[24]) && (uart_frame_err == 0);
                for (i = 0; i < expv[24] && i < n_uart_rx; i = i + 1)
                    if (uart_rx_bytes[i] !== expv[25 + i][7:0]) okb = 0;
                if (okb && n_uart_rx == 2 && uart_rx_bytes[0] == 8'h30 + expv[0][7:0] && uart_rx_bytes[1] == 8'h0A)
                    $display("PASS: D5 UART pin decoded (115200 8N1, real-time receiver) %0d bytes: 0x%02h 0x%02h = \"%0d\\n\"; %0d frames",
                             n_uart_rx, uart_rx_bytes[0], uart_rx_bytes[1], expv[0], n_frames);
                else fail("D5 UART bytes");
            end
            // D6 CYCLES
            k_exp = expv[3];
            cyc_formula = 10 * (1 << k_exp) + 368;
            if (ram_word(32'h0E00) == cyc_formula && dut.u_tpu.cycles == cyc_formula && busy_cycles == cyc_formula)
                $display("PASS: D6 CYCLES stored at 0x0E00 = %0d = 10*2^%0d+368 (formula) = TB-measured BUSY cycles %0d = TPU CYCLES register",
                         ram_word(32'h0E00), k_exp, busy_cycles);
            else begin
                $display("INFO: RAM[0x0E00]=%0d formula=%0d busy=%0d reg=%0d", ram_word(32'h0E00), cyc_formula, busy_cycles, dut.u_tpu.cycles);
                fail("D6 CYCLES");
            end
            // D7
            if (dut.bus_err === 1'b0 && !dut.cpu_halted && viol == 0 && lat_max <= LAT_MAX)
                $display("PASS: D7 bus_err = 0, CPU not halted, 0 protocol violations, max latency %0d cycles", lat_max);
            else fail("D7 bus_err / halted / protocol");
            // measurements
            $display("INFO: end-to-end: reset release -> TOHOST write = %0d cycles (%.1f us at 27 MHz); START at cycle %0d, RESULT read at cycle %0d (START->RESULT read %0d cycles), TPU BUSY %0d cycles, %0d STATUS polls",
                     tohost_cyc, tohost_cyc / 27.0, start_cyc, result_cyc, result_cyc - start_cyc, busy_cycles, n_status_polls);
            $display("INFO: instructions retired up to TOHOST %0d; UART_STATUS polls %0d; last UART byte received at cycle ~%0d",
                     instret, n_uart_status, cyc - 3 * EXP_DIV);
        end else begin : cpu_checks
            // C1
            if (meta[0] == 1) begin
                if (stop_trap && dut.cpu_trap_cause == meta[1][3:0] && dut.cpu_dbg_pc == meta[2])
                    $display("PASS: C1 trap stop: cause %0d at PC 0x%08h", dut.cpu_trap_cause, dut.cpu_dbg_pc);
                else fail("C1 trap stop kind / cause / PC");
            end else begin
                if (!stop_trap && tohost_seen && tohost_pc == meta[2] && !dut.cpu_halted)
                    $display("PASS: C1 TOHOST stop at PC 0x%08h (cycle %0d)", tohost_pc, tohost_cyc);
                else fail("C1 TOHOST stop kind / PC");
            end
            // C2
            if (instret == meta[3]) $display("PASS: C2 instret = %0d", instret);
            else begin $display("INFO: instret %0d expected %0d", instret, meta[3]); fail("C2 instret"); end
            // C3
            if ((meta[4] == 0 && !tohost_seen) || (meta[4] == 1 && tohost_seen && tohost_val == meta[5]))
                $display("PASS: C3 TOHOST %0s", tohost_seen ? "value as expected" : "not written (as expected)");
            else fail("C3 TOHOST value");
            // C4
            begin : c4
                integer bad;
                bad = 0;
                for (i = 0; i < 32; i = i + 1)
                    if (ram_word(32'h0F00 + 4 * i) !== sig[i]) begin
                        bad = bad + 1;
                        if (bad < 5) $display("FAIL: C4 signature word %0d = 0x%08h expected 0x%08h", i, ram_word(32'h0F00 + 4 * i), sig[i]);
                    end
                if (bad == 0) $display("PASS: C4 signature 0x0F00..0x0F7C (32 words) equal to the ISS");
                else errors = errors + 1;
            end
            // C5..C8
            if (dut.bus_err == meta[6][0]) $display("PASS: C5 bus_err = %0d", dut.bus_err);
            else fail("C5 bus_err");
            if (led_n === ~meta[7][5:0]) $display("PASS: C6 led_n = 6'b%06b = ~LED (LED %0d)", led_n, meta[7]);
            else fail("C6 LED pins");
            begin : c7
                reg okb;
                okb = (n_uart_rx == meta[8]) && (uart_frame_err == 0);
                for (i = 0; i < meta[8] && i < n_uart_rx; i = i + 1)
                    if (uart_rx_bytes[i] !== meta[9 + i][7:0]) okb = 0;
                if (okb) $display("PASS: C7 UART %0d bytes as expected", n_uart_rx);
                else fail("C7 UART bytes");
            end
            if (viol == 0 && lat_max <= LAT_MAX) $display("PASS: C8 0 protocol violations, max latency %0d cycles", lat_max);
            else fail("C8 protocol");
            $display("INFO: stop at cycle %0d after reset release, instret %0d", stop_cyc, instret);
        end

        // ---- common: UART timing, protocol summary -----------------------------
        if (uart_timing_err == 0 && uart_frame_err == 0)
            $display("PASS: U1 UART timing: %0d frames, every edge on a multiple of %0d clocks, tx_busy = %0d clocks per frame, real-time receiver: 0 framing/stability errors",
                     n_frames, EXP_DIV, 10 * EXP_DIV);
        else begin
            errors = errors + 1;
            $display("FAIL: U1 UART timing errors %0d, frame errors %0d", uart_timing_err, uart_frame_err);
        end
        $display("INFO: bus transactions RAM %0d (max latency %0d), PERIPH %0d (%0d), TPU %0d (%0d), unmapped %0d (%0d); protocol violations %0d",
                 n_tr[0], lat_max_slave[0], n_tr[1], lat_max_slave[1], n_tr[2], lat_max_slave[2],
                 n_tr[3], lat_max_slave[3], viol);
        if (viol != 0) errors = errors + 1;

        if (errors == 0) begin
            $display("TEST PASSED");
            $finish;
        end else begin
            $display("errors=%0d", errors);
            $display("TEST FAILED");
            $fatal(1, "tb_soc failed");
        end
    end

endmodule

`default_nettype wire
