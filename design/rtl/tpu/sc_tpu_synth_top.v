// =============================================================================
// File      : design/rtl/tpu/sc_tpu_synth_top.v
// Module    : sc_tpu_synth_top   (SYNTHESIS-ONLY wrapper, not part of the SoC)
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Reqs      : requirements/REQUIREMENTS.md REQ-RES-001..006, REQ-TIM-001 (evidence vehicle only)
// Task      : RTL-TPU (fpga-engineer): stand-alone synthesis / P&R of sc_tpu
//             for utilisation and Fmax, and the RNG_MODE / IL variant study
//             (scripts/synth_tpu_variants.sh).
//
// PURPOSE
//   sc_tpu has a 12-bit address / 32-bit data bus that does not fit the few
//   board pins, and an unconnected bus would let Yosys delete the whole TPU.
//   This wrapper keeps every TPU input "live" and every TPU output
//   observable with only the board pins of design/constraints/tangnano9k.cst:
//     * a 32-bit pseudo-random bus master (Galois LFSR, mixed with the
//       uart_rx pin so the stimulus is not a compile-time constant) issues
//       random reads and writes over the whole 4 KiB TPU window, including
//       CTRL.START, CONFIG, INPUT, BIAS and WEIGHT writes, following the
//       valid/ready protocol (hold until mem_ready, then one idle cycle);
//     * every returned mem_rdata word is XOR-accumulated into a 32-bit
//       signature register that is folded onto the 6 LEDs and uart_tx.
//   The wrapper adds only ~100 LUT/FF; its own paths are short, so the
//   reported Fmax is that of the TPU (the critical path is checked in the
//   nextpnr report, see reports/fpga/tpu/).
//
// PORTS (names from INTERFACES.json top_ports, pins from tangnano9k.cst)
//   clk (27 MHz, pin 52), btn_rst_n (S1, active-low), uart_rx (input),
//   led_n[5:0] (active-low LEDs), uart_tx.
//   Reset: 2-FF synchroniser of btn_rst_n -> synchronous active-high rst
//   (ARCHITECTURE.md 2).
//
// PARAMETERS: forwarded to sc_tpu (NL, IL, RNG_MODE, init files).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module sc_tpu_synth_top #(
    parameter integer NL          = 16,
    parameter integer IL          = 8,
    parameter integer RNG_MODE    = 2,          // rev B default (ADR-008)
    parameter         WEIGHT_INIT = "",
    parameter         BIAS_INIT   = "",
    parameter         INPUT_INIT  = ""
) (
    input  wire       clk,
    input  wire       btn_rst_n,
    input  wire       uart_rx,
    output reg  [5:0] led_n,
    output reg        uart_tx
);

    // ---- reset synchroniser (2 FF), active-high synchronous rst -------------
    reg [1:0] rst_sync = 2'b11;
    always @(posedge clk) rst_sync <= {rst_sync[0], ~btn_rst_n};
    wire rst = rst_sync[1];

    // ---- pseudo-random stimulus: 32-bit Galois LFSR (taps 32,22,2,1) --------
    // uart_rx is XORed into bit 0 so the stimulus depends on a real input.
    reg [31:0] prng;
    always @(posedge clk) begin
        if (rst) prng <= 32'h1234_5678;
        else     prng <= {prng[30:0], 1'b0} ^ (prng[31] ? 32'h0040_0003 : 32'd0)
                         ^ {31'd0, uart_rx};
    end

    // ---- bus master: one transaction at a time, one idle cycle in between ---
    reg         mem_valid;
    reg  [11:0] mem_addr;
    reg  [31:0] mem_wdata;
    reg  [3:0]  mem_wstrb;
    wire        mem_ready;
    wire [31:0] mem_rdata;
    reg  [31:0] sig;              // XOR signature of all read data

    always @(posedge clk) begin
        if (rst) begin
            mem_valid <= 1'b0;
            mem_addr  <= 12'd0;
            mem_wdata <= 32'd0;
            mem_wstrb <= 4'd0;
            sig       <= 32'd0;
        end else if (mem_valid) begin
            if (mem_ready) begin
                mem_valid <= 1'b0;
                sig       <= {sig[30:0], sig[31]} ^ mem_rdata;
            end
        end else begin
            mem_valid <= 1'b1;
            mem_addr  <= prng[11:0];
            mem_wdata <= {prng[15:0], prng[31:16]};
            // About half of the requests are reads (wstrb = 0).
            mem_wstrb <= prng[20] ? prng[24:21] : 4'b0000;
        end
    end

    sc_tpu #(
        .NL(NL), .IL(IL), .RNG_MODE(RNG_MODE),
        .WEIGHT_INIT(WEIGHT_INIT), .BIAS_INIT(BIAS_INIT), .INPUT_INIT(INPUT_INIT)
    ) u_tpu (
        .clk(clk), .rst(rst),
        .mem_valid(mem_valid), .mem_addr(mem_addr), .mem_wdata(mem_wdata),
        .mem_wstrb(mem_wstrb), .mem_ready(mem_ready), .mem_rdata(mem_rdata));

    // ---- observability: fold the 32-bit signature onto 7 output pins --------
    always @(posedge clk) begin
        led_n[0] <= ~(^sig[4:0]);
        led_n[1] <= ~(^sig[9:5]);
        led_n[2] <= ~(^sig[14:10]);
        led_n[3] <= ~(^sig[19:15]);
        led_n[4] <= ~(^sig[24:20]);
        led_n[5] <= ~(^sig[29:25]);
        uart_tx  <= ^sig[31:30];
    end

endmodule

`default_nettype wire
