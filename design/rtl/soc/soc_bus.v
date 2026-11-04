// =============================================================================
// File      : design/rtl/soc/soc_bus.v
// Module    : soc_bus   (address decoder + read-data/ready multiplexer +
//                        unmapped-access responder)
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Reqs      : REQ-SYS-007 (valid/ready protocol), REQ-SYS-009 (memory map and
//             decoding), REQ-SYS-010 (unmapped access behaviour)
// Task      : RTL-SOC (fpga-engineer)
// Spec      : ARCHITECTURE.md 3 (bus), 4 (memory map); INTERFACES.json rev B
//             "bus", "memory_map".
//
// PURPOSE
//   The SoC has exactly one bus master (rv32i_core) and three slaves. This
//   block routes each CPU transaction to one slave, chosen by the top address
//   nibble, and returns that slave's mem_ready / mem_rdata to the CPU:
//
//       addr[31:28] | slave       | port of this module
//       ------------+-------------+-------------------------------------
//       0x0         | RAM 4 KiB   | ram_valid / ram_ready / ram_rdata
//       0x1         | peripherals | per_valid / per_ready / per_rdata
//       0x2         | SC-TPU      | tpu_valid / tpu_ready / tpu_rdata
//       0x3 .. 0xF  | none        | internal responder (see below)
//
//   Only addr[31:28] is decoded here (INTERFACES.json memory_map.decode).
//   Each slave decodes its own low address bits (RAM addr[11:2], peripherals
//   addr[11:2], TPU addr[11:0]); bits [27:12] are ignored, so every slave is
//   aliased throughout its 256 MiB region (allowed by ARCHITECTURE.md 4 for
//   the RAM; same rule applied to the other slaves for a uniform decoder).
//
// UNMAPPED ACCESSES (ARCHITECTURE.md 4 "other", REQ-SYS-010)
//   A request to 0x3xxx_xxxx .. 0xFxxx_xxxx is answered by this module:
//   read data 0, write ignored (nothing is written anywhere), mem_ready one
//   cycle later (1 wait state, like the RAM) so the CPU never hangs, and the
//   sticky debug flag bus_err is set. bus_err is cleared only by rst.
//
// TIMING
//   * Decode and the slave-select are purely combinational on mem_addr,
//     which the CPU holds stable while mem_valid = 1 (ARCHITECTURE.md 3), so
//     the select cannot change during a transaction.
//   * The returned mem_ready / mem_rdata are a 4:1 AND-OR multiplexer by the
//     same select (1 LUT level per bit). The select is needed because the RAM
//     read port is not zero outside its ready cycle (the TPU's is).
//   * Unmapped responder: un_ready_q <= un_valid & ~un_ready_q, i.e. a
//     one-cycle ready pulse in the 2nd cycle of the request; the ~un_ready_q
//     term prevents a second (spurious) pulse if the CPU keeps mem_valid
//     high for a back-to-back request in the cycle after mem_ready.
//
// RESET: synchronous active-high rst (ARCHITECTURE.md 2): un_ready_q = 0,
//   bus_err = 0.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module soc_bus (
    input  wire        clk,
    input  wire        rst,
    // ---- from / to the CPU (bus master) ---------------------------------------
    input  wire        mem_valid,
    input  wire [31:0] mem_addr,
    output reg         mem_ready,
    output reg  [31:0] mem_rdata,
    // ---- RAM slave (0x0xxx_xxxx) ------------------------------------------------
    output wire        ram_valid,
    input  wire        ram_ready,
    input  wire [31:0] ram_rdata,
    // ---- peripheral slave (0x1xxx_xxxx) ---------------------------------------
    output wire        per_valid,
    input  wire        per_ready,
    input  wire [31:0] per_rdata,
    // ---- SC-TPU slave (0x2xxx_xxxx) -------------------------------------------
    output wire        tpu_valid,
    input  wire        tpu_ready,
    input  wire [31:0] tpu_rdata,
    // ---- debug -------------------------------------------------------------------
    output reg         bus_err      // sticky: an unmapped address was accessed
);

    // -------------------------------------------------------------------------
    // Region select from the top nibble (memory map, ARCHITECTURE.md 4).
    // -------------------------------------------------------------------------
    wire [3:0] region  = mem_addr[31:28];
    wire       sel_ram = (region == 4'h0);
    wire       sel_per = (region == 4'h1);
    wire       sel_tpu = (region == 4'h2);
    wire       sel_un  = !(sel_ram || sel_per || sel_tpu);   // 0x3 .. 0xF

    // Bits [27:0] are decoded inside the slaves (they receive the full bus
    // address from the top level); collected here only to document that this
    // block deliberately ignores them (Verilator "unused" naming idiom).
    wire       addr_low_unused = &{1'b0, mem_addr[27:0]};

    // A slave sees mem_valid only for its own region, so a slave can never
    // respond to (or write on) a transaction that belongs to another one.
    assign ram_valid = mem_valid && sel_ram;
    assign per_valid = mem_valid && sel_per;
    assign tpu_valid = mem_valid && sel_tpu;
    wire   un_valid  = mem_valid && sel_un;

    // -------------------------------------------------------------------------
    // Unmapped-access responder + sticky bus_err flag.
    // -------------------------------------------------------------------------
    reg un_ready_q;
    always @(posedge clk) begin
        if (rst) begin
            un_ready_q <= 1'b0;
            bus_err    <= 1'b0;
        end else begin
            // ready in the 2nd cycle of the request, exactly one cycle long
            un_ready_q <= un_valid && !un_ready_q;
            // sticky: set on the first cycle of any unmapped request
            if (un_valid) bus_err <= 1'b1;
        end
    end

    // -------------------------------------------------------------------------
    // Return path: ready and read data of the SELECTED slave only.
    // An unmapped read returns 0 (REQ-SYS-010).
    // -------------------------------------------------------------------------
    always @(*) begin
        mem_ready = (sel_ram && ram_ready) || (sel_per && per_ready) ||
                    (sel_tpu && tpu_ready) || (sel_un  && un_ready_q);
        mem_rdata = ({32{sel_ram}} & ram_rdata) |
                    ({32{sel_per}} & per_rdata) |
                    ({32{sel_tpu}} & tpu_rdata);      // sel_un: 0
    end

endmodule

`default_nettype wire
