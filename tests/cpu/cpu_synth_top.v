`default_nettype none
`timescale 1ns / 1ps  // simulation only
// =============================================================================
// File        : tests/cpu/cpu_synth_top.v
// Module      : cpu_synth_top  (synthesis / P&R test wrapper, NOT the SoC)
// Project     : SC-TPU + RV32I SoC on Sipeed Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Task        : RTL-CPU (area and Fmax of rv32i_core alone)
// Author      : fpga-engineer (Claude Code specialist)
//
// PURPOSE
//   rv32i_core has 2 x 32 + 2 x 32 + ... ~140 bus/debug pins, far more than a
//   QN88 package offers, and with unconnected outputs Yosys would delete the
//   whole core. This wrapper gives the core a realistic environment so that
//   synth_gowin + nextpnr report the real cost and timing of the CPU:
//     * a 4 KiB program/data RAM in BSRAM (1024 x 32, byte write enables,
//       registered read -> 1 wait state, like the future SoC RAM), initialised
//       from INIT_FILE so the core has a real program to execute;
//     * a 6-bit "LED" register written by any store to region 0x1xxx_xxxx;
//     * LEDs driven by that register XOR-ed with XOR reductions of the bus
//       and debug signals, so every core output is observable and nothing
//       is optimised away;
//     * the board reset path of ARCHITECTURE.md 2: btn_rst_n (active-low) ->
//       2-FF synchroniser -> synchronous active-high rst.
//   Ports and pin names follow design/constraints/tangnano9k.cst.
//
// TIMING
//   RAM slave: mem_ready_q <= mem_valid & ~mem_ready_q, i.e. ready in the 2nd
//   cycle of every transaction; BSRAM read data is valid in that cycle.
//   Paths covered by P&R: core internal paths, core -> BSRAM address/data/
//   byte-enable inputs, BSRAM output -> core (ir, load extraction).
//
// PARAMETERS
//   INIT_FILE  $readmemh image of the RAM (1024 lines). Default: the official
//              random test rand_00 of the SW-01b CPU suite.
//
// REQUIREMENT REFERENCES
//   ARCHITECTURE.md 2, 3, 4 (RAM 4 KiB BSRAM), 6; RTL-CPU deliverable 3.
// =============================================================================

module cpu_synth_top #(
    parameter INIT_FILE = "sim/data/cpu_tests/rand_00.hex"
) (
    input  wire       clk,        // 27 MHz board oscillator (pin 52)
    input  wire       btn_rst_n,  // S1 push-button, active-low
    output wire [5:0] led_n       // board LEDs, active-low
);

    // ---- Reset synchroniser (power-up: reset asserted) ------------------------
    reg [1:0] rst_sync = 2'b11;
    always @(posedge clk) rst_sync <= {rst_sync[0], ~btn_rst_n};
    wire rst = rst_sync[1];

    // ---- Core -------------------------------------------------------------------
    wire        mem_valid, mem_instr;
    wire [31:0] mem_addr, mem_wdata;
    wire [3:0]  mem_wstrb;
    wire        mem_ready;
    wire [31:0] mem_rdata;
    wire        halted, retire;
    wire [3:0]  trap_cause;
    wire [31:0] dbg_pc;

    rv32i_core u_core (
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

    // ---- 4 KiB RAM (BSRAM), addr[11:2], byte enables, registered read ----------
    // no_rw_check: a write and a read of the same word never need a defined
    // result in the same cycle (a store transaction does not use mem_rdata).
    (* ram_style = "block", no_rw_check *) reg [31:0] ram [0:1023];
    initial $readmemh(INIT_FILE, ram);

    wire       is_ram = (mem_addr[31:28] == 4'h0);
    wire [9:0] ram_a  = mem_addr[11:2];
    wire [3:0] ram_we = (mem_valid & is_ram) ? mem_wstrb : 4'b0000;
    reg [31:0] ram_q;
    always @(posedge clk) begin
        if (ram_we[0]) ram[ram_a][7:0]   <= mem_wdata[7:0];
        if (ram_we[1]) ram[ram_a][15:8]  <= mem_wdata[15:8];
        if (ram_we[2]) ram[ram_a][23:16] <= mem_wdata[23:16];
        if (ram_we[3]) ram[ram_a][31:24] <= mem_wdata[31:24];
        ram_q <= ram[ram_a];
    end

    // One wait state for every slave (ready in the 2nd cycle of mem_valid).
    reg ready_q = 1'b0;
    always @(posedge clk) ready_q <= ~rst & mem_valid & ~ready_q;
    assign mem_ready = ready_q;
    assign mem_rdata = ram_q;

    // ---- LED register (stores to region 0x1) + observability XORs ---------------
    reg [5:0] led_reg = 6'd0;
    always @(posedge clk) begin
        if (rst)
            led_reg <= 6'd0;
        else if (mem_valid & mem_ready & (mem_addr[31:28] == 4'h1) & mem_wstrb[0])
            led_reg <= mem_wdata[5:0];
    end

    // Register the XOR reductions so the LED pins are driven from flops.
    reg [5:0] led_q = 6'd0;
    always @(posedge clk) begin
        led_q <= led_reg ^ {halted ^ retire,
                            ^trap_cause,
                            ^dbg_pc,
                            ^mem_addr,
                            ^mem_wdata ^ ^mem_wstrb,
                            mem_valid ^ mem_instr};
    end
    assign led_n = ~led_q;   // active-low LEDs

endmodule

`default_nettype wire
