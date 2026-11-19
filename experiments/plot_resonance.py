"""
Checks the PCB resonance claim in experiment.md ("Findings so far"): as the motor slows
after switch-off, it passes through the board's resonance and the signal grows again
60-100 ms later, so a 0 after a 1 reads as loud as a 1.

Uses saved runs only (no hardware). Every 1 -> 0 -> 0 in runs 1-3 at 15 cm, 150/50,
is lined up on the moment the motor was switched off (bit_start + switch_offset of
the first 0), so ~400 ms of coast-down follows with the motor off.

    python3 -m experiments.plot_resonance

Writes figures/demodulation/4_resonance_pcb.png (PCB in detail) and
figures/demodulation/5_coastdown_materials.png (wood, acrylic, PCB compared).
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import signal

from experiments.plot_demodulation import (AXIS, BANDS, FILTER, INK, INK_2, MUTED, OUT, RESULTS, ROOT,
                                           SENT_0, SENT_1, WINDOW)

MATERIALS = {"wood": "#8a6d3b", "acrylic": "#2a78d6", "pcb": "#1f9e74"}
RUNS = (1, 2, 3)
AFTER_MS = 380          # coast-down shown after switch-off (two quiet bits = 409.6 ms)


def case(material, run):
    return f"{material}_15cm_none_S150_W50_Pprbs5_run{run}"


def segments(material):
    """Coast-downs after 1 -> 0 -> 0, and the last 50 ms of steady 1s (1 -> 1), DC removed."""
    coast, driven, fs = [], [], None
    for run in RUNS:
        for path in sorted((RESULTS / case(material, run) / "raw").glob("codes_0_*.npz")):
            d = np.load(path)
            fs = int(d["sample_rate"])
            x = d["samples"].astype(float)
            x -= np.median(x)
            sent, start, off = d["sent"].astype(int), d["bit_start"].astype(int), d["switch_offset"].astype(int)
            bit_n = int(start[1] - start[0])
            n_after = int(AFTER_MS * fs / 1000)
            for i in range(1, len(sent) - 1):
                a = start[i] + off[i]
                if sent[i - 1] == 1 and sent[i] == 0 and sent[i + 1] == 0 and a + n_after <= len(x):
                    coast.append(x[a:a + n_after])
                if sent[i - 1] == 1 and sent[i] == 1:
                    b = start[i] + bit_n
                    seg = x[b - int(0.05 * fs):b]
                    driven.append(seg - seg.mean())
    return np.array(coast), np.array(driven), fs


def rms_track(coast, fs, bin_ms=10):
    n = int(bin_ms * fs / 1000)
    k = coast.shape[1] // n
    blocks = coast[:, :k * n].reshape(len(coast), k, n)
    blocks = blocks - blocks.mean(axis=2, keepdims=True)
    rms = np.sqrt((blocks ** 2).mean(axis=2))               # per transition, per bin
    t = (np.arange(k) + 0.5) * bin_ms
    return t, np.median(rms, axis=0), np.percentile(rms, 25, axis=0), np.percentile(rms, 75, axis=0)


def amp_spectrum(segs, fs, nfft=8192):
    segs = segs - segs.mean(axis=1, keepdims=True)
    f, p = signal.periodogram(segs, fs=fs, window="hann", nfft=nfft, axis=-1)
    return f, np.sqrt(p.mean(axis=0))


def peak(f, a, lo=20):
    m = f >= lo
    return f[m][np.argmax(a[m])]


def shade_window(ax):
    ax.axvspan(150, 200, color=WINDOW, alpha=0.6, lw=0, zorder=0)
    ax.text(175, 0.98, "measuring\nwindow", transform=ax.get_xaxis_transform(), ha="center", va="top",
            fontsize=8, color=INK_2)


def fig_pcb():
    coast, driven, fs = segments("pcb")
    band = BANDS["pcb"]
    fig, ax = plt.subplots(1, 2, figsize=(14, 5.2), constrained_layout=True)
    fig.suptitle(f"PCB coast-down after switch-off  ·  15 cm, runs 1-3, {len(coast)} transitions 1 → 0 → 0",
                 x=0.01, ha="left", fontsize=14, fontweight="bold", color=INK)

    # Loudness after switch-off
    a = ax[0]
    tt, med, q1, q3 = rms_track(coast, fs)
    d_rms = np.median(np.sqrt((driven ** 2).mean(axis=1)))
    a.fill_between(tt, q1, q3, color=MATERIALS["pcb"], alpha=0.2, lw=0, label="25th-75th percentile")
    a.plot(tt, med, color=MATERIALS["pcb"], lw=2, label="median")
    a.axhline(d_rms, color=SENT_1, ls="--", lw=1.4, label=f"steady 1 (driven), {d_rms:,.0f}")
    shade_window(a)
    i_pk = int(np.argmax(med))
    a.annotate(f"{med[i_pk] / d_rms:.1f}× a driven 1\nat {tt[i_pk]:.0f} ms (motor at ~85 Hz)", (tt[i_pk], med[i_pk]),
               xytext=(tt[i_pk] + 70, med[i_pk] * 0.8), arrowprops=dict(arrowstyle="->", color=INK),
               fontsize=9, color=INK)
    a.set_xlabel("time after switch-off (ms)")
    a.set_ylabel("RMS in 10 ms bins (ADC counts)")
    a.set_title("Loudness: the board rings up again after switch-off")
    a.legend(loc="upper right", fontsize=8)
    a.set_xlim(0, AFTER_MS)

    # Whole-recording PSD, PCB against wood
    a = ax[1]
    for material in ("wood", "pcb"):
        xs = []
        for run in RUNS:
            for path in sorted((RESULTS / case(material, run) / "raw").glob("codes_0_*.npz")):
                d = np.load(path)
                x = d["samples"].astype(float)
                xs.append(x - x.mean())
        fw, pw = signal.welch(np.concatenate(xs), fs=fs, nperseg=8192)
        a.semilogy(fw, pw, color=MATERIALS[material], lw=1.4, label=f"{material}, peak {peak(fw, pw):.0f} Hz")
    a.axvspan(band["lo"], band["hi"], color=FILTER, alpha=0.15, lw=0, label="PCB pass band")
    a.set_xlim(0, 500)
    a.set_xlabel("frequency (Hz)")
    a.set_ylabel("power spectral density (counts²/Hz)")
    a.set_title("Power spectral density, whole recordings (runs 1-3)")
    a.legend(loc="upper right", fontsize=8)

    path = OUT / "4_resonance_pcb.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path, coast, driven, fs, (tt, med, d_rms)


def fig_materials():
    fig, ax = plt.subplots(1, 2, figsize=(14, 5), constrained_layout=True)
    fig.suptitle("Coast-down after switch-off, by material  ·  15 cm, runs 1-3, 1 → 0 → 0",
                 x=0.01, ha="left", fontsize=14, fontweight="bold", color=INK)
    summary = {}
    for material, colour in MATERIALS.items():
        coast, driven, fs = segments(material)
        tt, med, _, _ = rms_track(coast, fs)
        d_rms = np.median(np.sqrt((driven ** 2).mean(axis=1)))
        ax[0].plot(tt, med / d_rms, color=colour, lw=2, label=f"{material} ({len(coast)})")
        # strongest frequency in each 50 ms window
        n = lambda ms: int(ms * fs / 1000)
        pk = []
        for lo in range(0, AFTER_MS - 50 + 1, 25):
            fw, aw = amp_spectrum(coast[:, n(lo):n(lo + 50)], fs)
            pk.append((lo + 25, peak(fw, aw)))
        pk = np.array(pk)
        ax[1].plot(pk[:, 0], pk[:, 1], color=colour, lw=2, marker="o", ms=4, label=material)
        summary[material] = (tt, med / d_rms, pk)
    for a in ax:
        shade_window(a)
        a.set_xlabel("time after switch-off (ms)")
        a.set_xlim(0, AFTER_MS)
        a.legend(loc="upper right")
    ax[0].axhline(1, color=SENT_1, ls="--", lw=1)
    ax[0].text(AFTER_MS, 1, "steady 1 ", color=SENT_1, ha="right", va="bottom", fontsize=9)
    ax[0].set_ylabel("RMS ÷ RMS of a steady 1")
    ax[0].set_title("Loudness relative to a driven 1")
    ax[1].set_ylabel("strongest frequency (Hz)")
    ax[1].set_title("Strongest frequency in a sliding 50 ms window")
    path = OUT / "5_coastdown_materials.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path, summary


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path, coast, driven, fs, (tt, med, d_rms) = fig_pcb()
    print(path.relative_to(ROOT))
    path, summary = fig_materials()
    print(path.relative_to(ROOT))
    for material, (t, rel, pk) in summary.items():
        sel = [0, 2, 5, 7, 9, 12, 15, 17, 19, 25, 30]
        print(f"{material:8s} RMS/steady-1 at " + ", ".join(f"{t[i]:.0f}ms {rel[i]:.2f}" for i in sel if i < len(t)))
        print(f"{'':8s} peak Hz at " + ", ".join(f"{a:.0f}ms {b:.0f}" for a, b in pk))


if __name__ == "__main__":
    main()
