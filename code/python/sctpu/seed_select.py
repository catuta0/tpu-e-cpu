"""Rev C LFSR seed selection on VALIDATION data only (task SW-03, step 1).

Protocol (fixed in advance by the manager, ADR-009; followed literally here)
---------------------------------------------------------------------------
* Data: the 288-image VALIDATION subset of the 1437-image training split, i.e.
  ``train.load_split()["val_idx"]`` = ``train_test_split(train_idx,
  test_size=288, stratify=y[train_idx], random_state=0)`` where ``train_idx``
  comes from ``train_test_split(arange(1797), test_size=360, stratify=y,
  random_state=0)`` on sklearn ``load_digits``. This is the same subset that
  SW-01a used to choose the activation shift s and the training variant. The
  360 TEST images are never loaded by this module (asserted: the validation
  indices are disjoint from the test indices).
  Caveat (stated in the report): the deployed weights were re-trained on all
  1437 training images, so these 288 images were seen in training; validation
  accuracies are therefore optimistic in absolute terms. The seeds do not
  change the weights, so the comparison BETWEEN seed sets is still a fair,
  test-independent selection.
* Candidates: all are points of the single m-sequence S(n) (state of the
  LFSR started at 0xACE1 after n single steps, ARCHITECTURE.md 11), so the
  RTL only changes constants:
    C0 = rev A seeds (ARCHITECTURE.md 5.3);
    C1 = rev B seeds (section 11): X_i = S(4096 i), W_i = S(32768 + 4096 i);
    C2 = rev B X seeds, W lane order reversed: W_i = S(32768 + 4096 (7 - i));
    C3, C4 = own designs (below), fixed from seed-structure CALCULATIONS only,
         before any accuracy was computed.
* Metric (mode 2 INDEPENDENT, the rev B/C default): deployed-seed validation
  accuracy for K = 8, 9, 10 (mean and worst) and the mean accuracy of the 20
  analysis-only start offsets (numpy default_rng(0), the SW-02 offsets) for
  K = 8, 9, 10.
* Selection: highest WORST-CASE deployed validation accuracy over K in
  {8, 9, 10}; tie-break: higher ensemble mean (average over K = 8, 9, 10 of
  the 20-offset means).

Seed-structure rules checked for every candidate (CALCULATION, exhaustive)
-------------------------------------------------------------------------
Notation: a generator g has single-step phase n_g (seed = S(n_g)) and
stream-cycle position P_g = n_g * 8^-1 mod 65535 (one stream cycle = 8 steps).
r_b(k) = r_a(k + P_b - P_a): every generator is a delayed copy of every other.
The joint (r_x, r_w) pair stream of lane i is a translate of lane j's iff
P_w(i) - P_x(i) = P_w(j) - P_x(j).

R1 (manager rule, ADR-009, "no translated pair streams"): for all lanes
    i != j: (lag_x(i) - lag_x(j)) != (lag_w(i) - lag_w(j)) mod 65535 in stream
    cycles, i.e. the pair offsets P_w(i) - P_x(i) are pairwise distinct.
    Rev B violates it (all eight offsets equal 4096).
R2 (stricter, introduced here; NOT part of the protocol, reported only):
    r is the low byte of the state, i.e. an 8-bit window of the common bit
    sequence; generator b at stream cycle k+D and generator a at cycle k share
    max(0, 8 - |n_b - n_a + 8 D|) bits (circular distance mod 65535). Two
    lanes' products are second-order correlated if BOTH operands share bits at
    the same lag D, either directly (X_i~X_j and W_i~W_j) or swapped
    (X_i~W_j and W_i~X_j, also i = j). With D_i = n_w(i) - n_x(i) (single
    steps) this happens for some D iff |D_i - D_j| <= 14 (direct, i != j) or
    |D_i + D_j| <= 14 (swapped, any i, j). R2 forbids both, which also
    excludes a same-instant X_i/W_i overlap (|D_i| <= 7). R1 is the 8-bit
    (exact) special case of the direct condition.
Lag metrics: lambda8 = minimum over the 120 generator pairs of the exact-copy
lag |P_b - P_a| (the "pairwise lag" of rev B, 512); lambda1 = minimum over the
pairs of the smallest lag at which they share at least one bit.

Own candidates (both one-line rules on one arithmetic progression of S):
    generator m = 0..15, X_i = generator i, W_i = generator 15 - i (reversed),
    seed(m) = S(alpha * m mod 65535), so D_i = alpha (15 - 2 i).
    C3: alpha = 32760 = 8 * 4095 -> stream positions P = 4095 m: the 16
        generators equally spaced in STREAM cycles; lambda8 = 4095, the
        maximum possible for 16 generators (floor(65535/16)); lambda1 = 1.
    C4: alpha = 4095 -> equally spaced in SINGLE STEPS (rev B spacing minus
        one step); lambda1 = 511 (maximum 512 is unreachable together with R2,
        see report), lambda8 = 3585.
    alpha was chosen by an exhaustive scan of alpha = 1..65534 of this family
    (``scan_progression_family``) for the two lexicographic objectives
    (lambda8, lambda1) and (lambda1, lambda8) subject to R1, R2 and no
    same-instant shared bits; ties (alpha vs 65535 - alpha) -> smaller alpha.

Outputs: ``reports/sw/seed_selection_revC.json`` and ``.md``; log
``logs/sw/seed_selection_revC.log``. All accuracies are SIMULATION results of
the bit-exact golden model (``sctpu.model``).
Run: ``cd code/python && ../../.venv/bin/python -m sctpu.seed_select``.
"""

from __future__ import annotations

import json
import math
import sys
import time

import numpy as np

from . import accuracy as A
from . import lfsr
from . import model as M
from . import train as T
from .compare_revs import identical_table_pairs, mcnemar_exact, paired_cells

PERIOD = lfsr.MAX_PERIOD  #: 65535
INV8 = M.INV8_MOD_PERIOD  #: 8^-1 mod 65535 = 8192
SEL_K = (8, 9, 10)  #: K values of the selection metric (protocol)
SEL_MODE = 2  #: RNG_MODE of the selection metric (rev B/C default)
N_ENS = 20  #: ensemble size (protocol; same offsets as SW-02)
ALPHA_C3 = 32760  #: C3 progression step (single steps) = 8 * 4095
ALPHA_C4 = 4095  #: C4 progression step (single steps)
R2_MARGIN = 15  #: |D_i -/+ D_j| >= 15 single steps: no simultaneous bit sharing


# ---------------------------------------------------------------------------
# Candidate seed sets
# ---------------------------------------------------------------------------

def progression_phases(alpha: int) -> tuple[list[int], list[int]]:
    """Single-step phases of the C3/C4 family: X_i = alpha*i, W_i = alpha*(15-i) (mod 65535)."""
    return ([(alpha * i) % PERIOD for i in range(M.IL)],
            [(alpha * (2 * M.IL - 1 - i)) % PERIOD for i in range(M.IL)])


def candidates() -> dict:
    """Return {name: {"x": seeds, "w": seeds, "rule": text}} for C0..C4 (mode 2, 8 lanes)."""
    ax, aw = M.lane_seeds(2, "A")
    bx, bw = M.lane_seeds(2, "B")
    out = {
        "C0": {"x": list(ax), "w": list(aw),
               "rule": "rev A: X_i = 0xACE1 + 0x3C5A*i, W_i = 0x7A5C + 0x2B67*i (mod 2^16)"},
        "C1": {"x": list(bx), "w": list(bw),
               "rule": "rev B: X_i = S(4096 i), W_i = S(32768 + 4096 i)"},
        "C2": {"x": list(bx), "w": [M.phase_state(M.PHASE_W + M.PHASE_LANE * (M.IL - 1 - i)) for i in range(M.IL)],
               "rule": "rev B X, W lanes reversed: X_i = S(4096 i), W_i = S(32768 + 4096 (7 - i))"},
    }
    for name, alpha, what in (("C3", ALPHA_C3, "equal spacing 4095 in stream cycles (max lambda8)"),
                              ("C4", ALPHA_C4, "equal spacing 4095 in single steps (max lambda1)")):
        nx, nw = progression_phases(alpha)
        out[name] = {"x": [M.phase_state(n) for n in nx], "w": [M.phase_state(n) for n in nw],
                     "rule": f"X_i = S({alpha} i), W_i = S({alpha} (15 - i)) (mod 65535): {what}"}
    return out


# ---------------------------------------------------------------------------
# Seed-structure analysis (CALCULATION)
# ---------------------------------------------------------------------------

def cdist(a: int) -> int:
    """Circular distance of ``a`` to 0 modulo the LFSR period 65535."""
    a %= PERIOD
    return min(a, PERIOD - a)


def stream_pos(n: int) -> int:
    """Stream-cycle position P = n * 8^-1 mod 65535 of a single-step phase n."""
    return n * INV8 % PERIOD


def shared_bits(n_a: int, n_b: int, lag: int) -> int:
    """Bits shared by r_a(k) and r_b(k + lag) for phases n_a, n_b (window model, R2)."""
    return max(0, 8 - cdist(n_b - n_a + 8 * lag))


def translate_rule_violations(sx: list, sw: list) -> list:
    """Manager rule R1: lane pairs (i, j) whose pair streams are exact translates.

    Uses the stream-cycle lags of every LFSR relative to X_0 (stream_lag_cycles
    on the common m-sequence): violation iff
    (lag_x(i) - lag_x(j)) == (lag_w(i) - lag_w(j)) mod 65535.
    """
    lx = [M.stream_lag_cycles(sx[0], v) for v in sx]
    lw = [M.stream_lag_cycles(sx[0], v) for v in sw]
    return [(i, j) for i in range(len(sx)) for j in range(i + 1, len(sx))
            if (lx[i] - lx[j]) % PERIOD == (lw[i] - lw[j]) % PERIOD]


def r2_violations(sx: list, sw: list) -> list:
    """Stricter rule R2: lane pairs whose operands share bits simultaneously (see module doc).

    Returns dicts {kind, i, j, margin, lag, shared_bits}; ``lag`` is the stream-cycle
    lag D (in -32767..32767) at which the coupling occurs and ``shared_bits`` the
    (X, W) bits shared there. Empty list = R2 satisfied.
    """
    nx = [M.phase_of(v) for v in sx]
    nw = [M.phase_of(v) for v in sw]
    D = [(nw[i] - nx[i]) % PERIOD for i in range(len(sx))]
    out = []

    def best_lag(a1, b1, a2, b2):
        """Lag maximising the simultaneous sharing of pairs (a1,b1) and (a2,b2)."""
        best = None
        for e in range(-7, 8):
            lag = ((e - (b1 - a1)) * INV8) % PERIOD
            lag = lag - PERIOD if lag > PERIOD // 2 else lag
            s = (shared_bits(a1, b1, lag), shared_bits(a2, b2, lag))
            if min(s) > 0 and (best is None or sum(s) > sum(best[1])):
                best = (lag, s)
        return best

    for i in range(len(sx)):
        for j in range(i, len(sx)):
            if i != j and cdist(D[i] - D[j]) < R2_MARGIN:
                lag, s = best_lag(nx[i], nx[j], nw[i], nw[j])
                out.append({"kind": "direct", "i": i, "j": j, "margin": cdist(D[i] - D[j]),
                            "lag": lag, "shared_bits": list(s)})
            if cdist(D[i] + D[j]) < R2_MARGIN:
                lag, s = best_lag(nx[i], nw[j], nw[i], nx[j])
                out.append({"kind": "swapped", "i": i, "j": j, "margin": cdist(D[i] + D[j]),
                            "lag": lag, "shared_bits": list(s)})
    return out


def lag_metrics(sx: list, sw: list) -> dict:
    """lambda8 (min exact-copy lag), lambda1 (min lag with >= 1 shared bit), min phase separation."""
    n = [M.phase_of(v) for v in list(sx) + list(sw)]
    pos = [stream_pos(v) for v in n]
    pairs = [(a, b) for a in range(len(n)) for b in range(a + 1, len(n))]
    lam8 = min(cdist(pos[b] - pos[a]) for a, b in pairs)
    lam1 = min(cdist((e - (n[b] - n[a])) * INV8) for a, b in pairs for e in range(-7, 8))
    sep = min(cdist(n[b] - n[a]) for a, b in pairs)
    return {"lambda8_min_pairwise_lag_cycles": lam8, "lambda1_min_lag_any_shared_bit_cycles": lam1,
            "min_phase_separation_single_steps": sep}


def structure(sx: list, sw: list) -> dict:
    """Full CALCULATION record of one candidate (seeds, phases, offsets, R1, R2, lags)."""
    nx = [M.phase_of(v) for v in sx]
    nw = [M.phase_of(v) for v in sw]
    off = [(stream_pos(nw[i]) - stream_pos(nx[i])) % PERIOD for i in range(len(sx))]
    r1 = translate_rule_violations(sx, sw)
    r2 = r2_violations(sx, sw)
    return {"seeds_x": [f"0x{v:04X}" for v in sx], "seeds_w": [f"0x{v:04X}" for v in sw],
            "phase_n_x": nx, "phase_n_w": nw,
            "stream_pos_x": [stream_pos(v) for v in nx], "stream_pos_w": [stream_pos(v) for v in nw],
            "pair_offset_cycles": off, "n_distinct_pair_offsets": len(set(off)),
            "R1_translate_rule": {"satisfied": not r1, "violating_lane_pairs": [list(p) for p in r1]},
            "R2_simultaneous_sharing_rule": {"satisfied": not r2, "n_violations": len(r2), "violations": r2},
            **lag_metrics(sx, sw)}


def scan_progression_family() -> dict:
    """Exhaustive scan of alpha = 1..65534 for X_i = S(alpha i), W_i = S(alpha (15-i)).

    Feasible: R1 and R2 hold and no two generators share bits at lag 0
    (phase separation >= 8). Returns the best alpha for the objectives
    (lambda8, lambda1) and (lambda1, lambda8); ties -> smaller alpha.
    Vectorised re-implementation of :func:`lag_metrics` / R2 (checked against
    the scalar functions for the chosen alphas in the unit tests).
    """
    m = np.arange(2 * M.IL, dtype=np.int64)
    iu = np.triu_indices(2 * M.IL, 1)
    ii, jj = np.triu_indices(M.IL, 1)
    e = np.arange(-7, 8, dtype=np.int64)

    def cd(a):
        a = np.mod(a, PERIOD)
        return np.minimum(a, PERIOD - a)

    rows = []
    for alpha in range(1, PERIOD):
        n = (alpha * np.concatenate([m[:M.IL], 2 * M.IL - 1 - m[:M.IL]])) % PERIOD
        d = (n[None, :] - n[:, None])[iu]
        sep = int(cd(d).min())
        D = (n[M.IL:] - n[:M.IL]) % PERIOD
        if sep < 8 or cd(D[ii] - D[jj]).min() < R2_MARGIN or \
                min(cd(D[ii] + D[jj]).min(), cd(2 * D).min()) < R2_MARGIN:
            continue
        lam8 = int(cd(d * INV8).min())
        lam1 = int(cd((e[None, :] - d[:, None]) * INV8).min())
        rows.append((alpha, lam8, lam1))
    best_l8 = min(rows, key=lambda r: (-r[1], -r[2], r[0]))
    best_l1 = min(rows, key=lambda r: (-r[2], -r[1], r[0]))
    return {"n_feasible": len(rows), "best_lambda8_then_lambda1": list(best_l8),
            "best_lambda1_then_lambda8": list(best_l1)}


# ---------------------------------------------------------------------------
# Validation evaluation (SIMULATION)
# ---------------------------------------------------------------------------

def load_validation() -> dict:
    """Validation codes/labels and the trained (selected) hardware parameters; test NOT loaded."""
    sel, allm = A.load_models()
    d = T.load_split()
    val = np.array(d["val_idx"])
    assert len(val) == T.N_VAL == 288
    assert not set(val.tolist()) & set(np.array(sel["test_indices"]).tolist()), "val/test overlap"
    assert set(val.tolist()) <= set(d["train_idx"].tolist())
    hw = A.hw_from_json(allm["models"][sel["variant"]])
    return {"idx": val, "codes": d["codes"][val], "y": d["y"][val], "hw": hw, "variant": sel["variant"],
            "sel": sel}


def evaluate_candidate(v: dict, sx: list, sw: list, offsets: np.ndarray, Ks=SEL_K) -> dict:
    """Deployed-seed and ensemble validation accuracy of one seed set, mode 2 (SIMULATION)."""
    xc, y, hw = v["codes"], v["y"], v["hw"]
    w1, w2 = M.unpack_weight_ram(hw["weight_ram"])
    out = {}
    for K in Ks:
        eng = M.SCEngine(K, SEL_MODE, seeds=(sx, sw))
        r = eng.run(xc, hw["weight_ram"], hw["biases"], hw["s"])
        dep = A.acc_entry(r["result"], y)
        correct = r["result"] == y
        ident = identical_table_pairs(eng)
        del eng
        accs, sq, pr = [], [], []
        for off in offsets:
            ee = M.SCEngine(K, SEL_MODE, start_offset=int(off), seeds=(sx, sw)).run(
                xc, hw["weight_ram"], hw["biases"], hw["s"])
            accs.append(float(np.mean(ee["result"] == y)))
            raw = A.error_arrays(ee, xc, w1, w2, hw["biases"], K, SEL_MODE, None)
            sq.append(float(np.mean(raw["layer1"]["e"] ** 2)))
            pr.append(float(np.mean(raw["layer1"]["vg"])))
        accs = np.array(accs)
        out[K] = {"deployed": dep, "_correct": correct, "ensemble_mean": float(accs.mean()), "ensemble_sd": float(accs.std(ddof=1)),
                  "ensemble_min": float(accs.min()), "ensemble_max": float(accs.max()),
                  "ensemble_n": int(len(accs)), "identical_table_pairs_deployed": ident,
                  "layer1_ensemble_rms_over_eq2": math.sqrt(np.mean(sq)) / math.sqrt(np.mean(pr))}
    dep = [out[K]["deployed"]["acc"] for K in Ks]
    ens = [out[K]["ensemble_mean"] for K in Ks]
    return {"per_K": out, "deployed_mean_K8_10": float(np.mean(dep)), "deployed_worst_K8_10": float(min(dep)),
            "deployed_worst_n_correct": int(min(out[K]["deployed"]["n_correct"] for K in Ks)),
            "ensemble_mean_K8_10": float(np.mean(ens))}


def select(results: dict) -> tuple[str, list]:
    """Protocol: max worst-case deployed accuracy (exact counts); tie -> max ensemble mean."""
    ranking = sorted(results, key=lambda c: (-results[c]["deployed_worst_n_correct"],
                                             -results[c]["ensemble_mean_K8_10"], c))
    return ranking[0], ranking


# ---------------------------------------------------------------------------
# Main + report
# ---------------------------------------------------------------------------

def main() -> int:
    """Run the protocol and write reports/sw/seed_selection_revC.{json,md}."""
    t0 = time.time()
    rev = T.git_rev()
    print(f"# seed_select.py rev={rev} numpy={np.__version__} (SW-03 step 1, VALIDATION ONLY)")
    v = load_validation()
    offsets = A.ensemble_offsets(N_ENS, A.ENSEMBLE_SEED)
    print(f"# validation images: {len(v['idx'])} (val_idx of train.load_split: split seed {T.SPLIT_SEED}, "
          f"val seed {T.VAL_SEED}); test images NOT loaded; variant {v['variant']} s={v['hw']['s']}")
    print(f"# ensemble offsets (default_rng({A.ENSEMBLE_SEED}), {N_ENS}): {[int(o) for o in offsets]}")
    scan = scan_progression_family()
    print(f"# progression-family scan: {scan}")
    assert scan["best_lambda8_then_lambda1"][0] == ALPHA_C3 and scan["best_lambda1_then_lambda8"][0] == ALPHA_C4
    cands = candidates()
    res = {}
    for name, c in cands.items():
        st = structure(c["x"], c["w"])
        print(f"{name}: {c['rule']}\n    R1 {'OK' if st['R1_translate_rule']['satisfied'] else 'VIOLATED'} "
              f"({len(st['R1_translate_rule']['violating_lane_pairs'])} pairs), R2 "
              f"{'OK' if st['R2_simultaneous_sharing_rule']['satisfied'] else 'VIOLATED'} "
              f"({st['R2_simultaneous_sharing_rule']['n_violations']}), lambda8={st['lambda8_min_pairwise_lag_cycles']} "
              f"lambda1={st['lambda1_min_lag_any_shared_bit_cycles']}", flush=True)
        ev = evaluate_candidate(v, c["x"], c["w"], offsets)
        for K in SEL_K:
            e = ev["per_K"][K]
            print(f"    K={K:2d} deployed {e['deployed']['n_correct']}/{e['deployed']['n']} = "
                  f"{100 * e['deployed']['acc']:.2f} %  ensemble {100 * e['ensemble_mean']:.2f} +- "
                  f"{100 * e['ensemble_sd']:.2f} %  ident_pairs={e['identical_table_pairs_deployed']} "
                  f"rms1 ratio={e['layer1_ensemble_rms_over_eq2']:.3f}", flush=True)
        res[name] = {"rule": c["rule"], "structure": st, "validation": ev}
    winner, ranking = select({k: r["validation"] for k, r in res.items()})
    print(f"# ranking (worst-case deployed count, then ensemble mean): {ranking}; SELECTED: {winner}")
    # Information only (not part of the protocol): how decisive is the choice?
    # Paired exact McNemar of the winner vs every other candidate, same images.
    decisiveness = {}
    for name in res:
        if name == winner:
            continue
        decisiveness[name] = {}
        for K in SEL_K:
            pc = paired_cells(res[winner]["validation"]["per_K"][K]["_correct"],
                              res[name]["validation"]["per_K"][K]["_correct"])
            decisiveness[name][K] = {"winner_only_correct": pc["A_only_correct"],
                                     "other_only_correct": pc["B_only_correct"],
                                     "mcnemar_exact_p": mcnemar_exact(pc["A_only_correct"], pc["B_only_correct"])}
            print(f"#   info: {winner} vs {name} K={K}: discordant {pc['A_only_correct']}/{pc['B_only_correct']} "
                  f"McNemar p={decisiveness[name][K]['mcnemar_exact_p']:.3g}")
    for c in res.values():
        for K in SEL_K:
            c["validation"]["per_K"][K].pop("_correct")
    out = {"label": "SIMULATION (Python golden model sctpu.model, bit-exact) + CALCULATION (seed structure)",
           "task": "SW-03 step 1: rev C seed selection on VALIDATION data only (ADR-009 protocol)",
           "command": "cd code/python && ../../.venv/bin/python -m sctpu.seed_select",
           "git_rev": rev, "test_split_used": False,
           "validation_set": {"n": int(len(v["idx"])), "definition":
                              "sklearn load_digits; train_idx, test_idx = train_test_split(arange(1797), "
                              "test_size=360, stratify=y, random_state=0); fit_idx, val_idx = "
                              "train_test_split(train_idx, test_size=288, stratify=y[train_idx], random_state=0); "
                              "validation = val_idx (same subset as the SW-01a s/variant selection)",
                              "load_digits_rows": [int(i) for i in v["idx"]],
                              "class_counts": np.bincount(v["y"], minlength=10).tolist(),
                              "caveat": "the deployed weights were re-trained on all 1437 training images "
                                        "(SW-01a), so these images were seen in training: absolute accuracies "
                                        "are optimistic; the seed comparison is test-independent"},
           "weights": {"variant": v["variant"], "s": v["hw"]["s"], "retrained": False},
           "rng_mode": SEL_MODE, "K_selection": list(SEL_K),
           "ensemble": {"numpy_seed": A.ENSEMBLE_SEED, "size": N_ENS, "offsets": [int(o) for o in offsets]},
           "selection_rule": "highest worst-case deployed validation accuracy over K in {8,9,10} "
                             "(compared as exact correct counts); tie-break: higher mean over K=8,9,10 "
                             "of the 20-offset ensemble mean accuracy",
           "progression_family_scan": scan, "candidates": res, "ranking": ranking, "selected": winner,
           "info_paired_mcnemar_winner_vs_others": decisiveness}
    (T.REPORT_DIR / "seed_selection_revC.json").write_text(json.dumps(out, indent=1) + "\n")
    write_markdown(out)
    print(f"# wrote reports/sw/seed_selection_revC.json/.md ({time.time() - t0:.1f} s)")
    return 0


def write_markdown(r: dict) -> None:
    """Human-readable selection report reports/sw/seed_selection_revC.md."""
    L = ["# Rev C LFSR seed selection on validation data (SW-03, step 1)", "",
         f"Command: `{r['command']}` · git `{r['git_rev']}` · log `logs/sw/seed_selection_revC.log`  ",
         "Accuracies: **SIMULATION** of the bit-exact Python golden model; seed structure: **CALCULATION** "
         "(exhaustive over the 65535-state m-sequence).  ",
         f"**Validation set only — the 360 test images were not used in this step.** n = "
         f"{r['validation_set']['n']} images: {r['validation_set']['definition']}. Class counts "
         f"{r['validation_set']['class_counts']}.  ",
         f"Caveat: {r['validation_set']['caveat']}.  ",
         f"Weights `{r['weights']['variant']}` (s = {r['weights']['s']}), not retrained. RNG_MODE 2. "
         f"Ensemble: {r['ensemble']['size']} analysis-only start offsets, numpy `default_rng("
         f"{r['ensemble']['numpy_seed']})`: {', '.join(map(str, r['ensemble']['offsets']))}.  ",
         f"Selection rule (fixed in advance, ADR-009): {r['selection_rule']}.", "",
         "## 1. Candidates and seed-structure checks", "",
         "| cand. | rule | R1 no translated pair streams | R2 no simultaneous sharing (stricter, info) | "
         "distinct pair offsets | λ8 min pairwise lag [cycles] | λ1 min lag with ≥1 shared bit [cycles] |",
         "|---|---|---|---|---|---|---|"]
    for n, c in r["candidates"].items():
        s = c["structure"]
        r1 = s["R1_translate_rule"]
        r2 = s["R2_simultaneous_sharing_rule"]
        L.append(f"| {n} | {c['rule']} | {'satisfied' if r1['satisfied'] else 'VIOLATED (' + str(len(r1['violating_lane_pairs'])) + ' of 28 lane pairs)'} | "
                 f"{'satisfied' if r2['satisfied'] else 'VIOLATED (' + str(r2['n_violations']) + ')'} | "
                 f"{s['n_distinct_pair_offsets']} of 8 | {s['lambda8_min_pairwise_lag_cycles']} | "
                 f"{s['lambda1_min_lag_any_shared_bit_cycles']} |")
    L += ["", "R2 violations (lag = stream-cycle lag of the coupling; shared bits of the two operand pairs):", ""]
    for n, c in r["candidates"].items():
        vs = c["structure"]["R2_simultaneous_sharing_rule"]["violations"]
        if vs:
            kinds = {}
            for x in vs:
                kinds.setdefault(x["kind"], []).append(f"({x['i']},{x['j']}) lag {x['lag']} bits {x['shared_bits']}")
            L.append(f"- {n}: " + "; ".join(f"{k} ×{len(v)}: " + ", ".join(v[:4]) + (" …" if len(v) > 4 else "")
                                           for k, v in kinds.items()))
    sc = r["progression_family_scan"]
    L += ["", f"C3/C4 family scan (X_i = S(α i), W_i = S(α (15 − i)), α = 1..65534, feasible = R1 ∧ R2 ∧ no "
              f"same-instant sharing): {sc['n_feasible']} feasible α; best (λ8, λ1): α = "
              f"{sc['best_lambda8_then_lambda1'][0]} → ({sc['best_lambda8_then_lambda1'][1]}, "
              f"{sc['best_lambda8_then_lambda1'][2]}); best (λ1, λ8): α = {sc['best_lambda1_then_lambda8'][0]} → "
              f"({sc['best_lambda1_then_lambda8'][2]}, {sc['best_lambda1_then_lambda8'][1]}). C3/C4 were fixed from "
              "this calculation before any accuracy was computed.", "",
          "## 2. Validation accuracy, mode 2 (SIMULATION, n = 288)", "",
          "| cand. | K=8 deployed | K=9 deployed | K=10 deployed | deployed mean | **deployed worst** | "
          "ens. K=8 mean ± sd | ens. K=9 | ens. K=10 | ens. mean K8–10 | identical table pairs K8/9/10 | "
          "layer-1 RMS ens./eq.(2) K8/9/10 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for n, c in r["candidates"].items():
        v = c["validation"]
        pk = {int(k): x for k, x in v["per_K"].items()}
        dep = " | ".join(f"{100 * pk[K]['deployed']['acc']:.2f} ({pk[K]['deployed']['n_correct']}/288)" for K in SEL_K)
        ens = " | ".join(f"{100 * pk[K]['ensemble_mean']:.2f} ± {100 * pk[K]['ensemble_sd']:.2f}" for K in SEL_K)
        L.append(f"| {n} | {dep} | {100 * v['deployed_mean_K8_10']:.2f} | **{100 * v['deployed_worst_K8_10']:.2f}** | "
                 f"{ens} | {100 * v['ensemble_mean_K8_10']:.2f} | "
                 + "/".join(str(pk[K]["identical_table_pairs_deployed"]) for K in SEL_K) + " | "
                 + "/".join(f"{pk[K]['layer1_ensemble_rms_over_eq2']:.2f}" for K in SEL_K) + " |")
    win = r["selected"]
    wv = r["candidates"][win]["validation"]
    wk = min(SEL_K, key=lambda K: wv["per_K"][K]["deployed"]["n_correct"])
    ci = wv["per_K"][wk]["deployed"]["ci95"]
    L += ["", f"Ranking by the protocol: {' > '.join(r['ranking'])}. **Selected: {win}** "
              f"({r['candidates'][win]['rule']}).", "",
          f"How decisive (information only, not part of the protocol): the winner's worst case is "
          f"{wv['deployed_worst_n_correct']}/288 = {100 * wv['deployed_worst_K8_10']:.2f} % "
          f"(95 % Wilson CI {100 * ci[0]:.1f}–{100 * ci[1]:.1f} %; one image = 0.35 pp). Paired exact McNemar "
          f"of {win} vs each other candidate on the same 288 images (discordant {win}-only / other-only, p):", "",
          "| other | K=8 | K=9 | K=10 |", "|---|---|---|---|"]
    for name, d in r["info_paired_mcnemar_winner_vs_others"].items():
        L.append(f"| {name} | " + " | ".join(f"{d[K]['winner_only_correct']}/{d[K]['other_only_correct']}, "
                                           f"p = {d[K]['mcnemar_exact_p']:.3g}" for K in SEL_K) + " |")
    L += ["", "The validation images were part of the final training set, so all candidates are near the "
              "ceiling (97–99 %) and the margins are a few images; among the rule-compliant candidates "
              "(C0, C3, C4) no difference is statistically significant, and the ranking among candidates with "
              "similar ensemble means is dominated by the realisation noise of a single seed set (ensemble "
              "sd 0.4–1.8 pp). The protocol was nevertheless applied as fixed in advance."]
    (T.REPORT_DIR / "seed_selection_revC.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    sys.exit(main())
