# Live demo

Two cases, each going through the same three methods in a fixed order:

1. **No code**: the Arduino receiver on the raw PRBS-5 string (the baseline).
2. **Repetition (R5)**: the same string, each bit sent 5 times, decoded by majority vote.
3. **Filtering**: the filter extension decides every string again from its raw samples. Its result is printed under each string and shown in its own live window.

The filter is a receiver, not a code, so it doesn't need its own string: it runs on the strings already sent. In the terminal, each string shows the Arduino's result, then the filter's directly underneath.

## Commands

Find the port first (close the Arduino Serial Monitor):

```
ls /dev/cu.usbmodem*
export PORT=/dev/cu.usbmodemXXXX
```

**Baseline (wood, 15 cm):**

```
python3 -m experiments.run_case $PORT --material wood --distance 15 --settle 150 --window 50 --prbs-per-code --sets 1 --codes none R5 --fixed-order --extension filter --live --no-video --run 20
```

**PCB (15 cm):**

```
python3 -m experiments.run_case $PORT --material pcb --distance 15 --settle 150 --window 50 --prbs-per-code --sets 1 --codes none R5 --fixed-order --extension filter --live --no-video --run 20
```

What each part does:

| Option | Why |
|---|---|
| `--settle 150 --window 50`, `--distance 15` | The same settings as the runs below, so the results are comparable |
| `--prbs-per-code --sets 1` | Each code sends the PRBS-5 string (31 bits) once |
| `--codes none R5 --fixed-order` | No code, then R5, always in that order (the experiment suite shuffles the order; `--fixed-order` turns that off) |
| `--extension filter` | Runs the filter on each string as soon as it finishes, using the material's saved band from `experiments/filter_bands.json` (wood 103–133 Hz, PCB 108–138 Hz) |
| `--live` | Opens the live view for the Arduino, plus a second window for the filter |
| `--no-video` | Skips making the video at the end, so you don't have to wait for it |
| `--run 20` | A new run number, so it doesn't clash with runs 1–3. **A finished run is skipped if the same command is run again.** For a rehearsal or a second go, change the number (`--run 21`, `--run 22`, ...) |

**Time per case:** about 3 s of calibration, then 31 + 155 bits × 204.8 ms ≈ 38 s of sending, so about 45–50 s in total.

**Before the demo:**
- Rehearse once with `--sim` in place of `$PORT` (no hardware needed; it saves to `experiments/results/sim/`).
- Keep the surface still during the 3 s calibration: the threshold is set from it.
- Leave the raw samples on (don't add `--no-raw`), as the filter needs them.

## Expected results

From runs 1–3 of the same settings (`wood_15cm_none_S150_W50_Pprbs5_run1–3`, `pcb_15cm_none_S150_W50_Pprbs5_run1–3`). Channel errors are wrong bits before decoding; message errors are wrong bits in the decoded 31-bit message.

### Baseline: wood, 15 cm

Arduino threshold about 3,420–3,440.

| Method | Channel errors | Message errors |
|---|---|---|
| No code (Arduino) | **8 / 31** in every run | **8 / 31 (26%)** |
| R5 (Arduino) | 8 / 155 in every run | **0 / 31** |
| Filter, no code | **0 / 31** | **0 / 31** |
| Filter, R5 | 0 / 155 | 0 / 31 |

### PCB, 15 cm

Arduino threshold about 4,060–4,110.

| Method | Channel errors | Message errors |
|---|---|---|
| No code (Arduino) | **8–12 / 31** (8, 11, 12) | **8–12 / 31 (26–39%)** |
| R5 (Arduino) | 8–16 / 155 (16, 8, 8) | **0 / 31** in every run |
| Filter, no code | **0 / 31** | **0 / 31** |
| Filter, R5 | 0 / 155 | 0 / 31 |

### What to point out

- **The 8 errors are predictable.** PRBS-5 has exactly 8 places where a 1 is followed by a 0. Each of those 0s is read as a 1, because the motor is still coasting (intersymbol interference). Every Arduino error is a "sent 0, read 1"; the live view's "error rate by previous and current bit" panel shows 1 → 0 at 100% and everything else at 0%.
- **R5 fixes them.** The R5 string also has 8 places where a 1 is followed by a 0, but only the *first* of the 5 copies of the 0 is wrong (10000 → majority 0), so every message bit survives. The price is speed: 0.98 message bits/s against 4.88 uncoded.
- **PCB is worse.** The board resonates as the motor slows (see `figures/demodulation/4_resonance_pcb.png`), so some 0s two bits after a 1 are hit as well: up to 12 errors uncoded, and up to 16 wrong copies in the R5 string. R5 still decodes every message bit (it outvotes up to 2 wrong copies in each group of 5), where R3 let 1 error through in 2 of the 3 runs.
- **The filter removes them all.** It keeps only the motor's drive frequency, and the leftover vibration (including the PCB ringing at about 85 Hz) is outside the band, so it gets 0 errors on both materials without any code: the same result as R5, at 5 times the data rate.

If a live result differs: a few extra errors usually mean the surface was touched or something moved during calibration, or the motor mount has shifted. The expected 8 should come back on a re-run (with a new `--run` number).
