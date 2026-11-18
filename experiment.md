# Experiment suite

There are 8 test cases with 3 runs each, so 24 runs in all. In each run, the same PRBS-5 string (31 bits) goes through every code once, in shuffled order:

| Code | Channel bits sent |
|---|---|
| none (uncoded baseline) | 31 |
| R3 | 93 |
| R5 | 155 |
| hamming74 (padded to 32) | 56 |
| conv75 | 66 |

That's 401 channel bits per run. At 150/50 each bit takes 204.8 ms, so a run takes **about 1.5 minutes** including calibration. The `none` string is the uncoded baseline. Every coded string's raw channel bits are saved too, so each one also counts as a noise sample.

**Each run gets its own folder, `experiments/results/<case>/`, holding:**
- `<case>.csv`: one row per string.
- `<case>.png`: the viewer as it was at the end of the run, saved by `--live`.
- `raw/`: one `.npz` per string, `codes_<set>_<code>.npz`, holding the raw piezo samples at 10 kHz for every bit, for the extensions.
- `<case>.mp4`: a video of the raw signal scrolling through the whole run at real speed, made automatically when the run finishes. It is 1080p (1920 × 1080, 30 fps), takes about 3 minutes to make and is about 20 MB. `--no-video` skips it. Remake one with `python3 -m experiments.make_video experiments/results/<case>/<case>.csv`.

The lists below give each run's folder.

| Group | Case | Material | Geometry | Separation | Disturbance (`--noise`) |
|---|---|---|---|---|---|
| Material | Wood (baseline) | wood | 30 × 6 | 20 cm | none |
| Material | Acrylic | acrylic | 30 × 6 | 20 cm | none |
| Material | PCB | pcb | 30 × 6 | 20 cm | none |
| Distance | 30 cm | wood | extended | 30 cm | none |
| Distance | 50 cm | wood | extended | 50 cm | none |
| Disturbance | Random taps | wood | 30 × 6 | 20 cm | taps |
| Disturbance | Low drone | wood | 30 × 6 | 20 cm | drone |
| Disturbance | High burst | wood | 30 × 6 | 20 cm | burst |

The wood 20 cm case is the control for both the material group and the disturbance group.

## Fixed for every run

- **Settle 150 ms, window 50 ms.** Each bit takes 204.8 ms, so about 4.9 bit/s before coding. This was chosen from the pilot and settle sweep (see below), before any suite data, and it stays the same for all 24 runs. Changing it partway would mean cases run at different speeds can't be compared.
- **`--prbs-per-code --sets 1`:** one PRBS-5 through each code. `--sets N` would send it N times per code. If you raise it, keep it the same for every case.
- **Motor and piezo positions on the specimen:** mark them so every re-mount puts them in the same place.
- **Firmware:** the current `piezo_receiver_v3.ino`, which can stream raw samples. **Upload it again before the first session** (the version on the board can't). The git hash is saved in every row, so commit code changes before you start.
- **Raw recording on for every run** (the default, so no flag is needed). Don't use `--no-raw` for any run in the suite. Sending the samples takes a few ms per bit out of the settle time, so runs with and without raw aren't quite the same timing.

## Before each session

```
cd ~/Documents/UCL_YEAR_4/SCADA/CW1/COMP0228_CW1_GRP1
source ../../scada-venv/bin/activate
python3 -m channel.hardware            # lists the ports; find the Giga
PORT=/dev/cu.usbmodemXXXX              # put the Giga's port here
python3 -m channel.hardware $PORT      # quick check that the channel and raw streaming work
```

The check prints its 8 test bits twice, the second time with raw on. Look at its last lines:
- `Raw:` should be 2048 samples per bit. The check uses the sketch's default 100/100 timing. In the suite, at 150/50, it's 2048 too.
- `Switch at:` is how many samples into each bit the motor switched. It's the time spent sending the previous bit's samples (10 samples = 1 ms). A few tens is fine.
- `Late bits:` should be 0. If it isn't, the board can't send raw samples fast enough and bits are running long. Stop and tell the group before running anything.

Close the Arduino Serial Monitor and Plotter first. Keep the surface still while it calibrates at the start of each run.

## Pilot and settle sweep (done 17 Nov 2026)

The earlier trial runs were done before the current mount, and partly while damping was being added, so they don't show how noisy the channel is now. The pilot checked the baseline on the setup as it will be used: wood 30 × 6, 20 cm, proper mount, no damping, no disturbance. It used PRBS-5 strings only (`--prbs-only`), window 50 ms, and varied the settle time.

| Settle / window | Time per bit | Runs × bits | Errors | 0 after a 1 | 0 after a 0 | 1s |
|---|---|---|---|---|---|---|
| 50 / 50 | 102.4 ms | 4 × 93 | 45% in every run | all wrong (24/24 per run) | mostly wrong (18/21 per run) | all right |
| 100 / 50 | 153.6 ms | 1 × 62 | 38.7% | all wrong (16/16) | 8/14 wrong | all right |
| 150 / 50 | 204.8 ms | 1 × 62 | 25.8% | all wrong (16/16) | all right (0/14) | all right |

What it shows:
- **No bit errors were random.** At 150/50, every error is a 0 straight after a 1, and nothing else is ever wrong. The vibration from a 1 is still going when the next bit is measured. This is intersymbol interference, not random noise.
- **The vibration takes about 220–250 ms to die away** after the motor switches off. This was measured from the 50/50 pilot's raw samples over the 4-bit run of 0s. The signal stays at the ADC maximum for about 60–100 ms, then has a tail of about 10,000–20,000 counts. It falls below the threshold (about 3,500) only after 220–250 ms. At 50/50 the window measures 50–100 ms after switch-off, while the signal is still at its maximum, which is why almost every 0 read as a 1.
- **The 1s always clip** near the ADC maximum (about 62,000–64,000).
- At 150/50 a 0 after a 1 reads at most about 31,000, against at least about 63,700 for a 1. So a threshold midway between them would separate them. The receiver's threshold sits just above the quiet noise floor instead.
- `late_bits` was 0 in every run, so raw streaming didn't affect the timing.

**Decision: settle 150 ms, window 50 ms.** The settings were chosen from the pilot and are fixed for the whole suite from here on.

The pilot files (`experiments/results/pilot/`, `wood_20cm_none_S100_W50_M32_run0/`, `wood_20cm_none_S150_W50_M32_run0/`) should be moved out of `experiments/results/` before the suite starts, so the summaries only include the suite:

```
mkdir -p archive/pilot
mv experiments/results/pilot/* experiments/results/wood_20cm_none_S100_W50_M32_run0 experiments/results/wood_20cm_none_S150_W50_M32_run0 archive/pilot/
```

(The 50/50 pilot files say `distance 450`. The setup was the 20 cm one.)

### Channel check, 17 Nov 2026 (100/100, before the pilot)

This was run with `python3 -m channel.hardware $PORT` straight after uploading the current sketch. That command doesn't set the timing, so it used the sketch's defaults: **settle 100 ms, window 100 ms** (2,048 samples, i.e. 204.8 ms per bit). Same wood 30 × 6 setup, proper mount, no damping, no disturbance.

```
Threshold: 3451
Sent:      [1, 0, 1, 0, 1, 1, 0, 0]
Received:  [1, 1, 1, 1, 1, 1, 1, 0]
Vibration: [64787, 26523, 64768, 25760, 64757, 64721, 24933, 2282]
Wrong:     3
Raw:        [2048, 2048, 2048, 2048, 2048, 2048, 2048, 2048] samples per bit
Switch at:  [3, 45, 46, 48, 50, 52, 45, 45] samples into each bit
Late bits:  0
Vibration:  [64630, 25961, 64768, 26882, 64759, 64587, 23969, 2523] (with raw on)
```

What it shows:
- **Raw streaming works.** No bits ran long. Sending a bit's samples took 4.5–5 ms (45–52 samples) at 2,048 samples per bit. At 50/50 (1,024 samples per bit) that should be about 2.5 ms. Turning raw on didn't change the readings beyond normal variation.
- **All 3 errors were a 0 straight after a 1,** reading about 24,000–27,000 against a threshold of 3,451, even after a 100 ms settle. The only 0 that came after another 0 read correctly (2,282). Vibration from a 1 is still strong 100 ms after the motor turns off. At 50/50 there's half as long for it to die away, so the 50/50 pilot is expected to show more of these errors, not fewer.
- **The 1s clip** at about 64,700, close to the 16-bit ADC maximum (65,535). The vibration value can't show differences in the strength of a 1, which limits comparing materials and distances by signal margin.

Only 8 bits were sent, so this is a first look and not a measurement. The pilot and settle sweep above give the actual baseline.

## Rules for every run

- **Re-mount between runs.** Take the piezo and motor off and put them back on the marks before each new run number. Then the 3 runs measure how much mounting varies, rather than repeating one mounting.
- **If a run stops,** run the exact same command again. It carries on from the last saved string.
- **If the setup changed in the middle of a run,** delete that run's folder, then run the command again from the start.
- Write anything unusual in `--notes`. It's saved in every row.
- **Each run tells you what it's doing,** in the terminal and the live viewer:
  - `>>> Calibrating: keep the surface still (3 s)`
  - `>>> Calibration complete, threshold N`, with a beep
  - `>>> Starting in 3... 2... 1...`
  - `>>> Sending now`, with a second beep, just before the first bit

  Keep still until calibration is complete. In the disturbance cases, start the disturbance during the countdown so it's already going when sending starts. Don't start it before calibration is complete, or it raises the threshold. `--countdown N` changes the countdown length.
- **`--live`** opens the viewer:
  - the raw piezo signal for the latest 6 bits, with each bit's measuring window and what it was read as;
  - the vibration per bit;
  - a channel error map for each coded string;
  - a map of message bits still wrong after decoding;
  - the error statistics.

  It saves the `.png` when the run finishes. Closing the window stops the run after the current string. A second window, **Raw signal scope**, shows the same raw signal scrolling smoothly, about 1.5 bits behind live. It runs on its own, so the main viewer's redraws don't make it stutter. To redraw a saved run: `python3 -m experiments.live_view experiments/results/<case>/<case>.csv`.
- **Check `late_bits` in the CSV** after the first run. It should be 0 in every row.

## Order

- **Rounds 1–3 (wood 30 × 6, 20 cm):** mount, then run the baseline, taps, drone and burst cases. Re-mount, then do the next round. Each disturbance run is then compared with a baseline on the same mounting.
- **Acrylic, PCB, extended wood 30 cm and 50 cm:** 3 runs each, re-mounting between runs.

Disturbances: replace the `<...>` in `--notes` with what made each one and where it was, e.g. the source, its frequency or volume, how far away it was, and the tapping rhythm. Use the same source and position in all 3 runs.

---

## Rounds 1–3: wood 30 × 6, 20 cm, baseline and disturbances

### Round 1

```
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise none  --settle 150 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6, baseline" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise taps  --settle 150 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6, random taps: <how/where>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise drone --settle 150 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6, low drone: <source, freq, distance>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise burst --settle 150 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6, high burst: <source, freq, distance>" --live
```

```
experiments/results/wood_20cm_none_S150_W50_Pprbs5_run1/
experiments/results/wood_20cm_taps_S150_W50_Pprbs5_run1/
experiments/results/wood_20cm_drone_S150_W50_Pprbs5_run1/
experiments/results/wood_20cm_burst_S150_W50_Pprbs5_run1/
```

### Round 2 (re-mount first)

```
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise none  --settle 150 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6, baseline" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise taps  --settle 150 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6, random taps: <how/where>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise drone --settle 150 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6, low drone: <source, freq, distance>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise burst --settle 150 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6, high burst: <source, freq, distance>" --live
```

```
experiments/results/wood_20cm_none_S150_W50_Pprbs5_run2/
experiments/results/wood_20cm_taps_S150_W50_Pprbs5_run2/
experiments/results/wood_20cm_drone_S150_W50_Pprbs5_run2/
experiments/results/wood_20cm_burst_S150_W50_Pprbs5_run2/
```

### Round 3 (re-mount first)

```
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise none  --settle 150 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6, baseline" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise taps  --settle 150 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6, random taps: <how/where>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise drone --settle 150 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6, low drone: <source, freq, distance>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise burst --settle 150 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6, high burst: <source, freq, distance>" --live
```

```
experiments/results/wood_20cm_none_S150_W50_Pprbs5_run3/
experiments/results/wood_20cm_taps_S150_W50_Pprbs5_run3/
experiments/results/wood_20cm_drone_S150_W50_Pprbs5_run3/
experiments/results/wood_20cm_burst_S150_W50_Pprbs5_run3/
```

---

## Acrylic 30 × 6, 20 cm (re-mount between runs)

```
python3 -m experiments.run_case $PORT --material acrylic --distance 20 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6" --live
python3 -m experiments.run_case $PORT --material acrylic --distance 20 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6" --live
python3 -m experiments.run_case $PORT --material acrylic --distance 20 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6" --live
```

```
experiments/results/acrylic_20cm_none_S150_W50_Pprbs5_run1/
experiments/results/acrylic_20cm_none_S150_W50_Pprbs5_run2/
experiments/results/acrylic_20cm_none_S150_W50_Pprbs5_run3/
```

## PCB 30 × 6, 20 cm (re-mount between runs)

```
python3 -m experiments.run_case $PORT --material pcb --distance 20 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6" --live
python3 -m experiments.run_case $PORT --material pcb --distance 20 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6" --live
python3 -m experiments.run_case $PORT --material pcb --distance 20 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6" --live
```

```
experiments/results/pcb_20cm_none_S150_W50_Pprbs5_run1/
experiments/results/pcb_20cm_none_S150_W50_Pprbs5_run2/
experiments/results/pcb_20cm_none_S150_W50_Pprbs5_run3/
```

---

## Extended wood, 30 cm (re-mount between runs)

```
python3 -m experiments.run_case $PORT --material wood --distance 30 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 1 --notes "extended" --live
python3 -m experiments.run_case $PORT --material wood --distance 30 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 2 --notes "extended" --live
python3 -m experiments.run_case $PORT --material wood --distance 30 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 3 --notes "extended" --live
```

```
experiments/results/wood_30cm_none_S150_W50_Pprbs5_run1/
experiments/results/wood_30cm_none_S150_W50_Pprbs5_run2/
experiments/results/wood_30cm_none_S150_W50_Pprbs5_run3/
```

## Extended wood, 50 cm (re-mount between runs)

```
python3 -m experiments.run_case $PORT --material wood --distance 50 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 1 --notes "extended" --live
python3 -m experiments.run_case $PORT --material wood --distance 50 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 2 --notes "extended" --live
python3 -m experiments.run_case $PORT --material wood --distance 50 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 3 --notes "extended" --live
```

```
experiments/results/wood_50cm_none_S150_W50_Pprbs5_run1/
experiments/results/wood_50cm_none_S150_W50_Pprbs5_run2/
experiments/results/wood_50cm_none_S150_W50_Pprbs5_run3/
```

---

## Checking the results

Materials:

```
python3 -m experiments.summarise experiments/results/wood_20cm_none_*_Pprbs5_*/*.csv experiments/results/acrylic_*_Pprbs5_*/*.csv experiments/results/pcb_*_Pprbs5_*/*.csv
```

Disturbances against the baseline:

```
python3 -m experiments.summarise experiments/results/wood_20cm_*_Pprbs5_*/*.csv
```

Distance:

```
python3 -m experiments.summarise experiments/results/wood_20cm_none_*_Pprbs5_*/*.csv experiments/results/wood_30cm_*_Pprbs5_*/*.csv experiments/results/wood_50cm_*_Pprbs5_*/*.csv
```

Filtering extension: decide every saved run's bits again with the filter, from the raw samples. Nothing is sent and no port is needed. The band is the one saved for each run's material in `experiments/filter_bands.json`, set from that material's run 1 (method in `extensions.md`), and each run gets `<case>_filter.csv` and `<case>_filter.png` next to its own files. Re-running it overwrites them.

```
python3 -m experiments.run_case --replay --extension filter
```

Only some runs, e.g. acrylic:

```
python3 -m experiments.run_case --replay experiments/results/acrylic_*_Pprbs5_run*/acrylic_*_run[0-9].csv --extension filter
```

The summaries above then show each run twice: as received by the Arduino, and as `<case>+filter`. The runs in `electrical-noise/` are one folder deeper, so give their CSVs to `--replay` directly.

Check that all 24 files exist (should print 24; this leaves out the `_filter.csv` files):

```
ls experiments/results/*_Pprbs5_run*/*_run[0-9].csv | wc -l
```

The earlier trial results are in `archive/trial_results/` and pilots go in `archive/pilot/`, so `experiments/results/` only holds this suite. Running `python3 -m experiments.summarise` with no file names summarises all of it.

## Findings so far (18 Nov 2026)

From the raw signal of the 150/50 runs recorded on 17 Nov: wood 15, 30 and 50 cm, PCB 15 cm and acrylic 15 cm, each runs 1–3.

### The leakage is the motor spinning down

After the motor is switched off, the vibration's main frequency falls steadily from the drive frequency to about 25 Hz over about 300 ms. A vibration motor's frequency is its rotation speed, so this is the rotor coasting to a stop. The specimen ringing would stay at one frequency. Median over every 1→0→0 in the runs, in 40 ms slices after switch-off:

| ms after motor off | 20 | 60 | 100 | 140 | 180 | 220 | 260 | 300 | 340 | 380 |
|---|---|---|---|---|---|---|---|---|---|---|
| **wood**, frequency (Hz) | 106 | 81 | 68 | 64 | 54 | 36 | 27 | 25 | 25 | 24 |
| wood, peak-to-peak | 63.6k | 28.0k | 19.1k | 13.6k | 6.6k | 6.0k | 4.2k | 2.8k | 2.1k | 1.6k |
| **acrylic**, frequency (Hz) | 119 | 76 | 67 | 59 | 49 | 42 | 37 | 29 | 26 | 25 |
| acrylic, peak-to-peak | 64.4k | 21.0k | 12.4k | 10.6k | 9.8k | 11.6k | 17.4k | 11.8k | 8.3k | 6.5k |
| **PCB**, frequency (Hz) | 108 | 92 | 67 | 54 | 46 | 37 | 30 | 26 | 25 | 26 |
| PCB, peak-to-peak | 13.7k | **53.9k** | **48.8k** | 8.3k | 10.8k | 12.4k | 8.6k | 5.2k | 4.2k | 2.9k |

(n = 356 for wood, 108 for acrylic and 108 for PCB. The acrylic row includes runs 2 and 3, whose electrical spikes are single samples and barely move these medians.)

- While the motor is driven, the main frequency is about 113–123 Hz. In the measuring window, 150–200 ms after a switch-off, the motor is down to about 50–60 Hz. That difference is what a frequency-based detector can use.
- **PCB resonates.** As the motor slows through about 70–90 Hz, it hits the board's resonance, and the signal gets *bigger* 60–100 ms after switch-off. So on PCB a 0 after a 1 reads as large as a 1: median peak-to-peak 10.8k against 10.2k for 1s. No amplitude threshold can separate them.
- **Acrylic has a second bump** at about 220–300 ms, where the signal grows again to about 17k. It's probably a lower resonance of the acrylic. It falls in the next bit, so a 0 two bits after a 1 can also be affected.
- **Wood decays smoothly**, with no resonance in the range the motor sweeps through.

### Which raw-signal measures separate a 1 from a 0 after a 1

Errors at the best single threshold for each measure (wood 2,507 bits, acrylic 759, PCB 759). The threshold was chosen on the same data, so these are optimistic: for the report, choose it on run 1 and test on runs 2–3.

| Measure, in the 50 ms window | wood | acrylic | PCB |
|---|---|---|---|
| Peak-to-peak (the current receiver) | 11 | 0 | **148** |
| Main frequency | 33 | 42 | **1** |
| Size in the last 50 ms of the bit ÷ size in the first 50 ms | **2** | **0** | 129 |

Frequency fixes PCB, and the decay trend fixes wood and acrylic, so the two together should work on all three. These are the basis of the DSP extension.

### PCB's higher noise floor is mains pickup

With the motor off for at least two bits, PCB's quiet peak-to-peak is about 720, against about 370 for wood and 330 for acrylic. Its main frequency is a steady 50 Hz (48–50 Hz), the UK mains frequency, while wood and acrylic show a mixture of low frequencies. The copper on the PCB most likely picks up mains hum like an antenna and couples it into the piezo; wood and acrylic are insulators. Connecting the copper to the Giga's GND should confirm it, if the noise floor drops. It only raises PCB's threshold by about 700 (4,100 against 3,400), which barely changes its errors.

### Electrical noise from the motor supply (acrylic runs 2 and 3)

Acrylic runs 2 and 3 (20:40, 17 Nov) caught one-sample electrical spikes of 7,000–20,000 counts from the motor supply. They are kept in `experiments/results/electrical-noise/` and are not part of the suite. One spike landed in calibration, so the thresholds were 9,616 and 12,686. Re-reading every run at one shared threshold from the saved vibration values:

| Run | Own threshold | Errors | At 3,400 | At 4,100 |
|---|---|---|---|---|
| acrylic run 1 | 3,368 | 14.5% | 14.5% | 13.7% |
| acrylic run 2 (noisy) | 9,616 | 12.2% | 24.9% | 24.4% |
| acrylic run 3 (noisy) | 12,686 | 8.0% | 24.9% | 24.7% |
| PCB runs 1–3 | 4,055–4,108 | 13.7–17.5% | 16.5–20.0% | 13.7–17.5% |
| wood, all 9 runs | 3,421–3,503 | 13.5% | 13.5% | 13.5% |

- At a shared threshold, every run has the same 54 leakage errors (a 0 straight after a 1), so the leakage behaves the same on all three materials at 150/50. Anything beyond 54 comes from something else: the spikes in acrylic runs 2 and 3, and the resonance in PCB.
- Their high thresholds hid most of the leakage, which made those runs look better than run 1. At a shared threshold the spikes get through, and they look about twice as bad. Neither version describes acrylic, so they need re-running once the supply noise is fixed.
- Peak-to-peak is very sensitive to a single spike. In the noisy runs, the largest quiet reading was 19,800–20,700 by peak-to-peak, but only 2,800–3,100 after a 3-sample median filter and 1,000–1,200 by RMS. RMS or band energy would make the receiver resistant to this kind of noise.

## Notes for the report

- **Distance is mixed up with geometry.** The 20 cm baseline uses the 30 × 6 specimen, but 30 cm and 50 cm use the extended one. If there's time, run extended wood at 20 cm as a control. Using `wood-ext` keeps it from overwriting the baseline:

  ```
  python3 -m experiments.run_case $PORT --material wood-ext --distance 20 --noise none --settle 150 --window 50 --prbs-per-code --sets 1 --run 1 --notes "extended, geometry control" --live
  ```
  → `experiments/results/wood-ext_20cm_none_S150_W50_Pprbs5_run1/`

- **Signal margin when there are no errors.** Every CSV stores the measured vibration for each bit (`vibration`) and the threshold. For each run, take the gap between the weakest "1" and the strongest "0", relative to the threshold. A smaller gap means that setup is closer to failing, even if it made no errors yet. Use this to compare materials and distances if their error rates are all zero.

- **Disturbances must be repeatable.** Taps on a fixed rhythm (e.g. a metronome app), with similar force at the same spot. Drone and burst from the same source, volume and position every time. Keep them going for the whole run, so that every code's string is hit, not just whichever one was being sent when a burst happened.

- **Sample size.** Each code gets 31 message bits per run, so 93 per case. A code with no errors in 93 bits still has a 95% upper bound of about 4% on its error rate. That's enough to separate "works" from "fails badly", but not to rank codes that all get close to zero. Mounting is re-done for each run, so report the spread across runs 1–3 as well as the mean.
