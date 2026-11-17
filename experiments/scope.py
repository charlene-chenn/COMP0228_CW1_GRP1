"""
The raw piezo signal, drawn like an oscilloscope.

RawScope draws the latest bits on any matplotlib axes. The live viewer uses one in
its raw panel. With --live, run_case also opens a separate "Raw signal scope"
window in its own process (open_scope_window), which scrolls smoothly at about
30 frames a second. It has its own process because matplotlib draws one window at
a time: in the same process, every redraw of the main viewer would freeze it.

Samples arrive one bit at a time (102.4 ms at 50/50), so the scope window plays
them back about one bit behind the newest sample, at the real sample rate. That
way it scrolls steadily instead of jumping a bit at a time.
"""
import multiprocessing
import queue
import time
from collections import deque

import numpy as np

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
AXIS = "#c3c2b7"
SENT_0 = "#eb6834"
SENT_1 = "#2a78d6"
BAD_MARK = "#0b0b0b"

ADC_MAX = 65535
TOP = ADC_MAX * 1.12   # Room above the signal for the window bars and read dots
RAW_BITS = 6           # How many bits wide the scope is
KEEP_S = 4.0           # Seconds of samples kept
DELAY_BITS = 1.5       # How far behind the newest sample the scope window plays. Over
                       # one bit, so it doesn't run out of samples before the next bit arrives
FRAME_MS = 33          # Scope window refresh, about 30 frames a second


class RawScope:
    def __init__(self, ax, animated: bool = False):
        """
        Set up the raw signal on some axes.

        Args:
            ax: the matplotlib axes to draw on.
            animated (bool, optional): True when the caller redraws only this
                axes with blitting, as the scope window does. Defaults to False.
        """
        from matplotlib.lines import Line2D

        self.ax = ax
        self.settle_ms = 0
        self.window_ms = 0
        self.sample_rate = 0

        self.ring = None
        self.ring_sent = None                # The bit sent at each sample, -1 for a gap
        self.total = 0                       # Samples added so far
        self.bits = deque(maxlen=4 * RAW_BITS)   # (first sample, length, sent, read)
        self.bit_length = 0                  # Samples in the latest bit
        self.head = 0.0                      # Sample shown at the right-hand edge
        self.last_tick = None
        self.new_string = False

        ax.set_facecolor(SURFACE)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(length=0)
        ax.set_xlabel("Time (ms, 0 = right-hand edge)")
        ax.set_ylabel("ADC counts")
        ax.set_ylim(0, TOP)
        ax.set_xlim(-RAW_BITS * 102.4, 0)
        ax.axhline(ADC_MAX, color=MUTED, linewidth=0.8, linestyle=":")
        ax.text(0.003, ADC_MAX, "ADC max", transform=ax.get_yaxis_transform(),
                ha="left", va="top", color=MUTED, fontsize=8)
        ax.legend(
            handles=[
                Line2D([], [], color=SENT_0, label="Signal while sending 0"),
                Line2D([], [], color=SENT_1, label="Signal while sending 1"),
                Line2D([], [], color=INK_SECONDARY, linewidth=3, alpha=0.45, label="Measuring window"),
                Line2D([], [], marker="o", linestyle="", color=MUTED, label="Read as (colour)"),
                Line2D([], [], marker="x", linestyle="", color=BAD_MARK, label="Read wrongly"),
            ],
            loc="lower right", bbox_to_anchor=(1, 1), ncol=5, frameon=False, fontsize=9,
        )

        # Few artists, and none with large see-through areas or text, so each frame is quick
        self.waiting = ax.text(0.5, 0.5, "Waiting for raw samples", transform=ax.transAxes,
                               ha="center", va="center", color=MUTED, animated=animated)
        self.trace_0 = ax.plot([], [], color=SENT_0, linewidth=0.7, animated=animated)[0]
        self.trace_1 = ax.plot([], [], color=SENT_1, linewidth=0.7, animated=animated)[0]
        self.window_bars = ax.plot([], [], color=INK_SECONDARY, linewidth=3, alpha=0.45,
                                   solid_capstyle="butt", animated=animated)[0]
        self.reads = ax.scatter([], [], s=42, edgecolors=SURFACE, linewidths=1, animated=animated)
        self.wrong = ax.scatter([], [], s=70, marker="x", color=BAD_MARK, linewidths=1.8,
                                animated=animated)

    def artists(self) -> list:
        """Everything that moves, in drawing order."""
        return [self.window_bars, self.trace_0, self.trace_1, self.reads, self.wrong, self.waiting]

    def configure(self, settle_ms: int, window_ms: int, sample_rate: int) -> None:
        self.settle_ms, self.window_ms, self.sample_rate = settle_ms, window_ms, sample_rate

    def start_string(self) -> None:
        """Mark that a new string starts, so the line breaks over the unrecorded gap."""
        self.new_string = True

    def add_bit(self, samples, sent: int, read: int) -> bool:
        """
        Add one bit's samples.

        Returns:
            bool: True if the bit length changed, so the time axis needs resizing.
        """
        if self.ring is None:
            size = int(KEEP_S * (self.sample_rate or 10000))
            self.ring = np.full(size, np.nan, dtype=np.float32)
            self.ring_sent = np.full(size, -1, dtype=np.int8)

        if self.new_string and self.total:
            self.ring[self.total % len(self.ring)] = np.nan
            self.ring_sent[self.total % len(self.ring)] = -1
            self.total += 1
        self.new_string = False

        start = self.total
        index = (start + np.arange(len(samples))) % len(self.ring)
        self.ring[index] = samples
        self.ring_sent[index] = sent
        self.total += len(samples)
        self.bits.append((start, len(samples), sent, read))

        changed = len(samples) != self.bit_length
        self.bit_length = len(samples)
        if changed:
            self.resize()
        return changed

    def resize(self) -> None:
        """Make the time axis RAW_BITS bits wide."""
        if self.bit_length and self.sample_rate:
            self.ax.set_xlim(-RAW_BITS * self.bit_length / self.sample_rate * 1000, 0)

    def show_newest(self) -> None:
        """Put the newest sample at the right-hand edge, for a still picture."""
        self.head = float(self.total)

    def advance(self, now: float) -> None:
        """Move on at the sample rate, staying about DELAY_BITS behind the newest sample."""
        if not self.total or not self.sample_rate:
            self.last_tick = now
            return

        target = self.total - DELAY_BITS * self.bit_length
        if self.last_tick is None or target - self.head > 3 * self.bit_length:
            self.head = target   # Starting, or so far behind that it should jump
        else:
            # Run slightly fast or slow to drift back to the target, rather than jumping.
            # The target leaps a whole bit each time one arrives, so only nudge gently
            correction = np.clip((target - self.head) / (8 * self.bit_length), -0.2, 0.2)
            self.head += (now - self.last_tick) * self.sample_rate * (1 + correction)
        self.head = min(self.head, float(self.total))
        self.last_tick = now

    def render(self) -> None:
        """Point the traces, window bars and read dots at the samples now on screen."""
        if not self.total or not self.sample_rate:
            self.waiting.set_visible(True)
            return
        self.waiting.set_visible(False)

        ms = 1000 / self.sample_rate
        width = RAW_BITS * self.bit_length
        right = int(self.head)
        left = max(right - width, self.total - len(self.ring) + 1, 0)

        # About one column of min and max per pixel, as a scope draws it, rather than every sample
        columns = max(int(self.ax.bbox.width), 200)
        step = max(1, (right - left) // columns)
        count = (right - left) // step
        start = right - count * step
        index = (start + np.arange(count * step)) % len(self.ring)
        values = self.ring[index].reshape(count, step)
        sent = self.ring_sent[index].reshape(count, step)[:, 0]
        x = (start + np.arange(count) * step - self.head) * ms

        with np.errstate(all="ignore"):
            low, high = np.nanmin(values, axis=1), np.nanmax(values, axis=1)
        xs = np.repeat(x, 2)
        ys = np.column_stack([low, high]).ravel()
        sent2 = np.repeat(sent, 2)
        self.trace_0.set_data(xs, np.where(sent2 == 0, ys, np.nan))
        self.trace_1.set_data(xs, np.where(sent2 == 1, ys, np.nan))

        # A bar over each bit's measuring window, and a dot for what it was read as
        on_screen = [b for b in self.bits if b[0] < right and b[0] + b[1] > right - width]
        bars_x, bars_y, dots, colours, wrong = [], [], [], [], []
        for first, length, bit_sent, read in on_screen:
            x0 = (first - self.head) * ms + self.settle_ms
            bars_x += [x0, x0 + self.window_ms, np.nan]
            bars_y += [ADC_MAX * 1.04] * 2 + [np.nan]
            centre = (x0 + self.window_ms / 2, ADC_MAX * 1.085)
            dots.append(centre)
            colours.append(SENT_0 if read == 0 else SENT_1)
            if read != bit_sent:
                wrong.append(centre)
        self.window_bars.set_data(bars_x, bars_y)
        self.reads.set_offsets(np.array(dots).reshape(-1, 2))
        self.reads.set_facecolor(colours or [MUTED])
        self.wrong.set_offsets(np.array(wrong).reshape(-1, 2))


def _scope_window(messages, title: str) -> None:
    """The scope window's process: draw the samples it is sent until told to stop."""
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.family": "sans-serif", "font.size": 10, "text.color": INK,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK_SECONDARY,
        "xtick.color": MUTED, "ytick.color": MUTED,
    })
    fig = plt.figure(figsize=(13, 3.6), facecolor=SURFACE)
    fig.canvas.manager.set_window_title("Raw signal scope")
    ax = fig.add_axes([0.06, 0.16, 0.92, 0.66])
    fig.text(0.06, 0.92, title, fontsize=12, weight="bold")
    fig.text(0.06, 0.865, f"Raw piezo signal, about {DELAY_BITS:g} bit behind live",
             color=INK_SECONDARY)
    scope = RawScope(ax, animated=True)
    state = {"background": None, "running": True}

    def on_draw(_event):
        state["background"] = fig.canvas.copy_from_bbox(ax.bbox)
        for artist in scope.artists():
            ax.draw_artist(artist)

    def tick():
        resized = False
        try:
            while True:
                message = messages.get_nowait()
                kind = message[0]
                if kind == "config":
                    scope.configure(*message[1:])
                    resized = True
                elif kind == "string":
                    scope.start_string()
                elif kind == "bit":
                    resized |= scope.add_bit(*message[1:])
                elif kind == "close":
                    state["running"] = False
        except queue.Empty:
            pass
        except (EOFError, OSError):
            state["running"] = False   # The viewer has gone

        if not state["running"]:
            plt.close(fig)
            return
        if resized:
            scope.resize()
            fig.canvas.draw_idle()   # New tick labels, so a full redraw once
            return

        scope.advance(time.monotonic())
        scope.render()
        if state["background"] is not None:
            fig.canvas.restore_region(state["background"])
            for artist in scope.artists():
                ax.draw_artist(artist)
            fig.canvas.blit(ax.bbox)

    fig.canvas.mpl_connect("draw_event", on_draw)
    timer = fig.canvas.new_timer(interval=FRAME_MS)
    timer.add_callback(tick)
    timer.start()
    plt.show()


class ScopeWindow:
    """The viewer's handle on the scope window process."""

    def __init__(self, title: str):
        context = multiprocessing.get_context("spawn")
        self.messages = context.Queue()
        self.process = context.Process(target=_scope_window, args=(self.messages, title), daemon=True)
        self.process.start()

    def send(self, *message) -> None:
        # Once its window is closed, stop sending, or unread samples would pile up
        if self.process.is_alive():
            self.messages.put(message)

    def close(self) -> None:
        self.send("close")
        self.process.join(timeout=2)
        if self.process.is_alive():
            self.process.terminate()
