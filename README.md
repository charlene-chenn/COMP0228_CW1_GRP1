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

Set up a test case, then run it through every code. Each string is saved to `experiments/results/<case>.csv` as it finishes, and running the same command again carries on from where it stopped.

```
# Quick look at a setting: 10 PRBS-5 strings
python3 -m experiments.run_case <port> --material wood --distance 20 --settle 50 --window 50 --prbs-only --live

# Full case: 10 PRBS-5 strings, 20 32-bit messages through every code, 1 PRBS-5 reference
python3 -m experiments.run_case <port> --material wood --distance 20 --noise fan --settle 50 --window 50 --live

# Tables of the results so far
python3 -m experiments.summarise

# Redraw and save the viewer for a saved case
python3 -m experiments.live_view experiments/results/<case>.csv
```

A full case at 50/50 takes about 14.6 minutes. Use `--codes none R3 R5` to run only some codes, or `--message-bits 64` for longer messages. Add `--run 2` when repeating a case, for example after re-mounting the piezo. Closing the viewer stops the case after the current string. Use `--sim` in place of `<port>` to try all of this with no hardware; those results go in `experiments/results/sim/`, which git ignores.
