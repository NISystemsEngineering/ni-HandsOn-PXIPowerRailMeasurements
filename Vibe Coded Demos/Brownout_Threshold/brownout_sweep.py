"""
ESP32-C6 BLE-Induced Brownout Characterization

Sweeps the gain of a 7 kHz ripple burst injected onto the ESP32-C6's supply rail and
measures how often the ripple triggers ESP-IDF's brownout detector. Produces a full
trip-probability-vs-gain curve, plus the ripple amplitude actually measured at the
rail for each gain.

Physical Setup:
    - ESP32-C6 DevKitC-1 powered via NI SMU (remote sense)
    - GPIO10 pulses before each BLE advertising burst. It is wired to the PXI
      controller's front-panel SMB TRIG input, which setup() routes onto the
      PXI_Trig0 backplane line so every module in the chassis can trigger from it
    - NI-FGEN replays a 7 kHz ripple waveform from CSV in arbitrary-waveform mode,
      one burst per trigger, coupled onto the rail through a high-pass network
    - NI-SCOPE captures rail voltage and current, triggered from PXI_Trig0
    - DUT serial port logs "Brownout detector was triggered" on a brownout reset

Why gain rather than volts:
    The coupling network between the arb and the rail is high-pass, so the commanded
    output amplitude bears no reliable relationship to the ripple that reaches the
    rail. The arb is therefore driven by a dimensionless gain, and the real ripple
    amplitude is measured from the captured waveform on every trial and reported
    alongside the brownout result.

Dependencies:
    pip install nidcpower niscope nifgen nidaqmx pyvisa numpy matplotlib

NI Driver Runtimes Required:
    - NI-VISA
    - NI-DCPower
    - NI-SCOPE
    - NI-FGEN
    - NI-DAQmx (used only to route the controller's SMB trigger input onto
      a PXI backplane trigger line -- see setup())

Instrument addresses:
    The BrownoutSweep constructor defaults are the single source of truth for this
    station's resource names and rail settings. Change them in one place -- the
    __init__ signature below -- and the demo, the smoke test, and the diagnostic
    all follow. Callers that need different hardware pass overrides as arguments.

Usage:
    # As a reusable module (e.g., from TestStand). Omit any argument to accept
    # the station default.
    with BrownoutSweep() as sweep:
        results = sweep.run_sweep(
            gain_start=0.1,
            gain_stop=3.0,
            gain_step=0.1,
            trials_per_gain=20
        )

    # Standalone demo (accepts --help for overrides)
    python brownout_sweep.py
"""

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple
import time
from datetime import datetime
import csv

import numpy as np
import niscope
import nifgen
import nidcpower
import nidaqmx
import pyvisa

# Emitted by the ESP32-C6 brownout ISR itself, ahead of the ROM bootloader banner.
# Preferred over decoding the rst: reason that follows, which reports the reset as a
# generic software reset (0x3 LP_SW_HPSYS) and so cannot distinguish a brownout.
BROWNOUT_MARKER = "Brownout detector was triggered"

_RIPPLE_CSV_NAME = "7kHz_ripple_10.5MHz_3p571ms.csv"


def default_ripple_csv_path() -> str:
    """Resolve in-repo PXI_Training/waveform CSV relative to this file."""
    here = Path(__file__).resolve().parent
    for root in (here, *here.parents):
        candidate = root / "PXI_Training" / "waveform" / _RIPPLE_CSV_NAME
        if candidate.is_file():
            return str(candidate)
    return str(here.parents[2] / "PXI_Training" / "waveform" / _RIPPLE_CSV_NAME)


@dataclass
class TrialResult:
    """One trigger trial at one gain setting."""
    gain: float
    trial_index: int
    tripped: bool
    timestamp: datetime
    ripple_vpp: float      # measured 7 kHz ripple at the rail, peak-to-peak volts
    ripple_vrms: float     # same ripple expressed as RMS volts
    ripple_dbv: float      # same ripple in dBV (referenced to 1 Vrms)
    rail_min: float        # lowest rail voltage in the captured record
    rail_max: float        # highest rail voltage in the captured record


@dataclass
class GainResult:
    """Aggregated results for one gain setting."""
    gain: float
    total_trials: int
    tripped_count: int
    trip_fraction: float
    mean_ripple_vpp: float
    mean_ripple_vrms: float
    mean_ripple_dbv: float
    mean_rail_min: float
    trials: List[TrialResult]


def measure_ripple_amplitude(
    samples: np.ndarray, sample_rate: float, frequency: float
) -> Tuple[float, float, float]:
    """
    Measure the amplitude of `frequency` in `samples`.

    Returns (vpp, vrms, dbv). dBV is referenced to 1 Vrms, matching what an FFT
    display in InstrumentStudio reports for the 7 kHz peak.

    The amplitude is obtained by projecting the signal onto sine and cosine at
    exactly `frequency` over a whole number of cycles, rather than by reading the
    tallest FFT bin. Both measure the same thing, but the scope's sample rate is
    quantised to 1 GS/s divided by an integer, and there is no available rate that
    places 7 kHz exactly on an FFT bin. Reading the peak bin therefore loses up to
    ~1.4 dB to scalloping, whereas the projection has no such error.
    """
    cycles = int(len(samples) * frequency / sample_rate)
    if cycles < 1:
        raise ValueError(
            f"record too short to measure {frequency} Hz: {len(samples)} samples "
            f"at {sample_rate} S/s spans less than one cycle"
        )
    n = int(round(cycles * sample_rate / frequency))
    x = np.asarray(samples[:n], dtype=float)
    x = x - x.mean()   # remove the DC rail so only the ripple remains
    t = np.arange(n) / sample_rate
    a = 2.0 / n * np.dot(x, np.cos(2.0 * np.pi * frequency * t))
    b = 2.0 / n * np.dot(x, np.sin(2.0 * np.pi * frequency * t))

    v_peak = float(np.hypot(a, b))
    v_rms = v_peak / np.sqrt(2.0)
    dbv = 20.0 * np.log10(v_rms) if v_rms > 0.0 else float("-inf")
    return 2.0 * v_peak, v_rms, dbv


class BrownoutSweep:
    """
    Brownout characterization test context manager.

    Manages NI instrument sessions (scope, arb, SMU), the DUT serial connection, and
    the backplane trigger route, providing setup/run/teardown lifecycle for TestStand
    compatibility.

    The defaults below are this station's actual configuration and are the single
    source of truth for resource names; other scripts in this folder read them from
    here rather than keeping their own copies.

    Note that these are NI MAX aliases, not slot names. Once a device is renamed in
    NI MAX the default "PXI1SlotN" name stops resolving, so the alias is the only
    valid string. The PXIe-4147 is a 4-channel SMU, hence the "/0" channel suffix.

    Args:
        scope_resource: NI-SCOPE resource name (default: "5164_Scope")
        fgen_resource: NI-FGEN resource name (default: "5433_Arb")
        smu_resource: NI-DCPower SMU resource name with channel (default: "4147_SMU/0")
        dut_visa_resource: DUT UART/serial VISA resource (default: "ASRL5::INSTR", COM5)
        supply_voltage: DUT supply voltage in volts (default: 3.4V)

            The brownout detector is configured at 3.27 V, so the nominal 3.3 V leaves
            only 30 mV of margin -- the dip at the start of a BLE packet trips it on
            its own and every gain reads 100%, giving no curve at all. The rail is
            deliberately raised to create headroom, so that a trip requires the
            injected ripple and the trip probability actually varies with gain.

            Expect to retune this per DUT. These boards are hand-built on solderless
            breadboards, so contact resistance and layout parasitics vary enough to
            shift where the curve lands. 3.4 V is a good starting point; if a board
            trips at every gain, raise it, and if it never trips, lower it.


        supply_current_limit: SMU current limit in amps (default: 0.5A)
        ripple_csv_path: Single-column CSV of normalised (+/-1) ripple samples
        arb_sample_rate: Arb playback rate; with the supplied file this yields 7 kHz
        ripple_frequency: Ripple fundamental in Hz, used for amplitude measurement
        scope_sample_rate: Scope sample rate for the rail capture
        scope_voltage_channel: Scope channel for rail voltage (default: "0")
        scope_current_channel: Scope channel for rail current (default: "1")
        trigger_route_source: Controller SMB input the DUT's GPIO10 is wired to
        trigger_route_dest: Backplane trigger line to drive from that SMB input
        scope_trigger_source: Trigger line the scope and arb listen on

    Note the two different trigger naming conventions. DAQmx routing needs a
    fully-qualified terminal ("/CharlieKnapp-8881/PXI_Trig0"), while NI-SCOPE and
    NI-FGEN want the short backplane name ("PXI_Trig0"). Same physical line.
    """

    def __init__(
        self,
        scope_resource: str = "5164_Scope",
        fgen_resource: str = "5433_Arb",
        smu_resource: str = "4147_SMU/0",
        dut_visa_resource: str = "ASRL5::INSTR",
        dut_serial_timeout_ms: float = 2500,
        supply_voltage: float = 3.4,
        supply_current_limit: float = .5,
        ripple_csv_path: Optional[str] = None,
        arb_sample_rate: float = 10.5e6,
        ripple_frequency: float = 7000.0,
        scope_sample_rate: float = 2.0e6,
        scope_voltage_channel: str = "0",
        scope_current_channel: str = "1",
        trigger_route_source: str = "/CharlieKnapp-8881/TRIG_SMB",
        trigger_route_dest: str = "/CharlieKnapp-8881/PXI_Trig0",
        scope_trigger_source: str = "PXI_Trig0",
    ):
        self.scope_resource = scope_resource
        self.fgen_resource = fgen_resource
        self.smu_resource = smu_resource
        self.dut_visa_resource = dut_visa_resource
        self.dut_serial_timeout_ms = dut_serial_timeout_ms
        self.supply_voltage = supply_voltage
        self.supply_current_limit = supply_current_limit
        self.ripple_csv_path = ripple_csv_path or default_ripple_csv_path()
        self.arb_sample_rate = arb_sample_rate
        self.ripple_frequency = ripple_frequency
        self.scope_sample_rate = scope_sample_rate
        self.scope_voltage_channel = scope_voltage_channel
        self.scope_current_channel = scope_current_channel
        self.trigger_route_source = trigger_route_source
        self.trigger_route_dest = trigger_route_dest
        self.scope_trigger_source = scope_trigger_source

        # Session handles (initialized in setup/teardown)
        self._scope: Optional[niscope.Session] = None
        self._fgen: Optional[nifgen.Session] = None
        self._smu: Optional[nidcpower.Session] = None
        self._dut_serial: Optional[pyvisa.Resource] = None
        self._visa_rm: Optional[pyvisa.ResourceManager] = None
        # Tracks whether the backplane trigger route was created, so teardown only
        # tries to remove a route that actually exists.
        self._route_connected: bool = False

        # Populated by setup() once the hardware reports what it actually did.
        self._burst_duration_s: float = 0.0
        self._actual_scope_rate: float = 0.0
        self._record_length: int = 0

    def __enter__(self) -> "BrownoutSweep":
        """Context manager entry: calls setup()."""
        self.setup()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context manager exit: calls teardown()."""
        self.teardown()
        return False  # Don't suppress exceptions

    def setup(self) -> None:
        """
        Open and configure all instrument sessions and the trigger route.

        Designed to be called once at the start of a test sequence (TestStand's Setup
        step). Leaves the arb armed-but-idle; run_sweep() sets the gain and starts it.

        Raises:
            RuntimeError: If any instrument, file, or route fails to initialise.
        """
        try:
            self._visa_rm = pyvisa.ResourceManager()

            # Open DUT serial connection (115200 baud, newline-terminated)
            self._dut_serial = self._visa_rm.open_resource(
                self.dut_visa_resource,
                baud_rate=115200,
                read_termination='\n',
                write_termination='\n'
            )
            # The brownout message appears quickly (under 1s), but a generous timeout
            # ensures late trips aren't missed. Lower values speed the sweep but risk
            # false negatives. A timeout means "did not trip", not an error.
            self._dut_serial.timeout = self.dut_serial_timeout_ms

            # Load the ripple waveform. Values are normalised to +/-1; the arb's gain
            # scales them, so the file is loaded once and reused for every step.
            ripple = np.loadtxt(self.ripple_csv_path)
            self._burst_duration_s = len(ripple) / self.arb_sample_rate

            # SMU: source the rail with remote sense.
            self._smu = nidcpower.Session(resource_name=self.smu_resource)
            self._smu.source_mode = nidcpower.SourceMode.SINGLE_POINT
            self._smu.output_function = nidcpower.OutputFunction.DC_VOLTAGE
            self._smu.sense = nidcpower.Sense.REMOTE  # 4-wire Kelvin at the DUT
            self._smu.voltage_level = self.supply_voltage
            self._smu.current_limit = self.supply_current_limit
            self._smu.voltage_level_range = 6.0
            self._smu.current_limit_range = self.supply_current_limit
            # Why NORMAL rather than FAST: the SMU's control loop actively opposes the
            # injected ripple. Measured on this rig, FAST suppresses the 7 kHz ripple
            # to about a third of what NORMAL passes, which would mask the effect
            # being characterised.
            self._smu.transient_response = nidcpower.TransientResponse.NORMAL
            self._smu.measure_when = \
                nidcpower.MeasureWhen.AUTOMATICALLY_AFTER_SOURCE_COMPLETE
            self._smu.output_enabled = True

            # Scope: capture the rail across the ripple burst.
            self._scope = niscope.Session(resource_name=self.scope_resource)
            self._scope.channels[self.scope_voltage_channel].configure_vertical(
                range=10.0,
                coupling=niscope.VerticalCoupling.DC,
                probe_attenuation=1.0
            )
            self._scope.channels[self.scope_current_channel].configure_vertical(
                range=2.0,
                coupling=niscope.VerticalCoupling.DC,
                probe_attenuation=1.0
            )
            # Size the record to the burst plus 25% margin. Capturing beyond the burst
            # would dilute the amplitude measurement, since the quiet tail contains no
            # ripple to average in.
            capture_s = self._burst_duration_s * 1.25
            self._scope.configure_horizontal_timing(
                min_sample_rate=self.scope_sample_rate,
                min_num_pts=int(capture_s * self.scope_sample_rate),
                ref_position=5.0,   # small pretrigger; the burst starts at the trigger
                num_records=1,      # single shot per trial
                enforce_realtime=True
            )
            self._actual_scope_rate = self._scope.horz_sample_rate
            self._record_length = self._scope.horz_record_length

            # The DUT's GPIO10 lands on the controller's front-panel SMB input, which
            # is not visible to the instrument modules on its own. Route it onto a
            # backplane trigger line so every module in the chassis can see it.
            #
            # Why route to the backplane rather than point the scope at the SMB: the
            # arb cannot reference the controller's SMB input directly, so a shared
            # backplane line is the only trigger source both modules can agree on.
            # Owning the route here (instead of in a separate LabVIEW VI) matters
            # because a DAQmx route lives only until it is disconnected -- if the VI
            # that created it closes, the line goes dead and every scope arm times out.
            nidaqmx.system.System.local().connect_terms(
                source_terminal=self.trigger_route_source,
                destination_terminal=self.trigger_route_dest,
            )
            self._route_connected = True

            # Why DIGITAL trigger (not EDGE): the ripple gets large enough near the
            # brownout threshold that an analog edge trigger fires unreliably on
            # multiple crossings. The DUT's own hardware trigger guarantees every
            # capture lines up with a real BLE advertising burst.
            self._scope.configure_trigger_digital(
                trigger_source=self.scope_trigger_source,
                slope=niscope.TriggerSlope.POSITIVE,
                holdoff=0.0,
                delay=0.0
            )

            # Arb: replay the ripple file, one burst per trigger.
            self._fgen = nifgen.Session(resource_name=self.fgen_resource)
            self._fgen.output_mode = nifgen.OutputMode.ARB
            handle = self._fgen.create_waveform(waveform_data_array=ripple)
            self._fgen.arb_sample_rate = self.arb_sample_rate
            # Gain 1.0 is only a valid placeholder to get through configuration;
            # run_sweep() overwrites it per step.
            self._fgen.configure_arb_waveform(
                waveform_handle=handle, gain=1.0, offset=0.0
            )
            self._fgen.output_impedance = 50.0
            # BURST plus a digital start trigger means one 3.57 ms ripple burst per
            # BLE advertising burst, so the ripple is always phase-aligned with the
            # radio activity rather than drifting against it. The arb stays armed
            # across triggers, so it only needs initiating once per gain step.
            self._fgen.trigger_mode = nifgen.TriggerMode.BURST
            self._fgen.start_trigger_type = nifgen.StartTriggerType.DIGITAL_EDGE
            self._fgen.digital_edge_start_trigger_source = self.scope_trigger_source
            self._fgen.digital_edge_start_trigger_edge = \
                nifgen.StartTriggerDigitalEdgeEdge.RISING
            self._fgen.output_enabled = True

            self._smu.initiate()

        except Exception as e:
            # Clean up anything that did open before reporting the failure.
            self.teardown()
            raise RuntimeError(f"Failed to setup instruments: {e}") from e

    def run_sweep(
        self,
        gain_start: float,
        gain_stop: float,
        gain_step: float,
        trials_per_gain: int,
        scope_timeout_s: float = 10.0,
    ) -> List[GainResult]:
        """
        Sweep arb gain and measure brownout trip probability at each step.

        At each gain the arb is set and started, then `trials_per_gain` trigger trials
        run. Each trial flushes the DUT serial buffer, arms the scope for one
        digitally-triggered capture, measures the ripple that actually reached the
        rail, and checks the serial port for a brownout reset.

        Why many trials per gain: near the threshold, brownouts are probabilistic.
        BLE's advertising-interval jitter shifts where the burst lands relative to the
        ripple phase, so one trial says very little. The full trip fraction is what
        characterises the threshold.

        Args:
            gain_start: First arb gain, must be greater than zero
            gain_stop: Last arb gain (inclusive)
            gain_step: Gain increment
            trials_per_gain: Trigger trials to run at each gain
            scope_timeout_s: How long to wait for a trigger before treating it as a
                failure. A timeout means the DUT stopped advertising, which is an
                error condition, never a "did not trip".

        Returns:
            One GainResult per gain, each carrying its individual TrialResults.

        Raises:
            RuntimeError: If setup() has not been called.
            ValueError: If the gain range is invalid.
            TimeoutError: If the scope fails to trigger within scope_timeout_s.
        """
        if self._scope is None or self._fgen is None or self._dut_serial is None:
            raise RuntimeError("run_sweep() called before setup()")
        if gain_step == 0:
            raise ValueError(f"gain_step must be non-zero, got {gain_step}")
        # The arb has no valid zero gain, so a sweep starting at or below zero fails
        # on the first step. Catch it here rather than partway through a demo.
        if gain_start <= 0:
            raise ValueError(f"gain_start must be greater than zero, got {gain_start}")

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

        results: List[GainResult] = []
        both_channels = f"{self.scope_voltage_channel},{self.scope_current_channel}"
        burst_samples = int(self._burst_duration_s * self._actual_scope_rate)

        for gain in gains:
            # Gain can only change while generation is stopped. The arb then stays
            # armed and bursts on every trigger, so this happens once per gain.
            self._fgen.abort()
            self._fgen.arb_gain = gain
            self._fgen.initiate()

            trials: List[TrialResult] = []
            for trial_idx in range(trials_per_gain):
                # Discard anything already in the serial buffer. A brownout message
                # left over from the previous trial would otherwise be attributed to
                # this one.
                self._flush_serial()

                with self._scope.initiate():
                    start = time.time()
                    status = self._scope.acquisition_status()
                    while status != niscope.AcquisitionStatus.COMPLETE:
                        if time.time() - start > scope_timeout_s:
                            raise TimeoutError(
                                f"Scope did not trigger within {scope_timeout_s}s at "
                                f"gain {gain}. The DUT has stopped advertising. Well "
                                f"above the threshold this is expected: the ripple "
                                f"browns the DUT out during boot, so it resets "
                                f"continuously and never reaches the advertising burst "
                                f"that pulses GPIO10. Lower gain_stop, or raise the "
                                f"rail voltage, to stay in the measurable range. "
                                f"Otherwise check that the DUT is powered, running the "
                                f"GPIO10 firmware, and cabled to the SMB TRIG input."
                            )
                        time.sleep(0.005)
                        status = self._scope.acquisition_status()

                    waveforms = self._scope.channels[both_channels].fetch(
                        num_samples=self._record_length, timeout=5.0
                    )

                rail = np.asarray(waveforms[0].samples, dtype=float)
                # Measure only the burst, starting at the trigger point. The small
                # pretrigger region has no ripple in it and would bias the amplitude
                # low if included.
                trigger_idx = max(
                    0,
                    int(round(-waveforms[0].relative_initial_x * self._actual_scope_rate))
                )
                burst = rail[trigger_idx:trigger_idx + burst_samples]
                vpp, vrms, dbv = measure_ripple_amplitude(
                    burst, self._actual_scope_rate, self.ripple_frequency
                )

                tripped = self._check_for_brownout()

                trials.append(TrialResult(
                    gain=gain,
                    trial_index=trial_idx,
                    tripped=tripped,
                    timestamp=datetime.now(),
                    ripple_vpp=vpp,
                    ripple_vrms=vrms,
                    ripple_dbv=dbv,
                    rail_min=float(rail.min()),
                    rail_max=float(rail.max()),
                ))

                # Let the DUT finish rebooting before the next trial, otherwise the
                # next arm can catch it mid-boot with no advertising yet.
                time.sleep(0.1)

            tripped_count = sum(1 for t in trials if t.tripped)
            results.append(GainResult(
                gain=gain,
                total_trials=trials_per_gain,
                tripped_count=tripped_count,
                trip_fraction=tripped_count / trials_per_gain,
                mean_ripple_vpp=float(np.mean([t.ripple_vpp for t in trials])),
                mean_ripple_vrms=float(np.mean([t.ripple_vrms for t in trials])),
                mean_ripple_dbv=float(np.mean([t.ripple_dbv for t in trials])),
                mean_rail_min=float(np.mean([t.rail_min for t in trials])),
                trials=trials,
            ))

            # Live progress, so the sweep is watchable during a demo.
            last = results[-1]
            print(f"  gain {last.gain:>5.2f}  "
                  f"ripple {last.mean_ripple_dbv:>7.2f} dBV "
                  f"({last.mean_ripple_vpp*1e3:>6.1f} mVpp)  "
                  f"rail min {last.mean_rail_min:>6.3f} V  "
                  f"trips {last.tripped_count:>3}/{last.total_trials} "
                  f"= {last.trip_fraction:>6.1%}")

        return results

    def teardown(self) -> None:
        """
        Close all instrument sessions and remove the trigger route.

        Safe to call even if setup() failed partway through, and safe to call twice.
        """
        # Stop the ripple first, so the DUT is not being stressed while the rest of
        # the teardown runs.
        if self._fgen is not None:
            try:
                self._fgen.abort()
                self._fgen.close()
            except Exception as e:
                print(f"Warning: Error closing fgen session: {e}")
            finally:
                self._fgen = None

        if self._smu is not None:
            try:
                self._smu.abort()
                self._smu.output_enabled = False
                self._smu.close()
            except Exception as e:
                print(f"Warning: Error closing SMU session: {e}")
            finally:
                self._smu = None

        if self._scope is not None:
            try:
                self._scope.close()
            except Exception as e:
                print(f"Warning: Error closing scope session: {e}")
            finally:
                self._scope = None

        # Remove the backplane trigger route after the instruments are closed, so
        # nothing is still armed against a line that is about to go away. Routes
        # survive process exit, so leaving one behind would affect the next run.
        if self._route_connected:
            try:
                nidaqmx.system.System.local().disconnect_terms(
                    source_terminal=self.trigger_route_source,
                    destination_terminal=self.trigger_route_dest,
                )
            except Exception as e:
                print(f"Warning: Error removing trigger route: {e}")
            finally:
                self._route_connected = False

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
                print(f"Warning: Error closing VISA resource manager: {e}")
            finally:
                self._visa_rm = None

    def _flush_serial(self) -> None:
        """
        Discard anything sitting in the DUT's serial receive buffer.

        Brownout messages from a previous trial linger otherwise, and would be
        misattributed to the next trial.
        """
        if self._dut_serial is None:
            return

        old_timeout = self._dut_serial.timeout
        self._dut_serial.timeout = 10   # ms; just long enough to see if data is there
        try:
            while True:
                try:
                    self._dut_serial.read_raw()
                except pyvisa.errors.VisaIOError:
                    break   # a read timeout means the buffer is empty
        finally:
            self._dut_serial.timeout = old_timeout

    def _check_for_brownout(self) -> bool:
        """
        Watch the DUT serial port for a brownout reset message.

        Returns True as soon as the marker appears. Returns False if the read window
        closes without it, which is the normal outcome for trials away from the
        threshold and is not an error.
        """
        if self._dut_serial is None:
            return False

        # Read bytes rather than text. A brownout reset drops the DUT into its ROM
        # bootloader, which emits a burst of non-ASCII garbage at a different baud
        # rate before the firmware banner appears -- strict decoding raises on it,
        # which would turn the very trips we are looking for into crashes.
        text = ""
        deadline = time.time() + self._dut_serial.timeout / 1000.0
        while time.time() < deadline:
            try:
                text += self._dut_serial.read_raw().decode("ascii", errors="replace")
            except pyvisa.errors.VisaIOError:
                break   # no more data within the timeout
            # Accumulate rather than testing line by line, so a marker split across
            # two reads by the boot garbage is still found.
            if BROWNOUT_MARKER in text:
                return True
        return False


# ============================================================================
# Standalone Demo Script
# ============================================================================

def main() -> None:
    """
    Standalone demo: run a full gain sweep, save a CSV, and plot the results.

    Instrument addresses are not repeated here -- they come from the BrownoutSweep
    constructor defaults. Every value can still be overridden on the command line,
    which is handy for a quick low-trial confidence check before the real run:

        python brownout_sweep.py --gain-stop 0.5 --trials 3
    """
    import argparse
    import matplotlib.pyplot as plt

    # Defaults come from the class so there is only one place to edit addresses.
    station = BrownoutSweep()

    parser = argparse.ArgumentParser(
        description="ESP32-C6 BLE-induced brownout characterization sweep."
    )
    parser.add_argument("--gain-start", type=float, default=0.1,
                        help="First arb gain, must be > 0 (default: %(default)s)")
    parser.add_argument("--gain-stop", type=float, default=3.0,
                        help="Last arb gain (default: %(default)s)")
    parser.add_argument("--gain-step", type=float, default=0.1,
                        help="Gain increment (default: %(default)s)")
    parser.add_argument("--trials", type=int, default=20,
                        help="Trials per gain (default: %(default)s)")
    parser.add_argument("--supply-voltage", type=float, default=station.supply_voltage,
                        help="Rail voltage in volts (default: %(default)s)")
    parser.add_argument("--scope", default=station.scope_resource,
                        help="NI-SCOPE resource (default: %(default)s)")
    parser.add_argument("--fgen", default=station.fgen_resource,
                        help="NI-FGEN resource (default: %(default)s)")
    parser.add_argument("--smu", default=station.smu_resource,
                        help="NI-DCPower resource (default: %(default)s)")
    parser.add_argument("--dut", default=station.dut_visa_resource,
                        help="DUT serial VISA resource (default: %(default)s)")
    # The plot is always written to a PNG; this only suppresses the blocking window,
    # which would otherwise stall an unattended or TestStand-driven run.
    parser.add_argument("--no-plot", action="store_true",
                        help="Skip the interactive plot window")
    args = parser.parse_args()

    print("=" * 84)
    print("ESP32-C6 BLE-Induced Brownout Characterization")
    print("=" * 84)
    print(f"  Gain range:    {args.gain_start} to {args.gain_stop} "
          f"(step {args.gain_step})")
    print(f"  Trials/gain:   {args.trials}")
    print(f"  Rail:          {args.supply_voltage} V")
    print(f"  Scope / Arb:   {args.scope} / {args.fgen}")
    print(f"  SMU / DUT:     {args.smu} / {args.dut}")
    print()

    try:
        with BrownoutSweep(
            scope_resource=args.scope,
            fgen_resource=args.fgen,
            smu_resource=args.smu,
            dut_visa_resource=args.dut,
            supply_voltage=args.supply_voltage,
        ) as sweep:
            print(f"Instruments ready. Ripple burst {sweep._burst_duration_s*1e3:.3f} ms "
                  f"at {sweep.ripple_frequency/1e3:.1f} kHz; scope "
                  f"{sweep._actual_scope_rate/1e6:.3f} MS/s x {sweep._record_length} "
                  f"samples.")
            print()
            results = sweep.run_sweep(
                gain_start=args.gain_start,
                gain_stop=args.gain_stop,
                gain_step=args.gain_step,
                trials_per_gain=args.trials,
            )
    except Exception as e:
        print(f"\nERROR: {e}")
        raise

    # Save every trial, including its measured ripple amplitude.
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_name = f"brownout_sweep_{stamp}.csv"
    with open(csv_name, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'gain', 'trial_index', 'tripped', 'timestamp',
            'ripple_vpp', 'ripple_vrms', 'ripple_dbv', 'rail_min', 'rail_max',
        ])
        writer.writeheader()
        for gain_result in results:
            for trial in gain_result.trials:
                writer.writerow(asdict(trial))
    trial_count = sum(len(r.trials) for r in results)
    print(f"\nSaved {trial_count} trials to {csv_name}")

    print()
    print(f"{'gain':>6} {'ripple dBV':>11} {'mVpp':>8} {'mVrms':>8} "
          f"{'rail min':>9} {'trips':>9} {'trip frac':>10}")
    print("-" * 70)
    for r in results:
        print(f"{r.gain:>6.2f} {r.mean_ripple_dbv:>11.2f} "
              f"{r.mean_ripple_vpp*1e3:>8.1f} {r.mean_ripple_vrms*1e3:>8.1f} "
              f"{r.mean_rail_min:>9.3f} "
              f"{r.tripped_count:>4}/{r.total_trials:<4} {r.trip_fraction:>10.1%}")

    # Two views of the same data: against the knob that was swept, and against the
    # ripple amplitude actually delivered, which is the physically meaningful axis.
    fig, (ax_gain, ax_amp) = plt.subplots(1, 2, figsize=(13, 5))

    ax_gain.plot([r.gain for r in results],
                 [r.trip_fraction for r in results], 'o-', linewidth=2)
    ax_gain.axhline(0.5, color='r', linestyle='--', linewidth=1,
                    label='50% trip probability')
    ax_gain.set_xlabel('Arb gain (dimensionless)')
    ax_gain.set_ylabel('Brownout trip probability')
    ax_gain.set_title('Trip probability vs arb gain')
    ax_gain.set_ylim(-0.05, 1.05)
    ax_gain.grid(True, alpha=0.3)
    ax_gain.legend()

    ax_amp.plot([r.mean_ripple_dbv for r in results],
                [r.trip_fraction for r in results], 's-', color='tab:green',
                linewidth=2)
    ax_amp.axhline(0.5, color='r', linestyle='--', linewidth=1)
    ax_amp.set_xlabel('Measured 7 kHz ripple at rail (dBV, ref 1 Vrms)')
    ax_amp.set_ylabel('Brownout trip probability')
    ax_amp.set_title('Trip probability vs measured ripple')
    ax_amp.set_ylim(-0.05, 1.05)
    ax_amp.grid(True, alpha=0.3)

    fig.suptitle('ESP32-C6 BLE-Induced Brownout Characterization',
                 fontsize=13, fontweight='bold')
    fig.tight_layout()
    plot_name = f"brownout_curve_{stamp}.png"
    fig.savefig(plot_name, dpi=150)
    print(f"\nPlot saved to {plot_name}")
    if not args.no_plot:
        plt.show()


if __name__ == "__main__":
    main()
