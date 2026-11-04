`default_nettype none
// =============================================================================
// File    : scripts/budgets/ubench/dt_mac_ubench.v
// Purpose : RESOURCE / TIMING MICRO-BENCHMARK for budget task REQ-03 (CR-001,
//           systems-engineer). NOT project RTL, NOT a deliverable design and
//           NOT verified by simulation. It only exists so that Yosys
//           synth_gowin + nextpnr-himbaechel can give a tool-based estimate
//           of the size and the critical path of the deterministic int8
//           datapath of ARCHITECTURE.md section 14 (rev D, DT-TPU):
//             acc_j += q(x_i) * q(W_ji),  q(c) = c - 128 (signed int8)
//           for NL neuron lanes in parallel, one input i per clock.
//
// What is modelled:
//   * the weight RAM as NB = NL/4 banks of 128 x 32 bit with a registered
//     (synchronous) read port, so that one clock delivers the NL weight bytes
//     of one input row (layout 14.3: byte 16*i + j, bank = j/4); written one
//     32-bit word per clock through a simple port (stands in for the bus);
//   * a 64 x 8 input buffer with a registered read (stands in for INPUT);
//   * the code -> int8 conversion q(c) = c - 128 = {~c[7], c[6:0]} (wiring
//     plus one inverter per operand, usually absorbed into a LUT);
//   * NL signed 8 x 8 multipliers (mapped either to MULT9X9 DSP blocks or to
//     LUT/ALU logic, chosen by the synthesis option -nodsp, not by RTL);
//   * an optional product pipeline register (PIPE = 1) per lane;
//   * NL ACCW-bit accumulators with a bias pre-load (acc <= 128*bias on clr),
//     which is the cheapest exact form of Dp = acc + 128*bias (14.1);
//   * a registered NL:1 read mux (stands in for the bus / post-processing read).
// What is NOT modelled: post-processing (hidden shift/clip), argmax, FSM,
//   bus decoding, SCORE/HIDDEN storage, CYCLES counter.
// =============================================================================
module dt_mac_ubench #(
    parameter integer NL   = 16,  // neuron lanes (multipliers in parallel)
    parameter integer ACCW = 24,  // |Dp| <= 5 242 752 < 2^23 -> 24-bit signed
    parameter integer PIPE = 1    // 1 = register the product before the add
) (
    input  wire            clk,
    input  wire            rst,
    input  wire            wwe,    // write one 32-bit weight word
    input  wire [8:0]      wwa,    // weight word address (bank = wwa mod NB)
    input  wire [31:0]     wwd,    // weight word data
    input  wire            xwe,    // write one input code
    input  wire [5:0]      xwa,    // input code address
    input  wire [7:0]      xwd,    // input code data
    input  wire [6:0]      ra,     // row index i (0..127; 0..79 used in rev D)
    input  wire            run,    // accumulate this clock
    input  wire            clr,    // pre-load accumulators with 128*bias
    input  wire [15:0]     bias,   // bias pre-load value (shared, bench only)
    input  wire [3:0]      sel,    // accumulator read select
    output reg  [ACCW-1:0] dout    // registered read-back of acc[sel]
);
    localparam integer NB = NL / 4;          // 32-bit banks, 4 weights each

    // ---------------- weight RAM: NB banks x 128 words x 32 bit -------------
    // One bank per group of 4 lanes; all banks read the same row address, so
    // one clock returns the NL weights of row i (layout 14.3).
    wire [NL*8-1:0] wrow;                    // weight bytes of the current row
    genvar gb;
    generate
        for (gb = 0; gb < NB; gb = gb + 1) begin : g_bank
            reg [31:0] mem [0:127];          // inferred as BSRAM (expected)
            reg [31:0] q;                    // registered read data
            always @(posedge clk) begin
                if (wwe && (wwa % NB) == gb) mem[wwa / NB] <= wwd;
                q <= mem[ra];
            end
            assign wrow[gb*32 +: 32] = q;
        end
    endgenerate

    // ---------------- input buffer 64 x 8, registered read -----------------
    reg [7:0] xmem [0:63];                   // inferred as LUT-RAM (expected)
    reg [7:0] xq;                            // registered input code x_i
    always @(posedge clk) begin
        if (xwe) xmem[xwa] <= xwd;
        xq <= xmem[ra[5:0]];
    end

    // run/clr delayed by the one-cycle read latency of the memories above
    reg run_d, clr_d;
    always @(posedge clk) begin
        run_d <= rst ? 1'b0 : run;
        clr_d <= rst ? 1'b0 : clr;
    end

    // ---------------- multipliers + accumulators ---------------------------
    wire signed [7:0] xs = {~xq[7], xq[6:0]};          // q(x) = x - 128
    reg  [NL*ACCW-1:0] acc;                            // per-lane accumulator
    reg  [NL*16-1:0]   pr;                             // per-lane product (PIPE)
    reg                run_p, clr_p;                   // control aligned to pr
    integer j;                                         // loop index (comb)
    integer k;                                         // loop index (seq)
    reg signed [15:0] prod [0:NL-1];                   // combinational products
    always @* begin
        for (j = 0; j < NL; j = j + 1)
            prod[j] = xs * $signed({~wrow[j*8+7], wrow[j*8 +: 7]});
    end

    always @(posedge clk) begin
        run_p <= rst ? 1'b0 : run_d;
        clr_p <= rst ? 1'b0 : clr_d;
        for (k = 0; k < NL; k = k + 1) begin
            pr[k*16 +: 16] <= prod[k];
            if (rst)
                acc[k*ACCW +: ACCW] <= {ACCW{1'b0}};
            else if (PIPE ? clr_p : clr_d)              // acc = 128 * bias
                acc[k*ACCW +: ACCW] <= {{(ACCW-23){bias[15]}}, bias, 7'd0};
            else if (PIPE ? run_p : run_d)              // acc += q(x) * q(w)
                acc[k*ACCW +: ACCW] <= acc[k*ACCW +: ACCW]
                    + {{(ACCW-16){(PIPE ? pr[k*16+15] : prod[k][15])}},
                       (PIPE ? pr[k*16 +: 16] : prod[k])};
        end
        dout <= acc[(sel % NL)*ACCW +: ACCW];   // NL is a power of 2
    end
endmodule
`default_nettype wire

`default_nettype none
// -----------------------------------------------------------------------------
// dt_ubench_top: pin-limited wrapper (same idea as sc_ubench_top): data from an
// internal 32-bit Galois LFSR, addresses from counters, read-back XOR-reduced
// to one pin. Uses only board pins listed in design/constraints/tangnano9k.cst.
// The wrapper adds a few tens of LUT/FF (counted in the bench result).
// -----------------------------------------------------------------------------
module dt_ubench_top #(
    parameter integer NL = 16, parameter integer ACCW = 24, parameter integer PIPE = 1
) (
    input  wire clk, input wire btn_s1_n,
    input  wire we, input wire xwe, input wire start, input wire run, input wire clr,
    output wire dout_x
);
    reg s1 = 1'b1, s2 = 1'b1;                // 2-FF reset synchroniser
    always @(posedge clk) begin s1 <= ~btn_s1_n; s2 <= s1; end
    wire rst = s2;

    reg [31:0] src;                          // data source (Galois LFSR)
    reg [8:0]  wa;                           // write address counter
    reg [6:0]  ra;                           // row counter
    reg [3:0]  sel;                          // read select counter
    always @(posedge clk) begin
        if (rst) begin src <= 32'h1; wa <= 0; ra <= 0; sel <= 0; end
        else begin
            src <= src[0] ? ((src >> 1) ^ 32'h80200003) : (src >> 1);
            if (we | xwe) wa <= wa + 1'b1;
            if (run | start) ra <= start ? 7'd0 : ra + 1'b1;
            sel <= sel + 1'b1;
        end
    end
    wire [ACCW-1:0] dout;
    dt_mac_ubench #(.NL(NL), .ACCW(ACCW), .PIPE(PIPE)) u (
        .clk(clk), .rst(rst), .wwe(we), .wwa(wa), .wwd(src), .xwe(xwe),
        .xwa(wa[5:0]), .xwd(src[15:8]), .ra(ra), .run(run), .clr(clr),
        .bias(src[31:16]), .sel(sel), .dout(dout));
    assign dout_x = ^dout;
endmodule
`default_nettype wire
