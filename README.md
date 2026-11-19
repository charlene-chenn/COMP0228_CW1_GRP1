# COMP0228 CW1: a vibration communication channel

We send bits through a solid surface. A vibration motor on the specimen is switched on and off to send them, and a piezo disc on the same specimen picks the vibration up. An Arduino Giga R1 drives the motor and samples the piezo. Python on the laptop encodes each message with an error-correcting code, sends it, and decodes what comes back.

We measured how well this works on three materials, at three distances and under two kinds of disturbance, with five codes. Then we added two receiver extensions that target the main source of errors we found: a band-pass filter, and a small neural network (a 1D CNN) trained on the recorded signals.

## How the channel works

```
laptop: encode -> USB -> Giga D3 -> motor driver -> motor -> specimen -> piezo -> front end -> Giga A0 -> threshold -> USB -> laptop: decode
```

- **Modulation: on-off keying.** A 1 is the motor on for the whole bit, a 0 is the motor off. A vibration motor's frequency and phase can't be controlled precisely, so frequency or phase keying isn't practical. Whether it is vibrating can be.
- **Timing: settle 150 ms, then measure for 50 ms.** Each bit takes 204.8 ms (rounded up to whole 25.6 ms DMA buffers), so the raw rate is about 4.9 bit/s. 150/50 came from a settle sweep: at 50/50 the bit error rate was 45%, at 100/50 39% and at 150/50 26%. The motor takes about 250 ms to coast to a stop (details in `experiment.md`, "Pilot and settle sweep").
- **Receiver: peak-to-peak against a threshold.** The Giga samples A0 at 10 kHz. Each bit's reading is the highest sample minus the lowest in its measuring window. It is read as a 1 if that's above a threshold, set at start-up from 3 s of background noise (the loudest noise + 3,000 ADC counts).
- **Codes (in Python, `codes/`):** uncoded (`none`), repetition R3 and R5, Hamming(7,4) and a rate-1/2 convolutional code (generators 7, 5, Viterbi decoding). Keeping them in Python means a new code needs no firmware change, and the same code runs on the simulated channel (`run_sim.py`).

## Experiments

Each run sends the same PRBS-5 string (31 bits) through every code once, in a shuffled order: 401 channel bits per run. Each case has 3 runs, with the motor and piezo re-mounted between runs. Every run saves the raw piezo samples, so results can be re-analysed later without new hardware runs. The full procedure is in `experiment.md`.

| Case | Material | Motor to piezo | Disturbance | Runs | Results folders |
|---|---|---|---|---|---|
| Wood, 15 cm (baseline) | wood | 15 cm | none | 3 | `wood_15cm_none_*` |
| Wood, 30 cm | wood | 30 cm | none | 3 | `wood_30cm_none_*` |
| Wood, 45 cm | wood | 45 cm | none | 3 | `wood_450cm_none_*` (typo in the folder name: it was 45 cm) |
| Acrylic, 15 cm | acrylic | 15 cm | none | 3 | `acrylic_15cm_none_*` |
| PCB, 15 cm | PCB | 15 cm | none | 3 | `pcb_15cm_none_*` |
| Wood, 15 cm, constant noise | wood | 15 cm | constant | 4 | `wood_15cm_constant_noise_*` |
| Wood, 15 cm, burst noise | wood | 15 cm | bursts | 3 | `wood_15cm_burst_*` |

All at settle 150 ms, window 50 ms. Not in the tables below:
- `wood_15cm_none_*_run4` and `acrylic_15cm_none_*_run4`: 3 uncoded strings each, sent to test the filter live.
- `wood_45cm_burst-on_*`: an early trial that stopped after 2 strings.
- `electrical-noise/`: acrylic runs spoiled by spikes from the motor's power supply (see below).

## Core results

### Summary

- **The main source of errors is intersymbol interference, not random noise.** With the Arduino's peak-to-peak receiver, every 0 sent straight after a 1 is read as a 1, because the motor is still coasting down. That gives 13.5–15.5% channel errors in every case.
- **Codes alone are a poor fix.** Only repetition corrects it (R3 and R5, 0–5% message errors), at a third or a fifth of the data rate. Hamming(7,4) leaves 23–28% message errors, and the convolutional code makes them worse (51–65%), because the errors come in patterns.
- **The filter removes the interference.** With no disturbance, channel errors fall to 0–1.2% and every code decodes correctly, uncoded included. Under disturbance its midpoint threshold is the weak point: 7.8% channel errors with constant noise, and 23.8% with bursts (worse than the plain receiver).
- **The network also removes it, and handles bursts best.** It has 0 channel errors in every case without disturbance (on wood and acrylic these are runs it was trained on; PCB it never saw). Under bursts it has 4.6% channel errors, and R3, R5 and the convolutional code then decode everything. Under constant noise it does worst of the two extensions (11.9%), reading most zeros after a 1 as 1s again.
- **Fixing the receiver works better than adding redundancy.** With a good receiver, a rate-1/2 convolutional code is enough to decode every message in each condition:

| Condition | Best receiver | Message errors with the convolutional code |
|---|---|---|
| No disturbance | filter or network | 0% |
| Constant noise | filter | 0% |
| Burst noise | network | 0% |

### Channel errors

Bit errors before decoding, all 3 runs together (4 for constant noise), with 95% Wilson confidence intervals. † marks cases the network was trained on, which aren't a fair test of it (see the notes below).

| Case | Receiver (peak-to-peak) | Receiver + filter extension | Receiver + network extension |
|---|---|---|---|
| Wood, 15 cm | 162 / 1203 = 13.5% [11.7, 15.5] | 0 / 1203 = 0.0% [0.0, 0.3] | 0 / 1203 = 0.0% [0.0, 0.3] † |
| Wood, 30 cm | 162 / 1203 = 13.5% [11.7, 15.5] | 15 / 1203 = 1.2% [0.8, 2.0] | 0 / 1203 = 0.0% [0.0, 0.3] † |
| Wood, 45 cm | 162 / 1203 = 13.5% [11.7, 15.5] | 5 / 1203 = 0.4% [0.2, 1.0] | 0 / 1203 = 0.0% [0.0, 0.3] † |
| Acrylic, 15 cm | 176 / 1203 = 14.6% [12.7, 16.7] | 0 / 1203 = 0.0% [0.0, 0.3] | 0 / 1203 = 0.0% [0.0, 0.3] † |
| PCB, 15 cm | 184 / 1203 = 15.3% [13.4, 17.4] | 0 / 1203 = 0.0% [0.0, 0.3] | 0 / 1203 = 0.0% [0.0, 0.3] |
| Wood, 15 cm, constant noise | 218 / 1604 = 13.6% [12.0, 15.4] | 125 / 1604 = 7.8% [6.6, 9.2] | 191 / 1604 = 11.9% [10.4, 13.6] |
| Wood, 15 cm, burst noise | 186 / 1203 = 15.5% [13.5, 17.6] | 286 / 1203 = 23.8% [21.5, 26.3] | 55 / 1203 = 4.6% [3.5, 5.9] |

### Message errors after decoding

Message bit error rate for each configuration and code: the share of decoded message bits that were wrong, all runs together (93 message bits per code, 124 for constant noise). † = the network was trained on these runs.

| Configuration | Receiver | none (rate 1) | R3 (rate 1/3) | R5 (rate 1/5) | Hamming(7,4) (rate 4/7) | Convolutional 7,5 (rate 1/2) |
|---|---|---|---|---|---|---|
| Wood, 15 cm | peak-to-peak | 25.8% | 0.0% | 0.0% | 25.8% | 64.5% |
| | filter | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| | network † | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Wood, 30 cm | peak-to-peak | 25.8% | 0.0% | 0.0% | 25.8% | 64.5% |
| | filter | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| | network † | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Wood, 45 cm | peak-to-peak | 25.8% | 0.0% | 0.0% | 25.8% | 64.5% |
| | filter | 1.1% | 0.0% | 0.0% | 0.0% | 0.0% |
| | network † | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Acrylic, 15 cm | peak-to-peak | 26.9% | 4.3% | 0.0% | 28.0% | 63.4% |
| | filter | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| | network † | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| PCB, 15 cm | peak-to-peak | 33.3% | 2.2% | 0.0% | 28.0% | 61.3% |
| | filter | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| | network | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| Wood, 15 cm, constant noise | peak-to-peak | 26.6% | 0.0% | 0.0% | 25.8% | 64.5% |
| | filter | 1.6% | 12.1% | 12.1% | 0.0% | 0.0% |
| | network | 18.5% | 0.0% | 0.0% | 28.2% | 59.7% |
| Wood, 15 cm, burst noise | peak-to-peak | 23.7% | 5.4% | 1.1% | 22.6% | 50.5% |
| | filter | 2.2% | 30.1% | 38.7% | 12.9% | 14.0% |
| | network | 3.2% | 0.0% | 0.0% | 1.1% | 0.0% |

The convolutional code sends 66 channel bits for its 31 message bits (rate 0.47, with the tail bits). Hamming pads the message to 32 bits, so 56 channel bits (rate 0.55).

### What the results show

- **The errors aren't random.** With the plain receiver, every 0 sent straight after a 1 is read as a 1: 54 per run, on every material and distance and under constant noise. Under burst noise it's 140 of 162, as one run calibrated a higher threshold (4,140 against about 3,470). The motor is still coasting down when the next bit is measured, so its vibration leaks into the next bit. That's intersymbol interference, not random noise. On wood without disturbance, these are the only errors. The other errors are a few 0s further after a 1 on acrylic (14) and PCB (22), and some errors under burst noise (46 of 186). No 1 is ever read as a 0.
- **The codes built for random errors don't help.** Hamming(7,4) leaves message errors where they were (26%), and the convolutional code makes them much worse (65%), because the errors come in patterns rather than one at a time. Only repetition fixes them (R3 and R5, near 0%), at the cost of a third or a fifth of the data rate.
- **The filter removes the leakage.** The motor vibrates at 111–123 Hz while driven, but has slowed to about 40–60 Hz by the time the next bit is measured. Keeping only a band around the drive frequency drops the leftover vibration. Channel errors fall from 13–15% to 0–1.2% on every material and distance, and every code then decodes correctly, uncoded included. PCB was the hardest case for the plain receiver, because a 0 after a 1 reads as loud as a 1 there. With the filter it goes to 0.
- **The filter struggles under disturbance.** With the filter, every error under noise is a 1 read as a 0:
  - **Constant noise:** runs 1–2 are near 0 (0 and 2 errors). Runs 3–4 have 77 and 46, almost all from two strings where a few very loud bits pulled the filter's threshold above the normal 1s.
  - **Burst noise:** worse than the plain receiver overall.

  Both come from the filter's midpoint threshold, which is set halfway between each string's quiet and loud bits, so a few loud bits drag it upwards. Starting that search from the median level instead brings constant noise down to 2 errors (from 125) and burst noise to 175 (from 286). This was checked offline only and isn't in the code.
- **The network learns the leakage too, and copes better with bursts.** On PCB, which it never saw in training, it reads every bit correctly, like the filter. Under burst noise it has 55 channel errors against the filter's 286, and R3, R5 and the convolutional code then decode everything. Most of its remaining burst errors (48 of 55) are a 0 after a 0 read as a 1, where a knock looks like the motor running.
- **The network fails under constant noise.** It reads 186 of the 216 zeros sent after a 1 as 1s, the exact error it was trained to fix, so it does worse than the filter (191 errors against 125) and the convolutional code goes back to 60% message errors. It was only trained on quiet runs, and its envelope isn't band-passed, so a steady noise floor raises every level and a 0 after a 1 no longer looks like one it has seen. Training on noisy runs too, or band-passing before the envelope, would be the next things to try.

Notes on these numbers:
- The filter's band for each material was set from wood, acrylic and PCB 15 cm run 1, so those three runs aren't a fair test of the filter. Their results (0 errors) match the other runs.
- The filter results are offline. They come from running the filter on the raw samples each run recorded, not from separate hardware runs. The same filter also runs during a live run (see "Receiver extensions").
- The network was trained on every wood and acrylic run without disturbance (marked †), so its 0 errors there show only that it fits its training data. PCB, constant noise and burst noise are the fair tests: it never saw those runs. Its results are offline too.
- 3 runs × 31 message bits per code is a small sample. The Wilson intervals above are for channel bits. Message-level intervals are wider.

### Other findings

- **The motor supply injected noise.** With the motor's bench supply switched on, single-sample spikes of 7,000–20,000 ADC counts appeared on A0 even with the motor idle. This raised the calibrated threshold from about 3,400 to 9,600–12,700. Turning the supply off removed them. Those acrylic runs are in `electrical-noise/` and were re-run.
- **PCB picks up 50 Hz mains.** Its quiet noise floor (peak-to-peak about 720) is about twice that of wood and acrylic, at a steady 50 Hz, most likely through its copper. It raises PCB's threshold by only about 700.
- **PCB resonates** as the motor slows through about 70–90 Hz, so its leftover vibration gets louder 60–100 ms after switch-off. The spin-down measurements are in `experiment.md`, "Findings so far".

## Setup

```
pip install -r requirements.txt
```

Install `Arduino_AdvancedAnalog` from the Arduino Library Manager, then upload `piezo_receiver_v3/piezo_receiver_v3.ino` to the Giga (board "Arduino GIGA R1 WiFi", M7 core). Close the Serial Monitor and Plotter afterwards, as only one program can use the port.

Wiring:

- Front-end ADC node (after R5/C3/clamps) to A0
- Driver Signal to D3, driver GND to Giga GND. Don't connect driver V+ to the Giga.
- Power the motor from its own supply through the driver's terminal blocks

The sketch waits for the port to open, then calibrates. `NOISE_MARGIN` in the sketch is set for the big piezo. Keep the surface still during calibration.

```
python3 run_sim.py                     # all codes, simulated channel
python3 -m channel.hardware            # list serial ports; the Giga is /dev/cu.usbmodemXXXX
python3 -m channel.hardware $PORT      # test the real channel
```

## Running experiments

One run of a case, as in the suite (see `experiment.md` for every case):

```
python3 -m experiments.run_case $PORT --material wood --distance 15 --settle 150 --window 50 --prbs-per-code --sets 1 --run 1 --live
```

- Each string is saved to `experiments/results/<case>/<case>.csv` as it finishes. Running the same command again carries on from where it stopped.
- `--run N` numbers repeats (re-mount between runs). `--noise` labels a disturbance, `--notes` records anything else.
- `--codes none R3` runs only some codes. `--sim` in place of `$PORT` uses the simulated channel; those results go in `experiments/results/sim/`, which git ignores.
- `--live` shows the live viewer: the raw signal, each bit's reading, error maps for each code and error statistics. Closing it stops the run after the current string.

```
python3 -m experiments.summarise                                          # tables for every saved run
python3 -m experiments.summarise experiments/results/<case>/*.csv         # one run, with its filter results
python3 -m experiments.live_view experiments/results/<case>/<case>.csv    # redraw a run's picture
```

## Receiver extensions

An extension decides the bits again from each string's raw samples, in place of the Arduino's peak-to-peak and threshold. The string's code then decodes those bits. The sending doesn't change, so every run with raw samples gives results for every receiver. The extensions are listed in `experiments/extensions.py`, and either or both can be run (`--extension filter`, `--extension cnn`, or `--extension filter cnn`).

### Filter

`filter` is the filtering in `codes/filtering.py`:

```
raw samples -> band-pass around the motor's drive frequency -> envelope -> mean level in each bit -> midpoint threshold -> bits
```

**The band.** Only the band was chosen; everything else is `codes/filtering.py`'s default. It is set once for each material by `find_motor_band` (the strongest peak in the spectrum ± 15 Hz) over all of that material's run 1, and saved in `experiments/filter_bands.json`:

| Material | Drive frequency | Band |
|---|---|---|
| wood | 118.4 Hz | 103.4–133.4 Hz |
| acrylic | 111.1 Hz | 96.1–126.1 Hz |
| PCB | 123.3 Hz | 108.3–138.3 Hz |

Every run of that material uses its band, including live runs. The method, and a comparison with other bands, is in `extensions.md`.

```
# Live: a second window shows the filter's decisions as each string finishes, and its errors print under each string
python3 -m experiments.run_case $PORT --material acrylic --distance 15 --settle 150 --window 50 --prbs-per-code --sets 3 --codes none --run 5 --extension filter --live

# Offline, on saved runs (sends nothing, needs no port)
python3 -m experiments.run_case --replay --extension filter
python3 -m experiments.run_case --replay experiments/results/<case>/<case>.csv --extension filter

# Set or reset a material's band from its run 1
python3 -m experiments.run_case --set-band experiments/results/<run 1>/<run 1>.csv
```

Each run's filter results go in `<case>_filter.csv` next to its own CSV, with the same columns, plus a picture `<case>_filter.png`. The settings used are in the `notes` column. `experiments.summarise` shows them as `<case>+filter`. Re-running `--replay` overwrites them. Other options: `--filter-band auto` (find the peak in each string by itself), `--filter-band LO HI` (a fixed band in Hz), `--filter-notch`, `--filter-sharpen`, `--filter-smooth`, `--filter-kind`.

### Network

`cnn` is a small 1D convolutional network in `codes/cnn_decoder.py`. Instead of fixing a filter and a threshold by hand, it learns from the recorded signals what each bit looks like, including the leftover vibration after a 1:

```
raw samples -> envelope -> 16 steps per bit -> this bit and 2 bits either side -> CNN -> P(bit = 1) -> bit
```

- **Input.** The envelope is the rectified signal, low-passed at 30 Hz (no band-pass). Each bit's slot starts when the motor was switched (`bit_start + switch_offset`) and is averaged into 16 steps of 12.8 ms, scaled so the string's loud level is about 1. For each bit the network sees its own 16 steps plus the 2 bits either side (80 steps), so it can see the motor spinning up and coasting down. A log copy of the envelope keeps small leftover levels visible next to a full 1.
- **Model.** Two convolution layers (16 filters of width 5), then a 32-unit layer and two outputs: the probability that the bit is a 1, and which transition it was (0→0, 0→1, 1→0, 1→1). The second output is only used in training, to teach it the four level shapes. About 43,000 parameters.
- **Training.** Adam, 60 epochs, with the level of each example randomly scaled by ±20% so it doesn't rely on one exact loudness. The saved model `models/cnn_decoder.pt` was trained on the wood and acrylic runs without disturbance (78 strings, 5,862 bits). That includes the 10 `electrical-noise/` acrylic strings, which the training script reads as undisturbed because of their folder names. A plain linear model on the same input is trained alongside as a baseline (`models/cnn_decoder_linear.pt`).
- **Decision.** A bit is read as 1 when P(1) ≥ 0.5, then the string's code decodes as usual. Like the filter, it needs the whole string first, so it runs after each string, not bit by bit.

It needs PyTorch (in `requirements.txt`). Its results go in `<case>_cnn.csv` and `<case>_cnn.png`, with the same columns as the filter's. The `vibration` column holds P(1) × 1000 and the threshold is 500. Strings the model was trained on are marked `in CNN training set` in the `notes` column.

```
# Offline, on saved runs
python3 -m experiments.run_case --replay --extension cnn
python3 -m experiments.run_case --replay --extension filter cnn         # both

# Live, alongside the filter
python3 -m experiments.run_case $PORT ... --extension filter cnn --live

# Train or test the network itself (prints tables against the other receivers)
python3 -m codes.cnn_decoder train                                       # default: trains on wood and acrylic, no disturbance
python3 -m codes.cnn_decoder eval --test "material=pcb"
python3 -m codes.cnn_decoder predict --npz experiments/results/<case>/raw/codes_0_R3.npz
```

`--cnn-model PATH` picks another trained model for `run_case`.

## Raw signal files

Each run's folder holds its CSV, its picture (`<case>.png`), a video (`<case>.mp4`) and `raw/`, with one `.npz` per string named `<block>_<set>_<code>.npz`:

```
experiments/results/wood_15cm_none_S150_W50_Pprbs5_run1/
    wood_15cm_none_S150_W50_Pprbs5_run1.csv
    wood_15cm_none_S150_W50_Pprbs5_run1.png
    wood_15cm_none_S150_W50_Pprbs5_run1.mp4
    wood_15cm_none_S150_W50_Pprbs5_run1_filter.csv
    wood_15cm_none_S150_W50_Pprbs5_run1_filter.png
    wood_15cm_none_S150_W50_Pprbs5_run1_cnn.csv
    wood_15cm_none_S150_W50_Pprbs5_run1_cnn.png
    raw/
        codes_0_none.npz
        codes_0_R3.npz
        codes_0_R5.npz
        codes_0_hamming74.npz
        codes_0_conv75.npz
```

Each CSV row's `raw_file` column names its file relative to the CSV. To load one string:

```python
import numpy as np
d = np.load("experiments/results/wood_15cm_none_S150_W50_Pprbs5_run1/raw/codes_0_R3.npz")
start = d["bit_start"]
bit_5 = d["samples"][start[5]:start[6]]   # 2048 samples at 10 kHz for bit 5
```

Each file also holds:

- `sent`, `received`, `vibration` and `threshold`: the same values as the CSV
- `sample_rate`, `settle_ms` and `window_ms`
- `switch_offset`: how many samples into each bit the motor was switched (about 47, because the Giga reports the previous bit before switching)
- `late_bits`: bits that ran long, leaving a gap in the recording after them; 0 in every run

The measuring window runs from `settle_ms` to `settle_ms + window_ms` after the start of each bit's samples, so about 145–195 ms after the motor actually switched.

The video is the raw signal scrolling through the whole run at real speed, with the bit sent, what it was read as and each measuring window marked. It needs ffmpeg (`brew install ffmpeg` or `pip install imageio-ffmpeg`). `--no-video` skips it. Remake one with:

```
python3 -m experiments.make_video experiments/results/<case>/<case>.csv
```
