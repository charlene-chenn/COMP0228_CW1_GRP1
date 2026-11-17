# Experiment suite

There are 8 test cases with 3 runs each, so 24 runs in all. In each run, the same PRBS-5 string (31 bits) goes through every code once, in shuffled order:

| Code | Channel bits sent |
|---|---|
| none (uncoded baseline) | 31 |
| R3 | 93 |
| R5 | 155 |
| hamming74 (padded to 32) | 56 |
| conv75 | 66 |

That's 401 channel bits per run, which takes **about 45 seconds** including calibration. The `none` string is the uncoded baseline. Every coded string's raw channel bits are saved too, so each one also counts as a noise sample.

**Each run produces three things:**
- `experiments/results/<case>.csv`: one row per string.
- `experiments/results/<case>.png`: the viewer as it was at the end of the run, saved by `--live`.
- `experiments/results/<case>_raw/`: one `.npz` per string, `codes_<set>_<code>.npz`, holding the raw piezo samples at 10 kHz for every bit, for the extensions.

The file lists below give the CSV name. The `.png` and the `_raw/` folder always sit next to it with the same name.

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

- **Settle 50 ms, window 50 ms, whatever the pilot shows.** Each bit takes 102.4 ms, so about 9.8 bit/s before coding. This was decided before seeing any data from the new mount, and it stays the same for all 24 runs even if the baseline turns out error-free. If the speed were changed after looking at the baseline, cases run at different speeds couldn't be compared, and it would look like the speed was tuned to get a result. If the baseline is clean, the disturbance cases supply the physical noise. Material and distance are then compared by signal margin instead of error rate (see the notes at the end).
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
- `Raw:` should be 1024 samples per bit (at 50/50).
- `Switch at:` is how many samples into each bit the motor switched. It's the time spent sending the previous bit's samples (10 samples = 1 ms). A few tens is fine.
- `Late bits:` should be 0. If it isn't, the board can't send raw samples fast enough and bits are running long. Stop and tell the group before running anything.

Close the Arduino Serial Monitor and Plotter first. Keep the surface still while it calibrates at the start of each run.

## Pilot (once, before the suite)

The earlier trial runs were done before the current mount, and partly while damping was being added. They don't show how noisy the channel is now. This pilot checks the baseline on the setup as it will be used: wood 30 × 6, 20 cm, proper mount, no damping, no disturbance. It takes about 10 seconds.

```
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise none --settle 50 --window 50 --prbs-only --prbs-repeats 3 --run 0 --notes "pilot, new mount, no damping" --live
```

→ `experiments/results/wood_20cm_none_S50_W50_M32_run0.csv`

Write down the error rate it prints, then move its files out of the suite's folder:

```
mv experiments/results/wood_20cm_none_S50_W50_M32_run0.csv experiments/results/wood_20cm_none_S50_W50_M32_run0.png experiments/results/wood_20cm_none_S50_W50_M32_run0_raw archive/trial_results/
```

The pilot is only there to know what to expect. **It doesn't change the settings** (see the 50/50 rule above):

- **Some errors (roughly 1–10%):** all cases give error rates to compare.
- **No or almost no errors:** go ahead unchanged. The baseline is the clean control, and the disturbance cases are where the codes get compared.

## Rules for every run

- **Re-mount between runs.** Take the piezo and motor off and put them back on the marks before each new run number. Then the 3 runs measure how much mounting varies, rather than repeating one mounting.
- **If a run stops,** run the exact same command again. It carries on from the last saved string.
- **If the setup changed in the middle of a run,** delete that CSV, its `.png` and its `_raw/` folder, then run the command again from the start.
- Write anything unusual in `--notes`. It's saved in every row.
- **`--live`** opens the viewer:
  - the raw piezo signal for the latest 6 bits, with each bit's measuring window and what it was read as;
  - the vibration per bit;
  - a channel error map for each coded string;
  - a map of message bits still wrong after decoding;
  - the error statistics.

  It saves the `.png` when the run finishes. Closing the window stops the run after the current string. To redraw a saved run: `python3 -m experiments.live_view experiments/results/<case>.csv`.
- **Check `late_bits` in the CSV** after the first run. It should be 0 in every row.

## Order

- **Rounds 1–3 (wood 30 × 6, 20 cm):** mount, then run the baseline, taps, drone and burst cases. Re-mount, then do the next round. Each disturbance run is then compared with a baseline on the same mounting.
- **Acrylic, PCB, extended wood 30 cm and 50 cm:** 3 runs each, re-mounting between runs.

Disturbances: replace the `<...>` in `--notes` with what made each one and where it was, e.g. the source, its frequency or volume, how far away it was, and the tapping rhythm. Use the same source and position in all 3 runs.

---

## Rounds 1–3: wood 30 × 6, 20 cm, baseline and disturbances

### Round 1

```
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise none  --settle 50 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6, baseline" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise taps  --settle 50 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6, random taps: <how/where>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise drone --settle 50 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6, low drone: <source, freq, distance>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise burst --settle 50 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6, high burst: <source, freq, distance>" --live
```

```
experiments/results/wood_20cm_none_S50_W50_Pprbs5_run1.csv
experiments/results/wood_20cm_taps_S50_W50_Pprbs5_run1.csv
experiments/results/wood_20cm_drone_S50_W50_Pprbs5_run1.csv
experiments/results/wood_20cm_burst_S50_W50_Pprbs5_run1.csv
```

### Round 2 (re-mount first)

```
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise none  --settle 50 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6, baseline" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise taps  --settle 50 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6, random taps: <how/where>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise drone --settle 50 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6, low drone: <source, freq, distance>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise burst --settle 50 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6, high burst: <source, freq, distance>" --live
```

```
experiments/results/wood_20cm_none_S50_W50_Pprbs5_run2.csv
experiments/results/wood_20cm_taps_S50_W50_Pprbs5_run2.csv
experiments/results/wood_20cm_drone_S50_W50_Pprbs5_run2.csv
experiments/results/wood_20cm_burst_S50_W50_Pprbs5_run2.csv
```

### Round 3 (re-mount first)

```
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise none  --settle 50 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6, baseline" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise taps  --settle 50 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6, random taps: <how/where>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise drone --settle 50 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6, low drone: <source, freq, distance>" --live
python3 -m experiments.run_case $PORT --material wood --distance 20 --noise burst --settle 50 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6, high burst: <source, freq, distance>" --live
```

```
experiments/results/wood_20cm_none_S50_W50_Pprbs5_run3.csv
experiments/results/wood_20cm_taps_S50_W50_Pprbs5_run3.csv
experiments/results/wood_20cm_drone_S50_W50_Pprbs5_run3.csv
experiments/results/wood_20cm_burst_S50_W50_Pprbs5_run3.csv
```

---

## Acrylic 30 × 6, 20 cm (re-mount between runs)

```
python3 -m experiments.run_case $PORT --material acrylic --distance 20 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6" --live
python3 -m experiments.run_case $PORT --material acrylic --distance 20 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6" --live
python3 -m experiments.run_case $PORT --material acrylic --distance 20 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6" --live
```

```
experiments/results/acrylic_20cm_none_S50_W50_Pprbs5_run1.csv
experiments/results/acrylic_20cm_none_S50_W50_Pprbs5_run2.csv
experiments/results/acrylic_20cm_none_S50_W50_Pprbs5_run3.csv
```

## PCB 30 × 6, 20 cm (re-mount between runs)

```
python3 -m experiments.run_case $PORT --material pcb --distance 20 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 1 --notes "30x6" --live
python3 -m experiments.run_case $PORT --material pcb --distance 20 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 2 --notes "30x6" --live
python3 -m experiments.run_case $PORT --material pcb --distance 20 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 3 --notes "30x6" --live
```

```
experiments/results/pcb_20cm_none_S50_W50_Pprbs5_run1.csv
experiments/results/pcb_20cm_none_S50_W50_Pprbs5_run2.csv
experiments/results/pcb_20cm_none_S50_W50_Pprbs5_run3.csv
```

---

## Extended wood, 30 cm (re-mount between runs)

```
python3 -m experiments.run_case $PORT --material wood --distance 30 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 1 --notes "extended" --live
python3 -m experiments.run_case $PORT --material wood --distance 30 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 2 --notes "extended" --live
python3 -m experiments.run_case $PORT --material wood --distance 30 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 3 --notes "extended" --live
```

```
experiments/results/wood_30cm_none_S50_W50_Pprbs5_run1.csv
experiments/results/wood_30cm_none_S50_W50_Pprbs5_run2.csv
experiments/results/wood_30cm_none_S50_W50_Pprbs5_run3.csv
```

## Extended wood, 50 cm (re-mount between runs)

```
python3 -m experiments.run_case $PORT --material wood --distance 50 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 1 --notes "extended" --live
python3 -m experiments.run_case $PORT --material wood --distance 50 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 2 --notes "extended" --live
python3 -m experiments.run_case $PORT --material wood --distance 50 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 3 --notes "extended" --live
```

```
experiments/results/wood_50cm_none_S50_W50_Pprbs5_run1.csv
experiments/results/wood_50cm_none_S50_W50_Pprbs5_run2.csv
experiments/results/wood_50cm_none_S50_W50_Pprbs5_run3.csv
```

---

## Checking the results

Materials:

```
python3 -m experiments.summarise experiments/results/wood_20cm_none_*_Pprbs5_*.csv experiments/results/acrylic_*_Pprbs5_*.csv experiments/results/pcb_*_Pprbs5_*.csv
```

Disturbances against the baseline:

```
python3 -m experiments.summarise experiments/results/wood_20cm_*_Pprbs5_*.csv
```

Distance:

```
python3 -m experiments.summarise experiments/results/wood_20cm_none_*_Pprbs5_*.csv experiments/results/wood_30cm_*_Pprbs5_*.csv experiments/results/wood_50cm_*_Pprbs5_*.csv
```

Check that all 24 files exist (should print 24):

```
ls experiments/results/*_Pprbs5_run*.csv | wc -l
```

The earlier trial results are in `archive/trial_results/`, so `experiments/results/` only holds this suite. Running `python3 -m experiments.summarise` with no file names summarises all of it.

## Notes for the report

- **Distance is mixed up with geometry.** The 20 cm baseline uses the 30 × 6 specimen, but 30 cm and 50 cm use the extended one. If there's time, run extended wood at 20 cm as a control. Using `wood-ext` keeps it from overwriting the baseline:

  ```
  python3 -m experiments.run_case $PORT --material wood-ext --distance 20 --noise none --settle 50 --window 50 --prbs-per-code --sets 1 --run 1 --notes "extended, geometry control" --live
  ```
  → `experiments/results/wood-ext_20cm_none_S50_W50_Pprbs5_run1.csv`

- **Signal margin when there are no errors.** Every CSV stores the measured vibration for each bit (`vibration`) and the threshold. For each run, take the gap between the weakest "1" and the strongest "0", relative to the threshold. A smaller gap means that setup is closer to failing, even if it made no errors yet. Use this to compare materials and distances if their error rates are all zero.

- **Disturbances must be repeatable.** Taps on a fixed rhythm (e.g. a metronome app), with similar force at the same spot. Drone and burst from the same source, volume and position every time. Keep them going for the whole run, so that every code's string is hit, not just whichever one was being sent when a burst happened.

- **Sample size.** Each code gets 31 message bits per run, so 93 per case. A code with no errors in 93 bits still has a 95% upper bound of about 4% on its error rate. That's enough to separate "works" from "fails badly", but not to rank codes that all get close to zero. Mounting is re-done for each run, so report the spread across runs 1–3 as well as the mean.
