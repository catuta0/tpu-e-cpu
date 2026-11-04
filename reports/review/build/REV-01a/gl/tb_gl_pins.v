// REV-01a reviewer testbench (simulation only): pin-level check of the ROUTED
// soc_top netlist (nextpnr output -> yosys write_verilog) with the Yosys Gowin
// cell models. Only board pins are used (no hierarchical probes):
//   * power-up, then button reset (btn_rst_n low 20 cycles, then high);
//   * waits for 2 UART bytes on uart_tx decoded at 115200 Bd real time
//     (mid-bit sampling, independent of the DUT divider);
//   * expects bytes 0x37 0x0A ("7\n", golden class 7 from sim/data/soc_expected.json)
//     and led_n = ~6'd7 = 6'b111000 after the second byte.
`timescale 1ns/1ps
module tb_gl_pins;
    reg clk = 1'b0;
    always #18.519 clk = ~clk;                 // 27 MHz
    reg btn_rst_n = 1'b1;
    wire [5:0] led_n;
    wire uart_tx;
    soc_top dut (.clk(clk), .btn_rst_n(btn_rst_n), .led_n(led_n), .uart_tx(uart_tx), .uart_rx(1'b1));
    localparam real BIT = 1.0e9 / 115200.0;
    reg [7:0] rx [0:3];
    integer n = 0, b, errs = 0;
    reg [7:0] byte_v;
    initial begin
        repeat (5) @(posedge clk);
        #10 btn_rst_n = 1'b0;
        repeat (20) @(posedge clk);
        if (led_n !== 6'b111111) begin errs = errs + 1; $display("FAIL: led_n during reset = %b", led_n); end
        if (uart_tx !== 1'b1)    begin errs = errs + 1; $display("FAIL: uart_tx during reset = %b", uart_tx); end
        #10 btn_rst_n = 1'b1;
        while (n < 2) begin
            @(negedge uart_tx);
            #(BIT * 0.5);
            if (uart_tx !== 1'b0) begin errs = errs + 1; $display("FAIL: start bit"); end
            for (b = 0; b < 8; b = b + 1) begin #(BIT); byte_v[b] = uart_tx; end
            #(BIT);
            if (uart_tx !== 1'b1) begin errs = errs + 1; $display("FAIL: stop bit"); end
            rx[n] = byte_v; n = n + 1;
            $display("INFO: UART byte %0d = 0x%02h at %0t ns", n - 1, byte_v, $time);
        end
        repeat (10) @(posedge clk);
        $display("INFO: led_n = %b", led_n);
        if (rx[0] !== 8'h37 || rx[1] !== 8'h0A) begin errs = errs + 1; $display("FAIL: UART bytes"); end
        if (led_n !== 6'b111000) begin errs = errs + 1; $display("FAIL: led_n"); end
        if (errs == 0) $display("GL TEST PASSED"); else $display("GL TEST FAILED (%0d)", errs);
        $finish;
    end
    initial begin #(37.038 * 400000.0); $display("GL TEST FAILED (watchdog)"); $finish; end
endmodule
