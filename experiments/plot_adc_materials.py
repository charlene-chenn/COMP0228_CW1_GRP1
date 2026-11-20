"""
Raw ADC signal for the same bits of the uncoded string on wood, acrylic and PCB,
stacked vertically:
    python3 -m experiments.plot_adc_materials
"""
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from experiments.scope import SENT_0, SENT_1, INK, INK_SECONDARY, AXIS

RESULTS = Path(__file__).parent / "results"
OUT = Path(__file__).parent.parent / "figures" / "adc" / "adc_materials"
CASES = [
    ("Wood", "wood_15cm_none_S150_W50_Pprbs5_run1"),
    ("Acrylic", "acrylic_15cm_none_S150_W50_Pprbs5_run1"),
    ("PCB", "pcb_15cm_none_S150_W50_Pprbs5_run2"),
]
FIRST_BIT, LAST_BIT = 4, 11     # Sent 1 0 0 1 1 0 1 0: three 0s straight after a 1
ADC_MAX = 65535


def main():
    plt.rcParams.update({"font.family": "serif", "font.serif": ["cmr10"], "mathtext.fontset": "cm",
                         "axes.formatter.use_mathtext": True, "font.size": 9, "axes.edgecolor": AXIS,
                         "xtick.color": INK_SECONDARY, "ytick.color": INK_SECONDARY})
    fig, axes = plt.subplots(len(CASES), 1, figsize=(7.16, 3.6), sharex=True, sharey=True)

    for ax, (name, case) in zip(axes, CASES):
        d = np.load(RESULTS / case / "raw" / "codes_0_none.npz")
        rate, starts = int(d["sample_rate"]), d["bit_start"]
        settle, window = int(d["settle_ms"]), int(d["window_ms"])
        origin = starts[FIRST_BIT]
        for b in range(FIRST_BIT, LAST_BIT + 1):
            seg = d["samples"][starts[b]:starts[b + 1] + 1].astype(float)
            t = (np.arange(starts[b], starts[b] + len(seg)) - origin) / rate * 1000
            ax.plot(t, seg / 1000, color=SENT_1 if d["sent"][b] else SENT_0, linewidth=0.5)
            # Measuring window and read errors
            t0 = (starts[b] - origin) / rate * 1000 + settle
            ax.plot([t0, t0 + window], [ADC_MAX * 1.06 / 1000] * 2,
                    color=INK_SECONDARY, linewidth=2.5, alpha=0.45, solid_capstyle="butt")
            if d["sent"][b] != d["received"][b]:
                ax.plot(t0 + window / 2, ADC_MAX * 1.06 / 1000, marker="x", color=INK,
                        markersize=5, markeredgewidth=1.2)
        ax.set_title(name, loc="left", fontsize=9, pad=2)
        ax.set_ylim(0, ADC_MAX * 1.12 / 1000)
        ax.set_yticks([0, 20, 40, 60])
        ax.spines[["top", "right"]].set_visible(False)
        ax.margins(x=0)

    axes[1].set_ylabel(r"ADC counts ($\times 10^3$)")
    axes[-1].set_xlabel("Time (ms)")
    handles = [plt.Line2D([], [], color=SENT_1, lw=1, label="Sending 1"),
               plt.Line2D([], [], color=SENT_0, lw=1, label="Sending 0"),
               plt.Line2D([], [], color=INK_SECONDARY, lw=2.5, alpha=0.45, label="Measuring window"),
               plt.Line2D([], [], color=INK, marker="x", ls="", label="Read wrongly")]
    fig.legend(handles=handles, loc="upper center", ncol=4, frameon=False, fontsize=8,
               bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 0.95), h_pad=0.4)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT.with_suffix(".pdf"))
    fig.savefig(OUT.with_suffix(".png"), dpi=300)
    print(OUT.with_suffix(".pdf"))


if __name__ == "__main__":
    main()
