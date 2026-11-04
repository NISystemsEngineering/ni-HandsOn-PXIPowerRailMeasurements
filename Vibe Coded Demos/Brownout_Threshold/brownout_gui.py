"""
Live GUI for the ESP32-C6 brownout characterization sweep.

Runs the same BrownoutSweep class as the command-line demo, but plots each point as
soon as its gain step finishes, so the curve builds on screen while the sweep runs.

The x axis is the ripple amplitude actually measured at the rail rather than the
commanded arb gain. Gain is only a knob on this station -- the high-pass coupling
network between the arb and the rail means the same gain delivers different amplitude
on different hardware, so amplitude is the axis that transfers.

Two statistical details matter for reading the plot honestly:

  * Error bars are Wilson score intervals, not the usual normal approximation. With
    only tens of trials per point the normal approximation gives a zero-width bar at
    0% and 100%, implying certainty that the data does not support. Wilson reports a
    real interval there, which is why 12-of-12 is not drawn as a bare dot.

  * The fitted curve is a logistic regression on the trial outcomes, which is what
    turns scattered points into a single defensible threshold number. Brownouts near
    the threshold are probabilistic, so the underlying transition is smooth and the
    point-to-point scatter is sampling noise rather than structure.

Usage:
    python brownout_gui.py

Requires the same NI runtimes and Python packages as brownout_sweep.py; tkinter ships
with Python on Windows.
"""

from __future__ import annotations

import csv
import queue
import threading
import tkinter as tk
from dataclasses import asdict
from datetime import datetime
from tkinter import messagebox, ttk
from typing import List, Optional, Tuple

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from brownout_sweep import BrownoutSweep, GainResult

# 95% two-sided normal quantile, for the Wilson interval.
Z_95 = 1.959963984540054

# The DUT's configured brownout detector level. Used only to annotate the plot: it is a
# firmware setting, not something this code measures or controls. Trips line up with the
# rail dipping below it, which is what makes the mechanism visible on the rail panel.
BROWNOUT_DETECTOR_V = 3.27


def wilson_interval(tripped: int, total: int, z: float = Z_95) -> Tuple[float, float]:
    """
    Wilson score confidence interval for a binomial proportion.

    Preferred over the normal approximation because the interesting points of a
    brownout curve are exactly where it fails: at 0 or 100% trips the normal
    approximation collapses to zero width, claiming certainty from a handful of
    trials. Wilson stays finite there.

    Args:
        tripped: Number of trials that tripped.
        total: Number of trials run.
        z: Normal quantile setting the confidence level (default 95%).

    Returns:
        (lower, upper) bounds, each clipped to [0, 1].
    """
    if total == 0:
        return 0.0, 1.0

    p = tripped / total
    denom = 1.0 + z * z / total
    center = (p + z * z / (2.0 * total)) / denom
    half = (z / denom) * np.sqrt(p * (1.0 - p) / total + z * z / (4.0 * total * total))
    return max(0.0, center - half), min(1.0, center + half)


def fit_logistic(
    x: np.ndarray, tripped: np.ndarray, total: np.ndarray
) -> Optional[Tuple[float, float]]:
    """
    Fit a logistic curve to binomial trip counts by iteratively reweighted least squares.

    Written out rather than pulled from scipy to keep the dependency list to what the
    sweep itself already needs. Returns None when the data cannot support a fit, which
    is the normal case early in a live sweep: with every point still at 0% trips there
    is no transition to locate, and a fit would only invent one.

    At least two points must be partially tripped. One is enough to satisfy the
    likelihood, but not to separate where the transition sits from how sharp it is, so
    the fit collapses to a near-vertical step at that point -- which looks like a
    confident measurement of a hard threshold when it is nothing of the kind.

    Args:
        x: Predictor at each point (measured ripple amplitude).
        tripped: Trips at each point.
        total: Trials at each point.

    Returns:
        (x50, slope) where x50 is the 50% crossing in the units of x, or None.
    """
    partial = int(np.sum((tripped > 0) & (tripped < total)))
    if len(x) < 3 or partial < 2:
        return None

    # Centre and scale the predictor. Amplitudes are order 100-400 mVpp, which makes
    # the raw design matrix badly conditioned and stalls the solve.
    x_mean, x_scale = float(x.mean()), float(x.std())
    if x_scale == 0.0:
        return None
    u = (x - x_mean) / x_scale

    design = np.column_stack([np.ones_like(u), u])
    beta = np.zeros(2)
    for _ in range(100):
        p = 1.0 / (1.0 + np.exp(-(design @ beta)))
        # Keep the weights away from zero, or a point that has saturated at 0 or 100%
        # contributes nothing and the normal equations go singular.
        w = np.clip(total * p * (1.0 - p), 1e-9, None)
        gradient = design.T @ (tripped - total * p)
        hessian = design.T @ (design * w[:, None])
        try:
            step = np.linalg.solve(hessian, gradient)
        except np.linalg.LinAlgError:
            return None
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break

    if beta[1] <= 0.0:   # a non-increasing fit is not physical here
        return None

    x50 = x_mean - x_scale * beta[0] / beta[1]
    return float(x50), float(beta[1] / x_scale)


class BrownoutGUI:
    """
    Tkinter window that runs a sweep on a worker thread and plots it as it goes.

    The sweep cannot run on the GUI thread: each trial blocks for up to several seconds
    waiting on the scope and the DUT serial port, which would freeze the window. The
    worker owns the instrument sessions for its whole life and hands finished results
    back through a queue, which the GUI drains on a timer. That keeps every instrument
    call on one thread and every widget call on another, with no shared mutable state.
    """

    POLL_MS = 100

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ESP32-C6 BLE-Induced Brownout Characterization")

        self._queue: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._results: List[GainResult] = []

        self._build_controls()
        self._build_plot()
        self.root.after(self.POLL_MS, self._drain_queue)

    def _build_controls(self) -> None:
        """Lay out the entry fields and buttons down the left side."""
        panel = ttk.Frame(self.root, padding=10)
        panel.grid(row=0, column=0, sticky="ns")

        # Defaults come from the class, so the GUI never becomes a second place where
        # this station's settings are written down.
        station = BrownoutSweep()
        self._fields = {
            "rail": tk.StringVar(value=f"{station.supply_voltage}"),
            "gain_start": tk.StringVar(value="6.0"),
            "gain_stop": tk.StringVar(value="3.0"),
            "gain_step": tk.StringVar(value="-1.0"),
            "trials": tk.StringVar(value="3"),
        }
        self._live_updates = tk.BooleanVar(value=True)
        self._partial_results: dict = {}  # gain -> partial GainResult being built
        labels = [
            ("Rail voltage (V)", "rail"),
            ("Gain start", "gain_start"),
            ("Gain stop", "gain_stop"),
            ("Gain step", "gain_step"),
            ("Trials per gain", "trials"),
        ]
        for row, (text, key) in enumerate(labels):
            ttk.Label(panel, text=text).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(panel, textvariable=self._fields[key], width=10).grid(
                row=row, column=1, sticky="e", pady=3
            )

        ttk.Separator(panel, orient="horizontal").grid(
            row=len(labels), column=0, columnspan=2, sticky="ew", pady=10
        )

        ttk.Checkbutton(panel, text="Live trial updates (more dynamic)",
                        variable=self._live_updates).grid(
            row=len(labels) + 1, column=0, columnspan=2, sticky="w", pady=(0, 8))

        self._run_button = ttk.Button(panel, text="Run sweep", command=self._start)
        self._run_button.grid(row=len(labels) + 2, column=0, columnspan=2, sticky="ew")

        self._stop_button = ttk.Button(
            panel, text="Stop", command=self._request_stop, state="disabled"
        )
        self._stop_button.grid(row=len(labels) + 3, column=0, columnspan=2,
                               sticky="ew", pady=4)

        self._save_button = ttk.Button(
            panel, text="Save CSV", command=self._save_csv, state="disabled"
        )
        self._save_button.grid(row=len(labels) + 4, column=0, columnspan=2, sticky="ew")

        ttk.Button(panel, text="Close", command=self.root.destroy).grid(
            row=len(labels) + 5, column=0, columnspan=2, sticky="ew", pady=4)

        self._status = tk.StringVar(value="Idle. Check the rail voltage, then run.")
        ttk.Label(panel, textvariable=self._status, wraplength=210,
                  foreground="#444").grid(row=len(labels) + 6, column=0, columnspan=2,
                                          sticky="w", pady=(12, 0))

        self._threshold = tk.StringVar(value="")
        ttk.Label(panel, textvariable=self._threshold, wraplength=210,
                  font=("TkDefaultFont", 9, "bold")).grid(
            row=len(labels) + 7, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _build_plot(self) -> None:
        """Embed a matplotlib canvas. Figure/canvas rather than pyplot, to stay off
        pyplot's global state now that a second thread is in play.

        Four panels, arranged so the demo can be walked through in reading order: the
        headline result, the knob that was actually turned, how close the rail gets to
        the detector, and what a unit of gain delivers at the rail.
        """
        self._figure = Figure(figsize=(11.5, 7.4), dpi=100)
        (self._ax_amplitude, self._ax_gain), (self._ax_rail, self._ax_transfer) = \
            self._figure.subplots(2, 2)
        self._canvas = FigureCanvasTkAgg(self._figure, master=self.root)
        self._canvas.get_tk_widget().grid(row=0, column=1, sticky="nsew")

        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        self._redraw()

    def _start(self) -> None:
        """Validate the fields, then hand a gain list to a worker thread."""
        try:
            rail = float(self._fields["rail"].get())
            gain_start = float(self._fields["gain_start"].get())
            gain_stop = float(self._fields["gain_stop"].get())
            gain_step = float(self._fields["gain_step"].get())
            trials = int(self._fields["trials"].get())
        except ValueError:
            messagebox.showerror("Invalid input", "All fields must be numbers.")
            return

        if gain_start <= 0 or gain_step == 0 or trials < 1:
            messagebox.showerror(
                "Invalid input",
                "Gain start must be greater than zero, step must be non-zero, "
                "and trials at least 1. The arb has no valid zero gain."
            )
            return

        gains: List[float] = []
        gain = gain_start
        # Handle both forward (positive step) and backward (negative step) sweeps
        if gain_step > 0:
            while gain <= gain_stop + abs(gain_step) / 2:
                gains.append(round(gain, 6))
                gain += gain_step
        else:
            while gain >= gain_stop - abs(gain_step) / 2:
                gains.append(round(gain, 6))
                gain += gain_step

        self._results.clear()
        self._threshold.set("")
        self._stop.clear()
        self._redraw()

        self._run_button.configure(state="disabled")
        self._stop_button.configure(state="normal")
        self._save_button.configure(state="disabled")
        self._status.set("Opening instrument sessions ...")

        live = self._live_updates.get()
        # Demo mode: faster serial timeout (1s instead of 2.5s). Brownout messages
        # appear within ~0.5s, so 1s is still safe while cutting 1.5s off every
        # non-tripping trial.
        timeout_ms = 1000

        self._partial_results.clear()
        self._worker = threading.Thread(
            target=self._run_sweep,
            args=(rail, gains, gain_step, trials, live, timeout_ms),
            daemon=True
        )
        self._worker.start()

    def _run_sweep(
        self, rail: float, gains: List[float], gain_step: float, trials: int,
        live_updates: bool, timeout_ms: float
    ) -> None:
        """
        Worker thread: own the instruments and run one gain step at a time.

        run_sweep() is called per gain rather than once for the whole range so a point
        reaches the plot as soon as it is measured, and so Stop takes effect at the end
        of the current gain instead of after the entire sweep.

        The serial timeout trades speed vs confidence: 1s is fast but risks missing
        late brownouts, 2.5s is conservative but each non-tripping trial waits longer.
        """
        try:
            with BrownoutSweep(supply_voltage=rail,
                               dut_serial_timeout_ms=timeout_ms) as sweep:
                self._queue.put(("ready", len(gains)))
                for index, gain in enumerate(gains, start=1):
                    if self._stop.is_set():
                        break
                    self._queue.put(("progress", (index, len(gains), gain)))
                    
                    if live_updates:
                        # Run trial-by-trial for live updates
                        for trial in range(trials):
                            if self._stop.is_set():
                                break
                            result = sweep.run_sweep(
                                gain_start=gain,
                                gain_stop=gain,
                                gain_step=gain_step,
                                trials_per_gain=1,
                            )[0]
                            # Send the single-trial result; GUI will accumulate it
                            self._queue.put(("trial", (gain, result.trials[0])))
                        # After all trials for this gain, mark it complete
                        self._queue.put(("gain_complete", gain))
                    else:
                        # Run all trials at once for speed
                        result = sweep.run_sweep(
                            gain_start=gain,
                            gain_stop=gain,
                            gain_step=gain_step,
                            trials_per_gain=trials,
                        )[0]
                        self._queue.put(("result", result))
            self._queue.put(("done", self._stop.is_set()))
        except Exception as exc:
            # Includes the scope-arm timeout, which is a real fault and must surface
            # rather than being recorded as a point that simply did not trip.
            self._queue.put(("error", f"{type(exc).__name__}: {exc}"))

    def _request_stop(self) -> None:
        self._stop.set()
        self._status.set("Stopping after the current gain step ...")
        self._stop_button.configure(state="disabled")

    def _drain_queue(self) -> None:
        """Pull worker messages on the GUI thread, where widget calls are safe."""
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "ready":
                    self._status.set(f"Instruments ready. {payload} gain steps queued.")
                elif kind == "progress":
                    index, count, gain = payload
                    self._status.set(
                        f"Gain step {index} of {count} (gain {gain:.2f}) ..."
                    )
                elif kind == "trial":
                    gain, trial = payload
                    # Accumulate trials for this gain
                    if gain not in self._partial_results:
                        self._partial_results[gain] = []
                    self._partial_results[gain].append(trial)
                    self._redraw()  # Redraw after every trial for live feel
                elif kind == "gain_complete":
                    gain = payload
                    # Build final GainResult from accumulated trials
                    trials = self._partial_results.get(gain, [])
                    if trials:
                        tripped_count = sum(1 for t in trials if t.tripped)
                        result = GainResult(
                            gain=gain,
                            total_trials=len(trials),
                            tripped_count=tripped_count,
                            trip_fraction=tripped_count / len(trials),
                            mean_ripple_vpp=float(np.mean([t.ripple_vpp for t in trials])),
                            mean_ripple_vrms=float(np.mean([t.ripple_vrms for t in trials])),
                            mean_ripple_dbv=float(np.mean([t.ripple_dbv for t in trials])),
                            mean_rail_min=float(np.mean([t.rail_min for t in trials])),
                            trials=trials,
                        )
                        self._results.append(result)
                        self._save_button.configure(state="normal")
                elif kind == "result":
                    self._results.append(payload)
                    self._redraw()
                    self._save_button.configure(state="normal")
                elif kind == "done":
                    self._finish("Stopped." if payload else "Sweep complete.")
                elif kind == "error":
                    self._finish("Failed.")
                    messagebox.showerror("Sweep failed", payload)
        except queue.Empty:
            pass
        self.root.after(self.POLL_MS, self._drain_queue)

    def _finish(self, message: str) -> None:
        self._status.set(message)
        self._run_button.configure(state="normal")
        self._stop_button.configure(state="disabled")

    def _probability_bars(
        self, axes, x: np.ndarray, p: np.ndarray, lower: np.ndarray, upper: np.ndarray,
        label: Optional[str] = None
    ) -> None:
        """Draw one probability panel's points with their confidence intervals."""
        axes.set_ylabel("Trip probability")
        axes.set_ylim(-0.05, 1.05)
        axes.grid(True, alpha=0.3)
        axes.axhline(0.5, color="r", linestyle="--", linewidth=1)
        axes.errorbar(x, p, yerr=[lower, upper], fmt="o", color="tab:blue",
                      ecolor="tab:blue", elinewidth=1.2, capsize=4, markersize=6,
                      label=label)

    def _redraw(self) -> None:
        """
        Redraw all four panels. Cheap at this point count, and avoids tracking artists
        across incremental updates.

        The panels answer four different questions, which is why they are not merged:
        what amplitude trips this DUT, why it trips, what was actually swept, and what
        the coupling network delivers for a given gain.
        """
        for axes in (self._ax_amplitude, self._ax_rail,
                     self._ax_gain, self._ax_transfer):
            axes.clear()

        # Combine completed results with partial in-progress results
        all_results = list(self._results)
        for gain in sorted(self._partial_results.keys()):
            trials = self._partial_results[gain]
            if trials and gain not in [r.gain for r in all_results]:
                # Build a temporary result from partial data
                tripped = sum(1 for t in trials if t.tripped)
                all_results.append(GainResult(
                    gain=gain,
                    total_trials=len(trials),
                    tripped_count=tripped,
                    trip_fraction=tripped / len(trials) if trials else 0,
                    mean_ripple_vpp=float(np.mean([t.ripple_vpp for t in trials])),
                    mean_ripple_vrms=float(np.mean([t.ripple_vrms for t in trials])),
                    mean_ripple_dbv=float(np.mean([t.ripple_dbv for t in trials])),
                    mean_rail_min=float(np.mean([t.rail_min for t in trials])),
                    trials=trials,
                ))

        if not all_results:
            self._ax_amplitude.set_title("Waiting for the first trial")
            for axes in (self._ax_amplitude, self._ax_rail,
                         self._ax_gain, self._ax_transfer):
                axes.grid(True, alpha=0.3)
                axes.text(0.5, 0.5, "No data yet", transform=axes.transAxes,
                          ha="center", va="center", color="#999")
            self._figure.tight_layout()
            self._canvas.draw_idle()
            return

        mvpp = np.array([r.mean_ripple_vpp * 1e3 for r in all_results])
        gain = np.array([r.gain for r in all_results])
        rail_min = np.array([r.mean_rail_min for r in all_results])
        p = np.array([r.trip_fraction for r in all_results])
        tripped = np.array([r.tripped_count for r in all_results])
        total = np.array([r.total_trials for r in all_results])

        bounds = [wilson_interval(k, n) for k, n in zip(tripped, total)]
        lower = np.array([max(0.0, pi - b[0]) for pi, b in zip(p, bounds)])
        upper = np.array([max(0.0, b[1] - pi) for pi, b in zip(p, bounds)])

        # Panel 1: the headline result. Amplitude rather than gain, because gain is
        # only meaningful on this station's coupling network.
        axes = self._ax_amplitude
        self._probability_bars(axes, mvpp, p, lower, upper,
                               label=f"{total[0]} trials/point, 95% Wilson CI")
        axes.set_xlabel("Measured 7 kHz ripple at rail (mVpp)")
        axes.set_title("Trip probability vs measured ripple")

        # Label each point with the gain that produced it, so this panel still connects
        # back to the knob being swept. Labels drop below the marker near the top of
        # the axes, where the error bar and the frame would otherwise clip them.
        for xi, pi, hi, result in zip(mvpp, p, upper, all_results):
            axes.annotate(f"{result.gain:g}", (xi, pi), textcoords="offset points",
                          xytext=(0, -15 if pi + hi > 0.9 else 10), ha="center",
                          fontsize=7, color="#777")

        fit = fit_logistic(mvpp, tripped, total)
        if fit is not None:
            x50, slope = fit
            smooth = np.linspace(mvpp.min(), mvpp.max(), 300)
            axes.plot(smooth, 1.0 / (1.0 + np.exp(-slope * (smooth - x50))),
                      color="tab:green", linewidth=2, label="Logistic fit")
            if mvpp.min() <= x50 <= mvpp.max():
                axes.axvline(x50, color="tab:green", linestyle=":", linewidth=1.2)
                axes.annotate(f"50% at {x50:.0f} mVpp", (x50, 0.5),
                              textcoords="offset points", xytext=(6, -16),
                              fontsize=8, color="tab:green")
                self._threshold.set(f"50% trip point: {x50:.0f} mVpp")
            else:
                # The crossing is outside the swept range, so it is an extrapolation.
                self._threshold.set(f"50% trip point: {x50:.0f} mVpp (extrapolated)")
        else:
            self._threshold.set("50% trip point: not yet determined")
        axes.legend(loc="upper left", fontsize=8)

        # Panel 2: the same curve against the knob that was actually turned, for anyone
        # who wants to reproduce the run rather than the physics.
        axes = self._ax_gain
        self._probability_bars(axes, gain, p, lower, upper)
        axes.set_xlabel("Arb gain (dimensionless)")
        axes.set_title("Trip probability vs arb gain")

        # Panel 3: how close the rail gets to the detector as ripple grows. Shown as a
        # trend against gain rather than as trip probability against dip depth, because
        # the dip crosses the detector level well before trips begin -- the detector
        # needs the excursion to last, not just to touch. Plotting it the other way
        # would imply a threshold the data does not actually support.
        axes = self._ax_rail
        axes.plot(gain, rail_min, "v-", color="tab:red", linewidth=1.5, markersize=5,
                  label="Lowest rail voltage")
        axes.axhline(BROWNOUT_DETECTOR_V, color="tab:purple", linewidth=1.5,
                     label=f"Detector at {BROWNOUT_DETECTOR_V} V")
        axes.set_xlabel("Arb gain (dimensionless)")
        axes.set_ylabel("Rail voltage (V)")
        axes.set_title("How far the rail dips")
        axes.grid(True, alpha=0.3)
        axes.legend(loc="lower left", fontsize=8)

        # Panel 4: what a unit of gain buys at the rail. Near-linear here, which is the
        # evidence that the coupling network is not compressing at these levels -- and
        # the reason the amplitude panel is worth plotting separately at all.
        axes = self._ax_transfer
        axes.plot(gain, mvpp, "s-", color="tab:orange", linewidth=1.5, markersize=5)
        axes.set_xlabel("Arb gain (dimensionless)")
        axes.set_ylabel("Measured ripple (mVpp)")
        axes.set_title("Coupling network transfer")
        axes.grid(True, alpha=0.3)
        if len(gain) >= 2:
            slope_mvpp = float(np.polyfit(gain, mvpp, 1)[0])
            axes.annotate(f"{slope_mvpp:.0f} mVpp per unit gain",
                          (0.04, 0.9), xycoords="axes fraction",
                          fontsize=8, color="#555")

        completed = len(self._results)
        in_progress = len(self._partial_results)
        total_gains = completed + in_progress
        self._figure.suptitle(
            f"ESP32-C6 BLE-Induced Brownout Characterization  --  "
            f"{total_gains} gain step{'s' if total_gains != 1 else ''}, "
            f"{total.sum()} trial{'s' if total.sum() != 1 else ''}",
            fontsize=12, fontweight="bold")
        self._figure.tight_layout()
        self._canvas.draw_idle()

    def _save_csv(self) -> None:
        """Write trial-level data, matching the command-line demo's columns."""
        name = f"brownout_sweep_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with open(name, "w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "gain", "trial_index", "tripped", "timestamp",
                "ripple_vpp", "ripple_vrms", "ripple_dbv", "rail_min", "rail_max",
            ])
            writer.writeheader()
            for result in self._results:
                for trial in result.trials:
                    writer.writerow(asdict(trial))
        self._status.set(f"Saved {sum(len(r.trials) for r in self._results)} "
                         f"trials to {name}")


def main() -> None:
    root = tk.Tk()
    BrownoutGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
