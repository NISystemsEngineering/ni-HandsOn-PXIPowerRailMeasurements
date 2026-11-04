# Demo Guide: ESP32-C6 Brownout Characterization

## Demo Context

**Audience:** Tech Exchange attendees who have completed hands-on InstrumentStudio exercises

**Prior activities:** Attendees manually used InstrumentStudio to:
- Set arb gain values
- Configure scope triggers
- Capture waveforms
- Read serial output from the DUT

**Your message:** "What you just did manually, here's how you automate it with the APIs"

## Running the Demo

```powershell
python brownout_gui.py
```

**Default settings (optimized for demo speed):**
- Rail voltage: 3.4 V (gives good headroom above the 3.27 V detector)
- Gain: 6.0 → 3.0, step -1.0 (4 points: 6, 5, 4, 3)
- Trials: 3 per gain (12 total trials)
- Live updates: Enabled (plot updates after each trial)
- Serial timeout: 1.0 s (fast mode)

**Estimated timing:**
- First data: ~0.7 seconds
- Full sweep: ~16-18 seconds
- Total with brief intro: Under 30 seconds

## What the Audience Sees

### Timeline

| Time | What Happens | What to Say |
|------|--------------|-------------|
| 0s | Click "Run sweep" | "Let's automate what you just did manually..." |
| 0.7s | First point appears (gain 6, 100% trips) | "First measurement complete — instant brownout at high gain" |
| 1-4s | Points 2-3 stream in | "Notice the plot updates continuously as trials complete" |
| 4-8s | Transition region appears | "Here's the probabilistic behavior near the threshold" |
| 8-16s | Final points fill in | "Low gain region — no more brownouts" |
| 16s | Curve complete, logistic fit appears | "And there's our characterization: 50% crossing at ~260 mVpp" |

### The Four Panels

Walk through in reading order (top-left → top-right → bottom-left → bottom-right):

**1. Trip probability vs measured ripple (top-left)**
- *"This is the headline result: at what ripple amplitude does this DUT brown out?"*
- Points are labeled with the gain that produced them
- Error bars show 95% confidence (Wilson intervals)
- Green curve is the logistic fit
- Dotted line marks the 50% crossing (~264 mVpp)

**2. Trip probability vs arb gain (top-right)**
- *"Same data, plotted against the knob we actually turned"*
- Useful for anyone who wants to reproduce the test
- Shows we swept from gain 6 down to 3

**3. How far the rail dips (bottom-left)**
- *"Here's why it trips: watch the rail dip approach the detector level"*
- Red line is the lowest rail voltage at each gain
- Purple horizontal line at 3.27 V is the detector threshold
- As ripple grows (higher gain), the rail dips deeper

**4. Coupling network transfer (bottom-right)**
- *"What does a unit of gain buy us at the rail?"*
- Near-linear: ~59 mVpp per unit gain
- Shows the coupling network isn't compressing
- Why we plot against measured amplitude, not just gain

## Key Talking Points

### Speed
- *"First measurement in under 1 second"*
- *"Full 12-trial characterization in 16 seconds"*
- *"The APIs don't add overhead — instruments run at full speed"*

### Integration
- *"Four instruments synchronized under program control:"*
  - Arb generating the ripple burst
  - Scope capturing each burst
  - SMU holding the rail voltage
  - Serial port monitoring for brownout messages
- *"You had to coordinate those manually in InstrumentStudio"*

### Analysis
- *"Error bars: 3 trials gives us ~20-60% confidence — that's honest uncertainty"*
- *"Logistic fit converts scattered points to a single threshold number"*
- *"Four different views of the same data, all computed automatically"*

### Automation Value
- *"This test is now repeatable — same code, same results every time"*
- *"Easily extended: want 20 trials per point? Change one number"*
- *"Want to characterize 10 DUTs? Loop this script"*
- *"Ready to integrate into TestStand for production"*

## Handling Questions

### "Why start at high gain instead of low?"
*"Demo optimization. High gain trips immediately (~0.7s per trial), low gain waits the full 1s serial timeout. Starting high gives instant visual feedback and finishes faster."*

For a careful characterization, you'd sweep low to high with more trials.

### "Why only 3 trials per point?"
*"For a live demo, 3 trials is enough to show the curve and compute confidence intervals. For a real characterization, you'd run 12-20 trials per point — just change that one field and re-run."*

### "What are the error bars?"
*"Wilson score 95% confidence intervals. Better than the normal approximation for small sample sizes. Shows that 3 out of 3 trips doesn't mean exactly 100% — it's roughly 30-100% with 95% confidence."*

### "Why is the step negative?"
*"We're sweeping backward (6 → 3) for demo speed. Negative step just means count down instead of up."*

### "Can I see the code?"
*"Absolutely."* Open `brownout_gui.py` in an editor and show:
- The `BrownoutSweep` context manager managing all four instruments
- The worker thread running trials and sending results via queue
- The four-panel matplotlib figure

Point out: *"This is ~500 lines including the GUI. The core measurement is maybe 100 lines."*

### "How do I run this myself?"
*"Requirements are in `requirements.txt` — just the NI Python drivers, numpy, and matplotlib. Then `python brownout_gui.py`."*

## Adjusting for Your DUT

If the curve isn't appearing or is saturated:

**Rail voltage tuning:**
- All trips even at low gain → Raise rail (not enough headroom)
- No trips even at high gain → Lower rail (too much headroom)
- Quick check: Run gain 6, check "rail min" in output
  - If rail min < 3.27 V → good
  - If rail min > 3.27 V → lower rail voltage

**Detector threshold:**
The 3.27 V is set in the DUT firmware. If your DUT differs, update:
- `brownout_gui.py` line defining `BROWNOUT_DETECTOR_V`
- Documentation in `README.md`

**Serial marker:**
If brownouts aren't being detected, the marker string might have changed:
- Run `test_serial_marker.py` at high gain
- Look for the actual string the DUT prints
- Update `BROWNOUT_MARKER` in `brownout_sweep.py` if needed

## Files Reference

| File | Purpose | Use in Demo |
|------|---------|-------------|
| `brownout_gui.py` | **The demo app** | What you run |
| `brownout_sweep.py` | Core measurement class | Show this if asked about the code |
| `teststand_example.py` | TestStand integration | "Here's how it integrates into production test" |
| `requirements.txt` | Python dependencies | "Here's what you need to install" |
| `README.md` | Full documentation | Reference for attendees |
| `QUICK_START.md` | Quick reference | Handout |

## Post-Demo Resources

Give attendees:
1. This repository URL (or a zip)
2. `QUICK_START.md` as a PDF
3. `requirements.txt`
4. Contact info for follow-up questions

Mention:
- *"All the NI Python drivers are on github.com/ni — well-documented, actively maintained"*
- *"The pattern you see here — context manager, worker thread, live GUI — works for any multi-instrument setup"*
- *"TestStand can call Python directly, so this path goes all the way to production"*

## Timing Troubleshooting

If the demo is running slower than expected:

1. **Uncheck "Live trial updates"** — Updates after each gain instead of each trial (faster but less dynamic)
2. **Reduce trials** — Try 2 per gain
3. **Coarser steps** — Change step to -2.0 (only 2 points: 6 and 4)
4. **Check serial timeout** — Should be 1.0s in fast mode

The GUI checkbox toggles between:
- **Checked (default):** Plot updates after every trial (12 updates, more dynamic, slightly slower)
- **Unchecked:** Plot updates after each gain step (4 updates, faster, less action)

Most impactful is the serial timeout — 1.0s vs 2.5s saves 12 seconds over a 12-trial run.

## Success Metrics

A successful demo:
- ✓ First data appears in under 1 second
- ✓ Continuous visual updates (no long pauses)
- ✓ Total time under 20 seconds
- ✓ Clean 0% → 100% curve visible
- ✓ Attendees see the "automation speed" message
- ✓ At least one question about extending/modifying it

If attendees are asking how to adapt it to their own measurements, you've succeeded.
