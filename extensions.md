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

### The threshold

After the band-pass and envelope, each bit has one level: the mean envelope in its measuring window. The filter decides 0 or 1 by comparing each level with a threshold, set separately for every string from that string's own levels (`codes/filtering.py`, `midpoint_threshold`).

**In one line:** the filter splits each string's bit levels into a quiet group and a loud group, and puts the threshold halfway between their averages, repeating until no bit changes group. This is 2-means clustering, done without knowing which bits were sent.

```python
t = (levels.min() + levels.max()) / 2        # first guess
for _ in range(20):
    lo = levels[levels < t]                  # quiet group: every level below t
    hi = levels[levels >= t]                 # loud group: every level at or above t
    if len(lo) == 0 or len(hi) == 0:
        break
    t = (lo.mean() + hi.mean()) / 2          # halfway between the two group averages
```

1. **First guess.** t is halfway between the quietest and loudest level in the string.
2. **Groups.** The groups aren't fixed in advance. The quiet group is every bit whose level is below the current t, and the loud group is every bit at or above it.
3. **Update.** t moves to halfway between the quiet group's average and the loud group's average.
4. **Repeat.** With the new t, some bits may switch groups, so steps 2–3 repeat until no bit switches (at most 20 rounds). Because t always sits halfway between the two averages, each bit ends up in whichever group's average it's nearer to.

The sent bits are never used. They're only compared with the result afterwards, to count errors, so the threshold could be set on a message whose content is unknown.

**Example** (wood 15 cm, run 1, convolutional string, 66 bits):

| Round | t | Quiet group | Loud group |
|---|---|---|---|
| First guess | (2 + 22,753) / 2 = 11,378 | 41 bits, average 2,123: all 34 real 0s, plus 7 quieter 1s (about 10,000–11,000) | 25 bits, average 17,576 |
| 1 | (2,123 + 17,576) / 2 = 9,849 | 34 bits, average 318: just the 0s | 32 bits, average 16,113: all the 1s |
| 2 | (318 + 16,113) / 2 = 8,216 | No bit switches, so it stops | |

The first guess was too high: 7 quieter 1s fell into the quiet group, raising its average, which pulled t down until they moved across. The final gap is wide: the loudest 0 is 896 and the quietest 1 is 10,302.

**Compared with the Arduino's threshold.** The Arduino sets one threshold per run at start-up, from 3 s of background noise with the motor off (the loudest noise + 3,000 ADC counts, about 3,425 on wood). It only knows how loud silence is, so a 0 after a 1, with the motor still coasting down (6,000–9,300 peak-to-peak in the string above), reads as a 1. The filter's threshold is set from the bits themselves, so it adapts to each material, distance and mounting without knowing in advance how loud a 1 will be.

**Weaknesses:**
- **It needs both 0s and 1s in the string.** An all-0 string would be split down the middle of its noise. The PRBS strings always have both.
- **It needs the whole string first,** so it decides once per string, not bit by bit.
- **A few very loud bits drag it upwards.** The first guess depends on the single loudest bit, and the loud group is summarised by its average. So a few extra-loud bits (knocks, bursts) raise t, normal 1s fall below it, and they're read as 0s. This is why every filter error under disturbance is a 1 read as a 0: 125 errors with constant noise and 286 with bursts (README, "What the results show"). Starting the search from the median level instead brought these down to 2 and 175. That was checked offline only and isn't in the code.

### Caveats

- **The run each band was set from is in the results.** Its numbers aren't a fair test. Report the other runs, and give those separately.
- **A new material needs a band first.** Run 1 for it, then `--set-band`. Until then, `--extension filter` refuses to start for that material.
- **The band follows the motor and its supply voltage.** If either changes, set the band again from a new run 1.
- **Only measured at 150/50.** At a shorter settle time, the window would be closer to switch-off, where the motor hasn't slowed as far, so its frequency is closer to the band.
- **The midpoint threshold** needs both 0s and 1s in each string, and the whole string before deciding (see "The threshold" above). So the live window updates once per string, not per bit.
