# Voltage Sweep Demo - Quick Start

## What Changed

**Previous approach:** Sweep arb gain from low to high at fixed voltage (3.4V)
- Slow (many gain steps needed)
- Indirect (gain → ripple → voltage dip → brownout)

**New approach:** Sweep voltage from high to low at fixed gain (2.0)
- Fast (<60 seconds for 8 voltages × 5 trials)
- Direct (voltage → voltage dip → brownout)
- More reliable for finding 3.27V threshold

## Hardware Requirement

**IMPORTANT:** DUT must have J5 jumper **removed** to enable external power via SMU at the 3.3V header. Without this, COM port won't work at voltages below normal USB levels.

## Quick Demo

### Option 1: Command Line (with plot saved to file)
```bash
python brownout_voltage_sweep.py --voltage-start 3.35 --voltage-stop 3.28 --voltage-step -0.01 --trials 5 --gain 2.0
```

Results saved to:
- `brownout_voltage_sweep_YYYYMMDD_HHMMSS.csv` (raw data)
- `brownout_voltage_curve_YYYYMMDD_HHMMSS.png` (plot)

### Option 2: Live GUI (recommended for demos)
```bash
python brownout_voltage_gui.py
```

Shows 4 panels updating in real-time:
- **Panel A:** Trip probability vs voltage (main result)
- **Panel B:** Trip probability vs ripple amplitude
- **Panel C:** Rail minimum vs voltage & detector threshold
- **Panel D:** Measured ripple vs voltage

Demo completes in ~60 seconds. Window stays open with "Close" button.

## Expected Results

- **4-8 brownouts detected** out of 40 trials (10-20% rate)
- Brownouts occur when rail_min dips below 3.27V detector threshold
- Ripple amplitude ~115-125 mVpp at gain 2.0
- Trip probability shows stochastic pattern (not smooth curve)

## Why Detection is Probabilistic

Brownout detection is **not deterministic**. Even when rail_min < 3.27V, detection probability is only ~10-20% due to:

1. **Timing alignment** - Detector samples at discrete intervals; brief dips between samples are missed
2. **Duration filtering** - Detector requires voltage < threshold for minimum duration (glitch rejection)
3. **Internal vs external voltage** - Detector monitors internal rail, which differs from external measurement point
4. **Serial communication** - Fast resets may prevent warning message from being sent

See `VOLTAGE_SWEEP_FINDINGS.md` for detailed analysis.

## Tuning for Your DUT

Default parameters are optimized for typical ESP32-C6 on breadboard:

```python
VOLTAGE_START = 3.35  # V, well above detector
VOLTAGE_STOP = 3.28   # V, below detector  
VOLTAGE_STEP = -0.01  # V, downward sweep
TRIALS_PER_VOLTAGE = 5
FIXED_GAIN = 2.0
```

**If you see:**
- **No brownouts:** Increase `FIXED_GAIN` to 2.5 or 3.0
- **Too many brownouts:** Decrease `FIXED_GAIN` to 1.5 or 1.8
- **Noisy data:** Increase `TRIALS_PER_VOLTAGE` to 8-10
- **Too slow:** Decrease `TRIALS_PER_VOLTAGE` to 3, or use larger `VOLTAGE_STEP` (-0.02)

Edit parameters at bottom of `brownout_voltage_gui.py` or use command-line args for `brownout_voltage_sweep.py`.

## Comparison: Gain Sweep vs Voltage Sweep

| Aspect | Gain Sweep (Old) | Voltage Sweep (New) |
|--------|------------------|---------------------|
| **Speed** | ~2-3 minutes | ~60 seconds |
| **Parameters** | 26 gain steps | 8 voltage steps |
| **Directness** | Indirect (gain→ripple→brownout) | Direct (voltage→brownout) |
| **Threshold** | Shows ripple amplitude needed | Shows voltage threshold |
| **Demo clarity** | Complex (coupling network effects) | Simple (voltage vs detector) |
| **Reliability** | Good | Good |

Both approaches work - voltage sweep is faster and more direct for demo purposes.

## Files

- `brownout_voltage_sweep.py` - Core implementation (can run standalone)
- `brownout_voltage_gui.py` - Live 4-panel GUI
- `brownout_sweep.py` - Original gain sweep (still works, not deprecated)
- `brownout_gui.py` - Original gain sweep GUI
- `VOLTAGE_SWEEP_FINDINGS.md` - Detailed analysis and explanations
- `README_VOLTAGE_SWEEP.md` - This file

## Troubleshooting

### "No serial data received"
- Check DUT is powered (LED on, current ~40-50 mA @ 3.4V)
- Verify J5 jumper removed (required for external power)
- Confirm COM5 is correct port (Device Manager)
- Check DUT firmware is running BLE advertising

### "Scope timeout"
- Verify GPIO10 trigger routing: `/CharlieKnapp-8881/TRIG_SMB` → `/CharlieKnapp-8881/PXI_Trig0`
- Check BLE advertising is active (should see bursts on GPIO10)
- Confirm arb waveform is loaded and enabled

### "SMU voltage error"
- Check remote sense connections (4-wire Kelvin at DUT)
- Verify 3.3V header has good connection (no loose wires)
- Confirm current limit not exceeded (should be ~40-60 mA)

### Contact
For issues, check `test_serial_simple.py` and `check_smu_voltage.py` diagnostics.
