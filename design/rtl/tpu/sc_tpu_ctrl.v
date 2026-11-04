// =============================================================================
// File      : design/rtl/tpu/sc_tpu_ctrl.v
// Module    : sc_tpu_ctrl
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Task      : RTL-TPU (fpga-engineer)
// Spec      : ARCHITECTURE.md rev A 5.3 (sequence after START) [BIT-EXACT],
//             5.4 (STATUS, RESULT, CYCLES), 5.5 (weight layout) [BIT-EXACT];
//             ADR-002 (weight-stationary 16x8 tile).
//
// PURPOSE
//   Sequencer of one SC-TPU inference (MLP 64-16-10). It owns no arithmetic;
//   it generates the read addresses of the weight/input/bias memories, the
//   load/shift strobes of the tile registers, the stream enable of the
//   LFSRs and of the APC array, the post-processing pipeline control, and
//   the architectural status (BUSY, DONE, RESULT, CYCLES).
//
// THEORY: weight-stationary tiling (ADR-002, spec 5.3)
//   A layer y_j = f(sum_i W_ji x_i + b_j) with N_in inputs is cut into
//   T = N_in/IL tiles of IL inputs. For one tile the NL x IL weights are
//   loaded into registers ("stationary") and the IL inputs are broadcast to
//   all NL neuron lanes; then L = 2^K stream cycles run, each adding IL
//   stochastic products per neuron into the binary accumulator acc_j. The
//   accumulators keep running across the T tiles of a layer, so after the
//   last tile acc_j holds the APC count of the complete dot product
//   (N_in * L products). Layer 1: N_in = 64, T = 64/IL = 8; layer 2:
//   N_in = 16, T = 16/IL = 2, whose inputs are the HIDDEN codes of layer 1.
//
// FSM (one state register; cnt is a shared cycle counter)
//   S_IDLE   : wait for START (the bus slave forwards it only when !BUSY).
//              On START (edge E0): BUSY <= 1, DONE <= 0, CYCLES <= 0,
//              layer <= 1, tile <= 0, word pointers <= 0; sc_rng re-loads the
//              LFSR seeds in the same edge (lfsr_load = start, spec 5.3).
//   S_LOAD   : tile load, NWT + 1 cycles (NWT = NL*IL/4 = 32 words).
//              cnt = 0..NWT-1 : weight word wptr is read (synchronous
//                               BSRAM, data 1 cycle later), wptr++.
//              cnt = 0..NXW-1 : input word xptr is read (INPUT RAM for layer
//                               1, HIDDEN register for layer 2; NXW = IL/4 = 2).
//              cnt = 1..NWT   : the returned word is shifted into the tile
//                               register (w_shift / x_shift = read issued in
//                               the previous cycle).
//              tile 0, cnt 0  : acc_clr (spec 5.3 step 1a: acc_j = 0).
//              Because the layout of 5.5 stores the tiles of a layer back to
//              back (tile t at bytes base_l + t*NL*IL), the weight pointer
//              simply keeps counting from tile to tile; it is set to
//              base_2/4 = 256 at the start of layer 2. The same holds for the
//              input word pointer (tile t uses input words t*IL/4 ..).
//              The LFSRs are frozen (adv = 0) in this state.
//   S_STREAM : L = 2^K cycles, cnt = 0..L-1. stream_en = 1: LFSRs advance
//              8 steps and every acc_j += popcount of its IL XNOR products.
//              After the last cycle: next tile (S_LOAD) or, after the last
//              tile of the layer, S_POST.
//   S_POST   : NL + 3 = 19 cycles, cnt = 0..NL+2. cnt = 0..NL-1 reads
//              BIAS[16*(l-1) + cnt] (synchronous RAM, 1 cycle) and one cycle
//              later presents (acc_cnt, bias) to sc_postproc (2-cycle
//              pipeline). The result of neuron j is valid in cycle j + 3 and
//              is written to HIDDEN[j] (layer 1) or SCORE[j] (layer 2) by
//              sc_tpu.v at the end of that cycle; the argmax over lanes 0..9
//              is updated on the fly here (strict '>' keeps the lowest index
//              on ties, spec 5.3 step 2). At cnt = NL+2 the last result is
//              written. Layer 1 -> layer 2 S_LOAD (HIDDEN is complete, so the
//              layer-2 input reads see the new codes); layer 2 -> RESULT <=
//              argmax, BUSY <= 0, DONE <= 1, S_IDLE (edge E1).
//
// CYCLES (spec 5.3 step 3, 5.4): counts every clock edge after E0 up to and
//   including E1, i.e. the number of clock cycles during which BUSY = 1.
//   CALCULATION from the FSM above:
//     CYCLES = (T1 + T2) * (NWT + 1 + L) + 2 * (NL + 3)
//            = 10 * (33 + 2^K) + 38 = 10 * 2^K + 368   (NL = 16, IL = 8)
//   e.g. K = 8: 2928 cycles = 108.4 us at 27 MHz. The value is live while
//   BUSY (counting) and frozen afterwards ("cycles of last inference").
//
// MEMORY PORT OWNERSHIP
//   port_busy = 1 in S_LOAD and S_POST: the controller drives the read
//   addresses of the weight, input and bias memories. The bus slave then
//   holds CPU reads of those regions (mem_ready is delayed, never lost).
//
// PARAMETERS: NL (16), IL (8; 4/16 for the synthesis study), DPW (Dp width).
// =============================================================================
`default_nettype none

module sc_tpu_ctrl #(
    parameter integer NL  = 16,
    parameter integer IL  = 8,
    parameter integer DPW = 20
) (
    input  wire           clk,
    input  wire           rst,
    // ---- from the bus slave -------------------------------------------------
    input  wire           start,        // START accepted (1-cycle pulse, only when !busy)
    input  wire [3:0]     cfg_k,        // CONFIG.LOG2_L, already clamped to 4..10
    // ---- from sc_postproc (results) -------------------------------------------
    input  wire           pp_out_valid,
    input  wire           pp_out_layer2,
    input  wire [3:0]     pp_out_idx,
    input  wire [DPW-1:0] pp_out_dp,
    // ---- architectural status ------------------------------------------------
    output reg            busy,         // STATUS[0]
    output reg            done,         // STATUS[1]
    output reg  [31:0]    cycles,       // CYCLES
    output reg  [3:0]     result,       // RESULT
    // ---- datapath control -----------------------------------------------------
    output reg            layer2,       // 0: layer 1, 1: layer 2
    output wire           port_busy,    // controller owns the memory read ports
    output wire [8:0]     w_raddr,      // weight RAM word address
    output wire [3:0]     x_raddr,      // INPUT word (layer 1) / HIDDEN word (layer 2)
    output wire [4:0]     b_raddr,      // BIAS index 16*(l-1) + j
    output reg            w_shift,      // shift the returned weight word into the tile reg
    output reg            x_shift,      // shift the returned input word into the x reg
    output wire           lfsr_load,    // reload LFSR seeds (START)
    output wire           stream_en,    // stream cycle: LFSR advance + APC accumulate
    output wire           acc_clr,      // clear all acc_j (start of a layer)
    output reg            pp_in_valid,  // post-processor input valid
    output reg  [3:0]     pp_in_idx     // neuron index of that input
);

    // ---- geometry (5.1, 5.3, 5.5) --------------------------------------------
    localparam integer NWT    = NL * IL / 4;   // 32-bit words per weight tile (32)
    localparam integer NXW    = IL / 4;        // 32-bit input words per tile (2)
    localparam integer T1     = 64 / IL;       // layer-1 tiles (8)
    localparam integer T2     = 16 / IL;       // layer-2 tiles (2)
    localparam [8:0]   WBASE2 = 9'd256;        // base_2 = 1024 bytes = word 256
    localparam integer PLAST  = NL + 2;        // last POST cycle (cnt value)
    localparam integer T1L    = T1 - 1;
    localparam integer T2L    = T2 - 1;
    // Sized copies for comparisons with the 11-bit / 4-bit counters.
    localparam [10:0]  NWT_C     = NWT[10:0];
    localparam [10:0]  NXW_C     = NXW[10:0];
    localparam [10:0]  POST_LAST = PLAST[10:0];
    localparam [10:0]  NL_C      = NL[10:0];
    localparam [3:0]   T1_LAST   = T1L[3:0];
    localparam [3:0]   T2_LAST   = T2L[3:0];

    // ---- states -----------------------------------------------------------------
    localparam [1:0] S_IDLE   = 2'd0;
    localparam [1:0] S_LOAD   = 2'd1;
    localparam [1:0] S_STREAM = 2'd2;
    localparam [1:0] S_POST   = 2'd3;

    reg  [1:0]  state;
    reg  [10:0] cnt;        // cycle counter inside a state (max L-1 = 1023)
    reg  [3:0]  tile;       // tile index inside the layer (max 15 for IL = 4)
    reg  [8:0]  wptr;       // next weight word to read
    reg  [3:0]  xptr;       // next input word to read
    reg  [3:0]  best_idx;   // running argmax (layer 2)
    reg  [DPW-1:0] best_dp; // running maximum score (signed)

    // L - 1 = 2^K - 1 (K clamped to 4..10, so this is 15..1023).
    wire [10:0] l_last    = (11'd1 << cfg_k) - 11'd1;
    wire [3:0]  tile_last = layer2 ? T2_LAST : T1_LAST;

    // ---- combinational control outputs -----------------------------------------
    wire in_load   = (state == S_LOAD);
    wire in_post   = (state == S_POST);
    wire w_issue   = in_load && (cnt < NWT_C);   // weight read issued this cycle
    wire x_issue   = in_load && (cnt < NXW_C);   // input read issued this cycle
    wire b_issue   = in_post && (cnt < NL_C);    // bias read issued this cycle

    assign port_busy = in_load || in_post;
    assign w_raddr   = wptr;
    assign x_raddr   = xptr;
    assign b_raddr   = {layer2, cnt[3:0]};
    assign lfsr_load = start && (state == S_IDLE);
    assign stream_en = (state == S_STREAM);
    assign acc_clr   = in_load && (tile == 4'd0) && (cnt == 11'd0);

    // ---- main FSM ---------------------------------------------------------------
    always @(posedge clk) begin
        if (rst) begin
            state    <= S_IDLE;
            cnt      <= 11'd0;
            tile     <= 4'd0;
            wptr     <= 9'd0;
            xptr     <= 4'd0;
            layer2   <= 1'b0;
            busy     <= 1'b0;
            done     <= 1'b0;
            result   <= 4'd0;
        end else begin
            case (state)
                // -------------------------------------------------------------
                S_IDLE: begin
                    if (start) begin
                        state  <= S_LOAD;
                        cnt    <= 11'd0;
                        tile   <= 4'd0;
                        wptr   <= 9'd0;      // base_1 = 0
                        xptr   <= 4'd0;
                        layer2 <= 1'b0;
                        busy   <= 1'b1;
                        done   <= 1'b0;      // DONE cleared by START (5.4)
                    end
                end
                // -------------------------------------------------------------
                S_LOAD: begin
                    if (w_issue) wptr <= wptr + 9'd1;
                    if (x_issue) xptr <= xptr + 4'd1;
                    if (cnt == NWT_C) begin   // last word shifted in this edge
                        state <= S_STREAM;
                        cnt   <= 11'd0;
                    end else begin
                        cnt   <= cnt + 11'd1;
                    end
                end
                // -------------------------------------------------------------
                S_STREAM: begin
                    if (cnt == l_last) begin
                        cnt <= 11'd0;
                        if (tile == tile_last) begin
                            state <= S_POST;
                        end else begin
                            tile  <= tile + 4'd1;
                            state <= S_LOAD;
                        end
                    end else begin
                        cnt <= cnt + 11'd1;
                    end
                end
                // -------------------------------------------------------------
                default: begin // S_POST
                    if (cnt == POST_LAST) begin
                        cnt <= 11'd0;
                        if (!layer2) begin
                            // Layer 1 finished: HIDDEN[0..15] written. Start layer 2.
                            layer2 <= 1'b1;
                            tile   <= 4'd0;
                            wptr   <= WBASE2;
                            xptr   <= 4'd0;
                            state  <= S_LOAD;
                        end else begin
                            // Layer 2 finished: publish RESULT, DONE (edge E1).
                            result <= best_idx;
                            busy   <= 1'b0;
                            done   <= 1'b1;
                            state  <= S_IDLE;
                        end
                    end else begin
                        cnt <= cnt + 11'd1;
                    end
                end
            endcase
        end
    end

    // ---- read-data alignment strobes (memories have a 1-cycle read latency) ----
    always @(posedge clk) begin
        if (rst) begin
            w_shift     <= 1'b0;
            x_shift     <= 1'b0;
            pp_in_valid <= 1'b0;
        end else begin
            w_shift     <= w_issue;
            x_shift     <= x_issue;
            pp_in_valid <= b_issue;
        end
        pp_in_idx <= cnt[3:0];      // neuron index of the bias read just issued
    end

    // ---- CYCLES counter (5.3 step 3) -------------------------------------------
    always @(posedge clk) begin
        if (rst)
            cycles <= 32'd0;
        else if (lfsr_load)          // START accepted (edge E0)
            cycles <= 32'd0;
        else if (busy)               // every edge E0+1 .. E1
            cycles <= cycles + 32'd1;
    end

    // ---- running argmax over lanes 0..9 of layer 2 (5.3 step 2) -----------------
    // Results arrive in index order 0, 1, ..., 15. Lane 0 initialises the
    // maximum; a later lane replaces it only if STRICTLY greater, so ties keep
    // the lowest index. Lanes 10..15 are padding and never considered.
    always @(posedge clk) begin
        if (rst) begin
            best_idx <= 4'd0;
            best_dp  <= {DPW{1'b0}};
        end else if (pp_out_valid && pp_out_layer2 && (pp_out_idx < 4'd10)) begin
            if ((pp_out_idx == 4'd0) || ($signed(pp_out_dp) > $signed(best_dp))) begin
                best_idx <= pp_out_idx;
                best_dp  <= pp_out_dp;
            end
        end
    end

endmodule

`default_nettype wire
