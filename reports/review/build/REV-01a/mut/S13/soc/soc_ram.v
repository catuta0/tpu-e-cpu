// =============================================================================
// File      : design/rtl/soc/soc_ram.v
// Module    : soc_ram   (4 KiB program + data RAM, Gowin BSRAM)
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Reqs      : REQ-SYS-007 (bus protocol), REQ-SYS-008 (little-endian byte
//             lanes), REQ-SYS-009 (RAM decodes addr[11:2]), REQ-RES-004 (RAM in
//             BSRAM, not LUTs)
// Task      : RTL-SOC (fpga-engineer)
// Spec      : ARCHITECTURE.md 3, 4 (RAM 4 KiB at 0x0000_0000, INIT_FILE),
//             5.6 (prog.hex = 1024 x 32-bit words); INTERFACES.json
//             memory_map.RAM.
//
// PURPOSE
//   Single-port 1024 x 32-bit RAM holding the CPU program and its data
//   (reset PC = 0). Initialised at configuration / simulation start from
//   INIT_FILE with $readmemh (one 32-bit word per line, word w = bytes
//   4w..4w+3, little-endian: byte 4w in bits [7:0]).
//
// INTERFACE / TIMING (native valid/ready slave, ARCHITECTURE.md 3)
//   mem_valid : already qualified by soc_bus (addr[31:28] == 0).
//   mem_addr  : only [11:2] is used (word index; aliases of the 4 KiB inside
//               0x0000_0000 - 0x0FFF_FFFF are allowed, ARCHITECTURE.md 4).
//               [1:0] are ignored: the CPU sends byte addresses, but byte and
//               halfword stores are expressed by mem_wstrb on replicated
//               data, and loads extract the lane themselves.
//   mem_wstrb : byte enables, 0000 = read.
//   Cycle 1 (mem_valid = 1, ready_q = 0): the request is ACCEPTED; a write
//               is performed with the byte enables at this edge; a read
//               presents the address to the BSRAM, whose output register
//               holds the word after the edge.
//   Cycle 2   : mem_ready = 1 (one cycle), mem_rdata = BSRAM output.
//   => 1 wait state for every access (CPU CPI 5.59 measured with 1 wait
//      state in RTL-CPU). The write is gated with ~ready_q so it happens
//      exactly once per transaction.
//   Back-to-back: if the CPU keeps mem_valid high in the cycle after
//   mem_ready (a store followed directly by the next fetch), ready_q = 1 in
//   the ready cycle blocks a re-accept of the OLD request; the new request
//   is accepted in the following cycle.
//   mem_rdata is the raw BSRAM output (not zeroed outside the ready cycle);
//   soc_bus multiplexes it by address, so this is safe.
//
// IMPLEMENTATION NOTES
//   (* ram_style = "block", no_rw_check *): forces BSRAM (SP/SPX9 primitives
//   on the GW1N-9C, 2 blocks for 32 kbit) and tells Yosys it need not emulate
//   read-during-write ordering. That is valid because a store transaction
//   never uses mem_rdata (lesson from RTL-CPU: without no_rw_check Yosys adds
//   bypass logic). The read is unconditional (every cycle) so that the BSRAM
//   output register is the only read pipeline stage.
//
// PARAMETERS
//   INIT_FILE : $readmemh image, 1024 lines (default: the SoC demo program).
//               "" -> RAM initialised to zero (simulation only; on the FPGA
//               an uninitialised BSRAM also powers up as 0).
// RESET: rst clears only ready_q; memory contents are not reset (RAM).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module soc_ram #(
    parameter INIT_FILE = "sim/data/soc_demo_prog.hex"
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        mem_valid,
    input  wire [31:0] mem_addr,
    input  wire [31:0] mem_wdata,
    input  wire [3:0]  mem_wstrb,
    output wire        mem_ready,
    output wire [31:0] mem_rdata
);

    (* ram_style = "block", no_rw_check *) reg [31:0] mem [0:1023];

    integer n;
    initial begin
        if (INIT_FILE != "") $readmemh(INIT_FILE, mem);
        else for (n = 0; n < 1024; n = n + 1) mem[n] = 32'd0;
    end

    wire [9:0] word = mem_addr[11:2];
    // Upper and lower address bits are intentionally not decoded here.
    wire       addr_unused = &{1'b0, mem_addr[31:12], mem_addr[1:0]};

    reg        ready_q;
    reg [31:0] q;
    // Accept = first cycle of the request (see TIMING).
    wire       accept = mem_valid && !ready_q;
    wire [3:0] we     = accept ? {4{|mem_wstrb}} : 4'b0000;

    // BSRAM port: byte-enabled write, registered read (read-first is not
    // required, see no_rw_check above).
    always @(posedge clk) begin
        if (we[0]) mem[word][7:0]   <= mem_wdata[7:0];
        if (we[1]) mem[word][15:8]  <= mem_wdata[15:8];
        if (we[2]) mem[word][23:16] <= mem_wdata[23:16];
        if (we[3]) mem[word][31:24] <= mem_wdata[31:24];
        q <= mem[word];
    end

    // One-cycle ready pulse in the 2nd cycle of every request.
    always @(posedge clk) begin
        if (rst) ready_q <= 1'b0;
        else     ready_q <= accept;
    end

    assign mem_ready = ready_q;
    assign mem_rdata = q;

endmodule

`default_nettype wire
