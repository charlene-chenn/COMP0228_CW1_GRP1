"""
Noise filtering before the signal is turned back into bits.

The Arduino thresholds the raw peak-to-peak of each bit window, so
any noise in any frequency adds to the reading. Here we work on the raw ADC
samples instead: band-pass around the motor's vibration frequency, take the
envelope, then measure each bit and threshold it.

    raw -> (remove DC) -> band-pass (-> notch) -> envelope -> per-bit level -> threshold

Run from the project folder:
    python3 -m codes.filtering                         # synthetic signal, with plot
    python3 -m codes.filtering --auto-band             # pick the band from the spectrum
    python3 -m codes.filtering --file rec.npy --bit-ms 100 --lo 70 --hi 105
    python3 -m codes.filtering --no-plot              # just print the bit errors

Needs raw samples (uint16 ADC counts). piezo_receiver_v3 streams them when raw
mode is on, and experiments/run_case.py saves them for every string in
experiments/results/<case>/raw/*.npz. --file takes a 1-D .npy array of samples.
"""
import argparse
from typing import List, Optional, Tuple

import numpy as np
from scipy import signal

FS = 10_000  # Hz, SAMPLE_RATE in the Arduino sketch



def bandpass(x, fs: float, lo: float, hi: float, order: int = 4, kind: str = "butter") -> np.ndarray:
    """
    Zero-phase band-pass. Keeps lo..hi Hz, removes DC drift and everything
    outside the motor's band.

    kind: "butter" (flat pass band, moderate overshoot), "bessel" (gentle
    roll-off but minimal ringing, keeps edges sharp) or "cheby1" (steepest, but
    ripple and the most ringing). fs, lo and hi are in Hz.
    """
    if kind == "bessel":
        sos = signal.bessel(order, [lo, hi], btype="bandpass", fs=fs, output="sos", norm="mag")
    elif kind == "cheby1":
        sos = signal.cheby1(order, 1.0, [lo, hi], btype="bandpass", fs=fs, output="sos")
    else:
        sos = signal.butter(order, [lo, hi], btype="bandpass", fs=fs, output="sos")
    return signal.sosfiltfilt(sos, np.asarray(x, dtype=float))


def notch(x, fs: float, freq: float, q: float = 30.0) -> np.ndarray:
    """Zero-phase notch, e.g. for 50 Hz mains hum if it sits inside the band."""
    b, a = signal.iirnotch(freq, q, fs=fs)
    return signal.filtfilt(b, a, np.asarray(x, dtype=float))


def envelope(x, fs: float, smooth_hz: float = 30.0) -> np.ndarray:
    """
    Amplitude envelope of a band-passed signal: |Hilbert transform|, smoothed
    with a low-pass so one bit's level doesn't ripple at the carrier frequency.
    """
    env = np.abs(signal.hilbert(x))
    sos = signal.butter(2, smooth_hz, btype="lowpass", fs=fs, output="sos")
    return signal.sosfiltfilt(sos, env)


def sharpen(env, fs: float, tau_ms: float) -> np.ndarray:
    """
    Undo the motor's slow spin-up/spin-down so edges become crisp. If the
    envelope follows e' = (u - e) / tau, the sharp on/off signal is
    u = e + tau * de/dt. This boosts noise too, so smooth the envelope first
    (lower smooth_hz) and keep tau_ms near the real spin-down time.
    """
    return env + (tau_ms / 1000) * np.gradient(env, 1 / fs)


def find_motor_band(x, fs: float, min_hz: float = 20.0, halfwidth: float = 15.0) -> Tuple[float, float]:
    """
    Guess the pass band from the spectrum: the strongest peak above min_hz,
    plus or minus halfwidth. Works best on a recording with the motor running.
    """
    x = np.asarray(x, dtype=float)
    f, p = signal.welch(x - x.mean(), fs=fs, nperseg=min(len(x), 8192))
    mask = f >= min_hz
    peak = f[mask][np.argmax(p[mask])]
    return max(peak - halfwidth, 1.0), peak + halfwidth



def bit_levels(env, fs: float, bit_ms: float, n_bits: int, settle_ms: float = 0.0, start: int = 0) -> np.ndarray:
    """
    Mean envelope in each bit's measuring window (skipping settle_ms at the
    start of the bit, while the motor spins up or down).

    bit_ms is the whole bit (settle + window); start is the sample index
    where bit 0 begins.
    """
    bit_n = int(round(bit_ms * fs / 1000))
    skip = int(round(settle_ms * fs / 1000))
    levels = []
    for i in range(n_bits):
        a = start + i * bit_n + skip
        b = start + (i + 1) * bit_n
        levels.append(np.mean(env[a:b]) if b <= len(env) else 0.0)
    return np.array(levels)


def midpoint_threshold(levels) -> float:
    """Threshold halfway between the mean of the low and high halves of the levels (2-means)."""
    levels = np.asarray(levels, dtype=float)
    t = (levels.min() + levels.max()) / 2
    for _ in range(20):
        lo, hi = levels[levels < t], levels[levels >= t]
        if len(lo) == 0 or len(hi) == 0:
            break
        t = (lo.mean() + hi.mean()) / 2
    return float(t)


def filter_and_detect(
    x,
    fs: float,
    bit_ms: float,
    n_bits: int,
    lo: float,
    hi: float,
    settle_ms: float = 0.0,
    start: int = 0,
    notch_hz: Optional[float] = None,
    threshold: Optional[float] = None,
    kind: str = "butter",
    order: int = 4,
    smooth_hz: float = 30.0,
    sharpen_tau_ms: Optional[float] = None,
) -> dict:
    """
    Full chain. Returns every intermediate so it can be plotted.

    threshold: if None, it is the midpoint of the bit levels (needs both 0s and
    1s in the message). Pass a number to use a calibrated one instead.
    """
    x = np.asarray(x, dtype=float)
    centred = x - np.mean(x)
    filtered = bandpass(centred, fs, lo, hi, order, kind)
    if notch_hz:
        filtered = notch(filtered, fs, notch_hz)
    env = envelope(filtered, fs, smooth_hz)
    if sharpen_tau_ms:
        env = sharpen(env, fs, sharpen_tau_ms)
    levels = bit_levels(env, fs, bit_ms, n_bits, settle_ms, start)
    thr = midpoint_threshold(levels) if threshold is None else threshold
    return dict(
        centred=centred, filtered=filtered, envelope=env,
        levels=levels, threshold=thr, bits=[int(v >= thr) for v in levels],
    )


def raw_peak_to_peak(x, fs: float, bit_ms: float, n_bits: int, settle_ms: float = 0.0, start: int = 0) -> np.ndarray:
    """What the Arduino does today: peak-to-peak of the unfiltered samples in each window."""
    bit_n = int(round(bit_ms * fs / 1000))
    skip = int(round(settle_ms * fs / 1000))
    out = []
    for i in range(n_bits):
        w = np.asarray(x[start + i * bit_n + skip:start + (i + 1) * bit_n], dtype=float)
        out.append(w.max() - w.min() if len(w) else 0.0)
    return np.array(out)



def synthetic_recording(
    bits,
    fs: float = FS,
    bit_ms: float = 100,
    carrier_hz: float = 87.0,
    amplitude: float = 4000,
    noise_std: float = 1500,
    hum_hz: float = 50.0,
    hum_amp: float = 1500,
    drift_amp: float = 4000,
    burst_amp: float = 8000,
    n_bursts: int = 3,
    tau_ms: float = 15.0,
    seed: int = 1,
) -> np.ndarray:
    """
    Fake piezo recording of on/off-keyed bits (uint16-like ADC counts around mid-scale):
    motor tone with a spin-up/down time constant, white noise, mains hum, slow
    drift and a few broadband bursts. Not a model of the real channel.
    """
    rng = np.random.default_rng(seed)
    bit_n = int(round(bit_ms * fs / 1000))
    n = bit_n * len(bits)
    t = np.arange(n) / fs

    # Motor on/off with a first-order spin-up and spin-down
    gate = np.repeat(np.asarray(bits, dtype=float), bit_n)
    sos = signal.butter(1, 1000 / (2 * np.pi * tau_ms), btype="lowpass", fs=fs, output="sos")
    drive = signal.sosfilt(sos, gate)

    x = amplitude * drive * np.sin(2 * np.pi * carrier_hz * t)
    x += rng.normal(0, noise_std, n)
    x += hum_amp * np.sin(2 * np.pi * hum_hz * t + 1.0)
    x += drift_amp * np.sin(2 * np.pi * 0.7 * t) + 0.5 * drift_amp * np.sin(2 * np.pi * 3.1 * t)
    for _ in range(n_bursts):
        a = rng.integers(0, n - 200)
        x[a:a + 200] += rng.normal(0, burst_amp, 200)

    return np.clip(32768 + x, 0, 65535)



def plot_filtering(x, result: dict, fs: float, bit_ms: float, sent=None, raw_levels=None,
                   lo: float = 0, hi: float = 0, settle_ms: float = 0.0, start: int = 0, save: Optional[str] = None):
    """Four panels: raw vs filtered signal, spectrum before and after, and per-bit levels vs threshold."""
    import matplotlib.pyplot as plt

    t = np.arange(len(x)) / fs
    n_bits = len(result["bits"])
    bit_s = bit_ms / 1000

    fig, ax = plt.subplots(4, 1, figsize=(12, 10), constrained_layout=True)

    def mark_bits(a):
        for i in range(n_bits + 1):
            a.axvline(start / fs + i * bit_s, color="0.85", lw=0.6, zorder=0)
        if sent is not None:
            for i, b in enumerate(sent):
                if b:
                    a.axvspan(start / fs + i * bit_s, start / fs + (i + 1) * bit_s, color="tab:blue", alpha=0.08, lw=0)

    ax[0].plot(t, result["centred"], lw=0.5, color="0.4")
    ax[0].set_title("1. Raw signal (DC removed). Shaded = bit sent as 1" if sent is not None else "1. Raw signal (DC removed)")
    mark_bits(ax[0])

    ax[1].plot(t, result["filtered"], lw=0.5, color="tab:blue", label=f"band-pass {lo:.0f}-{hi:.0f} Hz")
    ax[1].plot(t, result["envelope"], lw=1.5, color="tab:orange", label="envelope")
    ax[1].set_title("2. Filtered signal and envelope")
    ax[1].legend(loc="upper right")
    mark_bits(ax[1])

    f, p_raw = signal.welch(result["centred"], fs=fs, nperseg=min(len(x), 4096))
    _, p_fil = signal.welch(result["filtered"], fs=fs, nperseg=min(len(x), 4096))
    ax[2].semilogy(f, p_raw, color="0.4", label="raw")
    ax[2].semilogy(f, p_fil, color="tab:blue", label="filtered")
    ax[2].axvspan(lo, hi, color="tab:green", alpha=0.15, label="pass band")
    ax[2].set_xlim(0, min(500, fs / 2))
    ax[2].set_xlabel("Hz")
    ax[2].set_title("3. Spectrum before and after")
    ax[2].legend(loc="upper right")

    idx = np.arange(n_bits)
    ax[3].bar(idx, result["levels"], color=["tab:blue" if b else "tab:orange" for b in result["bits"]])
    ax[3].axhline(result["threshold"], color="k", ls="--", label="threshold")
    ax[3].set_xlabel("bit index")
    ax[3].set_ylabel("filtered level")
    title = "4. Per-bit level after filtering (blue = decoded 1)"
    if sent is not None:
        wrong = [i for i in idx if result["bits"][i] != sent[i]]
        for i in wrong:
            ax[3].annotate("x", (i, result["levels"][i]), ha="center", color="red", fontsize=12)
        title += f", {len(wrong)} wrong (red x)"
    ax[3].set_title(title)
    ax[3].legend(loc="upper right")

    if raw_levels is not None:
        # Same bars, but for the unfiltered peak-to-peak, scaled to share the axis
        ax2 = ax[3].twinx()
        ax2.plot(idx, raw_levels, "o-", color="0.5", ms=3, lw=0.8, label="raw peak-to-peak (today)")
        ax2.set_ylabel("raw p2p")
        ax2.legend(loc="upper left")

    if save:
        fig.savefig(save, dpi=150)
    return fig


def compare_filters(lo=70.0, hi=105.0, order=4, fs=FS, carrier=87.0, tau_ms=40.0, smooth_hz=100.0, save=None):
    """
    Compare butter / bessel / cheby1 band-passes side by side on a clean 1->0 edge
    (no noise, so only the filter shape shows): gain curve, and the envelope each one
    gives as the motor switches on then off.
    """
    import matplotlib.pyplot as plt

    colours = {"butter": "tab:blue", "bessel": "tab:red", "cheby1": "tab:green"}
    bits, bit_ms = [0, 1, 1, 0, 0], 100
    x = synthetic_recording(bits, fs, bit_ms, carrier, 4000, 0, 0, 0, 0, 0, 0, tau_ms=tau_ms)
    t = np.arange(len(x)) / fs

    fig, ax = plt.subplots(2, 1, figsize=(10, 7), constrained_layout=True)
    for kind, c in colours.items():
        if kind == "bessel":
            sos = signal.bessel(order, [lo, hi], btype="bandpass", fs=fs, output="sos", norm="mag")
        elif kind == "cheby1":
            sos = signal.cheby1(order, 1.0, [lo, hi], btype="bandpass", fs=fs, output="sos")
        else:
            sos = signal.butter(order, [lo, hi], btype="bandpass", fs=fs, output="sos")
        w, h = signal.sosfreqz(sos, worN=4096, fs=fs)
        ax[0].plot(w, np.abs(h), color=c, label=kind)

        env = envelope(bandpass(x - x.mean(), fs, lo, hi, order, kind), fs, smooth_hz)
        ax[1].plot(t, env, color=c, label=kind)

    ax[0].axvline(carrier, color="k", ls=":", label="motor tone")
    ax[0].set_xlim(0, 250)
    ax[0].set_xlabel("Hz")
    ax[0].set_ylabel("gain")
    ax[0].set_title("Band-pass gain: only the shape near the edges differs")
    ax[0].legend()

    ax[1].plot(t, np.abs(signal.hilbert(x - x.mean())), color="0.7", lw=1, label="unfiltered envelope")
    ax[1].set_xlabel("s")
    ax[1].set_title("Envelope on a clean signal (bits 0 1 1 0 0), grey = no filter")
    ax[1].legend()

    if save:
        fig.savefig(save, dpi=150)
    return fig


def compare_sharpen(x, sent, fs, bit_ms, lo, hi, settle_ms, tau_ms, smooth_hz=40.0, start=0, save=None):
    """
    Whole-sequence comparison, same band-pass and envelope, with and without sharpening:
    envelope over time, then per-bit levels (each normalised so its own threshold is 1).
    Returns (errors_without, errors_with).
    """
    import matplotlib.pyplot as plt

    n = len(sent)
    plain = filter_and_detect(x, fs, bit_ms, n, lo, hi, settle_ms, start, smooth_hz=smooth_hz)
    sharp = filter_and_detect(x, fs, bit_ms, n, lo, hi, settle_ms, start, smooth_hz=smooth_hz, sharpen_tau_ms=tau_ms)
    t = np.arange(len(x)) / fs
    bit_s = bit_ms / 1000
    err = [sum(a != b for a, b in zip(sent, r["bits"])) for r in (plain, sharp)]

    fig, ax = plt.subplots(3, 1, figsize=(13, 9), constrained_layout=True)
    for a in ax[:2]:
        for i, b in enumerate(sent):
            if b:
                a.axvspan(start / fs + i * bit_s, start / fs + (i + 1) * bit_s, color="0.9", lw=0)
            a.axvline(start / fs + i * bit_s, color="0.85", lw=0.5)
    ax[0].plot(t, plain["envelope"], color="tab:blue")
    ax[0].set_title("Without sharpening: envelope (grey = bit sent as 1). Falling edges slope slowly")
    ax[1].plot(t, sharp["envelope"], color="tab:green")
    ax[1].set_title(f"With sharpening (tau = {tau_ms:g} ms): falling edges are crisper")
    # Mark where each bit is measured
    for a in ax[:2]:
        for i in range(n):
            a.axvspan(start / fs + i * bit_s + settle_ms / 1000, start / fs + (i + 1) * bit_s, color="tab:orange", alpha=0.07, lw=0)
    ax[1].set_xlabel("s (orange = measuring window of each bit)")

    idx = np.arange(n)
    w = 0.4
    for off, r, c, name, e in ((-w / 2, plain, "tab:blue", "no sharpening", err[0]), (w / 2, sharp, "tab:green", "sharpened", err[1])):
        ax[2].bar(idx + off, r["levels"] / r["threshold"], w, color=c, label=f"{name}: {e} wrong")
        for i in idx:
            if r["bits"][i] != sent[i]:
                ax[2].annotate("x", (i + off, r["levels"][i] / r["threshold"]), ha="center", color="red", fontsize=11)
    ax[2].axhline(1, color="k", ls="--")
    ax[2].set_xticks(idx)
    ax[2].set_ylabel("level / threshold")
    ax[2].set_xlabel("bit index (sent bits shown in the string below)  " + "".join(map(str, sent)))
    ax[2].set_title("Per-bit level against each method's own threshold (above 1 = decoded 1, red x = wrong)")
    ax[2].legend(loc="upper right")
    if save:
        fig.savefig(save, dpi=150)
    return err



def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help=".npy of raw ADC samples. Default: a synthetic recording")
    ap.add_argument("--fs", type=float, default=FS)
    ap.add_argument("--bit-ms", type=float, default=100, help="settle + window per bit")
    ap.add_argument("--settle-ms", type=float, default=None, help="ignored at the start of each bit")
    ap.add_argument("--bits", default="1011001110001011010011100101", help="bits sent (synthetic) or expected (file)")
    ap.add_argument("--npz", help="raw capture from experiments (samples, sent, bit_start...): real hardware data")
    ap.add_argument("--csv", help="trial CSV: replay the bits it sent (synthetic signal), and print what the hardware received")
    ap.add_argument("--row", type=int, default=0, help="row of --csv to use")
    ap.add_argument("--max-bits", type=int, default=60, help="bits of the CSV string to replay")
    ap.add_argument("--n-bits", type=int, help="bits to read from a file when --bits is not given")
    ap.add_argument("--start", type=int, default=0, help="sample index of the start of bit 0")
    ap.add_argument("--lo", type=float, default=70.0)
    ap.add_argument("--hi", type=float, default=105.0)
    ap.add_argument("--auto-band", action="store_true", help="pick lo/hi from the strongest spectral peak")
    ap.add_argument("--filter", default="butter", choices=["butter", "bessel", "cheby1"])
    ap.add_argument("--order", type=int, default=4)
    ap.add_argument("--smooth-hz", type=float, default=30.0, help="envelope low-pass; higher = sharper edges, noisier")
    ap.add_argument("--sharpen", type=float, metavar="TAU_MS", help="undo the motor spin-down with this time constant, e.g. 40")
    ap.add_argument("--tau-ms", type=float, default=15.0, help="synthetic motor spin-up/down time constant")
    ap.add_argument("--notch", type=float, help="extra notch in Hz, e.g. 50")
    ap.add_argument("--carrier", type=float, default=87.0, help="synthetic motor frequency")
    ap.add_argument("--noise", type=float, default=1500, help="synthetic white noise std (ADC counts)")
    ap.add_argument("--amp", type=float, default=4000, help="synthetic motor amplitude (ADC counts)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--compare", action="store_true", help="plot butter vs bessel vs cheby1 on a clean edge, then exit")
    ap.add_argument("--compare-sharpen", action="store_true", help="whole-sequence plot with vs without --sharpen (default tau 40)")
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--save", help="save the figure to this path")
    args = ap.parse_args()

    if args.compare:
        import matplotlib.pyplot as plt
        compare_filters(args.lo, args.hi, args.order, args.fs, args.carrier, args.tau_ms if args.tau_ms != 15.0 else 40.0,
                        args.smooth_hz, args.save)
        if not args.save:
            plt.show()
        return

    sent: Optional[List[int]] = [int(c) for c in args.bits] if args.bits else None

    hw_received = None
    if args.csv:
        import csv
        row = list(csv.DictReader(open(args.csv)))[args.row]
        sent = [int(c) for c in row["sent"][:args.max_bits]]
        hw_received = row["received"][:args.max_bits]
        args.bit_ms = args.bit_ms if args.bit_ms != 100 else (float(row["settle_ms"]) + float(row["window_ms"]))
        if args.settle_ms is None:
            args.settle_ms = float(row["settle_ms"])
        args.tau_ms = 40.0 if args.tau_ms == 15.0 else args.tau_ms

    if args.npz:
        d = np.load(args.npz)
        x = d["samples"].astype(float)
        args.fs = float(d["sample_rate"])
        sent = [int(b) for b in d["sent"]]
        hw_received = "".join(str(int(b)) for b in d["received"])
        args.start = int(d["bit_start"][0])
        args.bit_ms = (int(d["bit_start"][1]) - int(d["bit_start"][0])) * 1000 / args.fs
        if args.settle_ms is None:
            args.settle_ms = float(d["settle_ms"])
        n_bits = len(sent)
    elif args.file:
        x = np.load(args.file).astype(float)
        n_bits = len(sent) if sent else (args.n_bits or int((len(x) - args.start) / (args.bit_ms * args.fs / 1000)))
        sent = sent if (sent and len(sent) == n_bits) else None
    else:
        x = synthetic_recording(sent, args.fs, args.bit_ms, args.carrier, args.amp, args.noise, tau_ms=args.tau_ms, seed=args.seed)
        n_bits = len(sent)

    if args.settle_ms is None:
        args.settle_ms = 50.0

    if args.compare_sharpen:
        import matplotlib.pyplot as plt
        tau = args.sharpen or 40.0
        e = compare_sharpen(x, sent, args.fs, args.bit_ms, args.lo, args.hi, args.settle_ms, tau,
                            args.smooth_hz if args.smooth_hz != 30.0 else 40.0, args.start, args.save)
        print(f"Wrong bits of {len(sent)}: without sharpening {e[0]}, with sharpening {e[1]}")
        if not args.save:
            plt.show()
        return

    lo, hi = args.lo, args.hi
    if args.auto_band:
        lo, hi = find_motor_band(x, args.fs)
        print(f"Auto band: {lo:.1f}-{hi:.1f} Hz")

    result = filter_and_detect(x, args.fs, args.bit_ms, n_bits, lo, hi,
                               args.settle_ms, args.start, args.notch,
                               kind=args.filter, order=args.order, smooth_hz=args.smooth_hz, sharpen_tau_ms=args.sharpen)
    raw = raw_peak_to_peak(x, args.fs, args.bit_ms, n_bits, args.settle_ms, args.start)
    raw_bits = [int(v >= midpoint_threshold(raw)) for v in raw]

    print("Decoded (filtered):", "".join(map(str, result["bits"])))
    print("Decoded (raw p2p): ", "".join(map(str, raw_bits)))
    if hw_received:
        print("Hardware received: ", hw_received, f"({sum(a != int(b) for a, b in zip(sent, hw_received))} wrong, real device)")
    if sent is not None:
        print("Sent:              ", "".join(map(str, sent)))
        print(f"Errors: filtered {sum(a != b for a, b in zip(sent, result['bits']))}, "
              f"raw {sum(a != b for a, b in zip(sent, raw_bits))} of {len(sent)}")

    if not args.no_plot:
        import matplotlib.pyplot as plt
        plot_filtering(x, result, args.fs, args.bit_ms, sent, raw, lo, hi, args.settle_ms, args.start, args.save)
        if not args.save:
            plt.show()


if __name__ == "__main__":
    main()
