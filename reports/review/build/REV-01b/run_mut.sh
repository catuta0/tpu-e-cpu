#!/usr/bin/env bash
# REV-01b mutation runner (independent reviewer). Copies design/rtl/tpu to a
# private directory, applies ONE sed mutation to the copy, compiles tb_sc_tpu
# with Icarus and runs directed tests + a vector subset. Never touches design files.
# usage: run_mut.sh <name> <mode> <file> '<sed-expr>' [vecfiles...]
set -u
ROOT=/home/user/tpu-e-cpu
cd "$ROOT"
name=$1; mode=$2; file=$3; expr=$4; shift 4
O=reports/review/build/REV-01b/mut/$name
rm -rf "$O"; mkdir -p "$O/rtl"
cp design/rtl/tpu/*.v "$O/rtl/"
if [ "$file" != none ]; then
  sed -i -e "$expr" "$O/rtl/$file"
  diff -u design/rtl/tpu/$file "$O/rtl/$file" > "$O/mutation.diff"
  if [ ! -s "$O/mutation.diff" ]; then echo "MUTATION_NOT_APPLIED $name"; exit 2; fi
fi
R="$O/rtl"
RTL="$R/sc_lfsr8.v $R/sc_rng.v $R/sc_lane_array.v $R/sc_postproc.v $R/sc_tpu_ctrl.v $R/sc_tpu.v"
args=(); n=1
for f in "$@"; do args+=("+VEC$n=$f"); n=$((n+1)); done
{
  echo "# REV-01b mutation $name mode $mode rev $(git rev-parse --short HEAD)"
  echo "# cmd: iverilog -g2005 -P tb_sc_tpu.RNG_MODE=$mode <mutated rtl> tests/tpu/tb_sc_tpu.v; vvp +DATA=sim/data +DIRECTED +CLAMP ${args[*]}"
  rc=0
  iverilog -g2005 -P tb_sc_tpu.RNG_MODE=$mode $RTL tests/tpu/tb_sc_tpu.v -o "$O/tb.vvp" || rc=$?
  [ $rc -eq 0 ] && { timeout 3000 vvp -n "$O/tb.vvp" +DATA=sim/data +DIRECTED +CLAMP "${args[@]}" || rc=$?; }
  echo "SIM_EXIT=$rc"
} > "$O/sim.log" 2>&1
fails=$(grep -c '^FAIL' "$O/sim.log")
verdict=$(grep -E '^TEST (PASSED|FAILED)' "$O/sim.log" | tail -1)
echo "MUT $name mode=$mode: ${verdict:-NO_VERDICT} FAIL_lines=$fails $(grep -E '^(PASS|FAIL): (VECFILE|R1)' "$O/sim.log" | sed 's/^\(PASS\|FAIL\): \(VECFILE\|R1\)[^:]*: *//' | cut -c1-70 | tr '\n' '|')"
