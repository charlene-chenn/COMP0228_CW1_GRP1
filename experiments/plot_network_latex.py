"""
The CNN bit decoder drawn with LaTeX/TikZ (PlotNeuralNet layers), the LaTeX version of
experiments/plot_network_diagram.py.

    python3 -m experiments.plot_network_latex

1. Draws the input sheet, figures/network/latex/envelope_input.png: the network's real
   input envelope (codes/cnn_decoder.envelope_steps) for 5 bits of a wood recording,
   centred on a 0 sent after a 1.
2. Compiles figures/network/latex/cnn_architecture.tex with tectonic
   (brew install tectonic) into figures/network/cnn_architecture_latex.pdf.
3. Converts that to figures/network/cnn_architecture_latex.png (macOS Quick Look).
"""
import shutil
import subprocess
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from codes.cnn_decoder import CONTEXT, STEPS_PER_BIT, envelope_steps, load_recording

ROOT = Path(__file__).resolve().parent.parent
LATEX = ROOT / "figures" / "network" / "latex"
OUT = ROOT / "figures" / "network"
RECORDING = ROOT / "experiments/results/wood_15cm_none_S150_W50_Pprbs5_run1/raw/codes_0_conv75.npz"
ENV = "#2a78d6"


def pick_bit(sent) -> int:
    """First bit that is a 0 sent after a 1, with 2 bits of context either side."""
    for i in range(CONTEXT + 1, len(sent) - CONTEXT):
        if sent[i - 1] == 1 and sent[i] == 0 and sent[i - 2] == 0:
            return i
    raise ValueError("no 0 after a 1 found")


def envelope_image(path: Path) -> None:
    rec = load_recording(str(RECORDING))
    env = envelope_steps(rec)
    i = pick_bit(rec.sent)
    window = env[i - CONTEXT:i + CONTEXT + 1].ravel()
    bits = rec.sent[i - CONTEXT:i + CONTEXT + 1]

    n = len(window)
    fig, ax = plt.subplots(figsize=(9.6 / 2.54 * 2, 4 / 2.54 * 2))
    fig.subplots_adjust(0, 0, 1, 1)
    ax.axvspan(CONTEXT * STEPS_PER_BIT, (CONTEXT + 1) * STEPS_PER_BIT, color="#cfe0f6")
    for k in range(1, 2 * CONTEXT + 1):
        ax.axvline(k * STEPS_PER_BIT, color="#9aa3ad", lw=1)
    x = np.arange(n + 1)
    y = np.append(window, window[-1])
    ax.fill_between(x, 0, y, step="post", color=ENV, alpha=0.25, lw=0)
    ax.step(x, y, where="post", color=ENV, lw=2.4)
    top = max(1.25, float(window.max()) * 1.25)
    for k, b in enumerate(bits):
        ax.text((k + 0.5) * STEPS_PER_BIT, top * 0.9, f"sent {b}", ha="center", va="center",
                fontsize=22, weight="bold" if k == CONTEXT else "normal",
                color="#000" if k == CONTEXT else "#555")
    ax.set_xlim(0, n)
    ax.set_ylim(-0.04 * top, top)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color("#1a1a1a")
        s.set_linewidth(2)
    fig.savefig(path, dpi=150, facecolor="#f7f9fc")
    plt.close(fig)
    print(f"{path.relative_to(ROOT)}  (bits {i - CONTEXT}-{i + CONTEXT}: {''.join(map(str, bits))})")


def main():
    envelope_image(LATEX / "envelope_input.png")
    tectonic = shutil.which("tectonic")
    if tectonic is None:
        raise SystemExit("tectonic not found: brew install tectonic")
    subprocess.run([tectonic, "cnn_architecture.tex"], cwd=LATEX, check=True)
    pdf = OUT / "cnn_architecture_latex.pdf"
    shutil.move(LATEX / "cnn_architecture.pdf", pdf)
    png = OUT / "cnn_architecture_latex.png"
    # Quick Look renders the PDF as vectors at the requested size (sips would rasterise at 72 dpi).
    subprocess.run(["qlmanage", "-t", "-s", "3000", "-o", str(OUT), str(pdf)], check=True, capture_output=True)
    shutil.move(OUT / (pdf.name + ".png"), png)
    print(pdf.relative_to(ROOT))
    print(png.relative_to(ROOT))


if __name__ == "__main__":
    main()
