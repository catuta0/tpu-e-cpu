#!/usr/bin/env python3
"""Smoke-test figure generator (task ST-DOC-01).

Plots y = x^2 for integer-spaced x in [0, 10] and saves it as a vector PDF
(reports/figures/smoke_plot.pdf) for inclusion in the IEEEtran smoke paper.
The data are purely synthetic (CALCULATION: y = x^2); they are not project
results.

Run with the project virtual environment:
    /home/user/tpu-e-cpu/.venv/bin/python reports/figures/smoke_plot.py
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # Headless backend: no display is available.
import matplotlib.pyplot as plt  # noqa: E402  (import after backend selection)
import numpy as np  # noqa: E402

# Output file lives next to this script so the figure and its generator stay together.
OUT = Path(__file__).resolve().parent / "smoke_plot.pdf"


def main() -> None:
    """Generate and save the y = x^2 figure."""
    # Dense sample of x in [0, 10] for a smooth curve, plus integer markers.
    x = np.linspace(0.0, 10.0, 201)
    xi = np.arange(0, 11)

    # Single-column IEEE figure width is about 3.5 in.
    fig, ax = plt.subplots(figsize=(3.4, 2.2))
    ax.plot(x, x**2, color="tab:blue", linewidth=1.2, label=r"$y = x^2$")
    ax.plot(xi, xi**2, "o", color="tab:blue", markersize=3)
    ax.set_xlabel(r"$x$")
    ax.set_ylabel(r"$y$")
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 100)
    ax.grid(True, linewidth=0.3, alpha=0.6)
    ax.legend(loc="upper left", frameon=False)

    # Vector PDF output, tight bounding box as required by the latex-flow skill.
    fig.savefig(OUT, format="pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
