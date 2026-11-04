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
