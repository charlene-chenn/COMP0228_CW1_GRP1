# Extension: learned leakage corrector

## Problem

At 150/50, every channel error is a 0 sent straight after a 1. After switch-off the motor coasts down: its frequency falls from about 120 Hz to about 25 Hz over about 300 ms, so vibration leaks into the next bit's measuring window. The noise is caused by the previous bit, so it is predictable from the bits around it. Codes built for random flips can't correct it: Hamming(7,4) gains nothing, and conv75 makes things worse (65% message errors against 26% uncoded). Details are in `experiment.md`, "Findings so far".

## Method

A small learned model that corrects the receiver's decisions using the **readings of neighbouring bits**. For bit *i*, it takes the receiver's existing peak-to-peak reading (log scale) for bits *i*−2, *i*−1, *i* and *i*+1, and outputs 0 or 1 by logistic regression (4 weights and a bias).

- It learns how much a loud previous bit inflates the current reading, so it doesn't mistake that leakage for a 1.
- It looks one bit ahead. Leakage in bit *i*+1 is evidence that bit *i* was a 1, so the leakage becomes information instead of noise.
- It uses only the one number per bit the receiver already outputs. There is no raw-signal processing, which is the DSP extension's job.

### Division of work with the DSP extension

| | DSP extension | This extension |
|---|---|---|
| Works on | Raw samples, inside one bit | One reading per bit, across neighbouring bits |
| Tool | Filtering (band-pass at the drive frequency) | Learning the channel's memory from sent/received pairs |
| Targets | Noise outside the motor's frequency band, including PCB's resonance | Leakage from the previous bit |

They can be combined by feeding the DSP extension's per-bit output in place of peak-to-peak.

## How it meets the brief

- **"A learning system trained on pairs of distorted and clean versions of the same signal, which learns to correct them":** the received readings are the distorted version, and the bits sent are the clean version. Both are already recorded for every run.
- **Builds on the brief's reflection question:** the codes fail because the noise isn't random flips. This targets the noise we actually found.
- **Error vs transmission rate:** it only changes the receiver, so any gain costs nothing in data rate. Compare R3 and R5, which cut the rate to a third and a fifth.

## Results of a first test, and hypotheses

First test on saved runs, all errors counted on runs not used for training:

| Train → test | Current threshold | Previous-decision threshold | Learned corrector |
|---|---|---|---|
| wood 15 cm run 1 → runs 2–3 | 108/802 | 3/802 | **0/802** |
| wood 30 cm run 1 → runs 2–3 | 108/802 | 0/802 | **0/802** |
| wood 15 cm run 1 → acrylic run 1 | 58/401 | 4/401 | **0/401** |
| PCB run 1 → runs 2–3 | 114/802 | 205/802 | **48/802** |
| wood 15 cm run 1 → PCB | 184/1203 | 319/1203 | 486/1203 |

Learned weights on wood (standardised), for bits *i*−2, *i*−1, *i*, *i*+1: 0.2, **−0.8**, 6.8, **+0.8**. The current reading dominates, a loud previous bit counts against a 1, and a loud next bit counts for it, as the physics predicts.

| | Hypothesis |
|---|---|
| H1 | On wood and acrylic, it removes almost all leakage errors on unseen runs and unseen materials |
| H2 | On PCB it helps only partly, because a 0 after a 1 reads as large as a 1. Combining it with the DSP extension's output fixes the rest |
| H3 | A model trained on one material doesn't carry over to PCB, because PCB's resonance changes the channel's memory |
| H4 | With channel errors near zero, every code's message errors fall to near zero, so the codes are compared at their real data rates |
| H5 | It beats the previous-decision threshold because it also uses the next bit, and it doesn't carry one mistake into the next decision |

## Experiments

- **Data:** the clean 150/50 PRBS runs: wood (9), PCB (3), acrylic (1, plus 2 to re-run). `electrical-noise/` is used as a robustness test.
- **Splits:**
  - within each material: run 1 → runs 2–3;
  - across materials: wood → acrylic and PCB.
- **Compare:**
  1. the current threshold;
  2. the previous-decision threshold;
  3. the learned corrector;
  4. the learned corrector on the DSP extension's output.
- **Ablation:** drop the *i*+1 input (no look-ahead) and the *i*−1, *i*−2 inputs (no memory) to show which part matters.
- **Measure:**
  - channel bit errors, overall and split into leakage and other;
  - message errors for each code after re-decoding;
  - Wilson 95% confidence intervals.
- **Report:** a table for each method and material, a bar chart with confidence intervals and the learned weights.

## Implementation (offline; no hardware or firmware changes)

- `experiments/corrector.py`:
  - loads runs from `experiments/results/*/*.csv`, using the `vibration` and `sent` columns;
  - builds the 4-value inputs, padding string edges with the quiet level;
  - logistic regression in NumPy: standardised inputs and gradient descent with light L2;
  - re-decodes each code from the corrected channel bits with the existing `codes/` decoders;
  - prints the tables and saves the plots.
- No new dependencies: scikit-learn isn't installed, and a 4-weight model is easy to write and explain.
- Live use would be a one-bit delay at the receiver, because of the look-ahead.

## Threats to validity

- **The same PRBS-5 is sent in every run.** With only 4 weights the model can't memorise the sequence, but add one test run with a different seed.
- **It's evaluated on the strings as sent,** so the look-ahead assumes the whole string is received before deciding. That's true for our receiver, which decodes after the full string.
- **Small samples:** acrylic has 1 clean run so far, and there are 93 message bits per code per case. Report confidence intervals and the spread between runs.
- **Only measured at 150/50.** At a shorter settle the leakage would span more bits, so more neighbours may be needed.
