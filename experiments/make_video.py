"""
Make a video of the raw piezo signal for a saved case: the scrolling scope from
the live view, played at real speed through every string of the case.

    python3 -m experiments.make_video experiments/results/<case>/<case>.csv

This writes experiments/results/<case>/<case>.mp4. run_case also does this at the
end of each finished case that recorded raw samples (skip it with --no-video).

The video joins the strings up in the order they were sent. Time spent between
strings (calibrating, encoding) wasn't recorded, so the line breaks there. It
needs ffmpeg: either on the PATH (e.g. brew install ffmpeg) or from
pip install imageio-ffmpeg.
"""
import csv
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

from experiments.scope import AXIS, INK, INK_SECONDARY, MUTED, SURFACE, RawScope

FPS = 30
WIDTH_IN, HEIGHT_IN, DPI = 12.8, 7.2, 150   # 1920 x 1080 pixels (1080p)


def find_ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        raise SystemExit(
            "Making the video needs ffmpeg. Install it with 'brew install ffmpeg' "
            "or 'pip install imageio-ffmpeg'."
        ) from None


def load_bits(path: Path):
    """The raw samples of each bit in a saved .npz, or None if the file is missing."""
    if not path.exists():
        return None
    data = np.load(path)
    starts = data["bit_start"]
    return [data["samples"][starts[i]:starts[i + 1]] for i in range(len(starts) - 1)]


def string_label(row: dict) -> str:
    if row["block"] == "codes":
        return f"{row['code']}, set {int(row['index']) + 1}"
    if row["block"] == "reference":
        return "PRBS-5 reference"
    return f"PRBS-5 #{int(row['index']) + 1}"


def make_video(csv_path: Path, out_path: Path = None, quiet: bool = False) -> Path:
    """
    Render the case's raw signal to an mp4.

    Args:
        csv_path (Path): the case's CSV.
        out_path (Path, optional): where to write. Defaults to <case>.mp4 next to the CSV.
        quiet (bool, optional): don't print progress. Defaults to False.

    Returns:
        Path: the video file.
    """
    # Drawn off screen, without pyplot, so it can't disturb a live viewer's window
    from matplotlib import rc_context
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    csv_path = Path(csv_path)
    out_path = Path(out_path) if out_path else csv_path.with_suffix(".mp4")
    with open(csv_path, newline="") as file:
        rows = [row for row in csv.DictReader(file) if row.get("raw_file")]
    if not rows:
        raise SystemExit(f"{csv_path} has no raw samples, so there's nothing to make a video of")
    rows.sort(key=lambda row: row["timestamp"])

    first = np.load(csv_path.parent / rows[0]["raw_file"])
    rate = int(first["sample_rate"])

    # Every bit of every string, in the order sent
    strings = []
    for row in rows:
        raw = load_bits(csv_path.parent / row["raw_file"])
        if raw is None:
            continue
        sent = [int(bit) for bit in row["sent"]]
        read = [int(bit) for bit in row["received"]]
        strings.append((string_label(row), raw, sent, read))
    total_samples = sum(len(bit) for _, raw, _, _ in strings for bit in raw) + len(strings)

    style = rc_context({
        "font.family": "sans-serif", "font.size": 10, "text.color": INK,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK_SECONDARY,
        "xtick.color": MUTED, "ytick.color": MUTED,
    })
    style.__enter__()
    fig = Figure(figsize=(WIDTH_IN, HEIGHT_IN), dpi=DPI, facecolor=SURFACE)
    FigureCanvasAgg(fig)
    ax = fig.add_axes([0.065, 0.09, 0.915, 0.76])
    fig.text(0.065, 0.955, csv_path.stem, fontsize=12, weight="bold")
    status = fig.text(0.065, 0.92, "", color=INK_SECONDARY, animated=True)
    clock = fig.text(0.98, 0.955, "", ha="right", color=INK_SECONDARY, animated=True)

    scope = RawScope(ax, animated=True)
    scope.configure(int(rows[0]["settle_ms"]), int(rows[0]["window_ms"]), rate)
    scope.bit_length = len(strings[0][1][0])
    scope.resize()
    fig.canvas.draw()
    background = fig.canvas.copy_from_bbox(fig.bbox)
    width, height = fig.canvas.get_width_height()

    encoder = subprocess.Popen(
        [find_ffmpeg(), "-y", "-loglevel", "error",
         "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{width}x{height}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "32", str(out_path)],
        stdin=subprocess.PIPE,
    )

    step = rate / FPS                 # Samples per frame, so the video plays at real speed
    queue = [(label, number, bits, sent, read)
             for number, (label, bits, sent, read) in enumerate(strings)]
    starts = []                       # (first sample, label, bit count) of each string added
    string_index, bit_index = 0, 0
    head = 0.0
    frames = int(np.ceil(total_samples / step)) + FPS   # One second of stillness at the end

    for frame in range(frames):
        head = min(head + step, total_samples)

        # Add bits until there are samples beyond the right-hand edge
        while string_index < len(queue) and scope.total < head + scope.bit_length:
            label, _, bits, sent, read = queue[string_index]
            if bit_index == 0:
                scope.start_string()
                starts.append((scope.total + (1 if scope.total else 0), label, len(bits)))
            scope.add_bit(bits[bit_index], sent[bit_index], read[bit_index])
            bit_index += 1
            if bit_index == len(bits):
                string_index, bit_index = string_index + 1, 0

        scope.head = min(head, float(scope.total))
        scope.render()

        current = [s for s in starts if s[0] <= scope.head]
        if current:
            label = current[-1][1]
            status.set_text(f"Sending: {label}   ({len(current)} of {len(strings)} strings)")
        seconds = scope.head / rate
        clock.set_text(f"{int(seconds // 60)}:{seconds % 60:04.1f} of signal")

        fig.canvas.restore_region(background)
        for artist in [*scope.artists(), status, clock]:
            fig.draw_artist(artist)
        encoder.stdin.write(bytes(fig.canvas.buffer_rgba()))

        if not quiet and frame % (FPS * 10) == 0:
            print(f"\rMaking video: {100 * frame // frames}%", end="", flush=True)

    encoder.stdin.close()
    encoder.wait()
    style.__exit__(None, None, None)
    if not quiet:
        print(f"\rMaking video: done, {frames / FPS:.0f} s long")
    if encoder.returncode != 0:
        raise RuntimeError("ffmpeg failed to write the video")
    return out_path


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return
    print("Saved", make_video(Path(sys.argv[1])))


if __name__ == "__main__":
    main()
