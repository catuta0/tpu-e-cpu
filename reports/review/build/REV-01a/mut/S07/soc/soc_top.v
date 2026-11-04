// =============================================================================
// File      : design/rtl/soc/soc_top.v
// Module    : soc_top   (Tang Nano 9K top level of the SC-TPU + RV32I SoC)
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Reqs      : REQ-SYS-003 (SoC composition), REQ-SYS-004 (single 27 MHz
//             clock domain), REQ-SYS-005 (2-FF reset synchroniser),
//             REQ-SYS-013 (LED inversion), REQ-SYS-014 (top-level ports),
//             REQ-TIM-002/003 (synchronous design, asynchronous inputs)
// Task      : RTL-SOC (fpga-engineer)
// Spec      : ARCHITECTURE.md 1 (block diagram), 2 (clock/reset), 4 (memory
//             map), 7 (ports); INTERFACES.json rev C "top_ports", "reset",
//             "memory_map", "init_files"; pins: design/constraints/tangnano9k.cst
//
// BLOCK DIAGRAM
//
//   btn_rst_n --> [2-FF sync] --> rst (synchronous, active-high, to all logic)
//
//                 +------------+  mem_valid/addr/wdata/wstrb   +---------+
//   clk --------> | rv32i_core |------------------------------>| soc_bus |
//   (27 MHz,      | (multicycle|<------------------------------|  addr   |
//    pin 52)      |  RV32I)    |  mem_ready / mem_rdata        | [31:28] |
//                 +------------+                               +---------+
//                       0x0 |               0x1 |                 0x2 |
//                 +---------v--+   +------------v---+   +-------------v--+
//                 | soc_ram    |   | soc_periph     |   | sc_tpu         |
//                 | 4 KiB BSRAM|   | LED UART CYCLE |   | SC-TPU 16x8,   |
//                 | INIT_FILE  |   | TOHOST         |   | 2 KiB weights  |
//                 +------------+   +--+--------+----+   +----------------+
//                                     | led    | uart_tx
//                                     v        v
//                       led_n = ~led (active-low)   uart_tx (8N1 115200)
//   Unmapped regions (0x3..0xF): answered inside soc_bus (read 0, sticky
//   bus_err).
//
// PORTS (exactly INTERFACES.json top_ports; pin numbers in tangnano9k.cst)
//   clk        in   27 MHz board oscillator (pin 52, GCLKT_3)
//   btn_rst_n  in   push-button S1, active-low (pin 3, pull-up)
//   led_n[5:0] out  LEDs 1..6, ACTIVE-LOW (pins 10,11,13,14,15,16):
//                   led_n[i] = ~LED[i] so LED register bit 1 = LED lit
//   uart_tx    out  to the on-board BL702 USB-UART bridge (pin 17)
//   uart_rx    in   from the BL702 (pin 18): UNUSED in rev A/B (INTERFACES.json
//                   note). It is tied to a kept "unused" net so that the
//                   input buffer and its pin constraint stay in the netlist
//                   (all 10 IOs of REQ-RES-005 are present); it feeds no logic,
//                   so no synchroniser is needed (REQ-TIM-003 applies only
//                   if it is ever used).
//
// RESET (ARCHITECTURE.md 2, REQ-SYS-005)
//   rst_sync is a 2-FF shift register clocked by clk that samples the
//   inverted, asynchronous button level. Both flops power up as 1 (FPGA
//   initial value), so the design is held in reset during the first 2 cycles
//   after configuration even without a button press. rst = rst_sync[1]:
//     button pressed (btn_rst_n = 0): rst = 1 after 2 rising edges;
//     button released              : rst = 0 after 2 rising edges.
//   The first flop may go metastable when the button edge is close to a
//   clock edge; it has one full clock period (37 ns) to resolve before the
//   second flop samples it, and only rst_sync[1] is used by the logic. Both
//   assertion and release are synchronous, which is all a fully synchronous
//   design needs (every internal register uses `if (rst)` inside
//   `always @(posedge clk)`; no asynchronous resets, REQ-TIM-002).
//   Button bounce simply produces a few extra reset pulses, which is
//   harmless (every reset is complete: the CPU re-runs its 32-cycle CLEAR).
//   After rst falls the CPU first clears its register file (32 cycles,
//   rv32i_core CLEAR state), then fetches from 0x0000_0000.
//
// DEBUG SIGNALS (not on pins; there are no spare ports in INTERFACES.json)
//   bus_err (soc_bus), cpu_halted, cpu_trap_cause, cpu_dbg_pc, cpu_retire and
//   tohost are internal nets, observed hierarchically by tests/soc/tb_soc.v.
//   Synthesis removes them (no load) except where they feed real logic.
//
// PARAMETERS
//   INIT_FILE   : RAM image ($readmemh, 1024 x 32-bit), default the SoC demo
//                 program sim/data/soc_demo_prog.hex (ARCHITECTURE.md 8).
//   WEIGHT_INIT / BIAS_INIT / INPUT_INIT : SC-TPU init files (spec 5.6),
//                 default sim/data/{weights,bias,input}.hex. Paths are
//                 relative to the project root (Icarus and Yosys are both run
//                 from there).
//   RNG_MODE    : SC-TPU RNG mode, default 2 (since rev B, ADR-008; rev C ADR-010).
//   UART_DIV    : clocks per UART bit, default 234 (115200 Bd at 27 MHz).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module soc_top #(
    parameter         INIT_FILE   = "sim/data/soc_demo_prog.hex",
    parameter         WEIGHT_INIT = "sim/data/weights.hex",
    parameter         BIAS_INIT   = "sim/data/bias.hex",
    parameter         INPUT_INIT  = "sim/data/input.hex",
    parameter integer RNG_MODE    = 2,
    parameter integer UART_DIV    = 234
) (
    input  wire       clk,
    input  wire       btn_rst_n,
    output wire [5:0] led_n,
    output wire       uart_tx,
    input  wire       uart_rx
);

    // =========================================================================
    // Reset synchroniser: btn_rst_n (async, active-low) -> rst (sync, active-high)
    // =========================================================================
    reg [1:0] rst_sync = 2'b11;          // power-up value: in reset
    always @(posedge clk)
        rst_sync <= {rst_sync[0], ~btn_rst_n};
    wire rst = rst_sync[0];

    // uart_rx is unused (INTERFACES.json); `keep` preserves its input buffer
    // so that the pin stays constrained and placed (see PORTS above).
    (* keep *) wire uart_rx_unused = uart_rx;

    // =========================================================================
    // CPU (bus master)
    // =========================================================================
    wire        mem_valid, mem_instr;
    wire [31:0] mem_addr, mem_wdata;
    wire [3:0]  mem_wstrb;
    wire        mem_ready;
    wire [31:0] mem_rdata;
    wire        cpu_halted, cpu_retire;
    wire [3:0]  cpu_trap_cause;
    wire [31:0] cpu_dbg_pc;

    rv32i_core u_cpu (
        .clk        (clk),
        .rst        (rst),
        .mem_valid  (mem_valid),
        .mem_instr  (mem_instr),
        .mem_addr   (mem_addr),
        .mem_wdata  (mem_wdata),
        .mem_wstrb  (mem_wstrb),
        .mem_ready  (mem_ready),
        .mem_rdata  (mem_rdata),
        .halted     (cpu_halted),
        .trap_cause (cpu_trap_cause),
        .dbg_pc     (cpu_dbg_pc),
        .retire     (cpu_retire)
    );

    // =========================================================================
    // Bus decoder / multiplexer
    // =========================================================================
    wire        ram_valid, ram_ready;
    wire [31:0] ram_rdata;
    wire        per_valid, per_ready;
    wire [31:0] per_rdata;
    wire        tpu_valid, tpu_ready;
    wire [31:0] tpu_rdata;
    wire        bus_err;

    soc_bus u_bus (
        .clk       (clk),
        .rst       (rst),
        .mem_valid (mem_valid),
        .mem_addr  (mem_addr),
        .mem_ready (mem_ready),
        .mem_rdata (mem_rdata),
        .ram_valid (ram_valid),
        .ram_ready (ram_ready),
        .ram_rdata (ram_rdata),
        .per_valid (per_valid),
        .per_ready (per_ready),
        .per_rdata (per_rdata),
        .tpu_valid (tpu_valid),
        .tpu_ready (tpu_ready),
        .tpu_rdata (tpu_rdata),
        .bus_err   (bus_err)
    );

    // =========================================================================
    // Slaves
    // =========================================================================
    soc_ram #(.INIT_FILE(INIT_FILE)) u_ram (
        .clk       (clk),
        .rst       (rst),
        .mem_valid (ram_valid),
        .mem_addr  (mem_addr),
        .mem_wdata (mem_wdata),
        .mem_wstrb (mem_wstrb),
        .mem_ready (ram_ready),
        .mem_rdata (ram_rdata)
    );

    wire [5:0]  led;
    wire [31:0] tohost;
    soc_periph #(.UART_DIV(UART_DIV)) u_periph (
        .clk       (clk),
        .rst       (rst),
        .mem_valid (per_valid),
        .mem_addr  (mem_addr),
        .mem_wdata (mem_wdata),
        .mem_wstrb (mem_wstrb),
        .mem_ready (per_ready),
        .mem_rdata (per_rdata),
        .led       (led),
        .uart_tx   (uart_tx),
        .tohost    (tohost)
    );

    // The TPU slave takes the 12-bit offset inside its 4 KiB window; its
    // mem_rdata is 0 outside its ready cycle (sc_tpu.v BUS TIMING).
    sc_tpu #(
        .NL          (16),
        .IL          (8),
        .RNG_MODE    (RNG_MODE),
        .WEIGHT_INIT (WEIGHT_INIT),
        .BIAS_INIT   (BIAS_INIT),
        .INPUT_INIT  (INPUT_INIT)
    ) u_tpu (
        .clk       (clk),
        .rst       (rst),
        .mem_valid (tpu_valid),
        .mem_addr  (mem_addr[11:0]),
        .mem_wdata (mem_wdata),
        .mem_wstrb (mem_wstrb),
        .mem_ready (tpu_ready),
        .mem_rdata (tpu_rdata)
    );

    // =========================================================================
    // LED pins: register bit 1 = lit, board LEDs are active-low.
    // led is a flip-flop output (soc_periph), so the pins are glitch-free.
    // =========================================================================
    assign led_n = ~led;

    // Debug-only nets (see header): no pin, no logic. Collected so that lint
    // documents them as intentionally unused (Verilator "unused" idiom).
    wire debug_unused = &{1'b0, bus_err, cpu_halted, cpu_retire, cpu_trap_cause,
                          cpu_dbg_pc, mem_instr, tohost};

endmodule

`default_nettype wire
