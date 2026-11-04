// =============================================================================
// File      : tests/smoke/dsp/dsp_timing_probe.v
// Module    : dsp_timing_probe   (SYNTHESIS-ONLY experiment, task ST-FPGA-02)
//
// PURPOSE
//   Answers: "does nextpnr-himbaechel-gowin (0.11.1) time paths that go
//   THROUGH a Gowin DSP primitive?"  The only register-to-register datapath
//   is   a,b,c (FF) -> (a*b)[15:8] * c  -> q (FF),
//   i.e. TWO 8x8 signed multipliers in series between flops.
//   Built twice by tests/smoke/dsp/run_dsp_smoke.sh:
//     * default synth_gowin  -> 2 x MULT9X9 in series,
//     * synth_gowin -nodsp   -> the same function in LUT/ALU fabric.
//   If the DSP build reports a routed Fmax far above any physically plausible
//   value for two multipliers in series (and its critical path does not
//   contain the MULT9X9 cells) while the LUT build reports a realistic value,
//   then DSP paths are NOT analysed by the timer.  (Supporting SOURCE: the
//   Apicula GW1N-9C chipdb timing table has classes lut/alu/sram/dff/bram/
//   fanout/glbsrc/hclk/iodelay/wire only - no DSP class.)
// PORTS: board pins of design/constraints/tangnano9k.cst.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module dsp_timing_probe (
    input  wire       clk,
    input  wire       btn_rst_n,   // unused (kept so the CST matches)
    input  wire       uart_rx,
    output reg  [5:0] led_n,
    output reg        uart_tx
);
    // 24-bit Fibonacci LFSR (taps 24,23,22,17) mixed with uart_rx: live
    // stimulus that Yosys cannot constant-fold.
    reg [23:0] l = 24'h1;
    always @(posedge clk) l <= {l[22:0], l[23] ^ l[22] ^ l[21] ^ l[16] ^ uart_rx};

    reg signed [7:0] a, b, c;
    always @(posedge clk) begin a <= l[7:0]; b <= l[15:8]; c <= l[23:16]; end

    wire signed [15:0] p1  = a * b;          // multiplier 1
    wire signed [7:0]  p1h = p1[15:8];       // upper byte feeds multiplier 2
    wire signed [15:0] p2  = p1h * c;        // multiplier 2 (in series)
    reg  signed [15:0] q;
    always @(posedge clk) q <= p2;

    always @(posedge clk) begin
        led_n   <= ~(q[5:0] ^ q[11:6]);
        uart_tx <= ^q[15:12];
    end

    // p1[7:0] is intentionally dropped (only the upper byte feeds multiplier 2).
    wire unused_ok = &{1'b0, btn_rst_n, p1[7:0]};
endmodule

`default_nettype wire
