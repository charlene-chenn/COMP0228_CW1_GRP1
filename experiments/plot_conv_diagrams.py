"""
Two simple explainer graphics for the rate-1/2 (7,5) convolutional code in
codes/convolutional.py: the encoder, and the Viterbi decoder on a trellis.

    python3 -m experiments.plot_conv_diagrams

Writes PNGs to figures/convolutional/.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch

from codes.convolutional import conv_encode, decode_viterbi

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "figures" / "convolutional"

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
FAINT = "#d6d4cc"
BOX = "#f1efe8"
G7 = "#2a78d6"     # generator 7 / out0
G5 = "#1f9e74"     # generator 5 / out1
ERR = "#d6342b"
PATH = "#eb6834"

MESSAGE = [1, 0, 1, 1]
plt.rcParams.update({"font.size": 12, "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE})


def arrow(ax, a, b, color=INK_2, lw=1.6, rad=0.0):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=14, lw=lw, color=color,
                                 connectionstyle=f"arc3,rad={rad}", shrinkA=0, shrinkB=0))


def line(ax, pts, color=INK_2, lw=1.6):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, lw=lw, solid_capstyle="round")


def cell(ax, x, y, label, sub, w=1.3, h=1.0):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=BOX, ec=INK_2, lw=1.4))
    ax.text(x, y + 0.08, label, ha="center", va="center", fontsize=17, fontweight="bold", color=INK)
    ax.text(x, y - h / 2 - 0.28, sub, ha="center", va="top", fontsize=10, color=MUTED)


def xor(ax, x, y, color):
    ax.add_patch(Circle((x, y), 0.36, fc=SURFACE, ec=color, lw=2))
    ax.text(x, y - 0.02, "+", ha="center", va="center", fontsize=20, color=color, fontweight="bold")


def encoder_figure():
    fig, ax = plt.subplots(figsize=(12, 6.6))
    ax.set_xlim(0, 15)
    ax.set_ylim(-2.1, 7.3)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.text(0.03, 0.95, "Convolutional encoder  ·  rate 1/2, generators (7, 5)", fontsize=17,
             fontweight="bold", color=INK)
    fig.text(0.03, 0.905, "Every input bit produces two output bits, each mixing it with the two bits before it",
             fontsize=12, color=INK_2)

    yr = 3.2                        # register row
    xb, x1, x2 = 4.0, 6.2, 8.4      # b, s1, s2
    yt, yb = 5.5, 0.9               # XOR rows
    xx = 10.6                       # XOR column

    # input
    ax.text(0.5, yr, "message\nbits in", ha="center", va="center", fontsize=11, color=INK_2)
    arrow(ax, (1.4, yr), (xb - 0.65, yr))
    cell(ax, xb, yr, "b", "current bit")
    cell(ax, x1, yr, "s1", "previous bit")
    cell(ax, x2, yr, "s2", "2 bits ago")
    arrow(ax, (xb + 0.65, yr), (x1 - 0.65, yr), color=MUTED, lw=1.2)
    arrow(ax, (x1 + 0.65, yr), (x2 - 0.65, yr), color=MUTED, lw=1.2)
    ax.text((x1 + x2) / 2 - 1.1, yr + 0.85, "shift right each step", ha="center", fontsize=10, color=MUTED,
            style="italic")

    # generator 7 = 111: taps b, s1, s2
    xor(ax, xx, yt, G7)
    for x in (xb, x1, x2):
        line(ax, [(x, yr + 0.5), (x, yt)], G7)
    line(ax, [(xb, yt), (xx - 0.36, yt)], G7)
    for x in (xb, x1, x2):
        ax.plot(x, yt, "o", ms=6, color=G7)
    ax.text(xx, yt + 0.6, "generator 7 = 111", ha="center", fontsize=11, color=G7, fontweight="bold")
    ax.text(xx + 1.0, yt, "out₀ = b ⊕ s1 ⊕ s2", ha="left", va="center", fontsize=12, color=G7)

    # generator 5 = 101: taps b, s2
    xor(ax, xx, yb, G5)
    for x in (xb, x2):
        line(ax, [(x, yr - 0.5), (x, yb)], G5)
    line(ax, [(xb, yb), (xx - 0.36, yb)], G5)
    for x in (xb, x2):
        ax.plot(x, yb, "o", ms=6, color=G5)
    ax.text(xx, yb - 0.75, "generator 5 = 101", ha="center", fontsize=11, color=G5, fontweight="bold")
    ax.text(xx + 1.0, yb, "out₁ = b ⊕ s2", ha="left", va="center", fontsize=12, color=G5)

    # example
    coded = conv_encode(MESSAGE)
    ins = MESSAGE + [0, 0]
    y0 = -1.0
    ax.text(0.5, y0 + 0.45, "Example", fontsize=12, fontweight="bold", color=INK, ha="left")
    ax.text(2.6, y0 + 0.45, "in", fontsize=11, color=MUTED, ha="right")
    ax.text(2.6, y0 - 0.25, "out", fontsize=11, color=MUTED, ha="right")
    for i, b in enumerate(ins):
        x = 3.4 + i * 1.45
        tail = i >= len(MESSAGE)
        ax.text(x, y0 + 0.45, str(b), ha="center", fontsize=14, fontweight="bold",
                color=MUTED if tail else INK)
        ax.text(x - 0.17, y0 - 0.25, str(coded[2 * i]), ha="center", fontsize=14, color=G7, fontweight="bold")
        ax.text(x + 0.17, y0 - 0.25, str(coded[2 * i + 1]), ha="center", fontsize=14, color=G5, fontweight="bold")
    ax.text(3.4 + 4.5 * 1.45, y0 - 0.85, "tail: flushes register to 00", ha="center", fontsize=9, color=MUTED)
    ax.text(3.4 + 6 * 1.45 - 0.2, y0 + 0.1, "4 bits in → 12 bits out", ha="left", va="center", fontsize=11,
            color=INK_2)

    path = OUT / "conv_encoder.png"
    fig.savefig(path, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path


def viterbi_trace(rx):
    """Same as decode_viterbi, but returns metrics and the survivor path for drawing."""
    inf = float("inf")
    metrics = [0, inf, inf, inf]
    all_metrics, history = [metrics], []
    for t in range(len(rx) // 2):
        r0, r1 = rx[2 * t], rx[2 * t + 1]
        new, prev = [inf] * 4, [None] * 4
        for s in range(4):
            if metrics[s] == inf:
                continue
            s1, s2 = s >> 1, s & 1
            for b in (0, 1):
                m = metrics[s] + ((b ^ s1 ^ s2) != r0) + ((b ^ s2) != r1)
                ns = (b << 1) | s1
                if m < new[ns]:
                    new[ns], prev[ns] = m, s
        metrics = new
        all_metrics.append(metrics)
        history.append(prev)
    path = [0]
    for prev in reversed(history):
        path.append(prev[path[-1]])
    return all_metrics, path[::-1]


def decoder_figure():
    coded = conv_encode(MESSAGE)
    rx = list(coded)
    flip = 2                        # flip out0 of step 1
    rx[flip] ^= 1
    decoded = decode_viterbi(rx)
    assert decoded == MESSAGE
    metrics, path = viterbi_trace(rx)
    steps = len(rx) // 2

    fig, ax = plt.subplots(figsize=(12, 7.2))
    ax.set_xlim(-1.6, steps + 0.7)
    ax.set_ylim(-1.75, 5.2)
    ax.axis("off")
    fig.text(0.03, 0.95, "Viterbi decoder  ·  finding the closest valid path", fontsize=17,
             fontweight="bold", color=INK)
    fig.text(0.03, 0.905, "Each column is one step; each row is what the encoder's register (s1 s2) could hold",
             fontsize=12, color=INK_2)

    ys = {0: 3, 1: 2, 2: 1, 3: 0}   # state -> row (00 at top)
    names = ["00", "01", "10", "11"]
    for s, y in ys.items():
        ax.text(-0.45, y, names[s], ha="right", va="center", fontsize=13, fontweight="bold", color=INK_2)
    ax.text(-0.45, 3.65, "state", ha="right", fontsize=10, color=MUTED)

    # branches the encoder could really take: start at 00, tail inputs are 0, end at 00
    def inputs(t):
        return (0,) if t >= steps - 2 else (0, 1)
    fwd = [{0}]
    for t in range(steps):
        fwd.append({(b << 1) | (s >> 1) for s in fwd[-1] for b in inputs(t)})
    bwd = [set() for _ in range(steps + 1)]
    bwd[steps] = {0}
    for t in range(steps - 1, -1, -1):
        bwd[t] = {s for s in range(4) for b in inputs(t) if ((b << 1) | (s >> 1)) in bwd[t + 1]}
    live = [fwd[t] & bwd[t] for t in range(steps + 1)]

    # all valid branches, faint (solid = input 0, dashed = input 1)
    for t in range(steps):
        for s in live[t]:
            for b in inputs(t):
                ns = (b << 1) | (s >> 1)
                if ns not in live[t + 1]:
                    continue
                ax.plot([t, t + 1], [ys[s], ys[ns]], color=FAINT, lw=1.3, ls="-" if b == 0 else (0, (4, 3)),
                        zorder=1)

    # survivor path
    for t in range(steps):
        a, b = path[t], path[t + 1]
        ax.plot([t, t + 1], [ys[a], ys[b]], color=PATH, lw=4, zorder=2, solid_capstyle="round")

    # nodes
    for t in range(steps + 1):
        for s in live[t]:
            if s != path[t]:
                ax.plot(t, ys[s], "o", ms=9, color=FAINT, zorder=3)
        ax.plot(t, ys[path[t]], "o", ms=24, color=PATH, zorder=3)
        ax.text(t, ys[path[t]], f"{metrics[t][path[t]]:g}", ha="center", va="center", fontsize=12,
                color="white", fontweight="bold", zorder=4)

    # received bits on top
    ax.text(-0.45, 4.45, "received", ha="right", va="center", fontsize=11, color=MUTED)
    for t in range(steps):
        x = t + 0.5
        for k in range(2):
            bit = rx[2 * t + k]
            bad = (2 * t + k) == flip
            ax.text(x - 0.12 + 0.24 * k, 4.45, str(bit), ha="center", va="center", fontsize=15,
                    fontweight="bold", color=ERR if bad else INK)
        if t == flip // 2:
            ax.text(x, 4.95, "1 bit flipped", ha="center", fontsize=10, color=ERR)

    # decoded bits below
    ax.text(-0.45, -0.8, "decoded", ha="right", va="center", fontsize=11, color=MUTED)
    for t in range(steps):
        bit = path[t + 1] >> 1
        tail = t >= len(MESSAGE)
        ax.text(t + 0.5, -0.8, str(bit), ha="center", va="center", fontsize=15, fontweight="bold",
                color=MUTED if tail else PATH)
    ax.text(steps - 1, -1.2, "tail (dropped)", ha="center", fontsize=9, color=MUTED)

    # key
    fig.text(0.03, 0.035,
             "①  Score every branch: how many of its 2 expected bits differ from the 2 received.     "
             "②  Where two paths meet, keep the lower total.     "
             "③  Trace back from state 00.",
             fontsize=11, color=INK_2)
    fig.text(0.97, 0.085, "number in orange circle = errors so far on the best path   ·   ─ input 0   - - input 1",
             fontsize=9.5, color=MUTED, ha="right")

    path_ = OUT / "conv_decoder.png"
    fig.savefig(path_, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return path_


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for p in (encoder_figure(), decoder_figure()):
        print(p.relative_to(ROOT))
