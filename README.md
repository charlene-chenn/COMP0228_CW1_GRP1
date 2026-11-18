# COMP0228 CW1

Sends coded bits across a motor-to-piezo vibration channel. Python does the encoding and decoding, and the Arduino Giga sends and measures the bits.

## Setup

```
pip install -r requirements.txt
```

Install `Arduino_AdvancedAnalog` from the Arduino Library Manager, then upload `piezo_receiver_v3/piezo_receiver_v3.ino` to the Giga (board "Arduino GIGA R1 WiFi", M7 core). Close the Serial Monitor and Plotter afterwards, as only one program can use the port.

Wiring:

- Front-end ADC node (after R5/C3/clamps) to A0
- Driver Signal to D3, driver GND to Giga GND. Don't connect driver V+ to the Giga.
- Power the motor from its own supply through the driver's terminal blocks

The sketch waits for the port to open, then calibrates. `NOISE_MARGIN` in the sketch is set for the big piezo.

## Use

Run from this folder:

```
python3 run_sim.py                     # all codes, simulated channel
python3 -m channel.hardware            # list serial ports
python3 -m channel.hardware <port>     # test the real channel
```

Keep the surface still during calibration.

## Experiments

Set up a test case, then run it through every code. Each string is saved to `experiments/results/<case>/<case>.csv` as it finishes, and running the same command again carries on from where it stopped.

```
# Quick look at a setting: 10 PRBS-5 strings
python3 -m experiments.run_case <port> --material wood --distance 20 --settle 50 --window 50 --prbs-only --live

# Full case: 10 PRBS-5 strings, 20 32-bit messages through every code, 1 PRBS-5 reference
python3 -m experiments.run_case <port> --material wood --distance 20 --noise fan --settle 50 --window 50 --live

# Tables of the results so far
python3 -m experiments.summarise

# Redraw and save the viewer for a saved case
python3 -m experiments.live_view experiments/results/<case>/<case>.csv
```

The full list of commands for the experiment suite is in `experiment.md`. Use `--prbs-per-code` to send one PRBS-5 string through every code and nothing else; the `none` code is then the uncoded baseline.

The raw piezo samples (10 kHz) for every string are saved in `experiments/results/<case>/raw/`, one `.npz` per string. `save_raw` in `experiments/run_case.py` describes what each file holds. Add `--no-raw` to skip them. With `--live`, the viewer also shows the raw signal for the latest bits, and a second window (Raw signal scope, `experiments/scope.py`) shows it scrolling smoothly.

A full case at 50/50 takes about 14.6 minutes. Use `--codes none R3 R5` to run only some codes, or `--message-bits 64` for longer messages. Add `--run 2` when repeating a case, for example after re-mounting the piezo. Closing the viewer stops the case after the current string. Use `--sim` in place of `<port>` to try all of this with no hardware; those results go in `experiments/results/sim/`, which git ignores.

## Receiver extensions

An extension decides the bits again from a string's raw samples, in place of the Arduino's peak-to-peak and threshold, and the string's code then decodes those bits. The sending doesn't change, so every run with raw samples gives results for both. Each extension's results go in `<case>_<extension>.csv` next to the case's CSV, with the same columns, so `experiments.summarise` shows them as their own case (`<case>+filter`). The settings used are in the `notes` column. Its picture, `<case>_<extension>.png`, is saved alongside: the same view as the case's own picture, with the extension's decisions and its level for each bit (redraw it with `python3 -m experiments.live_view <case>_<extension>.csv`). The extensions are listed in `experiments/extensions.py`; `filter` is the filtering in `codes/filtering.py`.

```
# During a run: print the extension's errors under each string, and save its results at the end
python3 -m experiments.run_case <port> --material wood --distance 15 --settle 150 --window 50 --prbs-per-code --sets 1 --extension filter

# Only the extension, on saved runs (sends nothing, needs no port)
python3 -m experiments.run_case --replay --extension filter
python3 -m experiments.run_case --replay experiments/results/<case>/<case>.csv --extension filter

# Filter settings
python3 -m experiments.run_case --replay --extension filter --filter-band 70 105
python3 -m experiments.run_case --replay --extension filter --filter-band 20 200 --filter-sharpen 40 --filter-notch 50
```

The filter's pass band is set once for each material, from the motor's frequency peak in all of that material's run 1 (`find_motor_band` in `codes/filtering.py`), and saved in `experiments/filter_bands.json`. Every run of that material then uses it (`--filter-band material`, the default), including live runs. Set or reset a material's band with `python3 -m experiments.run_case --set-band experiments/results/<run 1>/<run 1>.csv`. `--filter-band auto` finds the peak in each string by itself instead, and `LO HI` gives a fixed band in Hz. With `--live`, the filter gets its own window too, updated as each string finishes. The method and results are in `extensions.md`. Re-running `--replay` overwrites the extension's CSVs, so the latest settings are always what's saved.

## Raw signal files

Each run gets its own folder holding its CSV, its picture and a `raw/` folder of raw piezo signals, one `.npz` per string sent, named `<block>_<set>_<code>.npz`. For example, one `--prbs-per-code --sets 1` run gives:

```
experiments/results/wood_20cm_none_S50_W50_Pprbs5_run1/
    wood_20cm_none_S50_W50_Pprbs5_run1.csv
    wood_20cm_none_S50_W50_Pprbs5_run1.png
    wood_20cm_none_S50_W50_Pprbs5_run1.mp4
    raw/
        codes_0_none.npz
        codes_0_R3.npz
        codes_0_R5.npz
        codes_0_hamming74.npz
        codes_0_conv75.npz
```

A full case or `--prbs-only` names the other blocks the same way: `prbs5_0_none.npz`, `prbs5_1_none.npz`, …, `reference_0_none.npz`. With `--sim` the run folders go under `experiments/results/sim/`, which git ignores.

Each CSV row's `raw_file` column names its file relative to the CSV, e.g. `raw/codes_0_R3.npz`.

When a run finishes, `run_case` also makes `<case>.mp4` in the same folder. It's a video of the raw signal scrolling through the whole run at real speed, with the bit sent, what it was read as and each measuring window marked. It needs ffmpeg (`brew install ffmpeg` or `pip install imageio-ffmpeg`). Add `--no-video` to skip it, or make one later:

```
python3 -m experiments.make_video experiments/results/<case>/<case>.csv
```

To load one string:

```python
import numpy as np
d = np.load("experiments/results/wood_20cm_none_S50_W50_Pprbs5_run1/raw/codes_0_R3.npz")
start = d["bit_start"]
bit_5 = d["samples"][start[5]:start[6]]   # 1024 samples at 10 kHz for bit 5
```

Each file also holds:

- `sent`, `received`, `vibration` and `threshold`: the same values as the CSV
- `sample_rate`, `settle_ms` and `window_ms`
- `switch_offset`: how many samples into each bit the motor was switched
- `late_bits`: bits that ran long, leaving a gap in the recording after them; should be 0

Within each bit, the measuring window runs from `settle_ms` to `settle_ms + window_ms` after the start of the bit.

A run is roughly 400 bits × 1024 samples × 2 bytes, so about 0.8 MB before compression, and about 20 MB for the whole 24-run suite.
