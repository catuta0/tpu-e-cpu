`default_nettype none
// =============================================================================
// File    : scripts/budgets/ubench/cpu_proxy_top.v
// Purpose : RESOURCE / TIMING MICRO-BENCHMARK for budget task REQ-01. NOT
//           project RTL. Wraps the open-source PicoRV32 core (YosysHQ, ISC
//           licence, fetched by run_ubench.sh from raw.githubusercontent.com
//           into scripts/budgets/build/ext/) as a PROXY for "a multi-cycle
//           RV32I CPU with a native valid/ready bus" so the budget can quote a
//           tool-based LUT4/FF/Fmax figure on GW1N-9C instead of a guess.
//           The project CPU is written from scratch (ARCHITECTURE.md sec. 6)
//           and will differ; this is only a calibration point.
// Contents: PicoRV32 (RV32I, no counters, misalign/illegal traps enabled) +
//           1024 x 32-bit RAM with byte enables and clocked read (BSRAM
//           inference) + one LED register at 0x1000_0000, 2-FF reset sync.
// =============================================================================
module cpu_proxy_top (
    input  wire       clk,       // 27 MHz board clock
    input  wire       btn_s1_n,  // active-low reset button
    output wire [5:0] led_n      // active-low LEDs
);
    // 2-FF reset synchroniser (project convention)
    reg s1 = 1'b1, s2 = 1'b1;
    always @(posedge clk) begin s1 <= ~btn_s1_n; s2 <= s1; end
    wire rst = s2;

    wire        mem_valid, mem_instr, trap;
    wire [31:0] mem_addr, mem_wdata;
    wire [3:0]  mem_wstrb;
    reg         mem_ready;
    reg  [31:0] mem_rdata;

    picorv32 #(
        .ENABLE_COUNTERS(0), .ENABLE_COUNTERS64(0),
        .CATCH_MISALIGN(1), .CATCH_ILLINSN(1)
    ) u_cpu (
        .clk(clk), .resetn(~rst), .trap(trap),
        .mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_ready),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb),
        .mem_rdata(mem_rdata),
        .mem_la_read(), .mem_la_write(), .mem_la_addr(), .mem_la_wdata(), .mem_la_wstrb(),
        .pcpi_valid(), .pcpi_insn(), .pcpi_rs1(), .pcpi_rs2(),
        .pcpi_wr(1'b0), .pcpi_rd(32'd0), .pcpi_wait(1'b0), .pcpi_ready(1'b0),
        .irq(32'd0), .eoi(), .trace_valid(), .trace_data()
    );

    // 4 KiB RAM, clocked read -> BSRAM
    reg [31:0] ram [0:1023];
    reg [31:0] ram_q;
    wire       sel_ram = (mem_addr[31:28] == 4'h0);
    always @(posedge clk) begin
        if (mem_valid && sel_ram && mem_wstrb[0]) ram[mem_addr[11:2]][ 7: 0] <= mem_wdata[ 7: 0];
        if (mem_valid && sel_ram && mem_wstrb[1]) ram[mem_addr[11:2]][15: 8] <= mem_wdata[15: 8];
        if (mem_valid && sel_ram && mem_wstrb[2]) ram[mem_addr[11:2]][23:16] <= mem_wdata[23:16];
        if (mem_valid && sel_ram && mem_wstrb[3]) ram[mem_addr[11:2]][31:24] <= mem_wdata[31:24];
        ram_q <= ram[mem_addr[11:2]];
    end

    // LED register and 1-wait-state ready
    reg [5:0] led;
    reg       pend;
    always @(posedge clk) begin
        if (rst) begin led <= 6'd0; mem_ready <= 1'b0; pend <= 1'b0; end
        else begin
            mem_ready <= 1'b0;
            if (mem_valid && !mem_ready && !pend) pend <= 1'b1;
            else if (pend) begin pend <= 1'b0; mem_ready <= 1'b1; end
            if (mem_valid && !sel_ram && mem_wstrb[0]) led <= mem_wdata[5:0];
        end
    end
    always @* mem_rdata = sel_ram ? ram_q : {26'd0, led};

    assign led_n = ~(led ^ {5'd0, trap});
endmodule
`default_nettype wire
