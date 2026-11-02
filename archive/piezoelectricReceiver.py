from typing import List

import numpy as np

def receiver(sample_rate=44100) -> List[int]:
    """
    Args:
        sample_rate (int, optional): sampling rate of receiver. Defaults to 44100.
    """
    # Arduino code for recording vibrations in raw ADC counts
    pass

# All timings are in seconds and all frequencies in Hz. They must match
# the transmitter. The defaults below are placeholders scaled for
# low-frequency vibration, not values taken from the transmitter.
def recording_to_bits(
    recording,
    sample_rate,
    n_bits=None,
    sync_frequency=150,
    sync_duration=2.0,
    freq_0=50,
    freq_1=100,
    band_halfwidth=15,
    beep_duration=0.5,
    silence_duration=0.25,
    window_duration=0.2,
    hop_duration=0.02,
    margin_duration=0.1,
) -> List[int]:
    """
    Find the sync vibration in a piezo recording (raw ADC counts) and
    demodulate the bits that follow it.

    Args:
        recording: ADC samples, flat or (samples, channels).
        sample_rate (int): actual ADC sampling rate in Hz.
        n_bits (int, optional): number of bits to read. If None, reads
            until the recording ends.
    """

    # -----------------------------------------------
    # 1. Prepare the raw ADC samples
    # -----------------------------------------------

    # Accept either a flat array or a (samples, channels) array.
    recording = np.asarray(recording, dtype=float)
    if recording.ndim == 2:
        recording = recording[:, 0]

    # Piezo circuits are biased to mid-rail (e.g. ~512 counts), which
    # would otherwise appear as a huge 0 Hz peak in every FFT.
    recording = recording - np.mean(recording)

    # -----------------------------------------------
    # 2. Detect the synchronisation vibration
    # -----------------------------------------------

    # Longer window than for audio: low frequencies need several full
    # cycles per window, and bins are 1 / window_duration Hz wide.
    window_samples = int(sample_rate * window_duration)
    hop_samples = max(1, int(sample_rate * hop_duration))

    fft_freqs = np.fft.rfftfreq(
        window_samples, d=1 / sample_rate
    )

    sync_band = (
        (fft_freqs >= sync_frequency - band_halfwidth) &
        (fft_freqs <= sync_frequency + band_halfwidth)
    )

    if not np.any(sync_band):
        raise ValueError(
            "Sync band contains no FFT bins. Use a longer "
            "window_duration or check sample_rate (Nyquist)."
        )

    starts = []
    sync_energy = []

    for start in range(
        0,
        len(recording) - window_samples,
        hop_samples
    ):
        segment = recording[start:start + window_samples]
        segment = segment * np.hanning(window_samples)

        spectrum = np.abs(np.fft.rfft(segment))
        energy = np.sum(spectrum[sync_band] ** 2)

        starts.append(start)
        sync_energy.append(energy)

    starts = np.array(starts)
    sync_energy = np.array(sync_energy)

    if len(sync_energy) == 0 or np.max(sync_energy) < 1e-10:
        raise RuntimeError(
            "No clear synchronisation vibration detected. "
            "Check sensor coupling and ADC wiring."
        )

    # Find the first window with substantial sync energy.
    threshold = 0.25 * np.max(sync_energy)
    candidates = np.where(sync_energy >= threshold)[0]

    if len(candidates) == 0:
        raise RuntimeError("Synchronisation vibration not detected.")

    # The window overlaps the onset, so compensate for
    # most of the window duration.
    sync_start = (
        starts[candidates[0]] + int(0.75 * window_samples)
    )

    print(
        f"Synchronisation detected at approximately "
        f"{sync_start / sample_rate:.3f} seconds."
    )

    # -----------------------------------------------
    # 3. Decode the data vibrations
    # -----------------------------------------------

    beep_samples = int(sample_rate * beep_duration)
    period_samples = int(
        sample_rate * (beep_duration + silence_duration)
    )

    first_data_start = (
        sync_start
        + int(sample_rate * (sync_duration + silence_duration))
    )

    # Skip the start and end of each burst, where the actuator is
    # still spinning up / down and the sync estimate may be off.
    margin = int(margin_duration * sample_rate)
    analysis_samples = beep_samples - 2 * margin

    if analysis_samples <= 0:
        raise ValueError("margin_duration is too long for beep_duration.")

    bits = []
    i = 0

    while n_bits is None or i < n_bits:
        start = first_data_start + i * period_samples + margin
        end = start + analysis_samples

        if end > len(recording):
            if n_bits is not None:
                print(f"Warning: recording ended before bit {i}.")
            break

        segment = recording[start:end]
        segment = segment * np.hanning(len(segment))

        spectrum = np.abs(np.fft.rfft(segment))
        freqs = np.fft.rfftfreq(
            len(segment), d=1 / sample_rate
        )

        energy_0 = np.sum(
            spectrum[np.abs(freqs - freq_0) <= band_halfwidth] ** 2
        )

        energy_1 = np.sum(
            spectrum[np.abs(freqs - freq_1) <= band_halfwidth] ** 2
        )

        if energy_0 == 0 and energy_1 == 0:
            print(f"Warning: no clear vibration detected for bit {i}.")

        bits.append(
            0 if energy_0 > energy_1 else 1
        )
        i += 1

    return bits
