"""
Live viewer for the PRBS strings. Start it with --live on experiments.run_case.
Closing the window stops the case at the end of the current string.

Colour always means the bit that was sent: orange = sent 0, blue = sent 1.

With raw recording on (the default), the top panel shows the raw piezo signal
for the latest bits, with each bit's measuring window and the bit it was read as.
With --prbs-per-code, the coded strings get a channel error map, and a second map
shows which message bits were still wrong after decoding.

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

from codes import CODES
from experiments.sequences import map_key, prbs_name, row_label, shown
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

STRIP_BITS = 120     # How many of the latest bits to show in the vibration strip
RAW_BITS = 6         # How many of the latest bits to show in the raw signal
MAX_RUN_SHOWN = 8    # Longer error runs are counted in the last bar
REFRESH_MS = 200


def map_layout(strings) -> list:
    """
    Work out the error maps to draw: one for each length of PRBS string, and for
    coded strings one map of channel bits and one of decoded message bits.

    Args:
        strings: (block, index, code, channel bits, message bits) for each string
            the viewer shows, in the order sent.

    Returns:
        list: a dict for each map, with its key, title, x label, width, and the
        id (block, index, code) and label of each row.
    """
    prbs_maps, coded = {}, []
    for block, index, code, length, message_length in strings:
        row = (block, int(index), code)
        if block == "codes":
            coded.append((row, length, message_length))
        else:
            spec = prbs_maps.setdefault(length, {
                "key": map_key(block, length),
                "title": f"{prbs_name(length)} error map: where each string went wrong",
                "xlabel": f"Position in {prbs_name(length)} string (bit)",
                "width": length, "rows": [], "labels": [],
            })
            spec["rows"].append(row)
            spec["labels"].append(row_label(block, int(index)))

    maps = list(prbs_maps.values())
    if not coded:
        return maps

    # Rows in a fixed code order, whatever order they were sent in
    order = list(CODES)
    coded.sort(key=lambda item: (item[0][1], order.index(item[0][2])))
    several_sets = len({row[1] for row, _, _ in coded}) > 1
    rows = [row for row, _, _ in coded]
    labels = [f"{code} #{index + 1}" if several_sets else code for _, index, code in rows]

    maps.append({
        "key": "channel", "title": "Channel bits: where each coded string went wrong",
        "xlabel": "Position in coded string (bit)",
        "width": max(length for _, length, _ in coded), "rows": rows, "labels": labels,
    })
    maps.append({
        "key": "decoded", "title": "Decoded message: bits still wrong after decoding",
        "xlabel": "Position in message (bit)",
        "width": max(length for _, _, length in coded), "rows": list(rows), "labels": list(labels),
    })
    return maps


def load_raw(path: Path):
    """The raw samples of each bit in a saved .npz, or None if there isn't one."""
    if not path.exists():
        return None
    data = np.load(path)
    starts = data["bit_start"]
    return [data["samples"][starts[i]:starts[i + 1]] for i in range(len(starts) - 1)]


def saved_events(rows: dict, raw_dir: Path = None) -> list:
    """Turn saved strings back into viewer updates, so a resumed run shows them."""
    events = []
    for row in rows.values():
        if not shown(row["block"], row["seed"]):
            continue
        row_id = (row["block"], int(row["index"]), row["code"])
        sent = [int(bit) for bit in row["sent"]]
        events.append(("trial", map_key(row["block"], len(sent)), row_id, sent, int(row["threshold"])))

        raw = None
        if raw_dir is not None and row.get("raw_file"):
            raw = load_raw(raw_dir.parent / row["raw_file"])
        vibration = row["vibration"].split()
        for i, (bit, vib) in enumerate(zip(row["received"], vibration)):
            events.append(("bit", i, int(bit), int(vib), raw[i] if raw is not None else None))

        if row["block"] == "codes":
            message = [int(bit) for bit in row["message"]]
            decoded = [int(bit) for bit in row["decoded"]]
            events.append(("decoded", row_id, message, decoded))
    return events


class LiveView:
    def __init__(self, events: queue.Queue, case: str, layout: list, stop=None, save_path=None,
                 raw: bool = False):
        """
        Set up the window.

        Args:
            events (queue.Queue): updates from the running case.
            case (str): the case name for the title.
            layout (list): the error maps, from map_layout.
            stop (threading.Event, optional): set when the window closes.
            save_path (Path, optional): where to save a picture when the case ends.
            raw (bool, optional): show the raw signal panel. Defaults to False.
        """
        self.events = events
        self.case = case
        self.maps = {
            spec["key"]: {**spec, "raster": np.full((len(spec["rows"]), spec["width"]), NOT_SENT)}
            for spec in layout
        }
        self.stop = stop
        self.save_path = save_path
        self.show_raw = raw

        self.settle_ms = 0
        self.window_ms = 0
        self.sample_rate = 0
        self.raw_bits = deque(maxlen=RAW_BITS)   # (samples, sent, read) for the latest bits

        self.status = "Waiting"
        self.finished = False
        self.row = 0
        self.raster = None    # The map of the string being received
        self.sent = []
        self.threshold = 0
        self.position = 0
        self.total = 0

        self.strip = deque(maxlen=STRIP_BITS)
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

        # A map with few rows, like a single PRBS-9 string, doesn't need much height
        map_heights = [0.3 + 0.1 * len(m["labels"]) for m in self.maps.values()]
        top_heights = [1.3, 1.1] if self.show_raw else [1.1]
        height = 8.5 + (2.0 if self.show_raw else 0) + 0.8 * max(0, len(map_heights) - 1)

        self.fig = plt.figure(figsize=(13, height), facecolor=SURFACE)
        self.fig.canvas.manager.set_window_title("PRBS live view")
        grid = self.fig.add_gridspec(
            len(top_heights) + len(map_heights) + 1, 3,
            height_ratios=[*top_heights, *map_heights, 1.1],
            width_ratios=[0.8, 1, 1.2],
            left=0.09 if "channel" in self.maps else 0.06, right=0.98,
            top=1 - 1.0 / height, bottom=0.7 / height,
            hspace=0.62, wspace=0.26,
        )

        self.title = self.fig.text(0.06, 1 - 0.38 / height, self.case, fontsize=14, weight="bold")
        self.subtitle = self.fig.text(0.06, 1 - 0.64 / height, "", color=INK_SECONDARY)

        self.ax_raw = self.fig.add_subplot(grid[0, :]) if self.show_raw else None
        self.ax_strip = self.fig.add_subplot(grid[len(top_heights) - 1, :])
        for row, info in enumerate(self.maps.values(), len(top_heights)):
            info["ax"] = self.fig.add_subplot(grid[row, :])
        self.ax_stats = self.fig.add_subplot(grid[-1, 0])
        self.ax_after = self.fig.add_subplot(grid[-1, 1])
        self.ax_runs = self.fig.add_subplot(grid[-1, 2])

        map_axes = [info["ax"] for info in self.maps.values()]
        for ax in (self.ax_strip, *map_axes, self.ax_after, self.ax_runs):
            ax.set_facecolor(SURFACE)
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.tick_params(length=0)

        self._build_strip()
        for number, info in enumerate(self.maps.values()):
            self._build_raster(info, show_legend=number == 0)
        self.ax_stats.axis("off")
        if self.ax_raw is not None:
            self._draw_raw()

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

    def _build_raster(self, info: dict, show_legend: bool) -> None:
        ax = info["ax"]
        ax.set_title(info["title"], loc="left", fontsize=11)
        ax.set_xlabel(info["xlabel"])
        ax.set_yticks(range(len(info["labels"])), info["labels"], fontsize=8)

        info["image"] = ax.imshow(
            info["raster"], aspect="auto", interpolation="nearest",
            cmap=ListedColormap(RASTER_COLOURS),
            norm=BoundaryNorm([-0.5, 0.5, 1.5, 2.5, 3.5], 4),
        )

        if not show_legend:
            return

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
            _, key, row_id, self.sent, self.threshold = event
            info = self.maps[key]
            self.raster = info["raster"]
            self.row = info["rows"].index(row_id)
            self.position = 0
            label = info["labels"][self.row]
            if key == "channel":
                self.status = f"Coded {label}, string {self.row + 1} of {len(info['labels'])}"
            else:
                self.status = f"{prbs_name(len(self.sent))} {label} of {len(info['labels'])}"

        elif kind == "bit":
            _, index, bit, vibration, raw = event
            self._add_bit(index, bit, vibration)
            if raw is not None:
                self.raw_bits.append((raw, self.sent[index], bit))

        elif kind == "decoded":
            _, row_id, message, decoded = event
            info = self.maps["decoded"]
            row = info["rows"].index(row_id)
            for i, (want, got) in enumerate(zip(message, decoded)):
                info["raster"][row, i] = CORRECT if want == got else (
                    WRONG_SENT_0 if want == 0 else WRONG_SENT_1)

        elif kind == "config":
            _, self.settle_ms, self.window_ms, self.sample_rate = event

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
        if self.sent and self.status.startswith(("PRBS", "Coded")):
            detail += f", bit {self.position} of {len(self.sent)}"
        if self.threshold:
            detail += f"  |  threshold {self.threshold:,}"
        self.subtitle.set_text(detail)

        if self.ax_raw is not None:
            self._draw_raw()
        self._draw_strip()
        for info in self.maps.values():
            info["image"].set_data(info["raster"])
        self._draw_stats()
        self._draw_after()
        self._draw_runs()

    def _draw_raw(self) -> None:
        ax = self.ax_raw
        ax.clear()
        self._style(ax, f"Raw piezo signal, latest {RAW_BITS} bits", "Time (ms)", "ADC counts")
        ax.grid(False)
        ax.legend(
            handles=[
                Patch(color=SENT_0, alpha=0.25, label="Sent 0"),
                Patch(color=SENT_1, alpha=0.25, label="Sent 1"),
                Patch(facecolor="none", edgecolor=INK_SECONDARY, label="Measuring window"),
            ],
            loc="lower right", bbox_to_anchor=(1, 1), ncol=3, frameon=False, fontsize=9,
        )
        if not self.raw_bits or not self.sample_rate:
            ax.text(0.5, 0.5, "Waiting for raw samples", transform=ax.transAxes,
                    ha="center", va="center", color=MUTED)
            return

        ms_per_sample = 1000 / self.sample_rate
        start = 0
        low = min(int(r.min()) for r, _, _ in self.raw_bits)
        high = max(int(r.max()) for r, _, _ in self.raw_bits)
        pad = max(high - low, 1) * 0.08

        for samples, sent, read in self.raw_bits:
            t = (start + np.arange(len(samples))) * ms_per_sample
            end = start + len(samples)
            colour = SENT_0 if sent == 0 else SENT_1
            ax.axvspan(start * ms_per_sample, end * ms_per_sample, color=colour, alpha=0.10, linewidth=0)

            window_start = start * ms_per_sample + self.settle_ms
            ax.add_patch(plt.Rectangle(
                (window_start, low - pad * 0.5), self.window_ms, high - low + pad,
                fill=False, edgecolor=INK_SECONDARY, linewidth=0.8, linestyle="--",
            ))
            ax.plot(t, samples, color=INK, linewidth=0.6)

            wrong = read != sent
            ax.text((start + end) / 2 * ms_per_sample, high + pad * 1.2,
                    f"sent {sent}, read {read}" + ("  ✗" if wrong else ""),
                    ha="center", va="bottom", fontsize=9,
                    color=BAD_MARK if wrong else INK_SECONDARY, weight="bold" if wrong else "normal")
            start = end

        ax.set_xlim(0, start * ms_per_sample)
        ax.set_ylim(low - pad, high + pad * 3.5)

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

    layout = map_layout(
        (row["block"], row["index"], row["code"], len(row["sent"]), len(row["message"]))
        for row in rows.values() if shown(row["block"], row["seed"])
    )

    raw_dir = path.parent / f"{path.stem}_raw"
    has_raw = any(row.get("raw_file") for row in rows.values())
    first = next(iter(rows.values()), {})

    events = queue.Queue()
    if has_raw:
        settings = np.load(raw_dir.parent / next(r["raw_file"] for r in rows.values() if r.get("raw_file")))
        events.put(("config", int(first["settle_ms"]), int(first["window_ms"]), int(settings["sample_rate"])))
    for event in saved_events(rows, raw_dir):
        events.put(event)
    events.put(("done", "Saved run"))

    view = LiveView(events, path.stem, layout, save_path=path.with_suffix(".png"), raw=has_raw)
    view.update()
    print("Saved", path.with_suffix(".png"))
    plt.show()


if __name__ == "__main__":
    main()
