#!/usr/bin/env bash
# REV-01b independent re-run of the TPU regression at the reviewed revision.
# Same commands as scripts/sim_tpu.sh steps 3-5 but ALL outputs go to
# reports/review/build/REV-01b/rerun/ (logs/tpu/ is not touched).
set -u
ROOT=/home/user/tpu-e-cpu; cd "$ROOT"
O=reports/review/build/REV-01b/rerun; mkdir -p "$O"
D=design/rtl/tpu
RTL="$D/sc_lfsr8.v $D/sc_rng.v $D/sc_lane_array.v $D/sc_postproc.v $D/sc_tpu_ctrl.v $D/sc_tpu.v"
REV="$(git rev-parse --short HEAD)$( [ -n "$(git status --porcelain -- design/rtl/tpu tests/tpu sim/data sim/tpu)" ] && echo -dirty)"
echo "# REV-01b rerun rev $REV $(date -Is); $(iverilog -V 2>&1 | head -1)" > "$O/summary.log"
run() { # name, iverilog args..., --, vvp args...
  local n=$1; shift; local ia=() pa=()
  while [ "$1" != "--" ]; do ia+=("$1"); shift; done; shift; pa=("$@")
  local rc=0
  { echo "# rev $REV cmd: iverilog -g2005 -Wall ${ia[*]} ; vvp ${pa[*]}"
    iverilog -g2005 -Wall "${ia[@]}" -o "$O/$n.vvp" && vvp -n "$O/$n.vvp" "${pa[@]}" || rc=$?
    echo "SIM_EXIT=$rc"; } > "$O/$n.log" 2>&1
  echo "$n: $(grep -E '^TEST (PASSED|FAILED)' "$O/$n.log" | tail -1) $(grep -E '^SIM_EXIT' "$O/$n.log")" >> "$O/summary.log"
}
run tb_sc_lfsr8 $D/sc_lfsr8.v $D/sc_rng.v tests/tpu/tb_sc_lfsr8.v --
run tb_sc_postproc $D/sc_postproc.v tests/tpu/tb_sc_postproc.v --
run tb_sc_lane_array $D/sc_lane_array.v tests/tpu/tb_sc_lane_array.v --
run tb_sc_tpu_m2 -P tb_sc_tpu.RNG_MODE=2 $RTL tests/tpu/tb_sc_tpu.v -- +DATA=sim/data +DIRECTED +CLAMP \
    +VEC1=sim/data/tpu_vectors_mode2.txt +VEC2=sim/data/tpu_vectors_corner_mode2.txt +VEC3=sim/tpu/vectors/tpu_vectors_sweep_mode2.txt
run tb_sc_tpu_m1 -P tb_sc_tpu.RNG_MODE=1 $RTL tests/tpu/tb_sc_tpu.v -- +DATA=sim/data +DIRECTED +CLAMP \
    +VEC1=sim/data/tpu_vectors_K4_mode1.txt +VEC2=sim/data/tpu_vectors_K10_mode1.txt +VEC3=sim/data/tpu_vectors_corner_mode1.txt +VEC4=sim/tpu/vectors/tpu_vectors_sweep_mode1.txt
run tb_sc_tpu_m0 -P tb_sc_tpu.RNG_MODE=0 $RTL tests/tpu/tb_sc_tpu.v -- +DATA=sim/data +DIRECTED +CLAMP \
    +VEC1=sim/data/tpu_vectors_corner_mode0.txt +VEC2=sim/tpu/vectors/tpu_vectors_sweep_mode0.txt
run tb_sc_tpu_init_m2 -P tb_sc_tpu.RNG_MODE=2 -P tb_sc_tpu.INIT_FILES=1 $RTL tests/tpu/tb_sc_tpu.v -- +DATA=sim/data +INITVEC=sim/data/tpu_vectors_mode2.txt
sha256sum sim/data/tpu_vectors_*.txt sim/tpu/vectors/*.txt sim/data/*.hex sim/data/tpu_rng_trace_mode*.txt >> "$O/summary.log"
echo RERUN_DONE >> "$O/summary.log"
