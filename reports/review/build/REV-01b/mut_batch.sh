#!/usr/bin/env bash
# REV-01b: batch of single-point mutations of COPIES of design/rtl/tpu.
R=/home/user/tpu-e-cpu/reports/review/build/REV-01b/run_mut.sh
C0=sim/data/tpu_vectors_corner_mode0.txt
C1=sim/data/tpu_vectors_corner_mode1.txt
C2=sim/data/tpu_vectors_corner_mode2.txt
K4=sim/data/tpu_vectors_K4_mode1.txt
bash $R M01_seed_x5      2 sc_rng.v        "s/16'hDAA3/16'hDAA2/"  $C2
bash $R M02_rot_right    1 sc_rng.v        "s/else        rotl8 = (v << n) | (v >> (8 - n));/else        rotl8 = (v >> n) | (v << (8 - n));/" $C1 $K4
bash $R M03_stream_Lp1   2 sc_tpu_ctrl.v   "s/wire \[10:0\] l_last    = (11'd1 << cfg_k) - 11'd1;/wire [10:0] l_last    = (11'd1 << cfg_k);/" $C2
bash $R M04_bias_trunc   2 sc_postproc.v   "s/wire \[25:0\]    bias_sh = bias_x << in_k;/wire [25:0]    bias_sh = (bias_x << in_k) + (in_bias[15] ? 26'd127 : 26'd0);/" $C2
bash $R M05_argmax_ge    2 sc_tpu_ctrl.v   "s/(\$signed(pp_out_dp) > \$signed(best_dp))/(\$signed(pp_out_dp) >= \$signed(best_dp))/" $C2
bash $R M06_argmax_11    2 sc_tpu_ctrl.v   "s/(pp_out_idx < 4'd10)/(pp_out_idx < 4'd11)/" $C2
bash $R M07_adv_in_load  2 sc_tpu.v        "s/.load(lfsr_load), .adv(stream_en),/.load(lfsr_load), .adv(stream_en | w_shift),/" $C2
bash $R M08_no_reload    2 sc_tpu.v        "s/.load(lfsr_load), .adv(stream_en),/.load(1'b0), .adv(stream_en),/" $C2
bash $R M09_acc16        2 sc_tpu.v        "s/localparam integer AW  = 17;/localparam integer AW  = 16;/" $C2
bash $R M10_score_zext   2 sc_tpu.v        "s/reg_rdata = {{(32-DPW){score_sel\[DPW-1\]}}, score_sel};/reg_rdata = {{(32-DPW){1'b0}}, score_sel};/" $C2
bash $R M11_noneg_clip   2 sc_postproc.v   "s/wire        u_neg = u\[33\];/wire        u_neg = 1'b0;/" $C2
bash $R M12_lsr_floor    2 sc_postproc.v   "s/wire \[33:0\] u     = \$signed(wide) >>> k1;/wire [33:0] u     = wide >> k1;/" $C2
bash $R M13_wsng_le      2 sc_lane_array.v "s/assign bw\[i\] = (rw\[8\*i +: 8\] < /assign bw[i] = (rw[8*i +: 8] <= /" $C2
bash $R M14_xsng_le      2 sc_lane_array.v "s/assign bx\[i\] = (rx\[8\*i +: 8\] < /assign bx[i] = (rx[8*i +: 8] <= /" $C2
bash $R M15_nin_l2       2 sc_postproc.v   "s/in_layer2 ? 5'd4 : 5'd6/in_layer2 ? 5'd5 : 5'd6/" $C2
bash $R M16_leap7        2 sc_lfsr8.v      "s/for (n = 0; n < 8; n = n + 1)/for (n = 0; n < 7; n = n + 1)/" $C2
bash $R M17_r_highbyte   2 sc_lfsr8.v      "s/assign r = state\[7:0\];/assign r = state[15:8];/" $C2
bash $R M18_load_seed    2 sc_lfsr8.v      "s/state <= LOAD_VALUE;/state <= SEED16;/" $C2
bash $R M19_cycles_p1    2 sc_tpu_ctrl.v   "/else if (lfsr_load)/{n;s/cycles <= 32'd0;/cycles <= 32'd1;/}" $C2
bash $R M20_wr_busy      2 sc_tpu.v        "s/wire wr_ok    = accept \&\& !is_read \&\& !busy;/wire wr_ok    = accept \&\& !is_read;/" $C2
bash $R M21_seedw01      0 sc_rng.v        "s/localparam \[15:0\] SEED_W = 16'hF9DE;/localparam [15:0] SEED_W = 16'h7A5C;/" $C0
bash $R M22_hidword      2 sc_tpu.v        "s/hid_word_q <= hidden\[32\*ctl_x_raddr\[1:0\] +: 32\];/hid_word_q <= hidden[32*(~ctl_x_raddr[1:0]) +: 32];/" $C2
bash $R M23_clip126      2 sc_postproc.v   "s/(u_big ? 7'd127 : u\[6:0\])/(u_big ? 7'd126 : u[6:0])/" $C2
echo MUT_BATCH_DONE
