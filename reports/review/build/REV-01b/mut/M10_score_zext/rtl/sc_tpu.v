// =============================================================================
// File      : design/rtl/tpu/sc_tpu.v
// Module    : sc_tpu   (top of the stochastic-computing TPU)
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Reqs      : requirements/REQUIREMENTS.md REQ-TPU-002 (register map, reset values), REQ-TPU-003 (PARAMS), REQ-TPU-007 (LOG2_L clamp), REQ-TPU-011 (writes while BUSY), REQ-TPU-012 (init files), REQ-TPU-015 (reserved offsets), REQ-SYS bus rules (ARCHITECTURE.md 3)
// Task      : RTL-TPU (rev A), RTL-SOC (rev B / rev C update) - fpga-engineer
// Spec      : ARCHITECTURE.md rev A: 3 (bus), 5.1-5.6 (SC-TPU; 5.2, 5.3, 5.5
//             are [BIT-EXACT]) + 9 (A.1) + 10 (A.2) + 11 (rev B, ADR-008:
//             default RNG_MODE 2) + 12 (REV C, ADR-010, current: seed tables
//             in sc_rng.v, PARAMS version 0x03); management/INTERFACES.json
//             rev C "bus", "tpu".
//
// PURPOSE
//   Memory-mapped stochastic-computing accelerator for the MLP 64-16-10:
//   a native valid/ready bus slave (register map of spec 5.4) around
//     sc_rng        LFSR random-number generators (RNG_MODE 0/1/2)
//     sc_lane_array 16 x 8 SNG comparators + XNOR multipliers + APCs
//     sc_postproc   D, B, Dp, clipped-ReLU / score (time-shared, pipelined)
//     sc_tpu_ctrl   inference sequencer (tiles, layers, argmax, CYCLES)
//   and the storage: INPUT (64 codes), BIAS (32 x int16), weight RAM (2 KiB),
//   HIDDEN (16 codes), SCORE (16 x Dp), CONFIG/STATUS/RESULT/CYCLES/PARAMS.
//
// STOCHASTIC-COMPUTING SUMMARY (details in the sub-module headers)
//   code c (0..255) <-> bipolar value v = (c-128)/128            (5.2)
//   SNG:  b = (r < c), r from a leap-forward LFSR -> P(b=1) = (v+1)/2
//   mult: XNOR(b_x, b_w)  -> bipolar stream of v_x * v_w
//   APC:  acc_j += popcount over the IL products, every stream cycle
//   post: D = 2 acc - N_in L ; Dp = D + floor(bias 2^K / 128) ;
//         layer 1 HIDDEN = 128 + clip(floor(Dp 2^(s+7) / 2^K), 0, 127),
//         layer 2 SCORE = Dp ; RESULT = argmax SCORE[0..9]        (5.3)
//
// REGISTER MAP (offsets inside the 4 KiB TPU window, base 0x2000_0000, 5.4)
//   0x000 CTRL    W   [0] START: write 1 starts an inference; ignored while BUSY.
//                     Reads return 0.
//   0x004 STATUS  R   [0] BUSY, [1] DONE (DONE cleared by START, set at the end).
//   0x008 CONFIG  RW  [3:0] LOG2_L (reset 8), [6:4] ACT_SHIFT (reset 0).
//                     LOG2_L is CLAMPED TO 4..10 WHEN WRITTEN, so the read-back
//                     value is the effective K actually used (ARCHITECTURE.md
//                     10, rev A.2: write 15 -> read 10, write 1 -> read 4).
//   0x00C RESULT  R   [3:0] argmax class of the last inference (reset 0).
//   0x010 CYCLES  R   number of rising clock edges with BUSY = 1 of the last
//                     inference (ARCHITECTURE.md 10); counts live while BUSY;
//                     reset 0. Closed-form value in sc_tpu_ctrl.v.
//   0x014 PARAMS  R   [7:0] NL, [15:8] IL, [17:16] RNG_MODE, [31:24] version.
//                     version = 0x03 = rev C (ARCHITECTURE.md 12; 0x01 rev A,
//                     0x02 rev B). Rev C default build: 0x0302_0810.
//   0x040-0x07F INPUT  RW 64 codes, 4 per word, little-endian, byte writes OK.
//   0x080-0x0BF SCORE  R  16 x signed 32-bit (Dp sign-extended from 20 bits).
//   0x0C0-0x0CF HIDDEN R  16 codes, 4 per word.
//   0x100-0x17F BIAS   RW 32 words, [15:0] int16 bias, index 16*(l-1)+j.
//                     Read-back is SIGN-EXTENDED from [15:0]; write bits
//                     [31:16] are ignored (ARCHITECTURE.md 10, rev A.2).
//   0x800-0xFFF WEIGHT RW 2 KiB weight RAM (512 x 32-bit BSRAM), layout 5.5.
//   Everything else inside the window (0x018-0x03F, 0x0D0-0x0FF, 0x180-0x7FF):
//   reads 0, writes ignored, mem_ready is still returned (no hang;
//   ARCHITECTURE.md 10, REQ-TPU-015). The SoC decoder handles addr[31:28].
//   WRITES WHILE BUSY: ignored for every register and buffer (CTRL, CONFIG,
//   INPUT, BIAS, WEIGHT) - ASSUMPTION of 5.4 / INTERFACES.json busy_writes.
//
// BUS TIMING (ARCHITECTURE.md 3; latency chosen here, documented)
//   Native valid/ready. The slave takes mem_addr[11:0] only.
//     cycle A   : mem_valid = 1 and the slave is idle -> request ACCEPTED at
//                 the end of cycle A (writes are performed at this edge; reads
//                 present the address to the synchronous memories).
//     cycle A+1 : read data selected and registered into mem_rdata.
//     cycle A+2 : mem_ready = 1 for exactly one cycle, mem_rdata valid
//                 (mem_rdata is 0 in every other cycle, so an SoC may OR the
//                 slaves' read buses). The slave ignores mem_valid during
//                 A+1 and A+2, so a master that keeps mem_valid high for the
//                 next transaction is accepted again from cycle A+3.
//   => fixed latency: mem_ready 2 cycles after acceptance (3rd cycle of
//      mem_valid) for every register, buffer and the weight RAM.
//   Exception: a READ of INPUT, BIAS or WEIGHT while the controller owns the
//   memory read ports (tile load or post-processing, at most NWT+1 = 33
//   consecutive cycles) is not accepted until the ports are free; the
//   master simply waits with mem_valid = 1 (mem_ready never appears without
//   mem_valid). Reads of SCORE/HIDDEN while BUSY return the current
//   (possibly partially updated) contents.
//
// PARAMETERS
//   NL = 16, IL = 8 (rev A; IL = 4/16 only for the synthesis study; IL must
//   divide 16), RNG_MODE = 2 (0 SHARED, 1 ROTATE, 2 INDEPENDENT; ADR-003;
//   default 2 since rev B, ADR-008),
//   WEIGHT_INIT / BIAS_INIT / INPUT_INIT = $readmemh file names (spec 5.6:
//   weights.hex 512 x 32-bit, bias.hex 32 x 16-bit, input.hex 16 x 32-bit);
//   "" -> memory initialised to zero.
//
// RESET: synchronous, active-high rst (ARCHITECTURE.md 2). Reset values:
//   CONFIG = {s=0, K=8}, STATUS = 0 (BUSY = 0, DONE = 0), RESULT = 0,
//   CYCLES = 0, HIDDEN = 0, SCORE = 0 (ARCHITECTURE.md 9, rev A.1). They
//   keep these values until the first inference overwrites them; reads while
//   BUSY return the current storage contents (ARCHITECTURE.md 10, rev A.2),
//   so HIDDEN/SCORE may be partially updated during an inference.
//   Memories (INPUT, BIAS, WEIGHT) are not reset; they hold their
//   init-file contents until written.
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module sc_tpu #(
    parameter integer NL          = 16,
    parameter integer IL          = 8,
    parameter integer RNG_MODE    = 2,          // default since rev B (ADR-008), rev C
    parameter         WEIGHT_INIT = "",
    parameter         BIAS_INIT   = "",
    parameter         INPUT_INIT  = ""
) (
    input  wire        clk,
    input  wire        rst,
    // ---- native bus slave port (ARCHITECTURE.md 3) --------------------------
    input  wire        mem_valid,   // already qualified by the SoC decoder
    input  wire [11:0] mem_addr,    // byte offset inside the TPU window
    input  wire [31:0] mem_wdata,
    input  wire [3:0]  mem_wstrb,   // 0000 = read
    output reg         mem_ready,
    output reg  [31:0] mem_rdata
);

    // ---- widths -----------------------------------------------------------------
    localparam integer AW  = 17;          // accumulator width (sc_lane_array.v)
    localparam integer DPW = 20;          // Dp width (sc_postproc.v)
    localparam integer TWB = NL * IL * 8; // weight-tile register bits (1024)
    localparam integer XB  = IL * 8;      // input-tile register bits (64)

    // PARAMS register fields (5.4).
    localparam [7:0] P_NL      = NL[7:0];
    localparam [7:0] P_IL      = IL[7:0];
    localparam [1:0] P_MODE    = RNG_MODE[1:0];
    localparam [7:0] P_VERSION = 8'h03;   // rev C (ARCHITECTURE.md 12); rev A 0x01, rev B 0x02

    // =========================================================================
    // Address decode (combinational, on the bus address)
    // =========================================================================
    wire sel_regs   = (mem_addr[11:6] == 6'b000000);   // 0x000-0x03F
    wire sel_input  = (mem_addr[11:6] == 6'b000001);   // 0x040-0x07F
    wire sel_score  = (mem_addr[11:6] == 6'b000010);   // 0x080-0x0BF
    wire sel_hidden = (mem_addr[11:4] == 8'h0C);       // 0x0C0-0x0CF
    wire sel_bias   = (mem_addr[11:7] == 5'b00010);    // 0x100-0x17F
    wire sel_weight =  mem_addr[11];                   // 0x800-0xFFF
    wire [3:0] reg_idx = mem_addr[5:2];                // register / word index
    // mem_addr[1:0]: byte offset inside a word. All accesses are word
    // accesses with byte strobes (5.4), so the two LSBs are intentionally
    // unused (Verilator idiom: a signal whose name contains "unused").
    wire unused_addr_lsb = &{1'b0, mem_addr[1:0]};
    wire sel_ctrl   = sel_regs && (reg_idx == 4'd0);
    wire sel_config = sel_regs && (reg_idx == 4'd2);

    wire is_read    = (mem_wstrb == 4'b0000);
    wire sel_mem    = sel_input || sel_bias || sel_weight;  // shared read ports

    // =========================================================================
    // Bus slave FSM: IDLE -> WAIT -> RESP -> IDLE (see BUS TIMING above)
    // =========================================================================
    localparam [1:0] B_IDLE = 2'd0;
    localparam [1:0] B_WAIT = 2'd1;
    localparam [1:0] B_RESP = 2'd2;

    reg  [1:0]  bstate;
    wire        busy;            // from the controller
    wire        port_busy;       // controller owns the memory read ports

    // A read of a shared memory waits while the controller uses the ports.
    wire accept   = mem_valid && (bstate == B_IDLE) &&
                    !(is_read && sel_mem && port_busy);
    // Every write is ignored while BUSY (5.4); START is only seen when idle.
    wire wr_ok    = accept && !is_read && !busy;
    wire start    = wr_ok && sel_ctrl && mem_wstrb[0] && mem_wdata[0];

    // Read source selected at acceptance, used one cycle later.
    localparam [1:0] RS_REG = 2'd0, RS_INPUT = 2'd1, RS_BIAS = 2'd2, RS_WEIGHT = 2'd3;
    reg  [1:0]  rsrc_q;          // which source to return
    reg         rd_q;            // the accepted request is a read
    reg  [31:0] reg_rdata_q;     // register/HIDDEN/SCORE read data (captured at accept)

    // =========================================================================
    // CONFIG register (5.4): LOG2_L clamped to 4..10 at write time.
    // =========================================================================
    reg  [3:0] cfg_k;
    reg  [2:0] cfg_s;

    function [3:0] clamp_k;
        input [3:0] raw;
        begin
            if (raw < 4'd4)       clamp_k = 4'd4;
            else if (raw > 4'd10) clamp_k = 4'd10;
            else                  clamp_k = raw;
        end
    endfunction

    always @(posedge clk) begin
        if (rst) begin
            cfg_k <= 4'd8;           // reset LOG2_L = 8 (L = 256)
            cfg_s <= 3'd0;           // reset ACT_SHIFT = 0
        end else if (wr_ok && sel_config && mem_wstrb[0]) begin
            cfg_k <= clamp_k(mem_wdata[3:0]);
            cfg_s <= mem_wdata[6:4];
        end
    end

    // =========================================================================
    // Controller <-> datapath wiring
    // =========================================================================
    wire           done, layer2;
    wire [31:0]    cycles;
    wire [3:0]     result;
    wire [8:0]     ctl_w_raddr;
    wire [3:0]     ctl_x_raddr;
    wire [4:0]     ctl_b_raddr;
    wire           w_shift, x_shift, lfsr_load, stream_en, acc_clr;
    wire           pp_in_valid;
    wire [3:0]     pp_in_idx;
    wire           pp_out_valid, pp_out_layer2;
    wire [3:0]     pp_out_idx;
    wire [DPW-1:0] pp_out_dp;
    wire [7:0]     pp_out_hcode;

    // =========================================================================
    // Weight RAM: 512 x 32 bit, simple dual port, synchronous read -> BSRAM.
    //   Write port: CPU only (and only while !BUSY), byte strobes.
    //   Read port : controller while port_busy, otherwise the CPU.
    // =========================================================================
    reg  [31:0] wram [0:511];
    reg  [31:0] wram_q;
    wire [8:0]  wram_raddr = port_busy ? ctl_w_raddr : mem_addr[10:2];
    wire        wram_we    = wr_ok && sel_weight;

    integer nw;
    initial begin
        if (WEIGHT_INIT != "") $readmemh(WEIGHT_INIT, wram);
        else for (nw = 0; nw < 512; nw = nw + 1) wram[nw] = 32'd0;
    end

    always @(posedge clk) begin
        if (wram_we) begin
            if (mem_wstrb[0]) wram[mem_addr[10:2]][7:0]   <= mem_wdata[7:0];
            if (mem_wstrb[1]) wram[mem_addr[10:2]][15:8]  <= mem_wdata[15:8];
            if (mem_wstrb[2]) wram[mem_addr[10:2]][23:16] <= mem_wdata[23:16];
            if (mem_wstrb[3]) wram[mem_addr[10:2]][31:24] <= mem_wdata[31:24];
        end
        wram_q <= wram[wram_raddr];
    end

    // =========================================================================
    // INPUT buffer: 16 x 32 bit (64 codes), synchronous read -> LUT RAM + DFF.
    // =========================================================================
    reg  [31:0] inram [0:15];
    reg  [31:0] inram_q;
    wire [3:0]  inram_raddr = port_busy ? ctl_x_raddr : mem_addr[5:2];
    wire        inram_we    = wr_ok && sel_input;

    integer ni;
    initial begin
        if (INPUT_INIT != "") $readmemh(INPUT_INIT, inram);
        else for (ni = 0; ni < 16; ni = ni + 1) inram[ni] = 32'd0;
    end

    always @(posedge clk) begin
        if (inram_we) begin
            if (mem_wstrb[0]) inram[mem_addr[5:2]][7:0]   <= mem_wdata[7:0];
            if (mem_wstrb[1]) inram[mem_addr[5:2]][15:8]  <= mem_wdata[15:8];
            if (mem_wstrb[2]) inram[mem_addr[5:2]][23:16] <= mem_wdata[23:16];
            if (mem_wstrb[3]) inram[mem_addr[5:2]][31:24] <= mem_wdata[31:24];
        end
        inram_q <= inram[inram_raddr];
    end

    // =========================================================================
    // BIAS buffer: 32 x 16 bit, synchronous read -> LUT RAM + DFF.
    // =========================================================================
    reg  [15:0] bram [0:31];
    reg  [15:0] bram_q;
    wire [4:0]  bram_raddr = port_busy ? ctl_b_raddr : mem_addr[6:2];
    wire        bram_we    = wr_ok && sel_bias;

    integer nb;
    initial begin
        if (BIAS_INIT != "") $readmemh(BIAS_INIT, bram);
        else for (nb = 0; nb < 32; nb = nb + 1) bram[nb] = 16'd0;
    end

    always @(posedge clk) begin
        if (bram_we) begin
            if (mem_wstrb[0]) bram[mem_addr[6:2]][7:0]  <= mem_wdata[7:0];
            if (mem_wstrb[1]) bram[mem_addr[6:2]][15:8] <= mem_wdata[15:8];
        end
        bram_q <= bram[bram_raddr];
    end

    // =========================================================================
    // HIDDEN (16 codes) and SCORE (16 x Dp) result registers, written by the
    // post-processor output (one neuron per cycle during S_POST).
    // =========================================================================
    reg [16*8-1:0]   hidden;   // HIDDEN[j] at [8j +: 8]
    reg [16*DPW-1:0] score;    // SCORE[j]  at [DPW*j +: DPW]

    always @(posedge clk) begin
        if (rst) begin
            hidden <= {16*8{1'b0}};
            score  <= {16*DPW{1'b0}};
        end else if (pp_out_valid) begin
            if (!pp_out_layer2) hidden[8*pp_out_idx +: 8]     <= pp_out_hcode;
            else                score[DPW*pp_out_idx +: DPW]  <= pp_out_dp;
        end
    end

    // =========================================================================
    // Tile registers (weight-stationary operands of one tile)
    // =========================================================================
    // Layer-2 inputs come from HIDDEN: register the selected word so that it
    // arrives with the same 1-cycle latency as the INPUT RAM word.
    reg  [31:0] hid_word_q;
    always @(posedge clk)
        hid_word_q <= hidden[32*ctl_x_raddr[1:0] +: 32];

    wire [31:0] x_src_word = layer2 ? hid_word_q : inram_q;

    // Weight tile: NWT words shifted in from the top, so after NWT shifts
    // word 0 of the tile sits at bits [31:0] and tile byte b = j*IL + i is at
    // [8b +: 8] - exactly the order sc_lane_array expects (5.5).
    reg [TWB-1:0] w_tile;
    always @(posedge clk)
        if (w_shift) w_tile <= {wram_q, w_tile[TWB-1:32]};

    // Input tile: IL/4 words, same shifting scheme (IL = 4: a single word).
    reg [XB-1:0] x_tile;
    generate
        if (IL == 4) begin : g_x1
            always @(posedge clk)
                if (x_shift) x_tile <= x_src_word;
        end else begin : g_xn
            always @(posedge clk)
                if (x_shift) x_tile <= {x_src_word, x_tile[XB-1:32]};
        end
    endgenerate

    // =========================================================================
    // Sub-modules
    // =========================================================================
    wire [XB-1:0]    rx, rw;
    wire [NL*AW-1:0] acc;

    sc_rng #(.IL(IL), .RNG_MODE(RNG_MODE)) u_rng (
        .clk(clk), .rst(rst), .load(lfsr_load), .adv(stream_en),
        .rx(rx), .rw(rw));

    sc_lane_array #(.NL(NL), .IL(IL), .AW(AW)) u_array (
        .clk(clk), .clr(acc_clr), .en(stream_en),
        .w_tile(w_tile), .x_tile(x_tile), .rx(rx), .rw(rw), .acc(acc));

    sc_postproc #(.AW(AW), .DPW(DPW)) u_post (
        .clk(clk), .rst(rst),
        .in_valid(pp_in_valid), .in_layer2(layer2), .in_idx(pp_in_idx),
        .in_k(cfg_k), .in_s(cfg_s),
        .in_acc(acc[AW*pp_in_idx +: AW]), .in_bias(bram_q),
        .out_valid(pp_out_valid), .out_layer2(pp_out_layer2), .out_idx(pp_out_idx),
        .out_dp(pp_out_dp), .out_hcode(pp_out_hcode));

    sc_tpu_ctrl #(.NL(NL), .IL(IL), .DPW(DPW)) u_ctrl (
        .clk(clk), .rst(rst),
        .start(start), .cfg_k(cfg_k),
        .pp_out_valid(pp_out_valid), .pp_out_layer2(pp_out_layer2),
        .pp_out_idx(pp_out_idx), .pp_out_dp(pp_out_dp),
        .busy(busy), .done(done), .cycles(cycles), .result(result),
        .layer2(layer2), .port_busy(port_busy),
        .w_raddr(ctl_w_raddr), .x_raddr(ctl_x_raddr), .b_raddr(ctl_b_raddr),
        .w_shift(w_shift), .x_shift(x_shift), .lfsr_load(lfsr_load),
        .stream_en(stream_en), .acc_clr(acc_clr),
        .pp_in_valid(pp_in_valid), .pp_in_idx(pp_in_idx));

    // =========================================================================
    // Register read multiplexer (evaluated in the acceptance cycle)
    // =========================================================================
    reg  [31:0] reg_rdata;
    wire [DPW-1:0] score_sel = score[DPW*reg_idx +: DPW];
    always @(*) begin
        reg_rdata = 32'd0;
        if (sel_regs) begin
            case (reg_idx)
                4'd1:    reg_rdata = {30'd0, done, busy};                 // STATUS
                4'd2:    reg_rdata = {25'd0, cfg_s, cfg_k};               // CONFIG
                4'd3:    reg_rdata = {28'd0, result};                     // RESULT
                4'd4:    reg_rdata = cycles;                              // CYCLES
                4'd5:    reg_rdata = {P_VERSION, 6'd0, P_MODE, P_IL, P_NL}; // PARAMS
                default: reg_rdata = 32'd0;                               // CTRL (W only), unmapped
            endcase
        end else if (sel_score) begin
            reg_rdata = {{(32-DPW){1'b0}}, score_sel};        // sign-extend
        end else if (sel_hidden) begin
            reg_rdata = hidden[32*reg_idx[1:0] +: 32];
        end
    end

    // =========================================================================
    // Bus slave sequencing and read-data return
    // =========================================================================
    always @(posedge clk) begin
        if (rst) begin
            bstate      <= B_IDLE;
            mem_ready   <= 1'b0;
            mem_rdata   <= 32'd0;
            rsrc_q      <= RS_REG;
            rd_q        <= 1'b0;
            reg_rdata_q <= 32'd0;
        end else begin
            case (bstate)
                B_IDLE: begin
                    mem_ready <= 1'b0;
                    mem_rdata <= 32'd0;
                    if (accept) begin
                        bstate      <= B_WAIT;
                        rd_q        <= is_read;
                        reg_rdata_q <= reg_rdata;
                        rsrc_q      <= sel_input  ? RS_INPUT  :
                                       sel_bias   ? RS_BIAS   :
                                       sel_weight ? RS_WEIGHT : RS_REG;
                    end
                end
                B_WAIT: begin
                    // Synchronous memories present the data addressed in the
                    // acceptance cycle; select and register it.
                    bstate    <= B_RESP;
                    mem_ready <= 1'b1;
                    if (!rd_q)
                        mem_rdata <= 32'd0;
                    else case (rsrc_q)
                        RS_INPUT:  mem_rdata <= inram_q;
                        RS_BIAS:   mem_rdata <= {{16{bram_q[15]}}, bram_q};
                        RS_WEIGHT: mem_rdata <= wram_q;
                        default:   mem_rdata <= reg_rdata_q;
                    endcase
                end
                default: begin // B_RESP: mem_ready is 1 in this cycle
                    bstate    <= B_IDLE;
                    mem_ready <= 1'b0;
                    mem_rdata <= 32'd0;
                end
            endcase
        end
    end

endmodule

`default_nettype wire
