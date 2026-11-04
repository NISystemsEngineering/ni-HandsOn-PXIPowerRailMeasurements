"""
ESP32-C6 Brownout Voltage Sweep

Sweeps the rail voltage downward at a fixed ripple amplitude (arb gain) to find the
brownout threshold. Much faster than gain sweeps because:
  - Voltage directly controls when brownout occurs (no ripple phase variation)
  - Brownouts happen immediately when voltage is too low
  - Narrow voltage range (3.4V → 3.27V) with fine steps

Typical timing: ~20-30 seconds for full curve (15-20 voltage steps × 3 trials each).

Physical Setup: Same as brownout_sweep.py
Dependencies: Same as brownout_sweep.py
"""

from __future__ import annotations

import csv
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import niscope
import nifgen
import nidcpower
import nidaqmx
import nisyscfg
import nisyscfg.errors
import pyvisa

# Brownout marker emitted by ESP32-C6 ISR, ahead of ROM boot banner
BROWNOUT_MARKER = "Brownout detector was triggered"

# Ripple CSV ships in-repo under PXI_Training/waveform/. Resolve from this
# file so the path works wherever the hands-on tree is cloned.
_RIPPLE_CSV_NAME = "7kHz_ripple_10.5MHz_3p571ms.csv"


def default_ripple_csv_path() -> str:
    here = Path(__file__).resolve().parent
    for root in (here, *here.parents):
        candidate = root / "PXI_Training" / "waveform" / _RIPPLE_CSV_NAME
        if candidate.is_file():
            return str(candidate)
    # Expected layout when the tree is incomplete (clear FileNotFoundError).
    return str(here.parents[2] / "PXI_Training" / "waveform" / _RIPPLE_CSV_NAME)

# Preflight / recovery rail: below the 3.6 V absolute max, clearly above the
# detector and the demo sweep window so advertising is unambiguous.
HEALTHY_RAIL_VOLTAGE = 3.58

# Classify present PXI modules by product-name family. Controllers/chassis are
# excluded so the exercise can assume one scope, one arb, and one SMU.
_SCOPE_PRODUCT = re.compile(r"PXI[eE]?-51\d{2}|OSCILLOSCOPE|DIGITIZER", re.I)
_FGEN_PRODUCT = re.compile(
    r"PXI[eE]?-54\d{2}|WAVEFORM GENERATOR|ARBITRARY", re.I
)
_SMU_PRODUCT = re.compile(
    r"PXI[eE]?-41[3-6]\d|SOURCE MEASURE|\bSMU\b", re.I
)
_CONTROLLER_PRODUCT = re.compile(r"PXI[eE]?-88\d{2}|EMBEDDED CONTROLLER", re.I)
_CHASSIS_PRODUCT = re.compile(r"PXI[eE]?-10\d{2}", re.I)


@dataclass(frozen=True)
class DiscoveredPxiInventory:
    """All present PXIe scopes / arbs / SMUs, plus the trigger routing device."""

    scope_resources: Tuple[str, ...]
    fgen_resources: Tuple[str, ...]
    smu_resources: Tuple[str, ...]  # base MAX names; open as "<name>/0"
    trigger_device: str  # chassis/controller name for TRIG_SMB / PXI_Trig routes


@dataclass(frozen=True)
class DiscoveredPxiInstruments:
    """Resource names for the selected scope / arb / SMU on this station."""

    scope_resource: str
    fgen_resource: str
    smu_resource: str  # always channel 0, e.g. "4147_SMU/0"
    trigger_device: str  # chassis/controller name for TRIG_SMB / PXI_Trig routes


def _safe_syscfg_scalar(resource, property_name: str, default: str = "") -> str:
    try:
        if hasattr(resource, "get_property"):
            return str(resource.get_property(property_name, default) or default)
        return str(getattr(resource, property_name, default) or default)
    except (AttributeError, nisyscfg.errors.LibraryError):
        return default


def discover_pxi_instrument_inventory() -> DiscoveredPxiInventory:
    """
    Find every present PXIe scope, waveform generator, and SMU via nisyscfg.

    Uses each device's MAX name (nisyscfg ``name``), which is what the NI-SCOPE /
    NI-FGEN / NI-DCPower sessions accept. Multi-channel SMUs always use channel 0.
    """
    scopes: List[str] = []
    fgens: List[str] = []
    smus: List[str] = []
    controllers: List[str] = []
    chassis: List[str] = []

    with nisyscfg.Session(target="localhost") as session:
        filt = session.create_filter()
        filt.is_present = True
        filt.is_ni_product = True
        filt.is_device = True
        for resource in session.find_hardware(filt):
            product = _safe_syscfg_scalar(resource, "product_name")
            if "PXI" not in product.upper():
                continue
            name = _safe_syscfg_scalar(resource, "name")
            if not name:
                continue
            if _CONTROLLER_PRODUCT.search(product):
                controllers.append(name)
            elif _CHASSIS_PRODUCT.search(product):
                chassis.append(name)
            elif _SCOPE_PRODUCT.search(product):
                scopes.append(name)
            elif _FGEN_PRODUCT.search(product):
                fgens.append(name)
            elif _SMU_PRODUCT.search(product):
                smus.append(name)

    def _require_at_least_one(role: str, found: List[str]) -> Tuple[str, ...]:
        if not found:
            raise RuntimeError(f"No PXIe {role} found in the system")
        return tuple(found)

    if controllers:
        trigger_device = controllers[0]
    elif chassis:
        trigger_device = chassis[0]
    else:
        raise RuntimeError(
            "No PXI controller or chassis found for TRIG_SMB / PXI_Trig routing"
        )

    return DiscoveredPxiInventory(
        scope_resources=_require_at_least_one("oscilloscope", scopes),
        fgen_resources=_require_at_least_one("waveform generator", fgens),
        smu_resources=_require_at_least_one("SMU", smus),
        trigger_device=trigger_device,
    )


def discover_pxi_instruments() -> DiscoveredPxiInstruments:
    """
    Pick the first present PXIe scope, waveform generator, and SMU.

    Multi-channel SMUs always use channel 0. Prefer
    ``discover_pxi_instrument_inventory`` when the caller needs a choice list.
    """
    inventory = discover_pxi_instrument_inventory()
    return DiscoveredPxiInstruments(
        scope_resource=inventory.scope_resources[0],
        fgen_resource=inventory.fgen_resources[0],
        smu_resource=f"{inventory.smu_resources[0]}/0",
        trigger_device=inventory.trigger_device,
    )


@dataclass
class VoltageTrialResult:
    """Single trial result at one SMU voltage."""
    voltage: float              # SMU voltage for this trial (V)
    trial_index: int           # Trial number at this voltage (0-indexed)
    tripped: bool              # True if brownout detected via COM port
    timestamp: datetime        # When trial completed
    ripple_vpp: float          # Measured 7 kHz ripple (Vpp)
    ripple_vrms: float         # Measured ripple (Vrms)
    ripple_dbv: float          # Measured ripple (dBV, ref 1 Vrms)


@dataclass
class VoltageResult:
    """Aggregated results for one SMU voltage."""
    voltage: float
    total_trials: int
    tripped_count: int
    trip_fraction: float
    mean_ripple_vpp: float
    mean_ripple_vrms: float
    mean_ripple_dbv: float
    trials: List[VoltageTrialResult]


@dataclass
class ThresholdStepResult:
    """One rail voltage in a threshold search, with a Ch0 scope capture."""

    voltage: float
    advertising: bool  # True if GPIO10 triggered within the timeout
    brownout_warning: bool
    time_s: np.ndarray  # seconds relative to trigger (0 = edge / expected edge)
    samples_v: np.ndarray  # AC-coupled Ch0, volts
    ripple_vpp: float  # nan when there was no advertising burst


def measure_ripple_amplitude(
    samples: np.ndarray, sample_rate: float, frequency: float
) -> Tuple[float, float, float]:
    """
    Measure ripple amplitude by projection (lock-in / Goertzel) onto sin/cos at the
    exact frequency over whole cycles. Preferred over FFT peak-bin because no
    achievable scope rate puts 7 kHz exactly on a bin.

    Returns: (vpp, vrms, dbv) where dbv is referenced to 1 Vrms.
    """
    cycles = int(len(samples) * frequency / sample_rate)
    if cycles < 1:
        raise ValueError(
            f"record too short to measure {frequency} Hz: {len(samples)} samples "
            f"at {sample_rate} S/s spans less than one cycle"
        )
    n = int(round(cycles * sample_rate / frequency))
    x = np.asarray(samples[:n], dtype=float)
    x = x - x.mean()   # remove DC rail, leaving only ripple
    t = np.arange(n) / sample_rate
    a = 2.0 / n * np.dot(x, np.cos(2.0 * np.pi * frequency * t))
    b = 2.0 / n * np.dot(x, np.sin(2.0 * np.pi * frequency * t))

    v_peak = float(np.hypot(a, b))
    v_rms = v_peak / np.sqrt(2.0)
    dbv = 20.0 * np.log10(v_rms) if v_rms > 0.0 else float("-inf")
    return 2.0 * v_peak, v_rms, dbv


class BrownoutVoltageSweep:
    """
    Voltage sweep at fixed arb gain to find brownout threshold.

    Differs from BrownoutSweep (gain sweep) by sweeping the SMU voltage instead of
    the arb gain. Much faster because brownouts occur immediately when voltage is
    too low, rather than waiting for ripple phase alignment.
    """

    def __init__(
        self,
        scope_resource: Optional[str] = None,
        fgen_resource: Optional[str] = None,
        smu_resource: Optional[str] = None,
        dut_visa_resource: str = "ASRL5::INSTR",
        dut_serial_timeout_ms: float = 1500,  # Faster than gain sweep (brownouts immediate)
        fixed_arb_gain: float = 1.0,          # Fixed ripple amplitude for the sweep
        supply_current_limit: float = 0.5,
        ripple_csv_path: Optional[str] = None,
        arb_sample_rate: float = 10.5e6,
        ripple_frequency: float = 7000.0,
        scope_sample_rate: float = 2.0e6,
        scope_voltage_channel: str = "0",
        scope_current_channel: str = "1",
        # DUT GPIO10 lands on the chassis front-panel SMB. The scope triggers on
        # that terminal directly and exports its reference trigger onto PXI_Trig0
        # for the arb. No DAQmx route and no LabVIEW VI. None = discover.
        scope_trigger_source: Optional[str] = None,
        arb_trigger_source: str = "PXI_Trig0",
        scope_ref_trigger_terminal: str = "PXI_Trig0",
        # Stale route from earlier scripts. Cleared on setup so it cannot fight
        # the scope's PXI_Trig0 export. None = discover.
        trigger_route_source: Optional[str] = None,
        trigger_route_dest: Optional[str] = None,
    ):
        needs_discovery = any(
            value is None
            for value in (
                scope_resource,
                fgen_resource,
                smu_resource,
                scope_trigger_source,
                trigger_route_source,
                trigger_route_dest,
            )
        )
        discovered = discover_pxi_instruments() if needs_discovery else None

        self.scope_resource = scope_resource or discovered.scope_resource
        self.fgen_resource = fgen_resource or discovered.fgen_resource
        self.smu_resource = smu_resource or discovered.smu_resource
        self.dut_visa_resource = dut_visa_resource
        self.dut_serial_timeout_ms = dut_serial_timeout_ms
        self.fixed_arb_gain = fixed_arb_gain
        self.supply_current_limit = supply_current_limit
        self.ripple_csv_path = ripple_csv_path or default_ripple_csv_path()
        self.arb_sample_rate = arb_sample_rate
        self.ripple_frequency = ripple_frequency
        self.scope_sample_rate = scope_sample_rate
        self.scope_voltage_channel = scope_voltage_channel
        self.scope_current_channel = scope_current_channel
        trigger_device = discovered.trigger_device if discovered is not None else ""
        self.scope_trigger_source = scope_trigger_source or (
            f"/{trigger_device}/TRIG_SMB"
        )
        self.arb_trigger_source = arb_trigger_source
        self.scope_ref_trigger_terminal = scope_ref_trigger_terminal
        self.trigger_route_source = trigger_route_source or (
            f"/{trigger_device}/TRIG_SMB"
        )
        self.trigger_route_dest = trigger_route_dest or (
            f"/{trigger_device}/PXI_Trig0"
        )

        # Instrument session handles (None until setup)
        self._scope: Optional[niscope.Session] = None
        self._fgen: Optional[nifgen.Session] = None
        self._smu: Optional[nidcpower.Session] = None
        self._dut_serial = None
        self._visa_rm = None
        # True after the first nidcpower initiate(); later runs only change voltage_level.
        self._smu_sourcing: bool = False

        # Computed during setup
        self._burst_duration_s: float = 0.0
        self._actual_scope_rate: float = 0.0
        self._record_length: int = 0

        # Set by threshold / voltage sweeps for the GUI / CLI to display
        self.stop_reason: str = ""
        self.threshold_voltage: Optional[float] = None
        self.last_healthy_voltage: Optional[float] = None
        self._status_callback = None

    def __enter__(self):
        self.setup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.teardown()

    def setup(self) -> None:
        """Open instruments and configure for voltage sweep at fixed gain."""
        try:
            self._visa_rm = pyvisa.ResourceManager()
            self._dut_serial = self._visa_rm.open_resource(
                self.dut_visa_resource,
                baud_rate=115200,
                read_termination='\n',
                write_termination='\n',
                timeout=self.dut_serial_timeout_ms,
            )
            # RTS is the DevKit reset line. Leave both lines released so opening
            # the port does not hold the chip in reset or download mode.
            self._dut_serial.set_visa_attribute(
                pyvisa.constants.VI_ATTR_ASRL_FLOW_CNTRL,
                pyvisa.constants.VI_ASRL_FLOW_NONE,
            )
            self._set_dtr_rts(False, False)

            # Load ripple waveform
            ripple = np.loadtxt(self.ripple_csv_path)
            self._burst_duration_s = len(ripple) / self.arb_sample_rate

            # SMU: will be updated per voltage step
            self._smu = nidcpower.Session(resource_name=self.smu_resource)
            self._smu.source_mode = nidcpower.SourceMode.SINGLE_POINT
            self._smu.output_function = nidcpower.OutputFunction.DC_VOLTAGE
            self._smu.sense = nidcpower.Sense.REMOTE
            self._smu.voltage_level_range = 6.0
            self._smu.current_limit = self.supply_current_limit
            self._smu.current_limit_range = self.supply_current_limit
            # Match InstrumentStudio SourceAdapt after Fast preset + Voltage GBW
            # set to 100 kHz. CUSTOM is required for these attributes to apply.
            self._smu.transient_response = nidcpower.TransientResponse.CUSTOM
            self._smu.current_gain_bandwidth = 200e3
            self._smu.current_compensation_frequency = 40.0129e3
            self._smu.current_pole_zero_ratio = 0.59996
            self._smu.voltage_gain_bandwidth = 100e3
            self._smu.voltage_compensation_frequency = 200.023e3
            self._smu.voltage_pole_zero_ratio = 0.29996
            
            # Scope: Ch0 only, AC coupled for ripple measurement (Ch1 not needed)
            self._scope = niscope.Session(resource_name=self.scope_resource)
            ch0 = self.scope_voltage_channel
            
            # AC coupling removes DC component, 1V range for ~100-150 mVpp ripple with headroom
            self._scope.channels[ch0].configure_vertical(
                range=1.0, coupling=niscope.VerticalCoupling.AC)
            
            record_time = self._burst_duration_s * 1.25
            self._scope.configure_horizontal_timing(
                min_sample_rate=self.scope_sample_rate,
                min_num_pts=int(record_time * self.scope_sample_rate),
                ref_position=5.0,
                num_records=1,
                enforce_realtime=True,
            )
            self._actual_scope_rate = self._scope.horz_sample_rate
            self._record_length = self._scope.horz_record_length
            self._scope.channels[ch0].configure_chan_characteristics(
                input_impedance=1e6, max_input_frequency=0)

            # Drop any leftover SMB -> PXI_Trig0 route. The scope drives that
            # backplane line itself; a second driver would contend with it.
            self._clear_stale_trigger_route()

            # Rising edge from the DUT, no extra delay. A multi-millisecond delay
            # would slide this record past the 3.571 ms ripple burst.
            self._arm_advertising_trigger()

            print(f"  Scope trigger: {self._scope.trigger_type} on {self._scope.trigger_source}")
            delay_s = self._scope.trigger_delay_time.total_seconds()
            print(f"  Scope trigger delay: {delay_s * 1e3:.3f} ms")
            print(f"  Scope ref-trigger export: {self._scope.exported_ref_trigger_output_terminal}")

            # Arb: fixed gain for entire sweep
            self._fgen = nifgen.Session(resource_name=self.fgen_resource)
            self._fgen.output_mode = nifgen.OutputMode.ARB
            handle = self._fgen.create_waveform(waveform_data_array=ripple)
            self._fgen.arb_sample_rate = self.arb_sample_rate
            self._fgen.configure_arb_waveform(
                waveform_handle=handle, gain=self.fixed_arb_gain, offset=0.0
            )
            self._fgen.output_impedance = 50.0
            self._fgen.trigger_mode = nifgen.TriggerMode.BURST
            self._fgen.start_trigger_type = nifgen.StartTriggerType.DIGITAL_EDGE
            self._fgen.digital_edge_start_trigger_source = self.arb_trigger_source
            self._fgen.digital_edge_start_trigger_edge = \
                nifgen.StartTriggerDigitalEdgeEdge.RISING
            self._fgen.output_enabled = True
            self._fgen.initiate()  # Arb stays armed for entire sweep
            
            # Verify arb configuration
            print(f"  Arb mode: {self._fgen.output_mode}, trigger: {self._fgen.trigger_mode}")
            print(f"  Arb sample rate: {self._fgen.arb_sample_rate / 1e6:.1f} MHz")
            print(f"  Arb trigger source: {self._fgen.digital_edge_start_trigger_source}")

        except Exception as e:
            self.teardown()
            raise RuntimeError(f"Failed to setup instruments: {e}")

    def _arm_advertising_trigger(self) -> None:
        """Digital edge on DUT GPIO10; export ref trigger to the arb."""
        if self._scope is None:
            return
        self._scope.configure_trigger_digital(
            trigger_source=self.scope_trigger_source,
            slope=niscope.TriggerSlope.POSITIVE,
            holdoff=0.0,
            delay=0.0,
        )
        self._scope.trigger_modifier = niscope.TriggerModifier.NO_TRIGGER_MOD
        self._scope.exported_ref_trigger_output_terminal = self.scope_ref_trigger_terminal

    @staticmethod
    def _downsample_trace(
        time_s: np.ndarray, samples_v: np.ndarray, max_points: int = 800
    ) -> Tuple[np.ndarray, np.ndarray]:
        if len(samples_v) <= max_points:
            return time_s, samples_v
        idx = np.linspace(0, len(samples_v) - 1, max_points).astype(int)
        return time_s[idx], samples_v[idx]

    def _arrays_from_waveform(self, waveform) -> Tuple[np.ndarray, np.ndarray]:
        """Build (time_s, samples_v) with t=0 at the reference trigger."""
        w = waveform[0]
        samples = np.asarray(w.samples, dtype=float)
        dt = float(getattr(w, "dt", 0.0) or (1.0 / self._actual_scope_rate))
        t0 = float(w.relative_initial_x)
        time_s = t0 + np.arange(len(samples), dtype=float) * dt
        return time_s, samples

    def _capture_ch0(
        self, scope_timeout_s: float
    ) -> Tuple[bool, np.ndarray, np.ndarray, str]:
        """
        Capture AC-coupled Ch0 around an advertising edge when possible.

        Waits for the digital GPIO10 trigger. On timeout, takes an immediate
        (untriggered) record of the same length so the GUI can show a quiet
        "no advertising burst" trace in the same time window.
        """
        if self._scope is None:
            raise RuntimeError("Scope session is not open")

        ch0 = self.scope_voltage_channel
        serial_text = ""
        self._flush_serial()
        self._arm_advertising_trigger()

        with self._scope.initiate():
            start = time.time()
            status = self._scope.acquisition_status()
            while status != niscope.AcquisitionStatus.COMPLETE:
                serial_text += self._read_available()
                if time.time() - start > scope_timeout_s:
                    break
                time.sleep(0.005)
                status = self._scope.acquisition_status()

            triggered = status == niscope.AcquisitionStatus.COMPLETE
            if triggered:
                waveform = self._scope.channels[ch0].fetch(
                    num_samples=self._record_length, timeout=5.0
                )
                time_s, samples = self._arrays_from_waveform(waveform)
                return True, time_s, samples, serial_text

        # No advertising edge: same record length, free-run, then restore trigger.
        serial_text += self._read_available()
        try:
            self._scope.configure_trigger_immediate()
            with self._scope.initiate():
                start = time.time()
                status = self._scope.acquisition_status()
                while status != niscope.AcquisitionStatus.COMPLETE:
                    if time.time() - start > 2.0:
                        break
                    time.sleep(0.005)
                    status = self._scope.acquisition_status()
                waveform = self._scope.channels[ch0].fetch(
                    num_samples=self._record_length, timeout=5.0
                )
            time_s, samples = self._arrays_from_waveform(waveform)
            # Immediate trigger refs the start of the record. Shift so t=0 is at
            # 5% (same ref_position as advertising-triggered captures).
            if len(time_s) > 1:
                duration = float(time_s[-1] - time_s[0])
                time_s = time_s - time_s[0] - 0.05 * duration
        finally:
            self._arm_advertising_trigger()

        return False, time_s, samples, serial_text

    def _build_voltage_list(
        self, voltage_start: float, voltage_stop: float, voltage_step: float
    ) -> List[float]:
        if voltage_step == 0:
            raise ValueError("voltage_step must be non-zero")
        if voltage_start <= 0:
            raise ValueError(f"voltage_start must be positive, got {voltage_start}")
        voltages: List[float] = []
        v = voltage_start
        if voltage_step > 0:
            while v <= voltage_stop + abs(voltage_step) / 2:
                voltages.append(round(v, 4))
                v += voltage_step
        else:
            while v >= voltage_stop - abs(voltage_step) / 2:
                voltages.append(round(v, 4))
                v += voltage_step
        return voltages

    def run_threshold_search(
        self,
        voltage_start: float,
        voltage_stop: float,
        voltage_step: float,
        scope_timeout_s: float = 5.0,
        extra_quiet_steps: int = 1,
    ):
        """
        Sweep the rail downward until the brownout UART marker appears.

        Threshold is the first step where serial contains
        ``Brownout detector was triggered`` — not merely a GPIO10 timeout.
        Ch0 is still captured each step (triggered burst while advertising, or a
        quiet immediate window if not) for the waterfall display.

        Sets ``threshold_voltage`` and ``last_healthy_voltage``.
        Yields ``ThresholdStepResult`` as each step finishes.
        """
        if self._smu is None or self._scope is None:
            raise RuntimeError("run_threshold_search() called before setup()")

        voltages = self._build_voltage_list(voltage_start, voltage_stop, voltage_step)
        self.stop_reason = ""
        self.threshold_voltage = None
        self.last_healthy_voltage = None
        healthy_voltage = HEALTHY_RAIL_VOLTAGE
        quiet_after_threshold = 0

        if not self._health_check_advertising(
            healthy_voltage, scope_timeout_s=scope_timeout_s
        ):
            self.stop_reason = (
                f"Health check failed: DUT is not advertising at "
                f"{healthy_voltage:.2f} V (scope timed out waiting for GPIO10). "
                "Press the DevKit reset, check firmware / TRIG_SMB, then Run again."
            )
            print(f"  Sweep stopped: {self.stop_reason}")
            return

        def _threshold_message() -> str:
            if self.threshold_voltage is None:
                return f"No brownout text found down to {voltages[-1]:.3f} V."
            msg = f"Brownout threshold at {self.threshold_voltage:.3f} V"
            if self.last_healthy_voltage is not None:
                msg += f" (last healthy {self.last_healthy_voltage:.3f} V)"
            return msg

        for voltage in voltages:
            self._source_rail(voltage)
            # Fast SourceAdapt can undershoot on a step and print a one-shot
            # brownout marker while the settled rail is still fine. Wait, then
            # discard that transient text before the real observation window.
            time.sleep(0.75)
            self._flush_serial()

            advertising, time_s, samples, serial_text = self._capture_ch0(scope_timeout_s)
            serial_text += self._read_available()
            # Criterion: UART brownout marker during this step's window only
            # (not GPIO10 loss alone, not settle-transient text from the step).
            brownout = BROWNOUT_MARKER in serial_text or self._check_for_brownout()

            ripple_vpp = float("nan")
            if advertising and len(samples):
                trigger_idx = int(np.argmin(np.abs(time_s))) if len(time_s) else 0
                burst_samples = int(self._burst_duration_s * self._actual_scope_rate)
                burst = samples[trigger_idx : trigger_idx + burst_samples]
                if len(burst) >= 8:
                    try:
                        ripple_vpp, _, _ = measure_ripple_amplitude(
                            burst, self._actual_scope_rate, self.ripple_frequency
                        )
                    except ValueError:
                        ripple_vpp = float("nan")

            time_s, samples = self._downsample_trace(time_s, samples)
            step = ThresholdStepResult(
                voltage=voltage,
                advertising=advertising,
                brownout_warning=brownout,
                time_s=time_s,
                samples_v=samples,
                ripple_vpp=ripple_vpp,
            )

            tag = "advertising" if advertising else "no GPIO10"
            warn = "brownout" if brownout else "ok"
            ripple_txt = (
                f"{ripple_vpp * 1e3:.1f} mVpp"
                if advertising and ripple_vpp == ripple_vpp
                else "—"
            )
            print(
                f"  voltage {voltage:>5.3f} V  {tag:<12}  {warn:<9}  ripple {ripple_txt}"
            )
            yield step

            if not brownout:
                self.last_healthy_voltage = voltage
                if not advertising:
                    # Advertising died without UART proof of brownout — stop cleanly.
                    self.stop_reason = (
                        f"Advertising stopped at {voltage:.3f} V without brownout text."
                    )
                    print(f"  {self.stop_reason}")
                    break
                continue

            if self.threshold_voltage is None:
                self.threshold_voltage = voltage

            # Optional extra quiet row(s) under the threshold for the waterfall.
            if not advertising:
                quiet_after_threshold += 1
                if quiet_after_threshold > extra_quiet_steps:
                    self.stop_reason = _threshold_message()
                    print(f"  {self.stop_reason}")
                    break
            else:
                self.stop_reason = _threshold_message()
                print(f"  {self.stop_reason}")
                break
        else:
            self.stop_reason = _threshold_message()
            print(f"  {self.stop_reason}")

        # Leave the SMU at the threshold. Restoring to 3.58 V made InstrumentStudio
        # show a healthy advertising DUT and looked like the reported answer.
        # The next Run's health check brings the rail back to HEALTHY_RAIL_VOLTAGE.
        if self.threshold_voltage is not None:
            print(
                f"  Holding SMU at threshold {self.threshold_voltage:.3f} V "
                "(not restoring to health-check level)."
            )
            self._source_rail(self.threshold_voltage)

    def run_voltage_sweep(
        self,
        voltage_start: float,
        voltage_stop: float,
        voltage_step: float,
        trials_per_voltage: int,
        scope_timeout_s: float = 5.0,
    ) -> List[VoltageResult]:
        """
        Sweep rail voltage at fixed arb gain.

        Args:
            voltage_start: Starting rail voltage (V)
            voltage_stop: Ending rail voltage (V)
            voltage_step: Voltage increment (V), can be negative for downward sweep
            trials_per_voltage: Number of trials per voltage
            scope_timeout_s: Scope trigger timeout (seconds)

        Yields:
            VoltageResult for each voltage, as soon as its trials finish.
        """
        if self._smu is None or self._scope is None:
            raise RuntimeError("run_voltage_sweep() called before setup()")

        voltages = self._build_voltage_list(voltage_start, voltage_stop, voltage_step)

        results: List[VoltageResult] = []
        self.stop_reason = ""
        ch0 = self.scope_voltage_channel  # Ch0 only - ripple measurement
        burst_samples = int(self._burst_duration_s * self._actual_scope_rate)
        healthy_voltage = HEALTHY_RAIL_VOLTAGE

        if not self._health_check_advertising(
            healthy_voltage, scope_timeout_s=scope_timeout_s
        ):
            self.stop_reason = (
                f"Health check failed: DUT is not advertising at "
                f"{healthy_voltage:.2f} V (scope timed out waiting for GPIO10)."
            )
            print(f"  Sweep stopped: {self.stop_reason}")
            return results

        for voltage in voltages:
            self._source_rail(voltage)
            time.sleep(0.05)  # Let voltage settle

            trials: List[VoltageTrialResult] = []
            advertising_lost = False
            timeout_had_brownout = False
            for trial_idx in range(trials_per_voltage):
                self._flush_serial()
                serial_text = ""

                with self._scope.initiate():
                    start = time.time()
                    status = self._scope.acquisition_status()
                    while status != niscope.AcquisitionStatus.COMPLETE:
                        serial_text += self._read_available()
                        if time.time() - start > scope_timeout_s:
                            break
                        time.sleep(0.005)
                        status = self._scope.acquisition_status()

                    triggered = status == niscope.AcquisitionStatus.COMPLETE
                    if triggered:
                        waveform = self._scope.channels[ch0].fetch(
                            num_samples=self._record_length, timeout=5.0
                        )

                if not triggered:
                    # Near the 3.27 V detector the chip can brown out and stop
                    # toggling GPIO10 before a capture starts.
                    serial_text += self._read_available()
                    tripped = BROWNOUT_MARKER in serial_text or self._check_for_brownout()
                    print(f"  voltage {voltage:>5.3f} V  no GPIO10 trigger within "
                          f"{scope_timeout_s:.0f}s  "
                          f"brownout text {'yes' if tripped else 'no'}")
                    advertising_lost = True
                    timeout_had_brownout = tripped
                    break

                # Ch0: AC-coupled ripple waveform (DC component already removed by scope)
                ripple_waveform = np.asarray(waveform[0].samples, dtype=float)
                trigger_idx = max(
                    0,
                    int(round(-waveform[0].relative_initial_x * self._actual_scope_rate))
                )
                burst = ripple_waveform[trigger_idx:trigger_idx + burst_samples]
                vpp, vrms, dbv = measure_ripple_amplitude(
                    burst, self._actual_scope_rate, self.ripple_frequency
                )

                tripped = (
                    BROWNOUT_MARKER in serial_text or self._check_for_brownout()
                )

                trials.append(VoltageTrialResult(
                    voltage=voltage,
                    trial_index=trial_idx,
                    tripped=tripped,
                    timestamp=datetime.now(),
                    ripple_vpp=vpp,
                    ripple_vrms=vrms,
                    ripple_dbv=dbv,
                ))

                time.sleep(0.05)  # Brief delay between trials

            if trials:
                tripped_count = sum(1 for t in trials if t.tripped)
                results.append(VoltageResult(
                    voltage=voltage,
                    total_trials=len(trials),
                    tripped_count=tripped_count,
                    trip_fraction=tripped_count / len(trials),
                    mean_ripple_vpp=float(np.mean([t.ripple_vpp for t in trials])),
                    mean_ripple_vrms=float(np.mean([t.ripple_vrms for t in trials])),
                    mean_ripple_dbv=float(np.mean([t.ripple_dbv for t in trials])),
                    trials=trials,
                ))

                last = results[-1]
                print(f"  voltage {last.voltage:>5.3f} V  "
                      f"ripple {last.mean_ripple_dbv:>7.2f} dBV "
                      f"({last.mean_ripple_vpp*1e3:>6.1f} mVpp)  "
                      f"trips {last.tripped_count:>3}/{last.total_trials} "
                      f"= {last.trip_fraction:>6.1%}")
                yield last

            if advertising_lost:
                # Raise the rail and reboot so the next lower step can still be
                # attempted. Without this, one stall ends the whole sweep above
                # the requested stop voltage.
                if voltage == voltages[-1]:
                    self.stop_reason = (
                        f"Stop voltage reached with advertising stalled at {voltage:.3f} V."
                    )
                    print(f"  Sweep finished: {self.stop_reason}")
                    break
                # No brownout text usually means the rail is already under the
                # 3.27 V detector and the UART never came up. Further steps only
                # timeout, so end the demo here instead of recovering to 3.0 V.
                if not timeout_had_brownout:
                    self.stop_reason = (
                        f"DUT not advertising and no brownout text at {voltage:.3f} V "
                        "(rail at or below detector)."
                    )
                    print(f"  Sweep finished: {self.stop_reason}")
                    break
                if not self._recover_advertising(
                    healthy_voltage, scope_timeout_s=scope_timeout_s
                ):
                    # One more attempt before giving up the rest of the curve.
                    if not self._recover_advertising(
                        healthy_voltage, scope_timeout_s=scope_timeout_s
                    ):
                        self.stop_reason = (
                            f"DUT stopped advertising after {voltage:.3f} V; "
                            "recovery reset failed."
                        )
                        print(f"  Sweep stopped: {self.stop_reason}")
                        break

        if not self.stop_reason:
            self.stop_reason = (
                f"Sweep finished ({len(results)} voltage step(s))."
                if results
                else "Sweep finished with no completed voltage steps."
            )
        return results

    def teardown(self) -> None:
        """Close all sessions and remove trigger route."""
        if self._fgen is not None:
            try:
                self._fgen.abort()
                self._fgen.close()
            except Exception as e:
                print(f"Warning: Error closing fgen: {e}")
            finally:
                self._fgen = None

        if self._smu is not None:
            try:
                self._smu.abort()
                self._smu.output_enabled = False
                self._smu.close()
            except Exception as e:
                print(f"Warning: Error closing SMU: {e}")
            finally:
                self._smu = None
                self._smu_sourcing = False

        if self._scope is not None:
            try:
                self._scope.exported_ref_trigger_output_terminal = ""
                self._scope.close()
            except Exception as e:
                print(f"Warning: Error closing scope: {e}")
            finally:
                self._scope = None

        self._clear_stale_trigger_route()

        if self._dut_serial is not None:
            try:
                self._dut_serial.close()
            except Exception as e:
                print(f"Warning: Error closing DUT serial: {e}")
            finally:
                self._dut_serial = None

        if self._visa_rm is not None:
            try:
                self._visa_rm.close()
            except Exception as e:
                print(f"Warning: Error closing VISA RM: {e}")
            finally:
                self._visa_rm = None

    def _set_dtr_rts(self, dtr: bool, rts: bool) -> None:
        """Drive the DevKit auto-reset lines. Asserted means the RS-232 line is high."""
        if self._dut_serial is None:
            return
        asserted = pyvisa.constants.VI_STATE_ASSERTED
        released = pyvisa.constants.VI_STATE_UNASSERTED
        self._dut_serial.set_visa_attribute(
            pyvisa.constants.VI_ATTR_ASRL_DTR_STATE, asserted if dtr else released
        )
        self._dut_serial.set_visa_attribute(
            pyvisa.constants.VI_ATTR_ASRL_RTS_STATE, asserted if rts else released
        )

    def _source_rail(self, voltage: float) -> None:
        """
        Set the SMU rail voltage.

        Opens sourcing with initiate() only the first time for this session.
        Later calls (including a second GUI Run) only change voltage_level
        on the fly so NI-DCPower does not raise "session is already running".
        """
        if self._smu is None:
            raise RuntimeError("SMU session is not open")
        self._smu.voltage_level = float(voltage)
        if self._smu_sourcing:
            return
        self._smu.initiate()
        self._smu_sourcing = True

    def _reset_dut(self) -> None:
        """
        Reboot the ESP32-C6 into the application via the DevKit auto-reset circuit.

        There is no reset command in the warning-only firmware. RTS/DTR pulse EN
        and the boot strap the same way esptool does. The ending state (both
        released) boots the application rather than the download ROM.
        """
        print(f"  Resetting DUT on {self.dut_visa_resource} (DTR/RTS) and waiting for advertising...")
        self._set_dtr_rts(False, False)
        self._set_dtr_rts(True, True)
        self._set_dtr_rts(False, True)  # hold EN low, boot strap for the application
        time.sleep(0.1)
        self._set_dtr_rts(False, False)
        time.sleep(2.0)
        self._flush_serial()

    def _wait_for_gpio10_trigger(self, timeout_s: float) -> bool:
        """Return True if the scope sees one rising edge on the DUT trigger."""
        if self._scope is None:
            return False
        self._arm_advertising_trigger()
        with self._scope.initiate():
            start = time.time()
            status = self._scope.acquisition_status()
            while status != niscope.AcquisitionStatus.COMPLETE:
                if time.time() - start > timeout_s:
                    return False
                time.sleep(0.005)
                status = self._scope.acquisition_status()
            return status == niscope.AcquisitionStatus.COMPLETE

    def _recover_advertising(
        self, healthy_voltage: float, scope_timeout_s: float = 5.0
    ) -> bool:
        """
        Restore BLE advertising after a low-rail stall so the sweep can continue.

        Raises the SMU to a known-good voltage, resets the DUT, and checks for
        one GPIO10 edge. Returns False if advertising does not come back.
        """
        if self._smu is None:
            return False
        print(
            f"  Recovering advertising at {healthy_voltage:.2f} V before next step..."
        )
        self._source_rail(healthy_voltage)
        time.sleep(0.3)
        self._reset_dut()
        if self._wait_for_gpio10_trigger(scope_timeout_s):
            print("  Advertising restored.")
            return True
        print("  Advertising did not return after recovery reset.")
        return False

    def _ensure_advertising(
        self,
        healthy_voltage: float,
        scope_timeout_s: float = 5.0,
        attempts: int = 3,
    ) -> bool:
        """Reset at a healthy rail until GPIO10 toggles, or give up."""
        self._source_rail(healthy_voltage)
        time.sleep(0.3)
        self._reset_dut()
        if self._wait_for_gpio10_trigger(scope_timeout_s):
            return True
        for _ in range(max(0, attempts - 1)):
            if self._recover_advertising(
                healthy_voltage, scope_timeout_s=scope_timeout_s
            ):
                return True
        return False

    def _health_check_advertising(
        self,
        healthy_voltage: float = HEALTHY_RAIL_VOLTAGE,
        scope_timeout_s: float = 5.0,
        attempts: int = 3,
    ) -> bool:
        """
        Prove the DUT is alive before the sweep: source ``healthy_voltage``,
        reset, and require a non-timeout scope capture on GPIO10 (advertising).
        """
        print(
            f"  Health check at {healthy_voltage:.2f} V "
            "(expect GPIO10 / advertising, no scope timeout)..."
        )
        ok = self._ensure_advertising(
            healthy_voltage, scope_timeout_s=scope_timeout_s, attempts=attempts
        )
        if ok:
            print(f"  Health check passed at {healthy_voltage:.2f} V.")
        else:
            print(f"  Health check failed at {healthy_voltage:.2f} V.")
        return ok

    def _restore_healthy_rail(
        self,
        healthy_voltage: float = HEALTHY_RAIL_VOLTAGE,
        scope_timeout_s: float = 5.0,
    ) -> None:
        """Raise the rail and reboot after a search so the next Run starts clean."""
        try:
            print(f"  Restoring rail to {healthy_voltage:.2f} V after search...")
            self._ensure_advertising(
                healthy_voltage, scope_timeout_s=scope_timeout_s, attempts=2
            )
        except Exception as exc:
            print(f"  Warning: could not restore healthy rail: {exc}", flush=True)

    def _clear_stale_trigger_route(self) -> None:
        """Disconnect a leftover DAQmx SMB-to-PXI_Trig0 route, if one exists."""
        try:
            nidaqmx.system.System.local().disconnect_terms(
                source_terminal=self.trigger_route_source,
                destination_terminal=self.trigger_route_dest,
            )
        except Exception:
            pass

    def _read_available(self) -> str:
        """Read whatever the DUT has already sent, without waiting out the full timeout."""
        if self._dut_serial is None:
            return ""
        old_timeout = self._dut_serial.timeout
        self._dut_serial.timeout = 1
        try:
            return self._dut_serial.read_raw().decode("ascii", errors="replace")
        except pyvisa.errors.VisaIOError:
            return ""
        finally:
            self._dut_serial.timeout = old_timeout

    def _flush_serial(self) -> None:
        """Discard stale data in DUT serial buffer."""
        if self._dut_serial is None:
            return
        old_timeout = self._dut_serial.timeout
        self._dut_serial.timeout = 10
        try:
            while True:
                try:
                    self._dut_serial.read_raw()
                except pyvisa.errors.VisaIOError:
                    break
        finally:
            self._dut_serial.timeout = old_timeout

    def _check_for_brownout(self) -> bool:
        """
        Watch DUT serial for brownout marker.
        Returns True if marker found, False if timeout (normal for no-trip trials).
        """
        if self._dut_serial is None:
            return False

        text = ""
        deadline = time.time() + self._dut_serial.timeout / 1000.0
        while time.time() < deadline:
            try:
                text += self._dut_serial.read_raw().decode("ascii", errors="replace")
            except pyvisa.errors.VisaIOError:
                break
            if BROWNOUT_MARKER in text:
                return True
        return False


def main() -> None:
    """Standalone voltage sweep demo."""
    import argparse
    import matplotlib.pyplot as plt

    parser = argparse.ArgumentParser(
        description="ESP32-C6 brownout voltage sweep at fixed arb gain."
    )
    parser.add_argument("--voltage-start", type=float, default=3.44,
                        help="Start voltage (V, default: %(default)s)")
    parser.add_argument("--voltage-stop", type=float, default=3.38,
                        help="Stop voltage (V, default: %(default)s)")
    parser.add_argument("--voltage-step", type=float, default=-0.01,
                        help="Voltage step (V, can be negative, default: %(default)s)")
    parser.add_argument("--trials", type=int, default=3,
                        help="Trials per voltage (default: %(default)s)")
    parser.add_argument("--gain", type=float, default=1.0,
                        help="Fixed arb gain (default: %(default)s)")
    parser.add_argument("--no-plot", action="store_true",
                        help="Skip interactive plot")
    args = parser.parse_args()

    print("=" * 84)
    print("ESP32-C6 Brownout Voltage Sweep (Fixed Gain)")
    print("=" * 84)
    print(f"  Voltage range: {args.voltage_start} V to {args.voltage_stop} V "
          f"(step {args.voltage_step} V)")
    print(f"  Fixed arb gain: {args.gain}")
    print(f"  Trials/voltage: {args.trials}")
    print()

    try:
        with BrownoutVoltageSweep(fixed_arb_gain=args.gain) as sweep:
            print(f"  Scope: {sweep.scope_resource}")
            print(f"  Arb:   {sweep.fgen_resource}")
            print(f"  SMU:   {sweep.smu_resource}")
            print(f"Instruments ready. Fixed gain {sweep.fixed_arb_gain}, "
                  f"ripple burst {sweep._burst_duration_s*1e3:.3f} ms.")
            print()
            results = list(sweep.run_voltage_sweep(
                voltage_start=args.voltage_start,
                voltage_stop=args.voltage_stop,
                voltage_step=args.voltage_step,
                trials_per_voltage=args.trials,
            ))
    except Exception as e:
        print(f"\nERROR: {e}")
        raise

    # Save CSV
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_name = f"brownout_voltage_sweep_{stamp}.csv"
    with open(csv_name, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'voltage', 'trial_index', 'tripped', 'timestamp',
            'ripple_vpp', 'ripple_vrms', 'ripple_dbv',
        ])
        writer.writeheader()
        for result in results:
            for trial in result.trials:
                writer.writerow(asdict(trial))
    print(f"\nSaved {sum(len(r.trials) for r in results)} trials to {csv_name}")

    # Print summary
    print()
    print(f"{'voltage':>8} {'ripple dBV':>11} {'mVpp':>8} "
          f"{'trips':>9} {'trip frac':>10}")
    print("-" * 60)
    for r in results:
        print(f"{r.voltage:>8.3f} {r.mean_ripple_dbv:>11.2f} "
              f"{r.mean_ripple_vpp*1e3:>8.1f} "
              f"{r.tripped_count:>4}/{r.total_trials:<4} {r.trip_fraction:>10.1%}")

    # Plot
    fig, ax = plt.subplots(figsize=(8, 5))
    voltages = [r.voltage for r in results]
    probs = [r.trip_fraction for r in results]
    ax.plot(voltages, probs, 'o-', linewidth=2, markersize=8)
    ax.axhline(0.5, color='r', linestyle='--', linewidth=1, label='50% trip probability')
    ax.set_xlabel('Rail Voltage (V)')
    ax.set_ylabel('Brownout Trip Probability')
    ax.set_title(f'Voltage Sweep at Fixed Gain {args.gain}')
    ax.set_ylim(-0.05, 1.05)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    plot_name = f"brownout_voltage_curve_{stamp}.png"
    fig.savefig(plot_name, dpi=150)
    print(f"\nPlot saved to {plot_name}")
    if not args.no_plot:
        plt.show()


if __name__ == "__main__":
    main()
