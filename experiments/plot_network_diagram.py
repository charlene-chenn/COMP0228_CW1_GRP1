"""
Diagram of the CNN bit decoder in codes/cnn_decoder.py, drawn as 3D blocks
(in the style of PlotNeuralNet): input -> layers -> output.

    python3 -m experiments.plot_network_diagram

Writes figures/network/cnn_architecture.png.

Each block is one tensor. Its thickness (left to right) is the number of channels,
and the receding axis is time (80 envelope steps = 5 bits x 16 steps).
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, Polygon

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "figures" / "network"

SURFACE = "#ffffff"
EDGE = "#1a1a1a"
ARROW = "#3d7373"
INPUT = ("#dbe8f8", "#b9d2f0", "#97bce8")      # front, top, side
CONV = ("#ffe8bf", "#fff1d6", "#f5d9a8")
RELU = ("#fdc27a", "#fed59f", "#f0ae5c")
DENSE = ("#e8d9f5", "#f1e8fa", "#d6c1ec")
OUT_BIT = ("#e2603d", "#ec8a6e", "#c94e2e")
OUT_TR = ("#c3d8ec", "#d8e6f3", "#a9c6e2")
ENV = "#2a78d6"
plt.rcParams.update({"font.family": "serif", "mathtext.fontset": "cm", "font.size": 12,
                     "figure.facecolor": SURFACE, "savefig.facecolor": SURFACE})

H = 2.6                    # height of a block on the 80-step layers
DEPTH_PER_STEP = 0.03      # receding length per time step
YC = 0.0                   # vertical centre of the network


def depth_vec(d):
    return d * 0.72, d * 0.72


def cuboid(ax, x, w, h, d, colors, z=2, dashed=True, yc=None):
    """Front face at x..x+w, centred on yc (default YC), receding by depth d."""
    yc = YC if yc is None else yc
    ox, oy = depth_vec(d)
    yb, yt = yc - h / 2, yc + h / 2
    front, top, side = colors
    kw = dict(ec=EDGE, lw=0.8, zorder=z)
    ax.add_patch(Polygon([(x, yb), (x + w, yb), (x + w, yt), (x, yt)], fc=front, **kw))
    ax.add_patch(Polygon([(x, yt), (x + w, yt), (x + w + ox, yt + oy), (x + ox, yt + oy)], fc=top, **kw))
    ax.add_patch(Polygon([(x + w, yb), (x + w + ox, yb + oy), (x + w + ox, yt + oy), (x + w, yt)], fc=side, **kw))
    if dashed:   # hidden back edges
        for a, b in [((x, yb), (x + ox, yb + oy)), ((x + ox, yb + oy), (x + w + ox, yb + oy)),
                     ((x + ox, yb + oy), (x + ox, yt + oy))]:
            ax.plot(*zip(a, b), color=EDGE, lw=0.6, ls=(0, (3, 3)), alpha=0.45, zorder=z + 0.1)
    return x + w


def input_panel(ax, x, d):
    """The envelope of 5 bits drawn on a slanted sheet, like the image in a CNN figure."""
    ox, oy = depth_vec(d)
    yb, yt = YC - H / 2, YC + H / 2
    ax.add_patch(Polygon([(x, yb), (x + ox, yb + oy), (x + ox, yt + oy), (x, yt)],
                         fc="#f7f9fc", ec=EDGE, lw=0.8, zorder=2))
    shapes = ["one", "tail", "one", "one", "zero"]          # toy string; the middle bit is decided
    for k in range(5):
        t0, t1 = k / 5, (k + 1) / 5
        if k == 2:
            ax.add_patch(Polygon([(x + t0 * ox, yb + t0 * oy), (x + t1 * ox, yb + t1 * oy),
                                  (x + t1 * ox, yt + t1 * oy), (x + t0 * ox, yt + t0 * oy)],
                                 fc="#cfe0f6", ec="none", zorder=2.1))
        if k:
            ax.plot([x + t0 * ox] * 2, [yb + t0 * oy, yt + t0 * oy], color="#9aa3ad", lw=0.6, zorder=2.2)
        pts = []
        for i in range(17):
            u = i / 16
            a = {"one": min(1, u * 5), "tail": max(0, 1 - u * 3), "zero": 0.0}[shapes[k]]
            t = t0 + u * (t1 - t0)
            pts.append((x + t * ox, yb + 0.12 * H + 0.72 * H * a + t * oy))
        ax.plot(*zip(*pts), color=ENV, lw=1.6, zorder=2.3)
    for k, lab in enumerate(["−2", "−1", "0", "+1", "+2"]):
        t = (k + 0.5) / 5
        ax.text(x + t * ox + 0.12, yb + t * oy - 0.12, lab, fontsize=9, ha="left", va="top",
                color="#000" if k == 2 else "#666", weight="bold" if k == 2 else "normal", zorder=3)


def relu(ax, x, d, frac=0.82):
    """A ReLU slice inset on the conv block's middle plane, like the activation slice in PlotNeuralNet."""
    ox, oy = depth_vec(d * (1 - frac) / 2)
    cuboid(ax, x + ox, 0.18, H * frac, d * frac, RELU, z=3.5, dashed=False, yc=YC + oy)


def arrow(ax, a, b):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=15, lw=1.8, color=ARROW,
                                 shrinkA=0, shrinkB=0, zorder=10))


def label(ax, x, text, y=None, bold=False, size=11):
    ax.text(x, YC - H / 2 - 0.25 if y is None else y, text, ha="center", va="top", fontsize=size,
            weight="bold" if bold else "normal", zorder=5)


def depth_label(ax, x_right, d, text, h=H):
    ox, oy = depth_vec(d)
    ax.text(x_right + ox * 0.5 + 0.12, YC - h / 2 + oy * 0.5 - 0.05, text, rotation=45,
            ha="left", va="top", fontsize=10, zorder=5)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(16, 6.2))
    ax.set_aspect("equal")
    ax.axis("off")

    d80 = 80 * DEPTH_PER_STEP
    ox80, oy80 = depth_vec(d80)
    mid = lambda xr: (xr + ox80 / 2, YC + oy80 / 2)       # centre line through the 80-step blocks

    # Input sheet and input tensor (3 channels)
    x = 0.0
    input_panel(ax, x, d80)
    label(ax, x + 0.4, "5 bits × 16 steps", y=YC - H / 2 - 0.25, size=10)
    label(ax, x + 0.4, "envelope", y=YC - H / 2 - 0.65, bold=True)
    x_in = 2.55
    arrow(ax, (x + ox80 / 2 + 0.05, YC + oy80 / 2), (x_in + ox80 / 2, YC + oy80 / 2))
    xr = x_in
    for c in range(3):
        xr = cuboid(ax, xr, 0.13, H, d80, INPUT, z=3 + c * 0.01)
    depth_label(ax, xr, d80, "80")
    label(ax, x_in + 0.2, "3", size=10)
    label(ax, x_in + 0.2, "input", y=YC - H / 2 - 0.65, bold=True)
    label(ax, x_in + 0.2, "envelope, log envelope,\n'bit exists' flag", y=YC - H / 2 - 1.05, size=9)

    # Conv 1 and Conv 2 (16 filters, width 5, ReLU)
    end_prev = xr
    convs = []
    for i, x0 in enumerate([5.4, 8.1]):
        arrow(ax, mid(end_prev), (x0 + ox80 / 2, YC + oy80 / 2))
        xr = cuboid(ax, x0, 0.7, H, d80, CONV, z=3)
        relu(ax, xr, d80)
        xr += 0.18
        depth_label(ax, xr, d80, "80")
        label(ax, x0 + 0.44, "16", size=10)
        label(ax, x0 + 0.44, f"conv{i + 1}", y=YC - H / 2 - 0.65, bold=True)
        label(ax, x0 + 0.44, "width 5, ReLU", y=YC - H / 2 - 1.05, size=9)
        end_prev = xr
        convs.append(x0)

    # Flatten (1280) and dense (32)
    xf, hf, df = 11.0, 4.4, 0.25
    arrow(ax, mid(end_prev), (xf + depth_vec(df)[0] / 2, YC + oy80 / 2))
    xr = cuboid(ax, xf, 0.16, hf, df, CONV, z=3, dashed=False)
    label(ax, xf + 0.1, "1280", y=YC - hf / 2 - 0.2, size=10)
    label(ax, xf + 0.1, "flatten", y=YC - hf / 2 - 0.6, bold=True)
    label(ax, xf + 0.1, "dropout 0.3", y=YC - hf / 2 - 1.0, size=9)

    xd, hd = 12.3, 1.9
    arrow(ax, (xr + 0.1, YC + oy80 / 2), (xd + depth_vec(df)[0] / 2, YC + oy80 / 2))
    xr_d = cuboid(ax, xd, 0.16, hd, df, DENSE, z=3, dashed=False)
    xr_d = cuboid(ax, xr_d, 0.06, hd, df, RELU, z=3, dashed=False)
    label(ax, xd + 0.1, "32", y=YC - hd / 2 - 0.2, size=10)
    label(ax, xd + 0.1, "dense", y=YC - hd / 2 - 0.6, bold=True)
    label(ax, xd + 0.1, "ReLU", y=YC - hd / 2 - 1.0, size=9)

    # Two heads
    xo = 14.4
    yb_, yt_ = 1.55, -1.85
    for y_head, w, colors, n, name, sub in [
        (yb_, 0.22, OUT_BIT, "1", r"$P(\mathrm{bit}=1)$", r"$\geq 0.5 \rightarrow 1$"),
        (yt_, 0.42, OUT_TR, "4", "transition", "training only"),
    ]:
        sx, sy = xr_d + 0.12, YC + depth_vec(df)[1] / 2
        bx = 13.75
        ax.plot([sx, bx, bx], [sy, sy, y_head + 0.3], color=ARROW, lw=1.8, zorder=10)
        arrow(ax, (bx, y_head + 0.3), (xo, y_head + 0.3))
        cuboid(ax, xo, w, 0.6, 0.6, colors, z=3, dashed=False, yc=y_head)
        ax.text(xo + w / 2, y_head - 0.45, n, ha="center", va="top", fontsize=10)
        ax.text(xo + w + 0.75, y_head + 0.35, name, ha="left", va="center", fontsize=12.5,
                weight="bold")
        ax.text(xo + w + 0.75, y_head - 0.1, sub, ha="left", va="center", fontsize=10, color="#444")

    ax.set_xlim(-0.3, 17.6)
    ax.set_ylim(YC - 4.5, YC + 4.4)
    ax.text(8.6, YC + 4.2, "Network bit decoder  (≈ 43,000 parameters)", ha="center", va="top",
            fontsize=15, weight="bold")
    ax.text(8.6, YC - 4.1, "block thickness = channels  ·  receding axis = time (80 steps = 5 bits)  ·  "
            "orange slice = ReLU", ha="center", va="top", fontsize=10, color="#555")
    path = OUT / "cnn_architecture.png"
    fig.savefig(path, dpi=220, bbox_inches="tight")
    print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
