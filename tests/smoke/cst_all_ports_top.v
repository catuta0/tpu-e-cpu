`default_nettype none
`timescale 1ns / 1ps
// =============================================================================
// File    : tests/smoke/cst_all_ports_top.v
// Module  : cst_all_ports_top
// Task    : ST-FPGA-01 (constraint-file check, NOT a functional design)
//
// PURPOSE
//   smoke_counter uses only clk, btn_rst_n and led_n, so its P&R run leaves the
//   uart_tx / uart_rx / btn_s2_n constraints of design/constraints/tangnano9k.cst
//   untested. This throw-away top uses EVERY port of that CST so that
//   nextpnr-himbaechel must legalise all of them together (pin legality, IO
//   standard vs. bank voltage: LVCMOS18 on bank-3 pins next to LVCMOS33 on the
//   UART pins). The SoC top will use the same port names (INTERFACES.json rev A).
//
// BEHAVIOUR (only to give every port a real load/driver, never loaded on HW)
//   * uart_tx  = registered copy of uart_rx (loop-back) -> idle-high line.
//   * led_n    = registered {btn_s2_n, btn_rst_n, 4'b1111}: LED6/LED5 light
//                while S2/S1 are pressed (active-low LEDs, active-low buttons).
//   No reset is needed: the registers just follow their inputs.
// =============================================================================
module cst_all_ports_top (
    input  wire       clk,        // 27 MHz oscillator, pin 52
    input  wire       btn_rst_n,  // S1, pin 3 (active-low)
    input  wire       btn_s2_n,   // S2, pin 4 (active-low, spare)
    input  wire       uart_rx,    // from BL702, pin 18
    output reg        uart_tx,    // to BL702, pin 17
    output reg  [5:0] led_n       // LEDs, pins 10,11,13,14,15,16 (active-low)
);
    // Register every path so the design has a timed clock domain and the
    // input/output buffers cannot be optimised away.
    always @(posedge clk) begin
        uart_tx <= uart_rx;                          // loop-back, idles high
        led_n   <= {btn_s2_n, btn_rst_n, 4'b1111};   // pressed (0) -> LED on (0)
    end
endmodule
`default_nettype wire
