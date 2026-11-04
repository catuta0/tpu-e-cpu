// =============================================================================
// File      : design/rtl/tpu/sc_lfsr8.v
// Module    : sc_lfsr8
// Project   : SC-TPU + RV32I SoC on Tang Nano 9K (GW1NR-LV9QN88PC6/I5)
// Reqs      : requirements/REQUIREMENTS.md REQ-TPU-005 (LFSR definition and sequencing)
// Task      : RTL-TPU (fpga-engineer)
// Spec      : design/architecture/ARCHITECTURE.md rev A, section 5.3 [BIT-EXACT]
//             (RNG paragraph), management/INTERFACES.json tpu.lfsr, ADR-005.
//
// PURPOSE
//   16-bit Fibonacci LFSR, polynomial x^16 + x^14 + x^13 + x^11 + 1, that
//   advances by EIGHT single steps per enabled clock ("leap-forward" LFSR).
//   It is the pseudo-random source of the stochastic number generators (SNG)
//   of the SC-TPU.
//
// THEORY
//   * A stochastic number generator turns an 8-bit code c into a bit stream
//     b_k = (r_k < c). If the r_k are (close to) uniformly distributed over
//     0..255, P(b_k = 1) = c/256. The quality of the r_k sequence therefore
//     sets the accuracy of every stochastic product in the TPU.
//   * One LFSR step (spec 5.3):  fb = s[15]^s[13]^s[12]^s[10];
//                                s' = {s[14:0], fb}
//     i.e. the register shifts towards the MSB and the new bit enters at
//     bit 0. The polynomial is primitive, so the period is 2^16 - 1 = 65535
//     (CALCULATION/SOURCE: maximal-length LFSR theory) for every non-zero seed.
//   * If r were simply the low byte after ONE step, consecutive r values would
//     be shifted copies of each other (r_{k+1} = 2*r_k + fb mod 256): strong
//     serial correlation (ADR-005). The spec therefore advances 8 steps per
//     stream cycle, so the low byte consists of 8 brand-new feedback bits.
//   * Eight steps of a linear map over GF(2) are again a linear map, so the
//     "leap" is a pure XOR network: every bit of the new state is the XOR of
//     a fixed subset of the old bits. Here it is written as 8 chained copies
//     of the single-step function inside a Verilog function; synthesis
//     flattens it into that XOR network (2-3 LUT4 levels), no extra flops.
//   * gcd(8, 65535) = 1, so the 8-step sequence also has period 65535 and
//     visits every non-zero state (checked in tests/tpu/tb_sc_lfsr8.v).
//
// LOOK-AHEAD CONVENTION (important for bit-exactness, spec 5.3 reading A2)
//   The spec says: "one stream cycle advances every LFSR by 8 steps and uses
//   the low byte of the NEW state as r". To keep the leap network OUT of the
//   critical path (state -> XOR network -> comparator -> popcount -> adder),
//   this register always holds the state that the NEXT stream cycle will use:
//     - on load : state <= leap8(SEED)        (= state after stream cycle 0)
//     - on adv  : state <= leap8(state)
//   so during stream cycle k (k = 0, 1, ...) the output r = state[7:0] equals
//   low_byte(leap8^(k+1)(SEED)), which is exactly the r of spec 5.3. The
//   seed itself is never used as r. leap8(SEED) is a constant, so the load
//   path costs nothing.
//
// INTERFACE / TIMING
//   clk   : rising-edge clock (27 MHz system clock)
//   rst   : synchronous, active-high; same effect as load (defined reset
//           value, ARCHITECTURE.md 2)
//   load  : 1 -> state <= leap8(SEED) at the next edge (asserted by the TPU
//           controller in the cycle START is accepted, spec 5.3)
//   adv   : 1 -> state <= leap8(state) at the next edge (asserted in every
//           stream cycle and ONLY in stream cycles, spec 5.3)
//   state : current (look-ahead) 16-bit state, registered output
//   r     : state[7:0], the 8-bit random number of the current stream cycle
//   Priority: rst/load > adv. Latency: 0 (r is a flop output).
//
// PARAMETERS
//   SEED  : non-zero 16-bit seed, passed as an integer (bits [15:0] used; 0 is
//           the LFSR lock-up state and must never be used; all seeds of spec
//           5.3 are non-zero, see sc_rng.v).
//
// RESOURCES (expected): 16 DFF + ~16 LUT4 (XOR network + load/adv mux).
// =============================================================================
`timescale 1ns/1ps
`default_nettype none

module sc_lfsr8 #(
    // Seed as an integer so that callers can pass a modulo-2^16 expression
    // without width truncation; only bits [15:0] are used (SEED16 below).
    parameter integer SEED = 32'h0000_ACE1// spec 5.3: LFSR_X seed (0xACE1) by default
) (
    input  wire        clk,
    input  wire        rst,
    input  wire        load,
    input  wire        adv,
    output reg  [15:0] state,
    output wire [7:0]  r
);

    // -------------------------------------------------------------------------
    // step1: ONE step of the Fibonacci LFSR, literally as written in spec 5.3.
    //   feedback = s[15] ^ s[13] ^ s[12] ^ s[10]   (taps 16,14,13,11 -> bit-1)
    //   next     = {s[14:0], feedback}             ((s << 1) | fb) & 0xFFFF
    // -------------------------------------------------------------------------
    function [15:0] step1;
        input [15:0] s;
        begin
            step1 = {s[14:0], s[15] ^ s[13] ^ s[12] ^ s[10]};
        end
    endfunction

    // -------------------------------------------------------------------------
    // leap8: EIGHT chained single steps (spec 5.3 "advances every LFSR by 8
    // steps (unrolled leap-forward)"). The loop is unrolled at elaboration;
    // the result is a combinational XOR network (no state inside).
    // -------------------------------------------------------------------------
    function [15:0] leap8;
        input [15:0] s;
        integer n;
        reg [15:0] t;
        begin
            t = s;
            for (n = 0; n < 7; n = n + 1)
                t = step1(t);
            leap8 = t;
        end
    endfunction

    // Constant look-ahead load value: state after the 8 steps of stream cycle 0.
    localparam [15:0] SEED16     = SEED[15:0];
    localparam [15:0] LOAD_VALUE = leap8(SEED16);

    // Combinational 8-step image of the current state (the XOR network).
    wire [15:0] state_leap8 = leap8(state);

    // -------------------------------------------------------------------------
    // State register. rst and load share one behaviour (load the look-ahead
    // seed) so that the reset value is defined and equal to the post-START one.
    // The state only changes on load or adv: during weight/input loads and
    // post-processing adv is 0, so the LFSR is frozen (spec 5.3: "advance
    // only in stream cycles"; "NOT reset between tiles or layers").
    // -------------------------------------------------------------------------
    always @(posedge clk) begin
        if (rst || load)
            state <= LOAD_VALUE;
        else if (adv)
            state <= state_leap8;
    end

    // r = low byte of the (look-ahead) state = r of the current stream cycle.
    assign r = state[7:0];

endmodule

`default_nettype wire
