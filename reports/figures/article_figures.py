#!/usr/bin/env python3
"""Generate the vector figures of the scientific article and of the
engineering report (tasks DOC-01, DOC-02).

Every plotted value is read from project evidence files (SIMULATION of the
Python golden model ``sctpu.model``):
  * ``reports/sw/accuracy_revC.json``      (task SW-03, spec rev C, current);
  * ``reports/sw/revABC_comparison.json``  (task SW-03, rev A/B/C comparison).
Nothing is typed in by hand: the script only reads, plots and prints the data
it plotted, so the printed table can be compared with the document text.

Outputs (vector PDF, next to this script):
  * ``article_acc_vs_k.pdf``  -- test accuracy versus K = log2(L) for the three
    RNG modes; (a) the deployed (rev C) hardware seeds with 95 % Wilson
    confidence intervals, (b) the mean +/- one standard deviation over the
    analysis-only LFSR start offsets (20 in rev C).  The expected-value
    (K -> infinity) accuracy is drawn as a grey reference band (its own CI).
  * ``article_rms_vs_k.pdf``  -- RMS stochastic error of Dp/L versus K for
    layer 1 and layer 2: ensemble measurement (filled markers), the analytical
    prediction eq. (2) of ``reports/sw/error_model.md`` (lines) and the single
    hardware-seed realisation (open markers).
  * ``article_revBC.pdf``     -- design iteration rev B -> rev C, RNG mode 2:
    (a) deployed-seed accuracy versus K with Wilson CIs for rev B (phase-spaced
    seeds) and rev C, (b) layer-1 ensemble RMS / eq. (2) ratio, annotated with
    the number of identical (tile, lane) count-table pairs of rev B.

History: DOC-01 plotted reports/sw/accuracy.json (rev A, 16 offsets); DOC-02
switched to rev C (accuracy_revC.json, 20 offsets) and added article_revBC.pdf.

Usage (from the repository root):
    .venv/bin/python reports/figures/article_figures.py
"""

import json
import os
import sys

import matplotlib

matplotlib.use("pdf")  # vector output, no display needed
import matplotlib.pyplot as plt  # noqa: E402  (backend must be set first)

# ---------------------------------------------------------------------------
# Paths: resolved relative to this file so the script works from any cwd.
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
EVIDENCE = os.path.join(ROOT, "reports", "sw", "accuracy_revC.json")
EVIDENCE_ABC = os.path.join(ROOT, "reports", "sw", "revABC_comparison.json")

# Label of the deployed seed set in the evidence file (printed in the axes).
SEED_LABEL = "rev C"

# Selected network variant (SW-01a: chosen on the validation split).
VARIANT = "qat_noise"

# Categorical colours: first three slots of the validated reference palette
# (dataviz skill, references/palette.md; these three pass the all-pairs CVD
# check).  Marker shapes give a second, colour-independent encoding so the
# figure stays readable in grey-scale print.
MODE_STYLE = {
    "0": {"name": "mode 0 (shared)", "color": "#2a78d6", "marker": "o"},
    "1": {"name": "mode 1 (rotate)", "color": "#eb6834", "marker": "s"},
    "2": {"name": "mode 2 (independent)", "color": "#1baf7a", "marker": "^"},
}
REF_GREY = "#8a8985"   # recessive reference (EV) colour
TEXT = "#0b0b0b"
GRID = "#d9d8d4"

plt.rcParams.update({
    "font.family": "serif",          # matches the IEEEtran Times body text
    "font.size": 8,
    "axes.labelsize": 8,
    "legend.fontsize": 7,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "lines.linewidth": 1.2,
    "axes.edgecolor": "#52514e",
    "axes.labelcolor": TEXT,
    "xtick.color": "#52514e",
    "ytick.color": "#52514e",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "pdf.fonttype": 42,              # embed TrueType, keeps text selectable
})


def load(path=EVIDENCE):
    """Return the parsed evidence JSON (fails loudly if it is missing)."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def n_offsets(model):
    """Number of ensemble realisations stored in the evidence (16 or 20)."""
    return model["sc_ensemble_accuracy"]["2"]["8"]["n_realisations"]


def style_axes(ax):
    """Recessive horizontal grid behind the data."""
    ax.grid(axis="y", color=GRID, linewidth=0.5)
    ax.set_axisbelow(True)


def fig_accuracy(data, out_path):
    """Accuracy vs K, hardware seeds (a) and seed ensemble (b)."""
    model = data["models"][VARIANT]
    ks = [int(k) for k in data["K_range"]]
    n = data["n_test"]
    ev = model["expected_value_Kinf"]

    fig, axes = plt.subplots(2, 1, figsize=(3.45, 3.9), sharex=True)
    print(f"# accuracy figure: variant={VARIANT}, n_test={n}")
    print(f"# EV K->inf: {100*ev['acc']:.2f} % ({ev['n_correct']}/{ev['n']}), "
          f"CI95 [{100*ev['ci95'][0]:.2f}, {100*ev['ci95'][1]:.2f}]")
    print("# mode K hw_acc% hw_k ci_lo ci_hi ens_mean% ens_sd% n_real")

    # Small horizontal offsets keep the three modes' error bars apart.
    offs = {"0": -0.12, "1": 0.0, "2": 0.12}
    for ax in axes:
        ax.axhspan(100 * ev["ci95"][0], 100 * ev["ci95"][1],
                   color=REF_GREY, alpha=0.18, linewidth=0)
        ax.axhline(100 * ev["acc"], color=REF_GREY, linewidth=1.0,
                   linestyle="--")
        style_axes(ax)

    for mode, st in MODE_STYLE.items():
        hw = model["sc"][mode]
        ens = model["sc_ensemble_accuracy"][mode]
        x = [k + offs[mode] for k in ks]
        acc = [100 * hw[str(k)]["acc"] for k in ks]
        lo = [100 * (hw[str(k)]["acc"] - hw[str(k)]["ci95"][0]) for k in ks]
        hi = [100 * (hw[str(k)]["ci95"][1] - hw[str(k)]["acc"]) for k in ks]
        axes[0].errorbar(x, acc, yerr=[lo, hi], color=st["color"],
                         marker=st["marker"], markersize=4, capsize=1.5,
                         elinewidth=0.8, label=st["name"])
        mean = [100 * ens[str(k)]["mean"] for k in ks]
        sd = [100 * ens[str(k)]["std"] for k in ks]
        axes[1].errorbar(x, mean, yerr=sd, color=st["color"],
                         marker=st["marker"], markersize=4, capsize=1.5,
                         elinewidth=0.8, label=st["name"])
        for k in ks:
            h = hw[str(k)]
            e = ens[str(k)]
            print(f"{mode} {k:2d} {100*h['acc']:5.1f} {h['n_correct']:3d} "
                  f"{100*h['ci95'][0]:5.1f} {100*h['ci95'][1]:5.1f} "
                  f"{100*e['mean']:5.1f} {100*e['std']:4.1f} "
                  f"{e['n_realisations']}")

    nr = n_offsets(model)
    axes[0].set_ylabel(f"accuracy, {SEED_LABEL} seeds (%)")
    axes[1].set_ylabel(f"accuracy, {nr}-offset mean (%)")
    axes[1].set_xlabel(r"$K = \log_2 L$ (stream length $L = 2^K$)")
    axes[1].set_xticks(ks)
    for ax in axes:
        ax.set_ylim(20, 100)
    axes[0].text(4.0, 23, "(a) fixed hardware seeds, 95 % Wilson CI",
                 fontsize=7, color=TEXT)
    axes[1].text(4.0, 23, f"(b) mean $\\pm$ 1 s.d. over {nr} LFSR offsets",
                 fontsize=7, color=TEXT)
    for ax in axes:
        ax.text(3.85, 100 * ev["acc"] + 0.9,
                r"EV ($K\to\infty$) with 95 % CI", fontsize=6.5,
                color="#52514e", ha="left", va="bottom")
    # Legend above panel (a), outside the data area (no overlap with marks).
    axes[0].legend(loc="lower center", frameon=False, ncol=3,
                   bbox_to_anchor=(0.5, 1.0), fontsize=6.5,
                   columnspacing=0.8, handletextpad=0.3)
    fig.tight_layout(h_pad=0.6)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")


def fig_rms(data, out_path):
    """RMS error of Dp/L vs K: ensemble, prediction eq. (2), hardware seeds."""
    study = data["error_study"]["per_mode_K"]
    ks = [int(k) for k in data["K_range"]]
    layers = [("layer1", "layer 1 ($N_{in}=64$)"),
              ("layer2_real", "layer 2 ($N_{in}=16$, lanes 0..9)")]
    fig, axes = plt.subplots(1, 2, figsize=(3.45, 2.2), sharey=True)
    print("# rms figure: layer mode K ens_meas ens_pred_eq2 ratio hw_meas")
    for ax, (key, title) in zip(axes, layers):
        style_axes(ax)
        for mode, st in MODE_STYLE.items():
            rows = [study[mode][str(k)][key] for k in ks]
            ens = [r["ensemble_rms_measured"] for r in rows]
            pred = [r["ensemble_rms_predicted_eq2"] for r in rows]
            hw = [r["rms_measured"] for r in rows]
            ax.plot(ks, pred, color=st["color"], linewidth=1.0)
            ax.plot(ks, ens, color=st["color"], marker=st["marker"],
                    markersize=3.5, linestyle="none", label=st["name"])
            ax.plot(ks, hw, color=st["color"], marker=st["marker"],
                    markersize=3.5, linestyle="none", markerfacecolor="white",
                    markeredgewidth=0.7)
            for k, r in zip(ks, rows):
                print(f"{key} {mode} {k:2d} {r['ensemble_rms_measured']:.3f} "
                      f"{r['ensemble_rms_predicted_eq2']:.3f} "
                      f"{r['ensemble_ratio']:.2f} {r['rms_measured']:.3f}")
        ax.set_yscale("log")
        ax.set_xticks(ks)
        ax.set_title(title, fontsize=7)
        ax.set_xlabel(r"$K$")
    axes[0].set_ylabel(r"RMS error of $D'/L$ (bipolar units)")
    # Legend: modes (colour+shape) and the three encodings (fill / line).
    h_mode, l_mode = axes[0].get_legend_handles_labels()
    enc = [plt.Line2D([], [], color="#52514e", linewidth=1.0),
           plt.Line2D([], [], color="#52514e", marker="o", linestyle="none",
                      markersize=3.5),
           plt.Line2D([], [], color="#52514e", marker="o", linestyle="none",
                      markersize=3.5, markerfacecolor="white")]
    nr = n_offsets(data["models"][VARIANT])
    l_enc = ["eq. (2)", f"{nr}-offset ens.", f"{SEED_LABEL} seeds"]
    fig.legend(h_mode + enc, l_mode + l_enc, loc="lower center", ncol=2,
               frameon=False, fontsize=6.5, bbox_to_anchor=(0.53, -0.2),
               columnspacing=0.8, handletextpad=0.3)
    fig.tight_layout(w_pad=0.4)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")


# Colours of the two seed revisions in the design-iteration figure: rev B is
# the negative result (warm), rev C the adopted set (mode-2 green as above).
REV_STYLE = {
    "B": {"name": "rev B (phase-spaced, violates R1)", "color": "#eb6834",
          "marker": "s"},
    "C": {"name": "rev C (= rev A mode-2 seeds)", "color": "#1baf7a",
          "marker": "^"},
}


def fig_rev_bc(abc, out_path):
    """Design iteration rev B -> rev C for RNG mode 2 (deployed seeds).

    (a) test accuracy of the deployed seeds versus K with 95 % Wilson CIs and
        the EV reference; (b) layer-1 RMS error, ensemble / eq. (2), with the
        number of identical (tile, lane) count-table pairs of rev B printed
        next to each rev B point (rev C has 0 at every K).
    """
    # K = 6..10: rev B's translated pair streams produce identical count
    # tables from K = 6 on; K = 4, 5 (accuracy < 80 %) are in Fig. acc.
    ks = [k for k in sorted(int(k) for k in abc["per_rev"]["C"]["2"].keys())
          if k >= 6]
    ev = 100 * abc["ev_Kinf_acc"]
    fig, axes = plt.subplots(1, 2, figsize=(3.45, 1.9))
    print("# rev B/C figure (mode 2): rev K acc% k ci_lo ci_hi "
          "identical_pairs rms_ratio")
    offs = {"B": -0.08, "C": 0.08}
    style_axes(axes[0])
    style_axes(axes[1])
    axes[0].axhline(ev, color=REF_GREY, linewidth=1.0, linestyle="--")
    axes[1].axhline(1.0, color=REF_GREY, linewidth=1.0, linestyle="--")
    for rev, st in REV_STYLE.items():
        rows = [abc["per_rev"][rev]["2"][str(k)] for k in ks]
        acc = [100 * r["deployed"]["acc"] for r in rows]
        lo = [100 * (r["deployed"]["acc"] - r["deployed"]["ci95"][0])
              for r in rows]
        hi = [100 * (r["deployed"]["ci95"][1] - r["deployed"]["acc"])
              for r in rows]
        x = [k + offs[rev] for k in ks]
        axes[0].errorbar(x, acc, yerr=[lo, hi], color=st["color"],
                         marker=st["marker"], markersize=3.5, capsize=1.5,
                         elinewidth=0.8, label=st["name"])
        ratio = [r["layer1_rms_ensemble_over_eq2"] for r in rows]
        axes[1].plot(ks, ratio, color=st["color"], marker=st["marker"],
                     markersize=3.5, linewidth=1.0)
        for k, r in zip(ks, rows):
            d = r["deployed"]
            print(f"{rev} {k:2d} {100*d['acc']:5.1f} {d['n_correct']:3d} "
                  f"{100*d['ci95'][0]:5.1f} {100*d['ci95'][1]:5.1f} "
                  f"{r['identical_table_pairs']} "
                  f"{r['layer1_rms_ensemble_over_eq2']:.2f}")
            if rev == "B" and r["identical_table_pairs"]:
                axes[1].annotate(str(r["identical_table_pairs"]),
                                 (k, r["layer1_rms_ensemble_over_eq2"]),
                                 textcoords="offset points", xytext=(0, 5),
                                 ha="center", fontsize=5.5, color=st["color"])
    axes[0].set_ylim(80, 98)
    axes[1].set_ylim(0.8, 1.7)
    axes[1].set_xlim(5.6, 10.4)
    axes[0].set_xticks(ks)
    axes[1].set_xticks(ks)
    axes[0].set_xlabel(r"$K$")
    axes[1].set_xlabel(r"$K$")
    axes[0].set_ylabel("accuracy, mode 2 (%)")
    axes[1].set_ylabel("L1 RMS / eq. (2)")
    axes[0].set_title("(a) deployed seeds, 95 % CI", fontsize=7)
    axes[1].set_title("(b) ensemble error ratio", fontsize=7)
    axes[0].text(ks[0] - 0.2, ev + 0.8, "EV", fontsize=6, color="#52514e",
                 va="bottom")
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center",
               ncol=1, frameon=False, fontsize=6.5,
               bbox_to_anchor=(0.5, -0.17), handletextpad=0.3)
    fig.tight_layout(w_pad=1.2)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {out_path}")


def main():
    data = load()
    print(f"# evidence: {os.path.relpath(EVIDENCE, ROOT)} "
          f"(git_rev field: {data.get('git_rev')}, label: {data.get('label')})")
    fig_accuracy(data, os.path.join(HERE, "article_acc_vs_k.pdf"))
    fig_rms(data, os.path.join(HERE, "article_rms_vs_k.pdf"))
    abc = load(EVIDENCE_ABC)
    print(f"# evidence: {os.path.relpath(EVIDENCE_ABC, ROOT)} "
          f"(git_rev field: {abc.get('git_rev')}, label: {abc.get('label')})")
    fig_rev_bc(abc, os.path.join(HERE, "article_revBC.pdf"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
