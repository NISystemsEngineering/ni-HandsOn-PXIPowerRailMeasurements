# Quick Start Guide

## Files in This Module

| File | Purpose |
|------|---------|
| `brownout_sweep.py` | **Main module** — `BrownoutSweep` class and standalone demo. Also holds the station's instrument addresses, in the constructor defaults |
| `brownout_gui.py` | **Live GUI** — runs a sweep and builds the curve on screen as it goes. Best option for demoing |
| `requirements.txt` | Python package dependencies |
| `README.md` | Full documentation (hardware setup, usage, troubleshooting) |
| `teststand_example.py` | TestStand integration example (Setup/Main/Cleanup pattern) |
| `diagnose_instruments.py` | Opens each configured instrument and reports what fails. Run before a demo |
| `test_trigger_capture.py` | Confirms the DUT actually triggers the scope end to end. Run before a demo |
| `test_trigger_route.py` | Checks the SMB → PXI_Trig0 backplane route can be created |
| `test_route_ab.py` | A/B proof that the DAQmx route is what makes the scope trigger |
| `test_serial_marker.py` | Dumps raw DUT serial at high gain to verify `BROWNOUT_MARKER` matches the firmware |
| `test_setup_only.py` | ~8 second smoke test of `setup()`/`teardown()` without a full sweep |
| `test_simulated.py` | Exercises all configuration with no hardware attached |
| `scan_hardware.py` | Confirms modules are physically present, via NI System Configuration |
| `QUICK_START.md` | This file — quick reference |

## 5-Minute Setup

### 1. Install Dependencies

```bash
# Install NI driver runtimes first (from ni.com/downloads):
# - NI-VISA
# - NI-DCPower
# - NI-SCOPE
# - NI-FGEN
# - NI-DAQmx   (only for routing the SMB trigger input to PXI_Trig0)

# Then install Python packages:
pip install -r requirements.txt
```

### 2. Verify Your Instruments

```bash
python diagnose_instruments.py
```

You want all four rows reading `OK`. This opens each instrument at the address the
real sweep will use, so if something is misconfigured you find out here in a few
seconds rather than partway through a demo.

To confirm the modules are physically present and healthy:

```bash
python scan_hardware.py
```

### 3. Configuration (only if your hardware differs)

Instrument addresses live in **one place**: the `BrownoutSweep.__init__` signature in
`brownout_sweep.py`. Edit them there and the demo, smoke test, and diagnostic all
follow automatically.

```python
scope_resource: str = "5164_Scope",
fgen_resource: str = "5433_Arb",
smu_resource: str = "4147_SMU/0",
dut_visa_resource: str = "ASRL5::INSTR",   # COM5
```

These are NI MAX **aliases**, not slot names. To find yours, open NI MAX, expand
"Devices and Interfaces", and use the name shown in quotes next to each module. Once a
device has been renamed, its default `PXI1SlotN` name no longer resolves.

### 4. Run Demo

Easiest option is the GUI, which builds the curve on screen as the sweep runs:

```bash
python brownout_gui.py
```

Set the rail voltage and gain range, click **Run sweep**, and watch the points appear.
**Stop** ends the run after the current gain step; **Save CSV** works mid-sweep; **Close**
exits when you're done reviewing. The window stays open after the sweep completes.

For the command-line version:

First a quick confidence check that the DUT is triggering and tripping, using a tiny
sweep:

```bash
python brownout_sweep.py --gain-start 3.0 --gain-stop 6.0 --gain-step 1.0 --trials 3
```

Then the real thing:

```bash
python brownout_sweep.py --gain-start 2.0 --gain-stop 6.0 --gain-step 0.25
```

This will:
- Initialize instruments
- Run a full gain sweep (20 trials/gain by default)
- Print live progress, including measured ripple amplitude per gain
- Save trial-level results to CSV
- Plot trip probability against both gain and measured ripple

Run `python brownout_sweep.py --help` to see every override. Nothing needs editing to
change sweep size. Add `--no-plot` for unattended runs.

**Pick the rail voltage before the gain range.** The brownout detector sits at 3.27 V, so
at a nominal 3.3 V rail the BLE dip alone trips it and every gain reads 100%. The default
3.4 V leaves enough headroom to produce a real curve. The arb's gain ceiling is 6.

Expect to retune the rail per DUT — these are hand-built breadboard assemblies and vary
enough to shift the curve. The DUT is specified up to 3.6 V.

Fastest way to check a new board: run three trials at maximum gain and read `rail min`.
A trip needs the rail under 3.27 V, so this predicts the outcome without a full sweep.

```bash
python brownout_sweep.py --gain-start 6.0 --gain-stop 6.0 --gain-step 1.0 --trials 3 --no-plot
```

| `rail min` at gain 6 | Meaning | Action |
|---|---|---|
| Well below 3.27 V | Ripple has authority over the detector | Good, run the sweep |
| Above 3.27 V | Arb can't reach the threshold at any gain | Lower the rail |
| Trips at every gain | Too little headroom, BLE dip alone trips it | Raise the rail |

The useful window on this station is narrow — roughly 3.34 V to 3.45 V, with 3.4 V giving
the cleanest full curve. Above 3.5 V there are no trips at any gain. See `README.md` for
the measured table.

## Usage Patterns

### Pattern 1: Standalone Script (Demo, Interactive Testing)

```python
from brownout_sweep import BrownoutSweep

# No arguments needed -- the constructor defaults hold this station's addresses.
with BrownoutSweep() as sweep:
    results = sweep.run_sweep(
        gain_start=2.0,
        gain_stop=6.0,
        gain_step=0.25,
        trials_per_gain=20
    )
    
    # Process results
    for gain_result in results:
        print(f"gain {gain_result.gain:.2f} "
              f"({gain_result.mean_ripple_dbv:.2f} dBV): "
              f"{gain_result.trip_fraction:.1%} trip rate")
```

### Pattern 2: TestStand (Production Test Sequence)

See `teststand_example.py` for the three-function pattern:

1. **Setup Step** → `teststand_setup()` — Open instrument sessions
2. **Main Step** → `teststand_run_sweep()` — Run sweep, return results
3. **Cleanup Step** → `teststand_teardown()` — Close sessions

In TestStand, create three Python steps pointing to these functions.

### Pattern 3: Manual Lifecycle (Advanced)

When you need fine control over setup/teardown timing:

```python
sweep = BrownoutSweep()

try:
    sweep.setup()
    
    # Run multiple sweeps without tearing down
    results1 = sweep.run_sweep(2.0, 4.0, 0.25, 10)
    results2 = sweep.run_sweep(4.0, 6.0, 0.25, 10)
    
finally:
    sweep.teardown()
```

## Key Design Features

### For Reliability
- **Context manager** — Automatic resource cleanup even on errors
- **Type hints** — Catch mistakes before runtime
- **Clear exceptions** — Fails loudly with informative messages
- **Separate setup/run/teardown** — TestStand-compatible lifecycle

### For Readability
- **Inline comments explain WHY** — Physical reasoning, not just mechanics
- **Straightforward control flow** — No unnecessary abstraction
- **Docstrings** — Every function and class documented
- **Simple data structures** — Dataclasses, not inheritance hierarchies

### For Correctness
- **Digital trigger** — Reliable trigger at large ripple amplitudes
- **Serial buffer flushing** — No cross-contamination between trials
- **Scope timeout = error** — Won't silently hang on hardware faults
- **Serial timeout = normal** — Expected when no brownout occurs
- **N trials per gain** — Captures probabilistic behavior correctly
- **Ripple measured, not assumed** — The coupling network makes commanded gain an
  unreliable stand-in for delivered amplitude, so every trial measures it

## Understanding the Output

### Console Progress (Live During Demo)

```
  gain  2.00  ripple  -27.59 dBV ( 118.2 mVpp)  rail min  3.293 V  trips   0/12 =   0.0%
  gain  3.00  ripple  -23.95 dBV ( 179.5 mVpp)  rail min  3.251 V  trips   0/12 =   0.0%
  gain  4.00  ripple  -21.50 dBV ( 238.1 mVpp)  rail min  3.238 V  trips   2/12 =  16.7%
  gain  4.50  ripple  -20.42 dBV ( 269.6 mVpp)  rail min  3.202 V  trips   8/12 =  66.7%
  gain  6.00  ripple  -17.98 dBV ( 357.0 mVpp)  rail min  3.188 V  trips  12/12 = 100.0%
```

### CSV Output (Trial-Level Data)

```csv
gain,trial_index,tripped,timestamp,ripple_vpp,ripple_vrms,ripple_dbv,rail_min,rail_max
2.0,0,False,2026-09-25T16:38:31.123456,0.1182,0.0418,-27.59,3.293,3.498
4.5,0,True,2026-09-25T16:40:12.345678,0.2696,0.0953,-20.42,3.202,3.535
```

### Plot (Trip Probability Curve)

![Reference Curve](brownout_curve_20260925_163825.png)

Two panels of the same data:
- **Left:** trip probability vs arb gain — the knob that was swept
- **Right:** trip probability vs measured ripple in dBV — the physically meaningful axis
- Red dashed line at 50%; the crossing is the threshold region
- Both show the gradual 0% → 100% transition rather than a hard threshold

## Common Adjustments

### Faster Debug Sweeps

```python
results = sweep.run_sweep(
    gain_start=3.0,       # Narrow range around the transition
    gain_stop=6.0,
    gain_step=1.0,        # Coarser steps
    trials_per_gain=5     # Fewer trials
)
```

### High-Resolution Characterization

```python
results = sweep.run_sweep(
    gain_start=2.0,
    gain_stop=6.0,
    gain_step=0.1,        # Finer steps
    trials_per_gain=50    # More trials for better statistics
)
```

### Different Supply Voltage

Shifts the whole curve: more headroom moves the transition to higher gain.

```python
with BrownoutSweep(
    supply_voltage=3.5,       # More headroom than the 3.4V default
    supply_current_limit=0.5
) as sweep:
    ...
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `TimeoutError: Scope did not trigger` at high gain | Ripple browns the DUT out during boot, so it never advertises | Lower `gain_stop` or raise `supply_voltage` |
| `TimeoutError: Scope did not trigger` at all gains | DUT not toggling GPIO10, or trigger not routed | `test_trigger_capture.py`, then `test_route_ab.py` |
| All trials `tripped=False` | Marker string doesn't match firmware, or ripple not reaching DUT | `test_serial_marker.py` |
| All trials `tripped=True` | Not enough headroom; BLE dip alone trips the 3.27 V detector | Raise `supply_voltage` (3.4 V works here) |
| `UnicodeDecodeError` on serial | ROM bootloader garbage after a reset | Already handled; re-pull the module if you see it |
| Import errors | Missing packages | `pip install -r requirements.txt` |
| NI driver errors | Driver runtime not installed | Install from ni.com/downloads |
| Session lock / stack-overrun crashes | InstrumentStudio debug session is active | InstrumentStudio → Configure debug session → clear the checkbox |

See `README.md` for detailed troubleshooting.

## Next Steps

1. **Verify hardware setup** — Check wiring, trigger routing, remote sense
2. **Run demo with defaults** — `python brownout_sweep.py`
3. **Analyze results** — Check CSV and plot
4. **Adjust parameters** — Refine gain range, step size, trials, rail voltage
5. **Integrate into TestStand** — Use `teststand_example.py` as template

For questions or issues, refer to:
- `README.md` — Full documentation
- Inline code comments — Explain physical reasoning
- Docstrings — Function/class documentation
