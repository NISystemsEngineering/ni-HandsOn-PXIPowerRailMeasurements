# ESP32-C6 BLE-Induced Brownout Characterization

Automated probabilistic brownout characterization for ESP32-C6 using NI PXI instruments.

## Overview

This module sweeps the gain of an injected 7 kHz ripple burst on the ESP32-C6's 3.3V rail and measures brownout trip probability at each gain. It builds a full Shmoo-style curve showing the probabilistic nature of brownouts near the threshold.

**Why probabilistic?** Brownouts near the threshold don't happen deterministically. BLE advertising-interval jitter interacts with the injected ripple's phase, making each trial slightly different. This module runs N trials per gain (typically 20) to capture the true trip probability.

**Why gain rather than volts?** A high-pass coupling network sits between the arb and the rail, so the commanded amplitude has no fixed relationship to the ripple that actually arrives. The arb is driven in arbitrary-waveform mode where the only amplitude control is a dimensionless `arb_gain`. Rather than trusting that number, every trial measures the real 7 kHz ripple at the rail from the scope capture and reports it in dBV, Vpp, and Vrms — so the curve can be plotted against a physically meaningful axis.

## Hardware Setup

### Connections

1. **ESP32-C6 DevKitC-1 Power:**
   - Powered at 3.3V via NI SMU (NI-DCPower)
   - Use **remote sense** (4-wire Kelvin) for accurate voltage at DUT

2. **Trigger Signal:**
   - DUT GPIO10 → PXI chassis front-panel TRIG input → PXI_TRIG0 backplane
   - Firmware toggles GPIO10 before each BLE advertising burst

3. **Ripple Injection:**
   - NI-FGEN output → high-pass coupling network → 3.3V rail
   - Arbitrary-waveform mode, playing a 7 kHz sine from a CSV file
   - **Burst mode**: one 3.571 ms burst per trigger, so ripple is present only
     during the advertising event rather than running continuously

4. **Measurement:**
   - NI-SCOPE channel 0: Rail voltage (DC-coupled, 10V range)
   - NI-SCOPE channel 1: Rail current via current probe (DC-coupled, adjust range)
   - Scope triggered by PXI_TRIG0 (digital trigger, not analog edge)

5. **DUT Serial:**
   - USB-UART bridge to PC
   - 115200 baud, logs `Brownout detector was triggered` on brownout

   This marker is the ESP32-C6 brownout ISR's own message. It is preferred over the
   `rst:` reason that follows it in the boot banner, which reports the reset as a
   generic software reset (`0x3 LP_SW_HPSYS`) and cannot identify a brownout.

### Rail Voltage and Headroom

The brownout detector is set at **3.27 V**. Running the rail at a nominal 3.3 V leaves
only 30 mV of margin, and the negative-going dip at the start of every BLE packet trips
it *with no injected ripple at all* — every gain reads 100% and there is no curve to
measure. The rail is therefore deliberately raised (default **3.4 V**) so that a trip
requires the injected ripple, and trip probability varies with gain.

**Expect to retune the rail per DUT.** These boards are hand-built on solderless
breadboards, so contact resistance and layout parasitics vary enough to shift where the
curve lands. Set the rail with `supply_voltage=` on the constructor or `--supply-voltage`
on the command line — nothing else needs to change. The DUT is specified up to 3.6 V.

### Per-DUT Rail Tuning

A trip happens when the rail dips below the 3.27 V detector, so `rail_min` predicts it
directly — no need to run a full sweep to find the right rail. Run three trials at
maximum gain and read `rail min` off the progress line:

```bash
python brownout_sweep.py --gain-start 6.0 --gain-stop 6.0 --gain-step 1.0 --trials 3 --no-plot
```

- `rail min` well **below** 3.27 V → good, the sweep will resolve a full 0→100% curve
- `rail min` **above** 3.27 V → the arb cannot reach the threshold; lower the rail
- Trips at *every* gain → too little headroom; raise the rail

Measured on this station, showing how narrow the useful window is:

| Rail (V) | Rail min at gain 6 | Result |
|---------:|-------------------:|--------|
| 3.30 | 3.191 | 100% trips at every gain — no curve to measure |
| 3.34 | 3.219 | 0→100% across gain 0.5–2.5 |
| **3.40** | **3.188** | **0→100% across gain 3.5–6 — full curve, the default** |
| 3.45 | 3.232 | only reaches 50% at maximum gain |
| 3.50 | 3.302 | no trips at any gain — above the detector |
| 3.60 | 3.401 | no trips at any gain |

The arb's gain ceiling of 6 delivers about 350 mVpp at the rail, which is what sets the
upper limit: above roughly 3.45 V the ripple can no longer pull the rail under 3.27 V.
Note that raising the rail does **not** buy more ripple — delivered amplitude is flat at
about 350 mVpp across all these rails, so the only thing that changes is headroom.

### Why Digital Trigger?

The scope uses a **digital trigger** (PXI_TRIG0) rather than an analog edge trigger because:
- Ripple amplitude gets very large near the brownout threshold
- Analog edge triggering becomes unreliable with large ripple (multiple crossings, false triggers)
- Digital trigger from DUT GPIO10 ensures we always capture the exact BLE burst that matters

## Installation

### Prerequisites

1. **NI Driver Runtimes** (download from ni.com/downloads):
   - NI-VISA
   - NI-DCPower
   - NI-SCOPE
   - NI-FGEN
   - NI-DAQmx (used only to route the controller's SMB trigger input to PXI_TRIG0)

2. **Python 3.8+**

### Install Python Packages

```bash
pip install -r requirements.txt
```

## Usage

### Standalone Demo

```bash
python brownout_sweep.py
```

This will:
- Run a full sweep with default parameters
- Print live progress per gain, including the measured ripple amplitude
- Save trial-level results to CSV
- Plot trip probability against both gain and measured ripple
- Display the plot and save it as PNG

Every parameter can be overridden on the command line, which is useful for a quick
confidence check before the real run:

```bash
python brownout_sweep.py --gain-start 3.0 --gain-stop 6.0 --gain-step 0.5 --trials 5
```

Add `--no-plot` to skip the blocking plot window (the PNG is still written), which is
what you want for an unattended or TestStand-driven run.

### Live GUI (Best for Demoing)

```bash
python brownout_gui.py
```

Set the rail voltage, gain range, and trials per gain, then click **Run sweep**. Each
point appears as soon as its gain step finishes, so the curve builds while the audience
watches rather than appearing all at once at the end.

![GUI curve](brownout_gui_example.png)

The sweep runs on a worker thread because each trial blocks for up to several seconds
waiting on the scope and the DUT serial port, which would otherwise freeze the window.
The worker owns the instrument sessions for its whole life and passes finished results
back through a queue, keeping every instrument call on one thread and every widget call
on another.

**Stop** takes effect at the end of the current gain step. **Save CSV** writes the same
trial-level columns as the command-line demo, and works on a partial sweep. **Close**
exits the application — the window stays open after a sweep completes so you can review
the results and save the CSV.

#### The Four Panels

They are ordered so the demo can be walked through in reading order, each answering a
different question:

1. **Trip probability vs measured ripple** — the headline result, with the fit and the
   50% crossing. The x axis is measured mVpp rather than gain because gain is only a
   knob on this station; the coupling network means the same gain delivers different
   amplitude on different hardware, so amplitude is what transfers. Each point is still
   labelled with the gain that produced it.
2. **Trip probability vs arb gain** — the same curve against the knob actually turned,
   for anyone who wants to reproduce the run rather than the physics.
3. **How far the rail dips** — the lowest rail voltage at each gain, with a reference
   line at the 3.27 V detector level.
4. **Coupling network transfer** — measured mVpp against gain, annotated with the slope
   (about 59 mVpp per unit gain). Its near-linearity is the evidence that the coupling
   network is not compressing at these levels.

Panel 3 deliberately plots the rail dip as a *trend against gain* rather than plotting
trip probability against dip depth. The mean rail minimum crosses 3.27 V at around gain
2.5, where trips are still zero, because the detector needs the excursion to persist
rather than merely touch the threshold. Plotting it the other way would imply a clean
predictive threshold that the data does not support, and invites a question with no
short answer.

#### Reading the Uncertainty

**Error bars are Wilson score intervals**, not the normal approximation. With tens of
trials per point the normal approximation gives a zero-width bar at 0% and 100%,
implying certainty the data does not support — 12 out of 12 trials justifies roughly
76–100%, not exactly 100%. The intervals also show why the point-to-point wiggle is
sampling noise: on the reference run the 33% and 17% points have heavily overlapping
intervals.

The fitted curve is a logistic regression on the trial outcomes, which converts the
scattered points into a single 50% crossing (264 mVpp on the reference run). It is only
drawn once at least two points are partially tripped — one point satisfies the
likelihood but cannot separate *where* the transition sits from *how sharp* it is, so
fitting earlier would draw a confident-looking vertical step that the data does not
support.

Trial count controls how tight everything is. At 4 trials per point the same DUT put the
crossing anywhere from 252 to 281 mVpp as the sweep progressed, with error bars wide
enough to span most of the axis; at 12 trials it settled at 264 mVpp. Running the fast
version first and then the careful one makes a good talking point about why a
probabilistic curve needs trials.

### From TestStand

The `BrownoutSweep` class is designed for TestStand's Python adapter:

**Setup Step:**
```python
# Omit any argument to accept the station default from the constructor.
sweep = BrownoutSweep()
sweep.setup()

# Or pass overrides for a different station:
sweep = BrownoutSweep(
    scope_resource="5164_Scope",
    fgen_resource="5433_Arb",
    smu_resource="4147_SMU/0",
    dut_visa_resource="ASRL5::INSTR"
)
sweep.setup()
```

**Main Step:**
```python
results = sweep.run_sweep(
    gain_start=2.0,
    gain_stop=6.0,
    gain_step=0.25,
    trials_per_gain=20
)
# results is a list of GainResult dataclass instances
# Access via: results[0].trip_fraction, results[0].mean_ripple_dbv,
#             results[0].trials[0].tripped, etc.
```

**Cleanup Step:**
```python
sweep.teardown()
```

Or use context manager (combines all three):
```python
with BrownoutSweep(...) as sweep:
    results = sweep.run_sweep(...)
# teardown() called automatically
```

### From Other Python Code

```python
from brownout_sweep import BrownoutSweep

with BrownoutSweep() as sweep:
    results = sweep.run_sweep(
        gain_start=2.0,
        gain_stop=6.0,
        gain_step=0.25,
        trials_per_gain=20
    )
    
    for gain_result in results:
        print(f"gain {gain_result.gain:.2f} "
              f"({gain_result.mean_ripple_dbv:.2f} dBV, "
              f"{gain_result.mean_ripple_vpp*1e3:.1f} mVpp): "
              f"{gain_result.trip_fraction:.1%} trip rate "
              f"({gain_result.tripped_count}/{gain_result.total_trials})")
```

## Configuration Parameters

### Constructor Arguments

These defaults are the **single source of truth** for this station. They live in the
`BrownoutSweep.__init__` signature in `brownout_sweep.py`; change them there and the
demo, the smoke test, and the diagnostic all follow. No other file declares its own copy.

Note these are NI MAX **aliases**, not slot names. Renaming a device in NI MAX stops
the default `PXI1SlotN` name from resolving, so the alias becomes the only valid string.
The PXIe-4147 is a 4-channel SMU, hence the `/0` suffix.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `scope_resource` | str | `"5164_Scope"` | NI-SCOPE resource name |
| `fgen_resource` | str | `"5433_Arb"` | NI-FGEN resource name |
| `smu_resource` | str | `"4147_SMU/0"` | NI-DCPower resource name with channel |
| `dut_visa_resource` | str | `"ASRL5::INSTR"` | DUT UART VISA resource (COM5) |
| `supply_voltage` | float | `3.4` | DUT supply voltage (V) |
| `supply_current_limit` | float | `0.5` | SMU current limit (A) |
| `ripple_csv_path` | str | `PXI_Training/waveform/7kHz_ripple_10.5MHz_3p571ms.csv` (auto) | Normalised (±1) ripple samples |
| `arb_sample_rate` | float | `10.5e6` | Arb playback rate; yields 7 kHz with this file |
| `ripple_frequency` | float | `7000.0` | Ripple fundamental (Hz), used for measurement |
| `scope_sample_rate` | float | `2.0e6` | Scope sample rate for the rail capture |
| `scope_voltage_channel` | str | `"0"` | Scope channel for rail voltage |
| `scope_current_channel` | str | `"1"` | Scope channel for rail current |
| `trigger_route_source` | str | `"/CharlieKnapp-8881/TRIG_SMB"` | Controller SMB input GPIO10 is wired to |
| `trigger_route_dest` | str | `"/CharlieKnapp-8881/PXI_Trig0"` | Backplane line to drive from that SMB input |
| `scope_trigger_source` | str | `"PXI_Trig0"` | Trigger line the scope and arb listen on |

Note the two trigger naming conventions: DAQmx routing needs a fully-qualified terminal
(`/CharlieKnapp-8881/PXI_Trig0`), while NI-SCOPE and NI-FGEN want the short backplane
name (`PXI_Trig0`). Same physical line.

### `run_sweep()` Arguments

| Parameter | Type | Description |
|-----------|------|-------------|
| `gain_start` | float | First arb gain, must be > 0 |
| `gain_stop` | float | Last arb gain |
| `gain_step` | float | Gain increment |
| `trials_per_gain` | int | Number of trials per gain |
| `scope_timeout_s` | float | Scope trigger timeout (seconds, default 10.0) |

The arb's gain ceiling is **6**; this is a hardware limit and is not affected by
`analog_path`.

## Output Data Structures

### `TrialResult` (dataclass)
- `gain`: float — arb gain for this trial
- `trial_index`: int — trial number at this gain (0-indexed)
- `tripped`: bool — True if brownout detected
- `timestamp`: datetime — when trial completed
- `ripple_vpp`, `ripple_vrms`, `ripple_dbv`: float — 7 kHz ripple measured at the rail
- `rail_min`, `rail_max`: float — voltage extremes over the capture (V)

### `GainResult` (dataclass)
- `gain`: float — arb gain
- `total_trials`: int — number of trials run
- `tripped_count`: int — how many tripped
- `trip_fraction`: float — tripped_count / total_trials
- `mean_ripple_vpp`, `mean_ripple_vrms`, `mean_ripple_dbv`: float — mean measured ripple
- `mean_rail_min`: float — mean lowest rail voltage (V)
- `trials`: List[TrialResult] — all trial results for this gain

### How Ripple Amplitude Is Measured

The amplitude is obtained by projecting the capture onto sine and cosine at exactly
7 kHz over a whole number of cycles (a lock-in / single-bin Goertzel), after removing
the DC rail. This is preferred over reading an FFT peak bin because no achievable scope
sample rate puts 7 kHz exactly on a bin, so a raw peak-bin reading suffers up to ~1.4 dB
of scalloping loss. dBV is referenced to 1 Vrms.

## Measured Results

Reference run on this station: 3.4 V rail, 12 trials per gain, 108 trials total.

| Gain | Ripple (dBV) | mVpp | mVrms | Rail min (V) | Trips | Trip fraction |
|-----:|-------------:|-----:|------:|-------------:|:-----:|--------------:|
| 2.00 | −27.59 | 118.2 |  41.8 | 3.293 |  0/12 |   0.0% |
| 2.50 | −25.49 | 150.5 |  53.2 | 3.260 |  0/12 |   0.0% |
| 3.00 | −23.95 | 179.5 |  63.5 | 3.251 |  0/12 |   0.0% |
| 3.50 | −22.71 | 207.1 |  73.2 | 3.255 |  4/12 |  33.3% |
| 4.00 | −21.50 | 238.1 |  84.2 | 3.238 |  2/12 |  16.7% |
| 4.50 | −20.42 | 269.6 |  95.3 | 3.202 |  8/12 |  66.7% |
| 5.00 | −19.56 | 297.4 | 105.2 | 3.210 |  8/12 |  66.7% |
| 5.50 | −18.74 | 327.2 | 115.7 | 3.192 | 10/12 |  83.3% |
| 6.00 | −17.98 | 357.0 | 126.2 | 3.188 | 12/12 | 100.0% |

The 50% crossing sits near gain 4.2, about −20.9 dBV (roughly 255 mVpp). Trip
probability is flat at zero up to gain 3, then rises to certainty by the gain ceiling of
6 — the full probabilistic transition rather than a single threshold. Measured ripple
scales close to linearly with gain (~0.057 Vpp per unit), confirming the coupling
network is not compressing at these levels.

## Troubleshooting

### Scope Timeout Errors

**Error:** `TimeoutError: Scope did not trigger within 10s at gain N`

This is treated as a hard error, never as a silent "did not trip".

**Most likely cause at high gain:** the ripple is strong enough to brown the DUT out
*during boot*, so it resets continuously and never reaches the advertising burst that
pulses GPIO10. Lower `gain_stop`, or raise the rail voltage, to stay in the measurable
range. At a 3.3 V rail this starts happening around gain 3.

**Otherwise:**
- DUT firmware not running (not toggling GPIO10)
- GPIO10 not cabled to the controller's front-panel SMB TRIG input
- Trigger polarity — try `niscope.TriggerSlope.NEGATIVE` in `setup()`

Run `test_trigger_capture.py` to isolate the trigger chain from the rest of the
measurement, and `test_route_ab.py` to prove the DAQmx route is what makes it work.

### Serial Timeout (Not an Error)

The DUT serial read timeout (2.5s) is **normal behavior** when the DUT doesn't brownout. Most trials away from the threshold will time out without seeing the brownout message — this is recorded as `tripped=False`, not an error.

### No Brownouts at Any Gain

First check that the marker string matches what your firmware actually prints — a
mismatch produces a silent all-zero curve, which looks like a measurement result rather
than a bug. Run `test_serial_marker.py`, which dumps raw DUT serial traffic at high gain
and reports whether `BROWNOUT_MARKER` is present.

Other causes:
- Rail voltage too high, leaving more headroom than the ripple can overcome
- Ripple not reaching DUT rail (check the coupling network)
- `TransientResponse` set to `FAST`, which actively suppresses injected ripple to
  roughly a third of what `NORMAL` passes
- DUT brownout detector disabled in firmware

### All Trials Brownout, Even at the Lowest Gain

**Cause:** not enough headroom between the rail and the brownout threshold, so the BLE
current dip alone trips the detector and the ripple is irrelevant. With a 3.27 V
detector, a 3.3 V rail reads 100% at every gain — even at 7.8 mVpp of ripple, which is
far too small to matter.

**Fix:** raise `supply_voltage`. 3.4 V gives a clean 0%→100% transition on this DUT.
Also verify the SMU remote-sense voltage and that the coupling network is not adding a
DC offset.

### UnicodeDecodeError Reading DUT Serial

A brownout drops the DUT into its ROM bootloader, which emits non-ASCII bytes at a
different baud rate before the firmware banner appears. Serial reads therefore use raw
bytes with lenient decoding; strict decoding raises on exactly the trips you are trying
to detect.

## Code Style Notes

This module prioritizes **readability and simplicity** over enterprise patterns:

- Straightforward control flow, easy to read top-to-bottom
- Inline comments explain **why** (physical reasoning), not just **what**
- Context manager handles resource cleanup automatically
- Type hints and docstrings throughout
- Clear exceptions for failure conditions (never hangs silently)

## License

(Add your license here)
