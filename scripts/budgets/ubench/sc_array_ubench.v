`default_nettype none
// =============================================================================
// File    : scripts/budgets/ubench/sc_array_ubench.v
// Purpose : RESOURCE / TIMING MICRO-BENCHMARK for budget task REQ-01
//           (systems-engineer). NOT project RTL, NOT a deliverable design and
//           NOT verified by simulation. It only exists so that Yosys
//           synth_gowin + nextpnr-himbaechel can give a tool-based estimate of
//           the size and the critical path of the SC-TPU streaming datapath
//           described in design/architecture/ARCHITECTURE.md rev A, sec. 5.
//
// What is modelled (one weight-stationary tile, NL x IL lanes):
//   * NL*IL 8-bit weight registers (written one byte at a time through a
//     simple address/data port - stands in for the tile loader),
//   * IL 8-bit input-code registers,
//   * RNG per RNG_MODE (0 SHARED, 1 ROTATE, 2 INDEPENDENT) built from 16-bit
//     Fibonacci LFSRs x^16+x^14+x^13+x^11+1 advanced 8 steps per stream cycle,
//   * SNG comparators b = (r < c) for every input lane and every weight lane,
//   * bipolar XNOR multiply, per-neuron popcount over IL lanes and an ACCW-bit
//     accumulator (APC), exactly the per-cycle update of spec sec. 5.3 1.b,
//   * a registered NL:1 read mux (stands in for the bus read path).
// What is NOT modelled: post-processing, bias, buffers, bus decode, FSM.
//
// The critical path of interest is
//   LFSR state reg -> 8-bit compare (r < W) -> XNOR -> popcount(IL) -> ACCW-bit
//   add -> acc reg
// which the real RTL may or may not pipeline; this bench is the NON-pipelined
// (worst-case) version.
// =============================================================================

// -----------------------------------------------------------------------------
// 16-bit Fibonacci LFSR with 8-step leap-forward (spec 5.3, ADR-005).
// One "stream cycle" (adv = 1) applies the single step
//     fb = s[15]^s[13]^s[12]^s[10];  s = ((s << 1) | fb) & 16'hFFFF
// eight times in one clock (unrolled XOR network). r = low byte of the state
// after the 8 steps, i.e. of the register contents.
// -----------------------------------------------------------------------------
module lfsr16_leap8 #(
    parameter [15:0] SEED = 16'hACE1   // value loaded on rst or load
) (
    input  wire       clk,
    input  wire       rst,   // synchronous, active-high
    input  wire       load,  // reload seed (START accepted)
    input  wire       adv,   // advance 8 steps (one stream cycle)
    output wire [7:0] r      // 8 pseudo-random bits for this stream cycle
);
    reg [15:0] s;            // LFSR state
    reg [15:0] n;            // state after 8 single steps (combinational)
    integer    t;            // unroll index

    always @* begin
        n = s;
        for (t = 0; t < 8; t = t + 1)
            n = {n[14:0], n[15] ^ n[13] ^ n[12] ^ n[10]};
    end

    always @(posedge clk) begin
        if (rst || load) s <= SEED;   // seeds reloaded on START only
        else if (adv)    s <= n;      // advance only in stream cycles
    end

    assign r = s[7:0];
endmodule

// -----------------------------------------------------------------------------
// NL x IL stochastic MAC tile.
// -----------------------------------------------------------------------------
module sc_array_ubench #(
    parameter integer NL       = 16,  // neuron lanes
    parameter integer IL       = 8,   // input lanes
    parameter integer ACCW     = 17,  // accumulator width: 64*1024 = 2^16 -> 17 bits
    parameter integer RNG_MODE = 1,   // 0 SHARED, 1 ROTATE, 2 INDEPENDENT
    parameter integer AW       = 7    // weight byte address width, 2^AW >= NL*IL
) (
    input  wire            clk,
    input  wire            rst,
    input  wire            we,     // write weight byte  W[addr/IL][addr%IL]
    input  wire            xwe,    // write input byte   x[addr%IL]
    input  wire [AW-1:0]   addr,
    input  wire [7:0]      wdata,
    input  wire            start,  // reload LFSR seeds
    input  wire            run,    // one stream cycle per clock while 1
    input  wire            clr,    // clear accumulators
    input  wire [3:0]      sel,    // accumulator read select
    output reg  [ACCW-1:0] dout    // registered read-back of acc[sel]
);
    // ---------------- storage ----------------
    reg [NL*IL*8-1:0] w;     // weight tile, byte (j*IL+i) = W[j][i]
    reg [IL*8-1:0]    x;     // input codes, byte i = x_i
    reg [NL*ACCW-1:0] acc;   // per-neuron APC accumulators

    integer k;
    always @(posedge clk) begin
        for (k = 0; k < NL*IL; k = k + 1)
            if (we && addr == k) w[k*8 +: 8] <= wdata;
        for (k = 0; k < IL; k = k + 1)
            if (xwe && addr[2:0] == k[2:0] && (IL <= 8 || addr[3] == k[3])) x[k*8 +: 8] <= wdata;
    end

    // ---------------- RNG ----------------
    wire [IL*8-1:0] rx;   // per input lane random byte for x
    wire [IL*8-1:0] rw;   // per input lane random byte for W (shared over j)

    genvar gi;
    generate
        if (RNG_MODE == 2) begin : g_indep
            for (gi = 0; gi < IL; gi = gi + 1) begin : g_lane
                lfsr16_leap8 #(.SEED(16'hACE1 + 16'h3C5A * gi)) u_lx (
                    .clk(clk), .rst(rst), .load(start), .adv(run), .r(rx[gi*8 +: 8]));
                lfsr16_leap8 #(.SEED(16'h7A5C + 16'h2B67 * gi)) u_lw (
                    .clk(clk), .rst(rst), .load(start), .adv(run), .r(rw[gi*8 +: 8]));
            end
        end else begin : g_two
            wire [7:0] r_x, r_w;
            lfsr16_leap8 #(.SEED(16'hACE1)) u_lx (
                .clk(clk), .rst(rst), .load(start), .adv(run), .r(r_x));
            lfsr16_leap8 #(.SEED(16'h7A5C)) u_lw (
                .clk(clk), .rst(rst), .load(start), .adv(run), .r(r_w));
            for (gi = 0; gi < IL; gi = gi + 1) begin : g_lane
                if (RNG_MODE == 1 && (gi % 8) != 0) begin : g_rot
                    // rotl8(r, i): pure wiring, costs no LUTs
                    assign rx[gi*8 +: 8] = {r_x[7-(gi%8):0], r_x[7:8-(gi%8)]};
                    assign rw[gi*8 +: 8] = {r_w[7-(gi%8):0], r_w[7:8-(gi%8)]};
                end else begin : g_shr
                    assign rx[gi*8 +: 8] = r_x;
                    assign rw[gi*8 +: 8] = r_w;
                end
            end
        end
    endgenerate

    // ---------------- SNG + XNOR + popcount ----------------
    reg [IL-1:0]      bx;                 // input stream bits
    reg [NL*IL-1:0]   p;                  // product bits
    reg [NL*5-1:0]    pc;                 // popcount per neuron (<= 16 -> 5 bits)
    integer j, i;
    always @* begin
        for (i = 0; i < IL; i = i + 1)
            bx[i] = (rx[i*8 +: 8] < x[i*8 +: 8]);
        for (j = 0; j < NL; j = j + 1) begin
            pc[j*5 +: 5] = 5'd0;
            for (i = 0; i < IL; i = i + 1) begin
                p[j*IL+i] = ~(bx[i] ^ (rw[i*8 +: 8] < w[(j*IL+i)*8 +: 8]));
                pc[j*5 +: 5] = pc[j*5 +: 5] + {4'd0, p[j*IL+i]};
            end
        end
    end

    // ---------------- accumulate + read mux ----------------
    always @(posedge clk) begin
        for (j = 0; j < NL; j = j + 1) begin
            if (rst || clr) acc[j*ACCW +: ACCW] <= {ACCW{1'b0}};
            else if (run)   acc[j*ACCW +: ACCW] <= acc[j*ACCW +: ACCW] + {{(ACCW-5){1'b0}}, pc[j*5 +: 5]};
        end
        dout <= acc[sel*ACCW +: ACCW];
    end
endmodule
`default_nettype wire
`default_nettype none
// -----------------------------------------------------------------------------
// sc_ubench_top: pin-limited wrapper so that the bench can be placed on the
// QN88 package using only board pins already listed in
// design/constraints/tangnano9k.cst. Weight / input bytes come from an
// internal 32-bit Galois LFSR (data source), addresses from a counter, and the
// accumulator read-back is XOR-reduced to one output pin. The wrapper adds a
// few tens of LUT/FF of its own (counted in the bench result; see BUDGETS.md).
// -----------------------------------------------------------------------------
module sc_ubench_top #(
    parameter integer NL = 16, parameter integer IL = 8,
    parameter integer ACCW = 17, parameter integer RNG_MODE = 1,
    parameter integer AW = 7
) (
    input  wire clk, input wire btn_s1_n,
    input  wire we, input wire xwe, input wire start, input wire run, input wire clr,
    output wire dout_x
);
    reg s1 = 1'b1, s2 = 1'b1;
    always @(posedge clk) begin s1 <= ~btn_s1_n; s2 <= s1; end
    wire rst = s2;

    reg [31:0]   src;   // data source (Galois LFSR, taps 0x80200003)
    reg [AW-1:0] addr;  // write address counter
    reg [3:0]    sel;   // read select counter
    always @(posedge clk) begin
        if (rst) begin src <= 32'h1; addr <= 0; sel <= 0; end
        else begin
            src  <= src[0] ? ((src >> 1) ^ 32'h80200003) : (src >> 1);
            if (we | xwe) addr <= addr + 1'b1;
            sel  <= sel + 1'b1;
        end
    end
    wire [ACCW-1:0] dout;
    sc_array_ubench #(.NL(NL), .IL(IL), .ACCW(ACCW), .RNG_MODE(RNG_MODE), .AW(AW)) u (
        .clk(clk), .rst(rst), .we(we), .xwe(xwe), .addr(addr), .wdata(src[7:0]),
        .start(start), .run(run), .clr(clr), .sel(sel), .dout(dout));
    assign dout_x = ^dout;
endmodule
`default_nettype wire
