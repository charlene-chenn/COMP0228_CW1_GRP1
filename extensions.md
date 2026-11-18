# Extensions

Both extensions decide the bits again from the raw samples saved for every string. The sending doesn't change. How to run them: README, "Receiver extensions". The code is in `experiments/extensions.py`, and the filter itself is in `codes/filtering.py`.

## Filtering extension: choosing the band-pass

### Why the band matters

The filter keeps one frequency band, then measures how strong the signal is in each bit's window. The aim is to keep only the motor's **drive frequency**, the frequency it vibrates at while it is driven (a 1), and nothing else:

- **While driven**, the motor vibrates at its drive frequency, about 110–125 Hz.
- **After switch-off**, it coasts down and its frequency falls. In the measuring window, 150–200 ms after switch-off, it is at about 50–60 Hz (table in `experiment.md`, "Findings so far").

So a narrow band on the drive frequency keeps a 1 and leaves out the leftover vibration in a 0 after a 1.

### Checking the motor's frequency independently

As a check on `find_motor_band`, the drive frequency was also measured bit by bit, from the raw samples of every 1 in run 1 of each case:

1. Take the bit's 50 ms measuring window (500 samples) and remove its mean.
2. Apply a Hann window and take the FFT, zero-padded to 20,000 points (0.5 Hz bins).
3. Take the largest peak above 20 Hz.
4. Report the median over all the 1s (204 per run).

A 50 ms window can only separate tones about 20 Hz apart. Zero-padding doesn't change that, but it does place a single strong peak accurately. The interquartile ranges below are 1–2 Hz wide, so each 1 has one clear peak.

| Case (run 1) | Drive frequency, median | IQR |
|---|---|---|
| wood 15 cm | 118.5 Hz | 118–119 |
| wood 30 cm | 119.5 Hz | 119–120 |
| acrylic 15 cm | 111.5 Hz | 111–112 |
| PCB 15 cm | 124.0 Hz | 123–132 |
| "450cm" wood | 230.5 Hz | 230–231 |

In the "450cm" runs, the strongest peak is at about twice the other cases' drive frequency, most likely the second harmonic. Why that setup favours it hasn't been checked.

Both methods agree to within about 1 Hz on every case: `find_motor_band` gives 118.4, 118.4, 111.1, 123.3 and 230.7 Hz.

### Method for setting the band

Only the band is chosen. Everything else stays as `codes/filtering.py` has it: 4th-order Butterworth, 30 Hz envelope smoothing, no notch or sharpening, midpoint threshold.

The band is set with the method in `codes/filtering.py`, `find_motor_band`:

1. Take the Welch power spectrum of a recording with the motor running (segments of 8,192 samples, so about 1.2 Hz resolution).
2. Find the strongest peak above 20 Hz. That is the motor's drive frequency.
3. Keep that frequency ± 15 Hz.

**It is run once per material, on all of that material's run 1**, and the band is saved in `experiments/filter_bands.json`. Every string of run 1 (about 80 s of signal) is joined into one recording. From then on, every run of that material uses that band: runs 2–3, other distances and disturbances, and new live runs. So the band is known before a run starts, and the filter can decide each string as soon as it arrives. Run 1 works like a calibration run.

| Material | Set from | Drive frequency | Band |
|---|---|---|---|
| wood | `wood_15cm_none_S150_W50_Pprbs5_run1` | 118.4 Hz | 103.4–133.4 Hz |
| acrylic | `acrylic_15cm_none_S150_W50_Pprbs5_run1` | 111.1 Hz | 96.1–126.1 Hz |
| PCB | `pcb_15cm_none_S150_W50_Pprbs5_run1` | 123.3 Hz | 108.3–138.3 Hz |

To set or reset a material's band:

```
python3 -m experiments.run_case --set-band experiments/results/<run 1>/<run 1>.csv
```

**Why not on each string by itself?** A single string is only 6–30 s long, and the motor is off for about half of it, so its strongest peak isn't always the drive frequency. On PCB, the short strings (31–66 bits) often gave 87–90 Hz, and one long string gave 194 Hz, against 122–123 Hz for the others. All of run 1 joined together gives 123 Hz, the drive frequency.

### Results

Bands from the table above. Channel errors in each run.

| Case | Current receiver, runs 1, 2, 3 | Filter, runs 1, 2, 3 |
|---|---|---|
| wood 15 cm (band set here) | 54, 54, 54 | **0**, 0, 0 |
| wood 30 cm | 54, 54, 54 | 14, 1, 0 |
| "450cm" wood | 54, 54, 54 | 1, 1, 3 |
| acrylic 15 cm (band set here) | 58, 58, 60 | **0**, 0, 0 |
| acrylic 15 cm run 4 (uncoded only, 93 bits) | 33 | 0 |
| PCB 15 cm (band set here) | 70, 59, 55 | **0**, 0, 0 |

Bold is a run the band was set from, so not a fair test. Every other number is on a run the band never saw. Totals on those runs:
- **wood:** 108 errors → 0 at 15 cm, 162 → 15 at 30 cm, 162 → 5 at "450cm";
- **acrylic:** 151 → 0;
- **PCB:** 114 → 0.

For comparison, the same filter with other bands, run 1 | runs 2–3:

| Band | wood 15 cm | wood 30 cm | acrylic | PCB | "450cm" wood |
|---|---|---|---|---|---|
| 70–105 Hz (`codes/filtering.py` default) | 119 \| 198 | 61 \| 28 | 3 \| 0 | 185 \| 516 | 205 \| 403 |
| `find_motor_band` on each string | 0 \| 0 | 14 \| 1 | 0 \| 0 | 122 \| 228 | 0 \| 0 |
| **`find_motor_band` once per material** | **0 \| 0** | **14 \| 1** | **0 \| 0** | **0 \| 0** | **1 \| 4** |

What it shows:
- **With the band on the drive frequency, the filter removes almost every leakage error** on every material, including runs and distances the band was never set from.
- **PCB goes to 0.** Amplitude alone can't separate PCB, because a 0 after a 1 reads as large as a 1, but its leakage isn't at the drive frequency, so the band leaves it out.
- **The 70–105 Hz default is the worst choice.** It was set for the synthetic signal's 87 Hz motor. On the real channel, it misses the drive frequency and keeps the lower frequencies of the leftover vibration.
- **On each string by itself**, the band lands off the drive frequency on PCB's short strings, and the errors go up (122 | 228).
- **One band works for wood at every distance.** "450cm" wood's strongest peak is at about 230 Hz (twice the drive frequency), but the wood band at the drive frequency still gets 1–3 errors per run.
- **Wood 30 cm run 1 keeps 14 errors.** The same band gives 0 on wood 15 cm, so the band is unlikely to be the cause.

Run it with:

```
python3 -m experiments.run_case --replay --extension filter          # each material's band, the default
python3 -m experiments.run_case --replay --extension filter --filter-band 70 105   # a fixed band, to compare
```

Live, with a second window showing the filter's decisions as each string finishes:

```
python3 -m experiments.run_case $PORT --material acrylic --distance 15 --settle 150 --window 50 --prbs-per-code --sets 3 --codes none --run 5 --extension filter --live
```

### Caveats

- **The run each band was set from is in the results.** Its numbers aren't a fair test. Report the other runs, and give those separately.
- **A new material needs a band first.** Run 1 for it, then `--set-band`. Until then, `--extension filter` refuses to start for that material.
- **The band follows the motor and its supply voltage.** If either changes, set the band again from a new run 1.
- **Only measured at 150/50.** At a shorter settle time, the window would be closer to switch-off, where the motor hasn't slowed as far, so its frequency is closer to the band.
- **The midpoint threshold** needs both 0s and 1s in each string, and the whole string before deciding (see README). So the live window updates once per string, not per bit.
