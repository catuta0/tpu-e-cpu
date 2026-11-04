// =============================================================================
// File      : tests/smoke/dsp/dsp_smoke_top.v
// Module    : dsp_smoke_top   (SYNTHESIS-ONLY board wrapper of dsp_smoke_mac)
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Task      : ST-FPGA-02 - fpga-engineer
//
// PURPOSE
//   Gives dsp_smoke_mac live inputs and observable outputs using only the
//   board pins of design/constraints/tangnano9k.cst, so Yosys cannot
//   constant-fold or delete the multiplier:
//     * a 16-bit Galois LFSR (mixed with the uart_rx pin, so the stimulus is
//       not a compile-time constant) provides a = lfsr[7:0], b = lfsr[15:8];
//     * acc is XOR-folded onto the 6 LEDs and uart_tx (registered).
//   Not a functional design; never programmed into hardware (CLAUDE.md).
//
// PORTS (INTERFACES.json top_ports): clk (27 MHz, pin 52), btn_rst_n (S1,
//   active-low), uart_rx, led_n[5:0], uart_tx.
// RESET: 2-FF synchroniser -> synchronous active-high rst (ARCHITECTURE.md 2).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module dsp_smoke_top (
    input  wire       clk,
    input  wire       btn_rst_n,
    input  wire       uart_rx,
    output reg  [5:0] led_n,
    output reg        uart_tx
);

    // ---- reset synchroniser (2 FF) -------------------------------------------
    reg [1:0] rst_sync = 2'b11;
    always @(posedge clk) rst_sync <= {rst_sync[0], ~btn_rst_n};
    wire rst = rst_sync[1];

    // ---- stimulus: 16-bit Galois LFSR x^16+x^14+x^13+x^11+1 (+ uart_rx) ------
    reg [15:0] lfsr;
    always @(posedge clk) begin
        if (rst) lfsr <= 16'hACE1;
        else     lfsr <= {lfsr[14:0], 1'b0} ^ (lfsr[15] ? 16'h6801 : 16'h0000)
                         ^ {15'd0, uart_rx};
    end

    // Periodic clear (every 256 cycles) so the accumulator stays "interesting".
    reg [7:0] cnt;
    always @(posedge clk) cnt <= rst ? 8'd0 : cnt + 8'd1;

    wire signed [15:0] p_q;
    wire signed [23:0] acc;

    dsp_smoke_mac #(.ACC_W(24)) u_mac (
        .clk(clk), .rst(rst), .en(1'b1), .clr(cnt == 8'd0),
        .a(lfsr[7:0]), .b(lfsr[15:8]), .p_q(p_q), .acc(acc));

    // ---- observability: fold acc and p_q onto 7 pins -------------------------
    wire [23:0] obs = acc ^ {8'd0, p_q};
    always @(posedge clk) begin
        led_n[0] <= ~(^obs[3:0]);
        led_n[1] <= ~(^obs[7:4]);
        led_n[2] <= ~(^obs[11:8]);
        led_n[3] <= ~(^obs[15:12]);
        led_n[4] <= ~(^obs[19:16]);
        led_n[5] <= ~(^obs[21:20]);
        uart_tx  <= ^obs[23:22];
    end

endmodule

`default_nettype wire
