"""
Figures showing how the filter receiver turns the raw piezo signal into bits,
before the bits reach the decoder. Uses saved runs only (no hardware needed).

    raw -> remove DC -> band-pass -> envelope -> mean level per measuring window -> threshold -> bits

Run from the project folder:
    python3 -m experiments.plot_demodulation
    python3 -m experiments.plot_demodulation --case wood_15cm_none_S150_W50_Pprbs5_run1 --code conv75 --bits 0 12

Writes PNGs to figures/demodulation/.
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal

from codes.filtering import filter_and_detect

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "experiments" / "results"
BANDS = json.loads((ROOT / "experiments" / "filter_bands.json").read_text())
OUT = ROOT / "figures" / "demodulation"

# Same palette as live_view.py / scope.py
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SENT_0 = "#eb6834"
SENT_1 = "#2a78d6"
FILTER = "#1f9e74"
WINDOW = "#d9d7cf"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK_2, "xtick.color": INK_2, "ytick.color": INK_2,
    "axes.titlecolor": INK, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.labelsize": 10, "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "legend.frameon": False,
})


def load(case: str, code: str):
    d = np.load(RESULTS / case / "raw" / f"codes_0_{code}.npz")
    material = case.split("_")[0]
    band = BANDS[material]
    fs = int(d["sample_rate"])
    bit_n = int(np.diff(d["bit_start"])[0])
    sent = d["sent"].astype(int)
    res = filter_and_detect(
        d["samples"].astype(float), fs, bit_ms=bit_n * 1000 / fs, n_bits=len(sent),
        lo=band["lo"], hi=band["hi"], settle_ms=float(d["settle_ms"]),
    )
    return d, band, fs, bit_n, sent, res


def prev_bits(sent):
    return np.concatenate([[0], sent[:-1]])


def shade_bits(ax, sent, a, b, bit_n, fs, settle_n, win_n, labels=False):
    """Light band for every bit sent as 1, grey bar for each measuring window."""
    for i in range(a, b):
        t0 = i * bit_n / fs
        if sent[i]:
            ax.axvspan(t0, t0 + bit_n / fs, color=SENT_1, alpha=0.06, lw=0, zorder=0)
        ax.axvspan(t0 + settle_n / fs, t0 + (settle_n + win_n) / fs, color=WINDOW, alpha=0.55, lw=0, zorder=0)
        ax.axvline(t0, color=AXIS, lw=0.6, zorder=0)


def fig_pipeline(case, code, a, b):
    """One figure, shared time axis: each stage of the receiver on a short stretch of bits."""
    d, band, fs, bit_n, sent, res = load(case, code)
    settle_n = int(round(float(d["settle_ms"]) * fs / 1000))
    win_n = bit_n - settle_n          # filter receiver uses settle -> end of bit
    hw_win_n = int(round(float(d["window_ms"]) * fs / 1000))
    s0, s1 = a * bit_n, b * bit_n
    t = np.arange(s0, s1) / fs
    idx = np.arange(a, b)
    centres = (idx + 0.5) * bit_n / fs

    fig, ax = plt.subplots(5, 1, figsize=(13, 13), sharex=True, constrained_layout=True,
                           gridspec_kw={"height_ratios": [1.1, 1, 1, 1, 0.9]})
    fig.suptitle(f"Filter receiver, stage by stage  ·  {case}, {code} string, bits {a}–{b - 1}",
                 x=0.01, ha="left", fontsize=14, fontweight="bold", color=INK)

    # 1. Raw
    raw = d["samples"][s0:s1].astype(float)
    ax[0].plot(t, raw, lw=0.5, color=INK_2)
    ax[0].set_title("1. Raw piezo samples (10 kHz ADC)", pad=26)
    ax[0].set_ylabel("ADC counts")
    for i in idx:
        ax[0].text((i + 0.5) * bit_n / fs, 1.02, str(sent[i]), transform=ax[0].get_xaxis_transform(),
                   ha="center", va="bottom", fontsize=12, fontweight="bold",
                   color=SENT_1 if sent[i] else SENT_0)
    ax[0].text(0, 1.02, "sent:", transform=ax[0].transAxes, ha="right", va="bottom", color=MUTED)

    # 2. DC removed + band-pass
    ax[1].plot(t, res["centred"][s0:s1], lw=0.5, color=AXIS, label="DC removed (unfiltered)")
    ax[1].plot(t, res["filtered"][s0:s1], lw=0.6, color=FILTER,
               label=f"band-pass {band['lo']:.0f}–{band['hi']:.0f} Hz (4th-order Butterworth)")
    ax[1].set_title(f"2. Band-pass around the motor's drive frequency ({band['drive_hz']:.0f} Hz)")
    ax[1].set_ylabel("ADC counts")
    ax[1].legend(loc="upper right", ncols=2)

    # 3. Envelope
    ax[2].plot(t, res["filtered"][s0:s1], lw=0.4, color=FILTER, alpha=0.35)
    ax[2].plot(t, res["envelope"][s0:s1], lw=1.8, color=INK, label="envelope = |Hilbert|, smoothed at 30 Hz")
    ax[2].set_title("3. Envelope: the amplitude of the drive tone over time")
    ax[2].set_ylabel("ADC counts")
    ax[2].legend(loc="upper right")

    # 4. Per-bit level vs threshold
    lv = res["levels"][a:b]
    thr = res["threshold"]
    ax[3].plot(t, res["envelope"][s0:s1], lw=1, color=AXIS)
    for i, v in zip(idx, lv):
        x0 = (i * bit_n + settle_n) / fs
        ax[3].hlines(v, x0, x0 + win_n / fs, lw=4, color=SENT_1 if v >= thr else SENT_0)
    ax[3].axhline(thr, color=INK, ls="--", lw=1)
    ax[3].text(t[-1], thr, f"  threshold {thr:,.0f}", va="bottom", ha="right", color=INK, fontsize=9)
    ax[3].set_title("4. Mean envelope in each measuring window, compared with the threshold")
    ax[3].set_ylabel("ADC counts")

    # 5. Bits: hardware p2p vs filter
    hw = d["vibration"][a:b].astype(float) / float(d["threshold"])
    fl = lv / thr
    w = 0.32 * bit_n / fs
    ax[4].bar(centres - w / 2, hw, w, color=MUTED, label="peak-to-peak on raw signal (Arduino)")
    ax[4].bar(centres + w / 2, np.clip(fl, 4e-3, None), w, color=FILTER, label="filtered level")
    ax[4].axhline(1, color=INK, ls="--", lw=1)
    ax[4].set_yscale("log")
    ax[4].set_ylim(3e-3, 300)
    ax[4].set_ylabel("level / its threshold")
    ax[4].set_title("5. Decision: above 1 = read as 1.  × = wrong bit")
    hw_bits = d["received"][a:b]
    fl_bits = np.array(res["bits"][a:b])
    for c, v, bit, s in zip(centres, hw, hw_bits, sent[a:b]):
        if bit != s:
            ax[4].text(c - w / 2, v * 1.15, "×", ha="center", color=INK, fontsize=13, fontweight="bold")
    for c, v, bit, s in zip(centres, fl, fl_bits, sent[a:b]):
        if bit != s:
            ax[4].text(c + w / 2, v * 1.15, "×", ha="center", color=INK, fontsize=13, fontweight="bold")
    ax[4].legend(loc="upper left", ncols=2)
    ax[4].set_xlabel("time (s)   ·   grey bars = measuring window, blue tint = bit sent as 1", loc="left")

    for k in range(4):
        shade_bits(ax[k], sent, a, b, bit_n, fs, settle_n, win_n)
    for i in idx:
        ax[4].axvline(i * bit_n / fs, color=AXIS, lw=0.6, zorder=0)
    ax[4].set_xlim(t[0], t[-1])

    fig.text(0.99, 0.003, f"sent {''.join(map(str, sent[a:b]))}   ·   raw p2p read {''.join(map(str, hw_bits))}"
             f"   ·   filter read {''.join(map(str, fl_bits))}", ha="right", va="bottom", family="monospace",
             fontsize=9, color=INK_2)

    path = OUT / f"1_pipeline_{case}_{code}.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def fig_spectrum(case, codes):
    """
    Spectrum inside the measuring windows, split by what was sent: a 1, a 0 straight
    after a 1, and a 0 after a 0. Shows the leftover coast-down vibration sits below the
    pass band, which is why band-passing removes it.
    """
    groups = {"sent 1": [], "sent 0, previous bit 1": [], "sent 0, previous bit 0": []}
    full_raw, full_fil = [], []
    for code in codes:
        d, band, fs, bit_n, sent, res = load(case, code)
        settle_n = int(round(float(d["settle_ms"]) * fs / 1000))
        prev = prev_bits(sent)
        for i, s in enumerate(sent):
            seg = res["centred"][i * bit_n + settle_n:(i + 1) * bit_n]
            seg = seg - seg.mean()
            key = "sent 1" if s else ("sent 0, previous bit 1" if prev[i] else "sent 0, previous bit 0")
            groups[key].append(seg)
        full_raw.append(res["centred"])
        full_fil.append(res["filtered"])

    nfft = 8192
    colours = {"sent 1": SENT_1, "sent 0, previous bit 1": SENT_0, "sent 0, previous bit 0": MUTED}
    fig, ax = plt.subplots(2, 1, figsize=(12, 8.5), constrained_layout=True)
    fig.suptitle(f"Where the energy is  ·  {case}, all coded strings", x=0.01, ha="left",
                 fontsize=14, fontweight="bold", color=INK)

    for key, segs in groups.items():
        f, p = signal.periodogram(np.array(segs), fs=fs, window="hann", nfft=nfft, axis=-1)
        ax[0].plot(f, np.sqrt(p.mean(axis=0)), color=colours[key], lw=1.8, label=f"{key} ({len(segs)} bits)")
    ax[0].axvspan(band["lo"], band["hi"], color=FILTER, alpha=0.15, lw=0, label="pass band")
    ax[0].set_xlim(0, 300)
    ax[0].set_yscale("log")
    ax[0].set_xlabel("frequency (Hz)")
    ax[0].set_ylabel("amplitude spectrum (ADC counts/√Hz)")
    ax[0].set_title("Inside the measuring windows: a 0 after a 1 still vibrates, but below the pass band")
    ax[0].legend(loc="upper right")

    x_raw, x_fil = np.concatenate(full_raw), np.concatenate(full_fil)
    f, p_raw = signal.welch(x_raw, fs=fs, nperseg=8192)
    _, p_fil = signal.welch(x_fil, fs=fs, nperseg=8192)
    ax[1].semilogy(f, p_raw, color=INK_2, lw=1.2, label="raw (DC removed)")
    ax[1].semilogy(f, p_fil, color=FILTER, lw=1.5, label="after band-pass")
    ax[1].axvspan(band["lo"], band["hi"], color=FILTER, alpha=0.15, lw=0)
    ax[1].axvline(band["drive_hz"], color=INK, ls=":", lw=1)
    ax[1].text(band["drive_hz"], 0.97, f" drive {band['drive_hz']:.0f} Hz", transform=ax[1].get_xaxis_transform(),
               va="top", color=INK, fontsize=9)
    ax[1].set_xlim(0, 500)
    ax[1].set_ylim(1e-1, None)
    ax[1].set_xlabel("frequency (Hz)")
    ax[1].set_ylabel("power spectral density")
    ax[1].set_title("Whole recording, before and after the band-pass")
    ax[1].legend(loc="upper right")

    path = OUT / f"2_spectrum_{case}.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def fig_separation(case, codes):
    """Every bit of the run: raw p2p vs filtered level, each scaled to its own threshold."""
    rows = []
    for code in codes:
        d, band, fs, bit_n, sent, res = load(case, code)
        prev = prev_bits(sent)
        hw = d["vibration"].astype(float) / float(d["threshold"])
        fl = res["levels"] / res["threshold"]
        for s, p, h, l in zip(sent, prev, hw, fl):
            rows.append((s, p, h, l))
    rows = np.array(rows)
    cats = [("sent 0\nafter 0", (rows[:, 0] == 0) & (rows[:, 1] == 0), MUTED),
            ("sent 0\nafter 1", (rows[:, 0] == 0) & (rows[:, 1] == 1), SENT_0),
            ("sent 1", rows[:, 0] == 1, SENT_1)]

    fig, ax = plt.subplots(1, 2, figsize=(12, 5.5), sharey=True, constrained_layout=True)
    fig.suptitle(f"Can a threshold separate 0s from 1s?  ·  {case}, {len(rows)} bits",
                 x=0.01, ha="left", fontsize=14, fontweight="bold", color=INK)
    rng = np.random.default_rng(0)
    for k, (col, title) in enumerate(((2, "Peak-to-peak on raw signal (Arduino)"), (3, "Filter receiver"))):
        for j, (name, m, c) in enumerate(cats):
            v = np.clip(rows[m, col], 1e-4, None)
            ax[k].scatter(j + rng.uniform(-0.25, 0.25, len(v)), v, s=14, color=c, alpha=0.75, lw=0)
            wrong = (v >= 1) != (name == "sent 1")
            ax[k].text(j, 1e-4 * 0.55, f"{wrong.sum()} wrong", ha="center", va="top", fontsize=9,
                       color=INK if wrong.sum() else MUTED)
        ax[k].axhline(1, color=INK, ls="--", lw=1)
        ax[k].set_yscale("log")
        ax[k].set_ylim(3e-5, 30)
        ax[k].set_xticks(range(3), [c[0] for c in cats])
        ax[k].set_title(title)
    ax[0].set_ylabel("level / threshold  (above 1 = read as 1)")
    path = OUT / f"3_separation_{case}.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", default="wood_15cm_none_S150_W50_Pprbs5_run1")
    ap.add_argument("--code", default="conv75", help="string used for the stage-by-stage figure")
    ap.add_argument("--bits", type=int, nargs=2, default=[0, 12], metavar=("FROM", "TO"))
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    codes = sorted(p.stem.replace("codes_0_", "") for p in (RESULTS / args.case / "raw").glob("codes_0_*.npz"))
    for p in (fig_pipeline(args.case, args.code, *args.bits), fig_spectrum(args.case, codes),
              fig_separation(args.case, codes)):
        print(p.relative_to(ROOT))


if __name__ == "__main__":
    main()
