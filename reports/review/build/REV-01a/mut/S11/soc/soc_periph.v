// =============================================================================
// File      : design/rtl/soc/soc_periph.v
// Module    : soc_periph   (LED, UART TX, UART_STATUS, CYCLE, TOHOST)
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Reqs      : REQ-SYS-006 (reset values), REQ-SYS-007 (bus protocol),
//             REQ-SYS-011 (peripheral registers), REQ-SYS-012 (UART 8N1,
//             115200 Bd, divider 234), REQ-SYS-013 (LED register)
// Task      : RTL-SOC (fpga-engineer)
// Spec      : ARCHITECTURE.md 4.1 (+ 9: reset values LED = 0, TOHOST = 0);
//             INTERFACES.json rev C "periph_regs", "uart".
//
// REGISTER MAP (base 0x1000_0000; the block decodes mem_addr[11:2])
//   0x00 LED          RW  [5:0] 1 = LED lit (soc_top inverts for the active-
//                         low pins). Write needs mem_wstrb[0]. Reset 0.
//   0x04 UART_TX      W   [7:0] byte to send; IGNORED while tx_busy = 1 (the
//                         frame in progress is never disturbed). Reads 0.
//   0x08 UART_STATUS  R   [0] tx_busy (1 from the accepting edge of a UART_TX
//                         write until the end of the stop bit).
//   0x0C CYCLE        R   free-running 32-bit counter: number of rising clock
//                         edges since rst was released (0 in the first cycle
//                         after reset), wraps modulo 2^32 (REQ-SYS-011).
//                         The value returned is the one present in the cycle
//                         the read is accepted.
//   0x10 TOHOST       RW  [31:0] testbench mailbox (1 = pass, other odd value
//                         = fail code). Byte strobes honoured. Reset 0.
//   0x14 .. 0xFFC     -   reserved: read 0, writes ignored, mem_ready still
//                         returned (address bits [27:12] are not decoded, so
//                         the 32-byte block is aliased in 0x1xxx_xxxx).
//   Writes to read-only registers (UART_STATUS, CYCLE) are ignored.
//
// UART TRANSMITTER (8N1, LSB first, idle high)
//   Bit time = UART_DIV clock cycles; UART_DIV = 234 at 27 MHz gives
//   27e6 / 234 = 115384.6 Bd, +0.16 % vs 115200 Bd (bit time -0.16 %,
//   CALCULATION, ARCHITECTURE.md 4.1), far inside the 2 % budget of
//   REQ-SYS-012. Frame = start(0), d0..d7, stop(1) = 10 bits = 10*UART_DIV
//   cycles = 2340 cycles = 86.7 us. tx_busy covers the whole frame,
//   including the full stop bit, so back-to-back bytes (CPU polls tx_busy
//   then writes) always get a complete stop bit.
//   The line is driven from a flip-flop (tx_q) - no combinational glitches on
//   the pin. Implementation: a 9-bit shift register {stop, d7..d0}, a bit
//   counter 0..9 and a down-counter of UART_DIV cycles per bit:
//     write accepted (idle) : tx_q <= 0 (start bit), sh <= {1, data},
//                             div <= UART_DIV-1, nbit <= 0, busy <= 1
//     div == 0 and nbit < 9 : tx_q <= sh[0] (next bit), sh >>= 1, nbit++,
//                             div <= UART_DIV-1
//     div == 0 and nbit == 9: end of the stop bit -> busy <= 0, tx_q <= 1
//   So every bit lasts exactly UART_DIV cycles (checked in tests/soc).
//
// BUS TIMING (native valid/ready slave, same as soc_ram)
//   Cycle 1 (mem_valid = 1, ready_q = 0): ACCEPT - writes are performed at
//   this edge, read data is selected and registered into rdata_q.
//   Cycle 2: mem_ready = 1 for one cycle, mem_rdata = rdata_q.
//   => 1 wait state. ~ready_q prevents a duplicate accept when the CPU holds
//   mem_valid for a back-to-back request (see soc_ram.v).
//   mem_rdata is forced to 0 outside the ready cycle (cheap, and makes bus
//   traces easier to read).
//
// PARAMETERS
//   UART_DIV : clocks per UART bit (234 = 27 MHz / 115200 Bd, INTERFACES.json
//              uart.divider_clocks_per_bit). Changed only by the negative
//              testbench run that proves the bit-timing checker works.
// RESET: synchronous active-high rst: LED = 0, TOHOST = 0, CYCLE = 0,
//   tx_busy = 0, uart_tx = 1 (idle line), ready_q = 0 (ARCHITECTURE.md 9).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module soc_periph #(
    parameter integer UART_DIV = 234
) (
    input  wire        clk,
    input  wire        rst,
    // ---- bus slave port (qualified by soc_bus: addr[31:28] == 1) -------------
    input  wire        mem_valid,
    input  wire [31:0] mem_addr,
    input  wire [31:0] mem_wdata,
    input  wire [3:0]  mem_wstrb,
    output wire        mem_ready,
    output wire [31:0] mem_rdata,
    // ---- outputs -------------------------------------------------------------
    output wire [5:0]  led,        // LED register, 1 = lit (active-high here)
    output wire        uart_tx,    // serial line, idle 1
    output wire [31:0] tohost      // mailbox value (debug / testbench)
);

    // Width of the UART bit-time down-counter (234 needs 8 bits).
    localparam integer DIVW = (UART_DIV > 255) ? 16 : 8;
    localparam integer    DIV_M1     = UART_DIV - 1;
    localparam [DIVW-1:0] DIV_RELOAD = DIV_M1[DIVW-1:0];   // explicit truncation

    // -------------------------------------------------------------------------
    // Address decode: word index [11:2]; registers live at words 0..4.
    // -------------------------------------------------------------------------
    wire [9:0] widx       = mem_addr[11:2];
    wire       sel_led    = (widx == 10'd0);
    wire       sel_tx     = (widx == 10'd1);
    wire       sel_status = (widx == 10'd2);
    wire       sel_cycle  = (widx == 10'd3);
    wire       sel_tohost = (widx == 10'd4);
    // Not decoded: [31:12] (region/alias) and [1:0] (byte offset; byte
    // writes are expressed by mem_wstrb).
    wire       addr_unused = &{1'b0, mem_addr[31:12], mem_addr[1:0]};

    reg        ready_q;
    reg [31:0] rdata_q;
    wire       accept = mem_valid && !ready_q;
    wire       is_wr  = (mem_wstrb != 4'b0000);
    wire       wr     = accept && is_wr;

    // -------------------------------------------------------------------------
    // LED register (RW [5:0]); needs the byte-0 strobe.
    // -------------------------------------------------------------------------
    reg [5:0] led_q;
    always @(posedge clk) begin
        if (rst)                              led_q <= 6'd0;
        else if (wr && sel_led && mem_wstrb[0]) led_q <= mem_wdata[5:0];
    end
    assign led = led_q;

    // -------------------------------------------------------------------------
    // TOHOST mailbox (RW 32-bit, byte strobes).
    // -------------------------------------------------------------------------
    reg [31:0] tohost_q;
    always @(posedge clk) begin
        if (rst) tohost_q <= 32'd0;
        else if (wr && sel_tohost) begin
            if (mem_wstrb[0]) tohost_q[7:0]   <= mem_wdata[7:0];
            if (mem_wstrb[1]) tohost_q[15:8]  <= mem_wdata[15:8];
            if (mem_wstrb[2]) tohost_q[23:16] <= mem_wdata[23:16];
            if (mem_wstrb[3]) tohost_q[31:24] <= mem_wdata[31:24];
        end
    end
    assign tohost = tohost_q;

    // -------------------------------------------------------------------------
    // CYCLE counter: free-running since reset release, wraps at 2^32.
    // -------------------------------------------------------------------------
    reg [31:0] cycle_q;
    always @(posedge clk) begin
        if (rst) cycle_q <= 32'd0;
        else     cycle_q <= cycle_q + 32'd1;
    end

    // -------------------------------------------------------------------------
    // UART transmitter (see header for the bit sequencing).
    // -------------------------------------------------------------------------
    reg            tx_busy;
    reg            tx_q;
    reg [8:0]      tx_sh;      // {stop bit, d7 .. d0}; bit 0 is sent next
    reg [3:0]      tx_nbit;    // index of the bit currently on the line (0 = start)
    reg [DIVW-1:0] tx_div;     // cycles left in the current bit, minus 1
    // A UART_TX write starts a frame only when idle and only with byte 0
    // enabled (the byte lives in [7:0]); a write while busy is dropped.
    wire tx_start = wr && sel_tx && mem_wstrb[0] && !tx_busy;

    always @(posedge clk) begin
        if (rst) begin
            tx_busy <= 1'b0;
            tx_q    <= 1'b1;               // idle line = mark
            tx_sh   <= 9'h1FF;
            tx_nbit <= 4'd0;
            tx_div  <= {DIVW{1'b0}};
        end else if (!tx_busy) begin
            if (tx_start) begin
                tx_busy <= 1'b1;
                tx_q    <= 1'b0;           // start bit begins at this edge
                tx_sh   <= {1'b1, mem_wdata[7:0]};
                tx_nbit <= 4'd0;
                tx_div  <= DIV_RELOAD;
            end
        end else if (tx_div != {DIVW{1'b0}}) begin
            tx_div <= tx_div - 1'b1;       // stay in the current bit
        end else if (tx_nbit == 4'd9) begin
            tx_busy <= 1'b0;               // stop bit complete: frame done
            tx_q    <= 1'b1;
        end else begin
            tx_q    <= tx_sh[0];           // next bit: d0 .. d7, then stop
            tx_sh   <= {1'b1, tx_sh[8:1]};
            tx_nbit <= tx_nbit + 4'd1;
            tx_div  <= DIV_RELOAD;
        end
    end
    assign uart_tx = tx_q;

    // -------------------------------------------------------------------------
    // Read multiplexer (registered at accept) and ready pulse.
    // -------------------------------------------------------------------------
    reg [31:0] rd_mux;
    always @(*) begin
        rd_mux = 32'd0;                    // UART_TX (W only) and reserved: 0
        if (sel_led)    rd_mux = {26'd0, led_q};
        if (sel_status) rd_mux = 32'd0;
        if (sel_cycle)  rd_mux = cycle_q;
        if (sel_tohost) rd_mux = tohost_q;
    end

    always @(posedge clk) begin
        if (rst) begin
            ready_q <= 1'b0;
            rdata_q <= 32'd0;
        end else begin
            ready_q <= accept;
            // Write transactions return 0; reads return the selected register.
            rdata_q <= (accept && !is_wr) ? rd_mux : 32'd0;
        end
    end

    assign mem_ready = ready_q;
    assign mem_rdata = rdata_q;

endmodule

`default_nettype wire
