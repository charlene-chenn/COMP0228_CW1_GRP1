# COMP0228 CW1, Group 1: code

A vibration motor mounted on a test rig sends bits through the rig's surface by on-off keying, and a piezo disc on the same surface receives them. One Arduino GIGA R1 drives the motor and samples the piezo. Python on the laptop encodes each message, sends it to the Arduino, and decodes what comes back.

This archive holds the code for the transmitter, the receiver and the experiments. The recorded data, figures and tables are in the report, not here.

## Contents

```
piezo_receiver_v3/
    piezo_receiver_v3.ino   Arduino sketch: transmitter and receiver
channel/
    hardware.py             USB link to the Arduino (send bits, read decisions and raw samples)
    sim_channel.py          simulated channel, for testing without hardware
codes/
    __init__.py             CODES: every code behind one encode/decode interface
    repetition.py           R3 and R5
    hamming.py              Hamming(7,4)
    convolutional.py        rate-1/2 convolutional code (generators 7, 5), Viterbi decoder
    filtering.py            extension 1: band-pass filter receiver
    cnn_decoder.py          extension 2: 1D CNN receiver (training, evaluation, prediction)
experiments/
    run_case.py             runs one test case through every code and saves the results
    sequences.py            PRBS-5 and random test messages
    extensions.py           re-decides each string's bits with the filter or the network
    filter_bands.json       the filter's pass band for each material
    summarise.py            error rates with 95% Wilson intervals for saved runs
    live_view.py, scope.py  live viewer and raw signal scope during a run
    make_video.py           video of a run's raw signal
models/
    cnn_decoder.pt          the trained network used in the report
    cnn_decoder_linear.pt   linear baseline trained alongside it
run_sim.py                  every code through the simulated channel
requirements.txt
```

## Transmitter and receiver (`piezo_receiver_v3.ino`)

- **Transmitter.** A 1 switches the motor on (pin D3, through a motor driver) for the whole bit, and a 0 leaves it off.
- **Receiver.** The GIGA samples A0 at 10 kHz with DMA. Each bit waits a settle time, then takes the peak-to-peak of the samples in its measuring window. It reads a 1 if that is above a threshold, which it sets at start-up from 3 s of background noise.
- **Timing.** The report uses a 150 ms settle and 50 ms window. Each bit takes 204.8 ms, rounded up to whole 25.6 ms DMA buffers.
- **Serial commands.** `B<bits>` sends a bit string and replies with each bit's decision and reading. `S` and `W` set the settle and window. `C` recalibrates. `R1` streams the raw samples of every bit, which the extensions need. The full list is at the top of the sketch.

Wiring: front-end ADC node to A0. Driver signal to D3, driver GND to GIGA GND. Power the motor from its own supply through the driver, never from the GIGA.

## Setup

```
pip install -r requirements.txt
```

In the Arduino IDE, install `Arduino_AdvancedAnalog` from the Library Manager, select the board "Arduino GIGA R1 WiFi" (M7 core) and upload `piezo_receiver_v3/piezo_receiver_v3.ino`. Close the Serial Monitor afterwards, since only one program can use the port. Keep the rig still for the 3 s calibration after the port opens.

Run every command below from this folder.

```
python3 run_sim.py                     # every code through the simulated channel
python3 -m channel.hardware            # list serial ports
python3 -m channel.hardware $PORT      # test the real channel
```

## Running an experiment

One run of a case, as in the report:

```
python3 -m experiments.run_case $PORT --material wood --distance 15 --settle 150 --window 50 --prbs-per-code --sets 1 --run 1 --live
```

Each run sends the same PRBS-5 string (31 bits) through every code in a shuffled order. It saves every string to `experiments/results/<case>/<case>.csv`, with its raw samples in `raw/`. Re-running the same command carries on from where it stopped. `--noise` labels a disturbance, `--codes` picks a subset of codes, and `--sim` in place of `$PORT` uses the simulated channel. Making the video needs `ffmpeg` on the path; `--no-video` skips it.

```
python3 -m experiments.summarise                                         # error rates for every saved run
python3 -m experiments.live_view experiments/results/<case>/<case>.csv   # redraw a run
```

## Receiver extensions

Both extensions decide each string's bits again from its raw samples, in place of the Arduino's peak-to-peak threshold. The string's code then decodes those bits as usual.

- **Filter** (`codes/filtering.py`): band-pass around the motor's drive frequency (4th-order Butterworth, ±15 Hz), envelope, mean level in each bit's window, then a threshold halfway between the string's quiet and loud levels. `experiments/filter_bands.json` holds each material's band.
- **Network** (`codes/cnn_decoder.py`): a small 1D CNN that reads each bit's envelope with two bits of context either side and outputs P(bit = 1).

```
# During a run
python3 -m experiments.run_case $PORT ... --extension filter cnn --live

# On saved runs (needs no hardware)
python3 -m experiments.run_case --replay --extension filter cnn

# Set a material's filter band from its first run
python3 -m experiments.run_case --set-band experiments/results/<run 1>/<run 1>.csv

# Retrain or evaluate the network
python3 -m codes.cnn_decoder train
python3 -m codes.cnn_decoder eval --test "material=pcb"
```

`--replay`, `--set-band` and `cnn_decoder train` read recorded runs from `experiments/results/`, which this archive does not include. The trained model in `models/` lets the network extension run on new recordings without retraining.
