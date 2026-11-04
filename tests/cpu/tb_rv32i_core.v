`default_nettype none
`timescale 1ns / 1ps
// =============================================================================
// File        : tests/cpu/tb_rv32i_core.v
// Module      : tb_rv32i_core  (self-checking testbench, simulation only)
// Project     : SC-TPU + RV32I SoC on Sipeed Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Task        : RTL-CPU
// Author      : fpga-engineer (Claude Code specialist)
//
// PURPOSE
//   Runs ONE RV32I verification program on design/rtl/cpu/rv32i_core.v and
//   compares the end state with the expectations produced by the Python
//   reference ISS (code/python/rv32, task SW-01b):
//     * signature: RAM words 0x0F00..0x0F7C (32 words) vs <test>.sig
//     * stop reason (TOHOST write or trap/halt), trap cause, stop PC,
//       retired-instruction count, TOHOST value, sticky bus_err, LED value and
//       UART bytes vs the companion file made from <test>.meta.json by
//       scripts/cpu_meta_to_tb.py
//     * zero violations of the bus-protocol checker (below)
//   and prints the measured cycles and CPI.
//
// PLUSARGS
//   +prog=<file>   RAM image, 1024 x 32-bit hex ($readmemh)           [required]
//   +sig=<file>    expected signature, 32 x 32-bit hex                  [required]
//   +meta=<file>   companion expectation file (*.tbmeta.hex)            [required]
//   +name=<text>   test name for the log                                (default "test")
//   +ws=<n>        slave wait states 0..3: mem_ready comes in the
//                  (n+1)-th cycle of mem_valid; 0 = same cycle          (default 0)
//   +rand_stall=1  add a random 0..7 extra wait cycles per transaction (default 0)
//   +seed=<n>      seed of the random stalls                            (default 1)
//   +max_cycles=<n> watchdog                                            (default 200000)
//
// SYSTEM MODEL (matches the ISS, code/python/rv32/iss.py, and ARCHITECTURE.md 4)
//   0x0xxx_xxxx  4 KiB RAM, decoded with addr[11:2] only (aliases every 4 KiB)
//   0x1xxx_xxxx  peripherals, offset = addr[11:0]:
//                0x000 LED RW [5:0] | 0x004 UART_TX W (byte lane 0 recorded)
//                0x008 UART_STATUS R = 0 (never busy, like the ISS)
//                0x00C CYCLE R (TB cycle counter; tests never read it)
//                0x010 TOHOST RW (a write is the "pass/fail" stop event)
//                other offsets: read 0, write ignored
//   0x2xxx_xxxx  SC-TPU window: read 0, write ignored (no CPU test uses it)
//   other        unmapped: read 0, write ignored, sticky bus_err := 1
//   Byte lanes: writes merge the lanes enabled in mem_wstrb.
//   mem_rdata is driven with a GARBAGE pattern whenever mem_ready = 0, so a
//   core that samples read data at the wrong time fails.
//
// STOP CONDITIONS
//   * TOHOST write: the store completes, then the TB waits for its retire pulse
//     (the ISS counts the TOHOST store as retired) and freezes the counters.
//   * halted = 1 (trap): counters freeze immediately (trap does not retire).
//   * watchdog: max_cycles after reset -> FAIL.
//
// BUS-PROTOCOL CHECKER (ARCHITECTURE.md 3; every violation is counted and the
// first ones are printed; any violation fails the test)
//   P1 while mem_valid && !mem_ready: next cycle mem_valid must still be 1 and
//      mem_instr/mem_addr/mem_wdata/mem_wstrb must be unchanged
//   P2 mem_ready must never be 1 while mem_valid = 0 (checks the TB slave)
//   P3 no X/Z on mem_valid after reset; no X/Z on mem_addr/wstrb/instr while valid
//   P4 fetch: mem_addr[1:0] = 00 and mem_wstrb = 0000
//   P5 data access: the last fetched word must be a LOAD or STORE; the address
//      must be naturally aligned for its size (a misaligned access must NEVER
//      reach the bus); a load must have wstrb = 0000; a store must have exactly
//      the strobe pattern of its size and address (SB 0001<<a, SH 0011/1100,
//      SW 1111)
//   P6 at most one data access per fetched instruction
//   P7 no bus request while halted
//
// NEGATIVE CHECKS (compile-time defines, used by scripts/sim_cpu.sh to prove
// that the checks can fail)
//   -DINJECT_SIG_FAULT    flips bit 0 of expected signature word 5 -> FAIL
//   -DINJECT_PROTO_FAULT  the checker sees mem_addr ^ 4 during wait cycles,
//                         emulating an address that changes while waiting -> FAIL
//
// OUTPUT
//   "PASS: ..." / "FAIL: ..." lines per check, a machine-readable line
//   "RESULT name=... ws=... rand=... status=... cycles=... instret=... cpi=..."
//   and finally "TEST PASSED" or "TEST FAILED" ($fatal(1) on failure).
// =============================================================================

module tb_rv32i_core;

    // ---- Constants (UART_MAX/META_WORDS must match scripts/cpu_meta_to_tb.py)
    localparam integer UART_MAX   = 256;
    localparam integer META_WORDS = 9 + UART_MAX;
    localparam integer MAX_PRINT  = 10;          // printed protocol violations
    localparam [9:0]   SIG_WORD0  = 10'h3C0;     // 0x0F00 / 4

    // ---- Clock (100 MHz in simulation; the period does not matter) and reset
    reg clk = 1'b0;
    always #5 clk <= ~clk;
    reg rst = 1'b1;

    // ---- DUT ----------------------------------------------------------------------
    wire        mem_valid, mem_instr;
    wire [31:0] mem_addr, mem_wdata;
    wire [3:0]  mem_wstrb;
    wire        mem_ready;
    wire [31:0] mem_rdata;
    wire        halted, retire;
    wire [3:0]  trap_cause;
    wire [31:0] dbg_pc;

    rv32i_core dut (
        .clk        (clk),
        .rst        (rst),
        .mem_valid  (mem_valid),
        .mem_instr  (mem_instr),
        .mem_addr   (mem_addr),
        .mem_wdata  (mem_wdata),
        .mem_wstrb  (mem_wstrb),
        .mem_ready  (mem_ready),
        .mem_rdata  (mem_rdata),
        .halted     (halted),
        .trap_cause (trap_cause),
        .dbg_pc     (dbg_pc),
        .retire     (retire)
    );

    // ---- Plusargs -------------------------------------------------------------------
    reg [8*512-1:0] prog_file, sig_file, meta_file;
    reg [8*64-1:0]  test_name;
    integer ws, rand_stall, seed, max_cycles;

    // ---- Memories / expectations ----------------------------------------------------
    reg [31:0] ram     [0:1023];
    reg [31:0] sig_exp [0:31];
    reg [31:0] meta    [0:META_WORDS-1];

    // ---- Peripheral / bookkeeping state -------------------------------------------
    reg [5:0]  led;
    reg [31:0] tohost_val;
    reg        tohost_seen;        // a TOHOST write has completed
    reg [31:0] tohost_pc;          // dbg_pc during that write (= store PC)
    reg        bus_err;
    reg [7:0]  uart_buf [0:UART_MAX-1];
    integer    uart_n;
    reg [31:0] cyc;                // cycles since reset release (CYCLE register)
    reg        started;            // first mem_valid seen
    reg        freeze;             // stop point reached: counters frozen
    integer    run_cycles;         // cycles from the first mem_valid to the stop point
    integer    instret;            // retire pulses up to the stop point
    integer    n_fetch, n_load, n_store, n_wait;

    // =========================================================================
    // Slave model: wait states and (optionally) random stalls
    // =========================================================================
    // wcnt counts the cycles mem_valid has been high in the current
    // transaction (0 in its first cycle); mem_ready is asserted when it reaches
    // wtarget, which is drawn before the transaction starts.
    reg [3:0] wcnt, wtarget;
    assign mem_ready = mem_valid & (wcnt == wtarget);

    // Read-data path (continuous assignments so that RAM updates are seen).
    wire [3:0]  region    = mem_addr[31:28];
    wire [11:0] poff      = mem_addr[11:0];
    wire [31:0] ram_rd    = ram[mem_addr[11:2]];
    wire [31:0] periph_rd = (poff == 12'h000) ? {26'd0, led} :
                            (poff == 12'h008) ? 32'd0 :           // UART_STATUS: idle
                            (poff == 12'h00C) ? cyc :
                            (poff == 12'h010) ? tohost_val : 32'd0;
    wire [31:0] rd_value  = (region == 4'h0) ? ram_rd :
                            (region == 4'h1) ? periph_rd : 32'd0;
    // Garbage whenever no read completes: must never be sampled by the core.
    assign mem_rdata = mem_ready ? rd_value : {16'hBAD0, cyc[15:0]};

    // Merge the enabled byte lanes of d into old.
    function [31:0] merge;
        input [31:0] old;
        input [31:0] d;
        input [3:0]  strb;
        begin
            merge = {strb[3] ? d[31:24] : old[31:24],
                     strb[2] ? d[23:16] : old[23:16],
                     strb[1] ? d[15:8]  : old[15:8],
                     strb[0] ? d[7:0]   : old[7:0]};
        end
    endfunction

    // Random extra stall 0..7 derived from a 32-bit random word.
    function [3:0] stall_bits;
        input [31:0] r;
        reg   [31:0] m;
        begin
            m = r % 32'd8;
            stall_bits = m[3:0];
        end
    endfunction

    // LED register write data (all 32 lanes merged, only [5:0] kept).
    wire [31:0] led_merged = merge({26'd0, led}, mem_wdata, mem_wstrb);

    // Draw the wait count of the next transaction.
    task draw_wait;
        begin
            // $random(seed) % 8 uses every bit of the random word (0..7 extra).
            wtarget <= ws[3:0] + ((rand_stall != 0) ? stall_bits($random(seed)) : 4'd0);
        end
    endtask

    always @(posedge clk) begin
        if (rst) begin
            wcnt <= 4'd0;
            draw_wait;
        end else if (mem_valid) begin
            if (mem_ready) begin
                wcnt <= 4'd0;
                draw_wait;
                // ---- perform the write (if any) / flag unmapped accesses ----
                case (region)
                    4'h0: if (mem_wstrb != 4'd0)
                              ram[mem_addr[11:2]] <= merge(ram[mem_addr[11:2]], mem_wdata, mem_wstrb);
                    4'h1: if (mem_wstrb != 4'd0) begin
                              if (poff == 12'h000) begin
                                  led <= led_merged[5:0];         // 6-bit register
                              end else if (poff == 12'h004) begin
                                  if (mem_wstrb[0] && uart_n < UART_MAX) begin
                                      uart_buf[uart_n] <= mem_wdata[7:0];
                                      uart_n <= uart_n + 1;
                                  end
                              end else if (poff == 12'h010) begin
                                  tohost_val  <= merge(tohost_val, mem_wdata, mem_wstrb);
                                  tohost_seen <= 1'b1;
                                  tohost_pc   <= dbg_pc;
                              end
                          end
                    4'h2: ; // SC-TPU window: not modelled in the CPU TB
                    default: bus_err <= 1'b1;   // unmapped
                endcase
            end else begin
                wcnt   <= wcnt + 4'd1;
            end
        end
    end

    // =========================================================================
    // Counters: cycles, retired instructions, transaction statistics
    // =========================================================================
    always @(posedge clk) begin
        if (rst) begin
            cyc <= 32'd0; started <= 1'b0; freeze <= 1'b0;
            run_cycles <= 0; instret <= 0;
            n_fetch <= 0; n_load <= 0; n_store <= 0; n_wait <= 0;
        end else begin
            cyc <= cyc + 32'd1;
            if (mem_valid) started <= 1'b1;
            if (!freeze) begin
                if (started | mem_valid) run_cycles <= run_cycles + 1;
                if (retire) instret <= instret + 1;
                if (mem_valid & ~mem_ready) n_wait <= n_wait + 1;
                if (mem_valid & mem_ready) begin
                    if (mem_instr)              n_fetch <= n_fetch + 1;
                    else if (mem_wstrb == 4'd0) n_load  <= n_load + 1;
                    else                        n_store <= n_store + 1;
                end
                // Stop points: the retire pulse of the TOHOST store (counted
                // at this very edge), or the halt (a trap does not retire).
                if ((tohost_seen & retire) | halted) freeze <= 1'b1;
            end
        end
    end

    // =========================================================================
    // Bus-protocol checker
    // =========================================================================
    integer    n_viol;
    reg        prev_wait;          // previous cycle: mem_valid && !mem_ready
    reg        prev_instr;
    reg [31:0] prev_addr, prev_wdata;
    reg [3:0]  prev_wstrb;
    reg [6:0]  last_op;            // opcode of the last fetched instruction
    reg [1:0]  last_sz;            // funct3[1:0] (access size) of that instruction
    integer    data_acc;           // data transactions since that fetch

    // Address seen by the checker (fault injection only in the negative test).
`ifdef INJECT_PROTO_FAULT
    wire [31:0] chk_addr = mem_addr ^ (prev_wait ? 32'h4 : 32'h0);
`else
    wire [31:0] chk_addr = mem_addr;
`endif

    // Targeted lint waiver (listed in the RTL-CPU handoff): the violation
    // counter is a testbench-only integer that may be incremented several
    // times in one clock edge (several rules can fire together), so it must be
    // a blocking update; it is read only by the main sequence after the run.
    /* verilator lint_off BLKSEQ */
    task viol;
        input [8*64-1:0] what;
        begin
            n_viol = n_viol + 1;
            if (n_viol <= MAX_PRINT)
                $display("PROTOCOL VIOLATION #%0d at cycle %0d: %0s (valid=%b instr=%b addr=%08h wdata=%08h wstrb=%b ready=%b pc=%08h)",
                         n_viol, cyc, what, mem_valid, mem_instr, mem_addr, mem_wdata, mem_wstrb,
                         mem_ready, dbg_pc);
        end
    endtask
    /* verilator lint_on BLKSEQ */

    // Expected store strobe for funct3 size f3[1:0] at byte offset a.
    function [3:0] exp_strb;
        input [1:0] sz;
        input [1:0] a;
        begin
            case (sz)
                2'b00:   exp_strb = 4'b0001 << a;
                2'b01:   exp_strb = a[1] ? 4'b1100 : 4'b0011;
                default: exp_strb = 4'b1111;
            endcase
        end
    endfunction

    // Natural alignment of size sz (00 byte, 01 half, 10 word) at offset a.
    function aligned;
        input [1:0] sz;
        input [1:0] a;
        begin
            case (sz)
                2'b00:   aligned = 1'b1;
                2'b01:   aligned = ~a[0];
                2'b10:   aligned = (a == 2'b00);
                default: aligned = 1'b0;   // 11 is not a valid RV32I size
            endcase
        end
    endfunction

    always @(posedge clk) begin
        if (rst) begin
            prev_wait <= 1'b0;
            data_acc  <= 0;
            last_op   <= 7'd0;
            last_sz   <= 2'd0;
        end else begin
            // P3: X/Z checks
            if (^mem_valid === 1'bx) viol("X/Z on mem_valid");
            if (mem_valid && ((^chk_addr === 1'bx) || (^mem_wstrb === 1'bx) || (^mem_instr === 1'bx)))
                viol("X/Z on mem_addr/mem_wstrb/mem_instr while valid");
            // P2: ready without valid (checks the TB slave itself)
            if (mem_ready && !mem_valid) viol("mem_ready without mem_valid");
            // P7: no requests while halted
            if (halted && mem_valid) viol("bus request while halted");
            // P1: stability while waiting
            if (prev_wait) begin
                if (!mem_valid)
                    viol("mem_valid dropped before mem_ready");
                else if ((chk_addr !== prev_addr) || (mem_wdata !== prev_wdata) ||
                         (mem_wstrb !== prev_wstrb) || (mem_instr !== prev_instr))
                    viol("request changed while waiting for mem_ready");
            end
            // P4/P5/P6: checks in the first cycle of every transaction
            if (mem_valid && !prev_wait) begin
                if (mem_instr) begin
                    if (chk_addr[1:0] != 2'b00) viol("misaligned fetch address on the bus");
                    if (mem_wstrb != 4'd0)      viol("fetch with non-zero wstrb");
                end else begin
                    if (data_acc != 0) viol("more than one data access per instruction");
                    if (last_op == 7'b0000011) begin                // LOAD
                        if (mem_wstrb != 4'd0) viol("load with non-zero wstrb");
                        if (!aligned(last_sz, chk_addr[1:0]))
                            viol("MISALIGNED LOAD reached the bus");
                    end else if (last_op == 7'b0100011) begin       // STORE
                        if (!aligned(last_sz, chk_addr[1:0]))
                            viol("MISALIGNED STORE reached the bus");
                        else if (mem_wstrb != exp_strb(last_sz, chk_addr[1:0]))
                            viol("store strobe does not match size/address");
                    end else begin
                        viol("data access by a non load/store instruction");
                    end
                end
            end
            // bookkeeping
            if (mem_valid && mem_ready) begin
                if (mem_instr) begin
                    last_op  <= mem_rdata[6:0];
                    last_sz  <= mem_rdata[13:12];
                    data_acc <= 0;
                end else begin
                    data_acc <= data_acc + 1;
                end
            end
            prev_wait  <= mem_valid & ~mem_ready;
            prev_addr  <= chk_addr;
            prev_wdata <= mem_wdata;
            prev_wstrb <= mem_wstrb;
            prev_instr <= mem_instr;
        end
    end

    // =========================================================================
    // Main sequence
    // =========================================================================
    integer i, n_fail;
    reg     timeout;
    reg     ok;
    real    cpi;

    task check;       // print PASS/FAIL line for one comparison
        input [8*48-1:0] what;
        input [31:0]     got;
        input [31:0]     exp;
        begin
            if (got === exp)
                $display("PASS: %0s : got 0x%08h expected 0x%08h", what, got, exp);
            else begin
                $display("FAIL: %0s : got 0x%08h expected 0x%08h", what, got, exp);
                n_fail = n_fail + 1;
            end
        end
    endtask

    initial begin
        n_fail = 0; n_viol = 0;
        led = 6'd0; tohost_val = 32'd0; tohost_seen = 1'b0; tohost_pc = 32'd0;
        bus_err = 1'b0; uart_n = 0;
        for (i = 0; i < UART_MAX; i = i + 1) uart_buf[i] = 8'd0;
        for (i = 0; i < META_WORDS; i = i + 1) meta[i] = 32'd0;

        // ---- plusargs ----
        if (!$value$plusargs("prog=%s", prog_file)) begin $display("FAIL: +prog missing"); $fatal(1); end
        if (!$value$plusargs("sig=%s",  sig_file))  begin $display("FAIL: +sig missing");  $fatal(1); end
        if (!$value$plusargs("meta=%s", meta_file)) begin $display("FAIL: +meta missing"); $fatal(1); end
        if (!$value$plusargs("name=%s", test_name)) test_name = "test";
        if (!$value$plusargs("ws=%d", ws)) ws = 0;
        if (!$value$plusargs("rand_stall=%d", rand_stall)) rand_stall = 0;
        if (!$value$plusargs("seed=%d", seed)) seed = 1;
        if (!$value$plusargs("max_cycles=%d", max_cycles)) max_cycles = 200000;
        if (ws < 0 || ws > 3) begin $display("FAIL: +ws must be 0..3"); $fatal(1); end

        $readmemh(prog_file, ram);
        $readmemh(sig_file, sig_exp);
        $readmemh(meta_file, meta);
`ifdef INJECT_SIG_FAULT
        sig_exp[5] = sig_exp[5] ^ 32'h1;
        $display("NOTE: INJECT_SIG_FAULT active (expected signature word 5 corrupted)");
`endif
        $display("INFO: test=%0s ws=%0d rand_stall=%0d seed=%0d prog=%0s", test_name, ws, rand_stall, seed, prog_file);

        // ---- reset: 4 cycles ----
        repeat (4) @(posedge clk);
        #1 rst = 1'b0;

        // ---- run until the stop point or the watchdog ----
        timeout = 1'b0;
        while (!freeze && !timeout) begin
            @(posedge clk);
            if (cyc >= max_cycles) timeout = 1'b1;
        end
        #1;
        repeat (3) @(posedge clk);   // let a few idle cycles pass (P7 check while halted)
        #1;

        // ---- comparisons ----
        if (timeout) begin
            $display("FAIL: watchdog: no stop after %0d cycles (pc=%08h halted=%b)", max_cycles, dbg_pc, halted);
            n_fail = n_fail + 1;
        end
        check("stop kind (0 tohost, 1 trap)", {31'd0, halted}, meta[0]);
        if (meta[0] == 32'd1)
            check("halt pc", dbg_pc, meta[2]);
        else
            check("TOHOST store pc", tohost_pc, meta[2]);
        check("trap_cause", {28'd0, trap_cause}, meta[1]);
        check("instret (retire pulses)", instret, meta[3]);
        check("TOHOST written", {31'd0, tohost_seen}, meta[4]);
        check("TOHOST value", tohost_val, meta[5]);
        check("bus_err", {31'd0, bus_err}, meta[6]);
        check("LED", {26'd0, led}, meta[7]);
        check("UART byte count", uart_n, meta[8]);
        ok = 1'b1;
        for (i = 0; i < UART_MAX; i = i + 1)
            if (i < uart_n && i < meta[8] && {24'd0, uart_buf[i]} !== meta[9+i]) ok = 1'b0;
        check("UART bytes equal", {31'd0, ok}, 32'd1);
        ok = 1'b1;
        for (i = 0; i < 32; i = i + 1) begin
            if (ram[SIG_WORD0 + i[9:0]] !== sig_exp[i]) begin
                $display("FAIL: signature word %0d (addr 0x%04h): got 0x%08h expected 0x%08h",
                         i, 32'h0F00 + 4*i, ram[SIG_WORD0 + i[9:0]], sig_exp[i]);
                ok = 1'b0;
            end
        end
        check("signature 0x0F00..0x0F7C (32 words) equal", {31'd0, ok}, 32'd1);
        check("bus-protocol violations", n_viol, 32'd0);

        cpi = (instret > 0) ? (run_cycles * 1.0) / instret : 0.0;
        $display("INFO: cycles=%0d instret=%0d fetch=%0d load=%0d store=%0d wait_cycles=%0d",
                 run_cycles, instret, n_fetch, n_load, n_store, n_wait);
        $display("RESULT name=%0s ws=%0d rand=%0d status=%0s cycles=%0d instret=%0d cpi=%0.3f viol=%0d",
                 test_name, ws, rand_stall, (n_fail == 0) ? "PASS" : "FAIL",
                 run_cycles, instret, cpi, n_viol);
        if (n_fail == 0) begin
            $display("TEST PASSED");
            $finish;
        end else begin
            $display("TEST FAILED (%0d failing checks)", n_fail);
            $fatal(1);
        end
    end

endmodule

`default_nettype wire
