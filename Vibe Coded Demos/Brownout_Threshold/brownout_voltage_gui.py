"""
Live GUI: find the ESP32-C6 brownout threshold with a Ch0 scope waterfall.

Sweeps the SMU rail downward at fixed arb gain. Each step shows an AC-coupled
Channel 0 capture — advertising-triggered ripple burst while healthy, or a quiet
same-window capture once advertising stops. Reports a single threshold voltage.

Usage:
    python brownout_voltage_gui.py
"""

from __future__ import annotations

import argparse
import queue
import re
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import List, Optional, Tuple

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from brownout_voltage_sweep import (
    BrownoutVoltageSweep,
    DiscoveredPxiInventory,
    ThresholdStepResult,
    discover_pxi_instrument_inventory,
)

_ASRL_PORT = re.compile(r"^ASRL(\d+)::INSTR$")
_COM_DEVICE = re.compile(r"^COM(\d+)$", re.I)
_SILABS_UART = re.compile(r"Silicon Labs|CP210", re.I)
_BUILTIN_COM = re.compile(r"Communications Port|Standard port types", re.I)

DEFAULT_VOLTAGE_START = 3.45
DEFAULT_VOLTAGE_STOP = 3.30
DEFAULT_VOLTAGE_STEP = -0.01
DEFAULT_FIXED_GAIN = 1.0


def list_com_ports() -> List[Tuple[str, str, str]]:
    """Serial ports as (COM label, VISA resource, description); Silicon Labs first."""
    by_label: dict = {}

    try:
        from serial.tools import list_ports

        for port in list_ports.comports():
            match = _COM_DEVICE.match(port.device or "")
            if not match:
                continue
            label = f"COM{match.group(1)}"
            description = port.description or port.manufacturer or label
            by_label[label] = (label, f"ASRL{match.group(1)}::INSTR", description)
    except Exception:
        pass

    try:
        import pyvisa

        rm = pyvisa.ResourceManager()
        try:
            for name in rm.list_resources():
                match = _ASRL_PORT.match(name)
                if not match:
                    continue
                label = f"COM{match.group(1)}"
                if label not in by_label:
                    by_label[label] = (label, name, label)
        finally:
            rm.close()
    except Exception:
        pass

    ports = list(by_label.values())

    def _sort_key(item: Tuple[str, str, str]):
        label, _resource, description = item
        number = int(label[3:])
        if _SILABS_UART.search(description):
            rank = 0
        elif _BUILTIN_COM.search(description):
            rank = 2
        else:
            rank = 1
        return (rank, number)

    return sorted(ports, key=_sort_key)


def preferred_com_label(ports: List[Tuple[str, str, str]]) -> str:
    if not ports:
        return "COM5"
    for label, _resource, description in ports:
        if _SILABS_UART.search(description):
            return label
    for label, _resource, description in ports:
        if not _BUILTIN_COM.search(description):
            return label
    return ports[0][0]


class ThresholdWindow(tk.Tk):
    """Waterfall of Ch0 captures while searching for the brownout threshold."""

    def __init__(
        self,
        voltage_start: float,
        voltage_stop: float,
        voltage_step: float,
        fixed_gain: float,
        inventory: DiscoveredPxiInventory,
        auto_start: bool = False,
        auto_close: bool = False,
    ):
        super().__init__()
        self.title("ESP32-C6 Brownout Threshold")
        self.protocol("WM_DELETE_WINDOW", self._on_exit)

        self.fixed_gain = fixed_gain
        self.inventory = inventory
        self.auto_close = auto_close
        self._sweep_failed = False

        self.voltage_start = voltage_start
        self.voltage_stop = voltage_stop
        self.voltage_step = voltage_step

        self.steps: List[ThresholdStepResult] = []
        self.queue: queue.Queue = queue.Queue()
        self.sweep_thread: Optional[threading.Thread] = None
        self.stop_requested = False
        self.com_ports = list_com_ports()
        self.com_label = preferred_com_label(self.com_ports)
        self.dut_visa_resource = (
            f"ASRL{''.join(ch for ch in self.com_label if ch.isdigit()) or '5'}::INSTR"
        )

        self._sweep: Optional[BrownoutVoltageSweep] = None
        self._session_key: Optional[Tuple[str, str, str, str, float]] = None
        self._pending_session_key: Optional[Tuple[str, str, str, str, float]] = None
        self._exiting = False
        self._threshold_text = "—"

        self._build_ui(voltage_start, voltage_stop, voltage_step)
        if auto_start:
            self.after(300, self._start_sweep)

    def _build_ui(self, voltage_start: float, voltage_stop: float, voltage_step: float):
        tk.Label(
            self,
            text=(
                f"Rail sweep at fixed 7 kHz ripple (gain {self.fixed_gain}). "
                "Ch0 shows the advertising burst — or a quiet window once it stops."
            ),
            font=("Segoe UI", 10),
            anchor="w",
        ).pack(side=tk.TOP, fill=tk.X, padx=10, pady=(8, 2))

        instrument_row = tk.Frame(self)
        instrument_row.pack(side=tk.TOP, fill=tk.X, padx=10, pady=2)

        tk.Label(instrument_row, text="SMU", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.smu_choice = ttk.Combobox(
            instrument_row,
            values=list(self.inventory.smu_resources),
            state="readonly",
            width=14,
            font=("Segoe UI", 10),
        )
        self.smu_choice.set(self.inventory.smu_resources[0])
        self.smu_choice.pack(side=tk.LEFT, padx=(4, 2))
        tk.Label(instrument_row, text="(Ch0)", font=("Segoe UI", 9), fg="#555555").pack(
            side=tk.LEFT, padx=(0, 12)
        )

        tk.Label(instrument_row, text="Scope", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.scope_choice = ttk.Combobox(
            instrument_row,
            values=list(self.inventory.scope_resources),
            state="readonly",
            width=14,
            font=("Segoe UI", 10),
        )
        self.scope_choice.set(self.inventory.scope_resources[0])
        self.scope_choice.pack(side=tk.LEFT, padx=(4, 2))
        tk.Label(
            instrument_row, text="(Ch0, Ch1)", font=("Segoe UI", 9), fg="#555555"
        ).pack(side=tk.LEFT, padx=(0, 12))

        tk.Label(instrument_row, text="Arb", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.fgen_choice = ttk.Combobox(
            instrument_row,
            values=list(self.inventory.fgen_resources),
            state="readonly",
            width=14,
            font=("Segoe UI", 10),
        )
        self.fgen_choice.set(self.inventory.fgen_resources[0])
        self.fgen_choice.pack(side=tk.LEFT, padx=(4, 2))
        tk.Label(instrument_row, text="(Ch0)", font=("Segoe UI", 9), fg="#555555").pack(
            side=tk.LEFT
        )

        control_row = tk.Frame(self)
        control_row.pack(side=tk.TOP, fill=tk.X, padx=10, pady=4)

        tk.Label(control_row, text="Start (V)", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.start_entry = tk.Entry(control_row, width=7, font=("Segoe UI", 10))
        self.start_entry.insert(0, f"{voltage_start:.2f}")
        self.start_entry.pack(side=tk.LEFT, padx=(4, 10))

        tk.Label(control_row, text="Stop (V)", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.stop_entry = tk.Entry(control_row, width=7, font=("Segoe UI", 10))
        self.stop_entry.insert(0, f"{voltage_stop:.2f}")
        self.stop_entry.pack(side=tk.LEFT, padx=(4, 10))

        tk.Label(control_row, text="Step (V)", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        self.step_entry = tk.Entry(control_row, width=7, font=("Segoe UI", 10))
        self.step_entry.insert(0, f"{voltage_step:g}")
        self.step_entry.pack(side=tk.LEFT, padx=(4, 14))

        tk.Label(control_row, text="DUT COM", font=("Segoe UI", 10)).pack(side=tk.LEFT)
        labels = [label for label, _resource, _description in self.com_ports]
        self.com_choice = ttk.Combobox(
            control_row, values=labels, state="readonly", width=8, font=("Segoe UI", 10)
        )
        default_com = preferred_com_label(self.com_ports)
        self.com_choice.set(
            default_com if default_com in labels else (labels[0] if labels else "COM5")
        )
        self.com_choice.pack(side=tk.LEFT, padx=6)
        tk.Label(
            control_row,
            text="(Silicon Labs CP210x)",
            font=("Segoe UI", 9),
            fg="#555555",
        ).pack(side=tk.LEFT, padx=(0, 8))

        self.run_button = tk.Button(
            control_row, text="Run", font=("Segoe UI", 10), command=self._start_sweep
        )
        self.run_button.pack(side=tk.LEFT, padx=(8, 0))

        threshold_frame = tk.Frame(self, bg="#1a1f2e")
        threshold_frame.pack(side=tk.TOP, fill=tk.X, padx=10, pady=8)
        tk.Label(
            threshold_frame,
            text="BROWNOUT THRESHOLD",
            font=("Segoe UI", 9),
            fg="#9aa3b5",
            bg="#1a1f2e",
        ).pack(side=tk.TOP, anchor="w", padx=14, pady=(10, 0))
        self.threshold_label = tk.Label(
            threshold_frame,
            text="—",
            font=("Segoe UI", 28, "bold"),
            fg="#e8eef8",
            bg="#1a1f2e",
        )
        self.threshold_label.pack(side=tk.TOP, anchor="w", padx=14, pady=(0, 4))
        self.detail_label = tk.Label(
            threshold_frame,
            text="Set the sweep, then Run. Sessions stay open until Exit.",
            font=("Segoe UI", 10),
            fg="#9aa3b5",
            bg="#1a1f2e",
            anchor="w",
            justify="left",
        )
        self.detail_label.pack(side=tk.TOP, fill=tk.X, padx=14, pady=(0, 12))

        btn_frame = tk.Frame(self)
        btn_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=8)
        self.exit_button = tk.Button(
            btn_frame, text="Exit", font=("Segoe UI", 10), command=self._on_exit
        )
        self.exit_button.pack(side=tk.RIGHT)

        self.fig = Figure(figsize=(11, 5.5), dpi=100, facecolor="#f7f5f1")
        self.ax_ok = self.fig.add_subplot(1, 2, 1)
        self.ax_trip = self.fig.add_subplot(1, 2, 2)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8)

        self._draw_empty()

    def _style_scope_axis(self, ax, title: str, border_color: str) -> None:
        ax.clear()
        ax.set_facecolor("#f7f5f1")
        ax.set_xlabel("Time from advertising edge (ms)", fontsize=10)
        ax.set_ylabel("Ch0 (V, AC coupled)", fontsize=10)
        ax.set_title(title, fontsize=11, color=border_color, fontweight="bold")
        ax.axvline(0.0, color="#888888", linewidth=1.0, linestyle="--", alpha=0.7)
        ax.grid(True, alpha=0.25)
        for spine in ax.spines.values():
            spine.set_color(border_color)
            spine.set_linewidth(2.0)

    def _plot_capture(self, ax, step: Optional[ThresholdStepResult], color: str) -> None:
        if step is None or len(step.time_s) == 0:
            ax.text(
                0.5,
                0.5,
                "Waiting…",
                transform=ax.transAxes,
                ha="center",
                va="center",
                fontsize=14,
                color="#888888",
            )
            return
        t_ms = np.asarray(step.time_s, dtype=float) * 1e3
        y = np.asarray(step.samples_v, dtype=float)
        ax.plot(t_ms, y, color=color, linewidth=1.2)
        ax.axhline(0.0, color="#cccccc", linewidth=0.8)
        note = f"{step.voltage:.3f} V"
        if step.advertising and step.ripple_vpp == step.ripple_vpp:
            note += f" · {step.ripple_vpp * 1e3:.0f} mVpp"
        elif not step.advertising:
            note += " · no GPIO10"
        ax.text(
            0.02,
            0.98,
            note,
            transform=ax.transAxes,
            ha="left",
            va="top",
            fontsize=10,
            color=color,
            fontweight="bold",
        )

    def _last_healthy_step(self) -> Optional[ThresholdStepResult]:
        for step in reversed(self.steps):
            if not step.brownout_warning:
                return step
        return None

    def _first_brownout_step(self) -> Optional[ThresholdStepResult]:
        for step in self.steps:
            if step.brownout_warning:
                return step
        return None

    def _draw_empty(self):
        self._style_scope_axis(
            self.ax_ok, "Last healthy — OK / advertising", "#1f7a4c"
        )
        self._style_scope_axis(
            self.ax_trip, "First brownout text on COM", "#b33b3b"
        )
        self._plot_capture(self.ax_ok, None, "#1f7a4c")
        self._plot_capture(self.ax_trip, None, "#b33b3b")
        self.fig.tight_layout(pad=2.0)
        self.canvas.draw()

    def _selected_visa_resource(self) -> str:
        label = self.com_choice.get()
        for port_label, resource, _description in self.com_ports:
            if port_label == label:
                return resource
        number = "".join(ch for ch in (label or "") if ch.isdigit())
        return f"ASRL{number or '5'}::INSTR"

    def _selected_smu_resource(self) -> str:
        return f"{self.smu_choice.get()}/0"

    def _current_session_key(self) -> Tuple[str, str, str, str, float]:
        return (
            self.scope_choice.get(),
            self.fgen_choice.get(),
            self._selected_smu_resource(),
            self._selected_visa_resource(),
            self.fixed_gain,
        )

    def _read_sweep_parameters(self) -> Tuple[float, float, float]:
        try:
            start = float(self.start_entry.get().strip())
            stop = float(self.stop_entry.get().strip())
            step = float(self.step_entry.get().strip())
        except ValueError as exc:
            raise ValueError("Start, Stop, and Step must be numbers.") from exc
        if step == 0:
            raise ValueError("Step must be non-zero.")
        if start <= 0 or stop <= 0:
            raise ValueError("Start and Stop must be positive voltages.")
        if start > stop and step > 0:
            step = -step
        elif start < stop and step < 0:
            step = -step
        return start, stop, step

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        combo_state = "readonly" if enabled else "disabled"
        self.start_entry.configure(state=state)
        self.stop_entry.configure(state=state)
        self.step_entry.configure(state=state)
        self.com_choice.configure(state=combo_state)
        self.smu_choice.configure(state=combo_state)
        self.scope_choice.configure(state=combo_state)
        self.fgen_choice.configure(state=combo_state)
        self.run_button.configure(state=state)

    def _ensure_instruments(
        self, key: Tuple[str, str, str, str, float]
    ) -> BrownoutVoltageSweep:
        if self._sweep is not None and self._session_key == key:
            return self._sweep

        self._close_instruments()
        scope, fgen, smu, dut, gain = key
        trigger = self.inventory.trigger_device
        sweep = BrownoutVoltageSweep(
            scope_resource=scope,
            fgen_resource=fgen,
            smu_resource=smu,
            scope_trigger_source=f"/{trigger}/TRIG_SMB",
            trigger_route_source=f"/{trigger}/TRIG_SMB",
            trigger_route_dest=f"/{trigger}/PXI_Trig0",
            fixed_arb_gain=gain,
            dut_visa_resource=dut,
        )
        sweep.setup()
        self._sweep = sweep
        self._session_key = key
        return sweep

    def _close_instruments(self) -> None:
        if self._sweep is not None:
            try:
                self._sweep.teardown()
            except Exception as exc:
                print(f"Warning: Error closing instruments: {exc}", flush=True)
            finally:
                self._sweep = None
                self._session_key = None

    def _start_sweep(self):
        if self._exiting:
            return
        if self.sweep_thread is not None and self.sweep_thread.is_alive():
            return

        try:
            self.voltage_start, self.voltage_stop, self.voltage_step = (
                self._read_sweep_parameters()
            )
        except ValueError as exc:
            messagebox.showerror("Invalid Sweep Parameters", str(exc))
            return

        self.com_label = self.com_choice.get() or preferred_com_label(self.com_ports)
        self.dut_visa_resource = self._selected_visa_resource()
        self._pending_session_key = self._current_session_key()
        self.steps = []
        self.stop_requested = False
        self._sweep_failed = False
        self._threshold_text = "Searching…"
        self.threshold_label.config(text="Searching…", fg="#e8eef8")
        self.detail_label.config(
            text=(
                f"Sweeping {self.voltage_start:.2f} V → {self.voltage_stop:.2f} V "
                f"by {self.voltage_step:g} V on {self.com_label}…"
            )
        )
        self._set_controls_enabled(False)
        self._draw_empty()
        self.sweep_thread = threading.Thread(target=self._run_sweep, daemon=True)
        self.sweep_thread.start()
        self.after(100, self._poll_queue)

    def _run_sweep(self):
        try:
            key = self._pending_session_key
            if key is None:
                raise RuntimeError("Sweep started without a session key")
            sweep = self._ensure_instruments(key)
            for step in sweep.run_threshold_search(
                voltage_start=self.voltage_start,
                voltage_stop=self.voltage_stop,
                voltage_step=self.voltage_step,
            ):
                if self.stop_requested:
                    break
                self.queue.put(("data", step))
            self.queue.put(("done", None))
        except Exception as e:
            self.queue.put(("error", str(e)))

    def _poll_queue(self):
        if self._exiting:
            return

        while not self.queue.empty():
            msg_type, payload = self.queue.get_nowait()

            if msg_type == "data":
                self.steps.append(payload)
                self._update_compare_plots()
                latest = payload
                if latest.brownout_warning:
                    state = "brownout text on COM"
                elif latest.advertising:
                    state = "advertising + burst (no brownout text)"
                else:
                    state = "no advertising, no brownout text"
                self.detail_label.config(
                    text=f"Latest {latest.voltage:.3f} V — {state}"
                )

            elif msg_type == "done":
                self._finalize()
                return

            elif msg_type == "error":
                self._sweep_failed = True
                print(f"SWEEP_FAILED: {payload}", flush=True)
                self._set_controls_enabled(True)
                self.threshold_label.config(text="Failed", fg="#f0a0a0")
                self.detail_label.config(text=str(payload))
                if not self.auto_close:
                    messagebox.showerror("Sweep Error", f"Sweep failed:\n{payload}")
                if self.auto_close:
                    self.after(500, self._on_exit)
                return

        if not self.stop_requested:
            self.after(100, self._poll_queue)

    def _update_compare_plots(self):
        ok = self._last_healthy_step()
        trip = self._first_brownout_step()

        self._style_scope_axis(
            self.ax_ok,
            (
                f"Last healthy — {ok.voltage:.3f} V · OK / advertising"
                if ok is not None
                else "Last healthy — OK / advertising"
            ),
            "#1f7a4c",
        )
        self._style_scope_axis(
            self.ax_trip,
            (
                f"First brownout text — {trip.voltage:.3f} V"
                if trip is not None
                else "First brownout text on COM"
            ),
            "#b33b3b",
        )
        self._plot_capture(self.ax_ok, ok, "#1f7a4c")
        self._plot_capture(self.ax_trip, trip, "#b33b3b")

        # Match vertical scales so the burst vs quiet difference is obvious.
        ys = []
        for step in (ok, trip):
            if step is not None and len(step.samples_v):
                ys.append(np.asarray(step.samples_v, dtype=float))
        if ys:
            stacked = np.concatenate(ys)
            pad = max(0.05, 0.1 * float(np.max(np.abs(stacked))))
            lo, hi = float(np.min(stacked)) - pad, float(np.max(stacked)) + pad
            self.ax_ok.set_ylim(lo, hi)
            self.ax_trip.set_ylim(lo, hi)

        self.fig.tight_layout(pad=2.0)
        self.canvas.draw()

    def _finalize(self):
        if self._exiting:
            return
        self._update_compare_plots()
        self._set_controls_enabled(True)

        thr = self._sweep.threshold_voltage if self._sweep else None
        last_ok = self._sweep.last_healthy_voltage if self._sweep else None
        reason = (self._sweep.stop_reason if self._sweep else "") or ""

        if thr is not None:
            self.threshold_label.config(text=f"{thr:.3f} V", fg="#7dffa3")
            detail = f"First brownout text at {thr:.3f} V"
            if last_ok is not None:
                detail += f" · last healthy {last_ok:.3f} V"
            detail += " · SMU held at threshold (IS will match)"
            detail += "  |  Run again, or Exit to close instruments."
            self.detail_label.config(text=detail)
            print(
                f"THRESHOLD: {thr:.3f} V"
                + (f" (last healthy {last_ok:.3f} V)" if last_ok is not None else ""),
                flush=True,
            )
        else:
            self.threshold_label.config(text="Not found", fg="#f0d78c")
            self.detail_label.config(
                text=(reason or "No brownout in range.")
                + "  |  Run again, or Exit to close instruments."
            )
            print(f"THRESHOLD: not found ({reason})", flush=True)

        if self.auto_close:
            self.after(1500, self._on_exit)

    def _on_exit(self):
        if self._exiting:
            return
        self._exiting = True
        self.stop_requested = True
        self.run_button.configure(state="disabled")
        self.exit_button.configure(state="disabled")
        self.detail_label.config(text="Closing instrument sessions…")

        def _finish_exit():
            if self.sweep_thread is not None and self.sweep_thread.is_alive():
                self.sweep_thread.join(timeout=12.0)
            self._close_instruments()
            self.destroy()

        self.after(50, _finish_exit)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="ESP32-C6 brownout threshold search GUI."
    )
    parser.add_argument(
        "--start", type=float, default=DEFAULT_VOLTAGE_START,
        help="Start voltage in volts (default: %(default)s)",
    )
    parser.add_argument(
        "--stop", type=float, default=DEFAULT_VOLTAGE_STOP,
        help="Stop voltage in volts (default: %(default)s)",
    )
    parser.add_argument(
        "--step", type=float, default=DEFAULT_VOLTAGE_STEP,
        help="Step size in volts (default: %(default)s)",
    )
    parser.add_argument(
        "--gain", type=float, default=DEFAULT_FIXED_GAIN,
        help="Fixed arb gain (default: %(default)s)",
    )
    parser.add_argument(
        "--auto-start",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Start automatically after the window opens (default: off).",
    )
    parser.add_argument(
        "--auto-close",
        action="store_true",
        help="Close the window shortly after the search finishes.",
    )
    args = parser.parse_args(argv)

    try:
        inventory = discover_pxi_instrument_inventory()
    except Exception as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Instrument Discovery Failed",
            f"Could not find the PXIe scope, arb, and SMU:\n{exc}",
        )
        root.destroy()
        print(f"SWEEP_FAILED: instrument discovery: {exc}", flush=True)
        return 1

    app = ThresholdWindow(
        voltage_start=args.start,
        voltage_stop=args.stop,
        voltage_step=args.step,
        fixed_gain=args.gain,
        inventory=inventory,
        auto_start=args.auto_start,
        auto_close=args.auto_close,
    )
    app.mainloop()
    return 1 if getattr(app, "_sweep_failed", False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
