"""
Live viewer for the PRBS-9 strings. Start it with --live on experiments.run_case.
Closing the window stops the case at the end of the current string.

Colour always means the bit that was sent: orange = sent 0, blue = sent 1.

To redraw a saved case, for example for the report:
    python3 -m experiments.live_view experiments/results/<case>.csv
"""
import csv
import queue
import sys
from collections import Counter, deque
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.colors import BoundaryNorm, ListedColormap
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from experiments.summarise import wilson

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SENT_0 = "#eb6834"
SENT_1 = "#2a78d6"
BAD_MARK = "#0b0b0b"

NOT_SENT, CORRECT, WRONG_SENT_0, WRONG_SENT_1 = 0, 1, 2, 3
RASTER_COLOURS = [SURFACE, GRID, SENT_0, SENT_1]

STRIP_BITS = 120     # How many of the latest bits to show at the top
MAX_RUN_SHOWN = 8    # Longer error runs are counted in the last bar
REFRESH_MS = 200


def saved_events(rows: dict, repeats: int) -> list:
    """Turn saved PRBS-9 strings back into viewer updates, so a resumed run shows them."""
    events = []
    for row in rows.values():
        if row["block"] not in ("prbs", "reference"):
            continue
        position = repeats if row["block"] == "reference" else int(row["index"])
        sent = [int(bit) for bit in row["sent"]]
        events.append(("trial", position, sent, int(row["threshold"])))
        vibration = row["vibration"].split()
        for i, (bit, vib) in enumerate(zip(row["received"], vibration)):
            events.append(("bit", i, int(bit), int(vib)))
    return events


class LiveView:
    def __init__(self, events: queue.Queue, case: str, labels: list, stop=None, save_path=None):
        """
        Set up the window.

        Args:
            events (queue.Queue): updates from the running case.
            case (str): the case name for the title.
            labels (list): one label per row of the error map.
            stop (threading.Event, optional): set when the window closes.
            save_path (Path, optional): where to save a picture when the case ends.
        """
        self.events = events
        self.case = case
        self.labels = labels
        self.stop = stop
        self.save_path = save_path

        self.status = "Waiting"
        self.finished = False
        self.row = 0
        self.sent = []
        self.threshold = 0
        self.position = 0
        self.total = 0

        self.strip = deque(maxlen=STRIP_BITS)
        self.raster = np.full((len(labels), 511), NOT_SENT)
        self.errors = 0
        self.counts = {0: [0, 0], 1: [0, 0]}          # sent bit: [errors, bits]
        self.after = {}                               # (previous, sent): [errors, bits]
        for key in [(0, 0), (1, 0), (0, 1), (1, 1)]:
            self.after[key] = [0, 0]
        self.runs = Counter()
        self.run = 0

        self._build()

    def _build(self) -> None:
        plt.rcParams.update({
            "font.family": "sans-serif",
            "font.size": 10,
            "text.color": INK,
            "axes.edgecolor": AXIS,
            "axes.labelcolor": INK_SECONDARY,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
        })

        self.fig = plt.figure(figsize=(13, 8.5), facecolor=SURFACE)
        self.fig.canvas.manager.set_window_title("PRBS-9 live view")
        grid = self.fig.add_gridspec(
            3, 3, height_ratios=[1.1, 1.3, 1.1], width_ratios=[0.8, 1, 1.2],
            left=0.06, right=0.98, top=0.88, bottom=0.08, hspace=0.62, wspace=0.26,
        )

        self.title = self.fig.text(0.06, 0.955, self.case, fontsize=14, weight="bold")
        self.subtitle = self.fig.text(0.06, 0.925, "", color=INK_SECONDARY)

        self.ax_strip = self.fig.add_subplot(grid[0, :])
        self.ax_raster = self.fig.add_subplot(grid[1, :])
        self.ax_stats = self.fig.add_subplot(grid[2, 0])
        self.ax_after = self.fig.add_subplot(grid[2, 1])
        self.ax_runs = self.fig.add_subplot(grid[2, 2])

        for ax in (self.ax_strip, self.ax_raster, self.ax_after, self.ax_runs):
            ax.set_facecolor(SURFACE)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.tick_params(length=0)

        self._build_strip()
        self._build_raster()
        self.ax_stats.axis("off")

    def _build_strip(self) -> None:
        ax = self.ax_strip
        ax.set_title(f"Vibration per bit, latest {STRIP_BITS} bits", loc="left", fontsize=11)
        ax.set_ylabel("Peak-to-peak (ADC counts)")
        ax.set_xlabel("Bits sent")
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)

        self.dots_0 = ax.scatter([], [], s=34, color=SENT_0, edgecolors=SURFACE, linewidths=1)
        self.dots_1 = ax.scatter([], [], s=34, color=SENT_1, edgecolors=SURFACE, linewidths=1)
        self.dots_bad = ax.scatter([], [], s=60, marker="x", color=BAD_MARK, linewidths=1.6)
        self.line = ax.axhline(0, color=INK_SECONDARY, linewidth=1.2)
        self.line_label = ax.text(
            0.995, 0, "", transform=ax.get_yaxis_transform(), ha="right", va="bottom",
            color=INK_SECONDARY, fontsize=9,
        )

        ax.legend(
            handles=[
                Line2D([], [], marker="o", linestyle="", color=SENT_0, label="Sent 0"),
                Line2D([], [], marker="o", linestyle="", color=SENT_1, label="Sent 1"),
                Line2D([], [], marker="x", linestyle="", color=BAD_MARK, label="Read wrongly"),
            ],
            loc="lower right", bbox_to_anchor=(1, 1), ncol=3, frameon=False, fontsize=9,
        )

    def _build_raster(self) -> None:
        ax = self.ax_raster
        ax.set_title("Error map: where each repeat went wrong", loc="left", fontsize=11)
        ax.set_xlabel("Position in PRBS-9 string (bit)")
        ax.set_yticks(range(len(self.labels)), self.labels, fontsize=8)

        self.image = ax.imshow(
            self.raster, aspect="auto", interpolation="nearest",
            cmap=ListedColormap(RASTER_COLOURS),
            norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], 4),
        )

        ax.legend(
            handles=[
                Patch(color=GRID, label="Correct"),
                Patch(color=SENT_0, label="Sent 0, read 1"),
                Patch(color=SENT_1, label="Sent 1, read 0"),
            ],
            loc="lower right", bbox_to_anchor=(1, 1), ncol=3, frameon=False, fontsize=9,
        )

    def _handle(self, event) -> None:
        kind = event[0]

        if kind == "trial":
            self._end_run()
            _, self.row, self.sent, self.threshold = event
            self.position = 0
            self.status = f"PRBS-9 {self.labels[self.row]} of {len(self.labels)}"

        elif kind == "bit":
            _, index, bit, vibration = event
            self._add_bit(index, bit, vibration)

        elif kind == "status":
            self.status = event[1]

        elif kind == "done":
            self._end_run()
            self.status = event[1]
            self.finished = True

    def _add_bit(self, index: int, bit: int, vibration: int) -> None:
        sent = self.sent[index]
        wrong = bit != sent

        self.total += 1
        self.position = index + 1
        self.strip.append((self.total, vibration, sent, wrong))
        self.counts[sent][1] += 1

        if index > 0:
            self.after[(self.sent[index - 1], sent)][1] += 1

        if wrong:
            self.errors += 1
            self.counts[sent][0] += 1
            self.run += 1
            if index > 0:
                self.after[(self.sent[index - 1], sent)][0] += 1
            self.raster[self.row, index] = WRONG_SENT_0 if sent == 0 else WRONG_SENT_1
        else:
            self._end_run()
            self.raster[self.row, index] = CORRECT

    def _end_run(self) -> None:
        if self.run:
            self.runs[self.run] += 1
        self.run = 0

    def update(self, _frame=None) -> None:
        """Apply any waiting updates, then redraw once."""
        changed = False
        while True:
            try:
                self._handle(self.events.get_nowait())
                changed = True
            except queue.Empty:
                break

        if changed:
            self._draw()

        if changed and self.finished and self.save_path is not None:
            self.fig.savefig(self.save_path, dpi=150, facecolor=SURFACE)

    def _draw(self) -> None:
        detail = self.status
        if self.sent and self.status.startswith("PRBS-9"):
            detail += f", bit {self.position} of {len(self.sent)}"
        if self.threshold:
            detail += f"  |  threshold {self.threshold:,}"
        self.subtitle.set_text(detail)

        self._draw_strip()
        self.image.set_data(self.raster)
        self._draw_stats()
        self._draw_after()
        self._draw_runs()

    def _draw_strip(self) -> None:
        if not self.strip:
            return

        data = np.array(self.strip)
        x, vibration, sent, wrong = data[:, 0], data[:, 1], data[:, 2], data[:, 3] == 1

        self.dots_0.set_offsets(np.c_[x[sent == 0], vibration[sent == 0]])
        self.dots_1.set_offsets(np.c_[x[sent == 1], vibration[sent == 1]])
        self.dots_bad.set_offsets(np.c_[x[wrong], vibration[wrong]])

        self.line.set_ydata([self.threshold, self.threshold])
        self.line_label.set_y(self.threshold)
        self.line_label.set_text(f"Threshold {self.threshold:,}")

        self.ax_strip.set_xlim(max(0, x[-1] - STRIP_BITS), max(x[-1], STRIP_BITS) + 1)
        self.ax_strip.set_ylim(0, max(vibration.max(), self.threshold) * 1.12)

    def _draw_stats(self) -> None:
        ax = self.ax_stats
        ax.clear()
        ax.axis("off")

        bits = self.counts[0][1] + self.counts[1][1]
        rate = self.errors / bits if bits else 0
        low, high = wilson(self.errors, bits)

        ax.text(0, 0.98, "Bit error rate", va="top", fontsize=11)
        ax.text(0, 0.84, f"{rate:.2%}", va="top", fontsize=30, weight="bold")
        lines = [
            f"95% CI {low:.2%} to {high:.2%}",
            f"{self.errors:,} wrong of {bits:,} bits",
            f"Sent 0, read 1: {self._share(0)}",
            f"Sent 1, read 0: {self._share(1)}",
        ]
        ax.text(0, 0.42, "\n".join(lines), va="top", color=INK_SECONDARY, linespacing=1.5)

    def _share(self, sent: int) -> str:
        errors, bits = self.counts[sent]
        return f"{errors:,} of {bits:,}" + (f" ({errors / bits:.2%})" if bits else "")

    def _draw_after(self) -> None:
        ax = self.ax_after
        ax.clear()
        self._style(ax, "Error rate by previous and current bit", "Previous → sent bit", "Bits wrong (%)")

        keys = [(0, 0), (1, 0), (0, 1), (1, 1)]
        rates = [100 * self.after[k][0] / self.after[k][1] if self.after[k][1] else 0 for k in keys]
        colours = [SENT_0 if sent == 0 else SENT_1 for _, sent in keys]

        bars = ax.bar([f"{a} → {b}" for a, b in keys], rates, width=0.5, color=colours)
        ax.bar_label(bars, [f"{r:.1f}%" for r in rates], padding=3, color=INK_SECONDARY, fontsize=9)
        ax.set_ylim(0, max(max(rates) * 1.3, 1))

    def _draw_runs(self) -> None:
        ax = self.ax_runs
        ax.clear()
        self._style(ax, "Error run lengths, against random flips", "Wrong bits in a row", "Runs")

        counts = Counter(self.runs)
        if self.run:
            counts[self.run] += 1

        sizes = list(range(1, MAX_RUN_SHOWN + 1))
        seen = [counts[size] for size in sizes[:-1]]
        seen.append(sum(n for size, n in counts.items() if size >= MAX_RUN_SHOWN))
        ax.bar(sizes, seen, width=0.6, color=INK_SECONDARY, label="Seen")

        # With independent flips at rate p, a run of r has (1-p)^2 p^r chance at each bit
        bits = self.counts[0][1] + self.counts[1][1]
        p = self.errors / bits if bits else 0
        expected = [bits * (1 - p) ** 2 * p ** size for size in sizes]
        ax.plot(sizes, expected, linestyle="", marker="_", markersize=18, markeredgewidth=2.5,
                color=INK, label="Expected if random")

        ax.set_xticks(sizes, [str(s) for s in sizes[:-1]] + [f"{MAX_RUN_SHOWN}+"])
        ax.set_ylim(0, max(max(seen), max(expected), 1) * 1.2)
        ax.legend(loc="upper right", frameon=False, fontsize=9)

    @staticmethod
    def _style(ax, title: str, xlabel: str, ylabel: str) -> None:
        ax.set_title(title, loc="left", fontsize=11)
        ax.set_xlabel(xlabel)
        ax.set_ylabel(ylabel)
        ax.set_facecolor(SURFACE)
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.tick_params(length=0)

    def show(self) -> None:
        """Open the window and refresh it until it is closed."""
        if self.stop is not None:
            self.fig.canvas.mpl_connect("close_event", lambda _: self.stop.set())
        self.animation = FuncAnimation(
            self.fig, self.update, interval=REFRESH_MS, cache_frame_data=False,
        )
        plt.show()


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        return

    path = Path(sys.argv[1])
    with open(path, newline="") as file:
        rows = {i: row for i, row in enumerate(csv.DictReader(file))}

    repeats = sum(row["block"] == "prbs" for row in rows.values())
    has_reference = any(row["block"] == "reference" for row in rows.values())
    labels = [f"R{i + 1}" for i in range(repeats)] + (["ref"] if has_reference else [])

    events = queue.Queue()
    for event in saved_events(rows, repeats):
        events.put(event)
    events.put(("done", "Saved run"))

    view = LiveView(events, path.stem, labels, save_path=path.with_suffix(".png"))
    view.update()
    print("Saved", path.with_suffix(".png"))
    plt.show()


if __name__ == "__main__":
    main()
