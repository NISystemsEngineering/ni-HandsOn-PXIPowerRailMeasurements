"""
Confirm the trigger chain end to end: DUT GPIO10 -> controller SMB -> PXI_Trig0 -> scope.

This arms the scope exactly like a sweep trial does, but skips the serial check, so it
isolates "is the DUT triggering?" from the rest of the measurement. Run it before a
demo. If it reports captures, the sweep's scope-arm step will work.
"""

import time

import niscope

from brownout_sweep import BrownoutSweep

ARM_TIMEOUT_S = 10.0
ATTEMPTS = 3


if __name__ == "__main__":
    print()
    with BrownoutSweep() as sweep:
        print("Instruments configured and trigger route established.")
        # A mid-range gain so conditions resemble a real trial. The arb bursts off the
        # same trigger line as the scope; it is not what triggers the scope.
        sweep._fgen.abort()
        sweep._fgen.arb_gain = 3.0
        sweep._fgen.initiate()
        print("Arb armed at gain 3.00.")
        print()

        captured = 0
        for attempt in range(1, ATTEMPTS + 1):
            print(f"  attempt {attempt}: arming scope, waiting up to "
                  f"{ARM_TIMEOUT_S:.0f}s for PXI_Trig0 ... ", end="", flush=True)
            with sweep._scope.initiate():
                start = time.time()
                status = sweep._scope.acquisition_status()
                while status != niscope.AcquisitionStatus.COMPLETE:
                    if time.time() - start > ARM_TIMEOUT_S:
                        break
                    time.sleep(0.01)
                    status = sweep._scope.acquisition_status()

                elapsed = time.time() - start
                if status == niscope.AcquisitionStatus.COMPLETE:
                    channels = (f"{sweep.scope_voltage_channel},"
                                f"{sweep.scope_current_channel}")
                    waveforms = sweep._scope.channels[channels].fetch(
                        num_samples=sweep._record_length, timeout=5.0
                    )
                    rail = waveforms[0].samples
                    vmin, vmax = min(rail), max(rail)
                    print(f"TRIGGERED after {elapsed:.2f}s")
                    print(f"      rail: min={vmin:.3f} V  max={vmax:.3f} V  "
                          f"excursion={vmax - vmin:.3f} V  samples={len(rail)}")
                    captured += 1
                else:
                    print(f"NO TRIGGER (timed out after {elapsed:.1f}s)")

        sweep._fgen.abort()

    print()
    if captured == ATTEMPTS:
        print(f"All {ATTEMPTS} arms triggered. Trigger chain is working end to end.")
    elif captured:
        print(f"Only {captured} of {ATTEMPTS} arms triggered -- intermittent. "
              "Check the SMB cable seating and that GPIO10 pulses every advertising burst.")
    else:
        print("No triggers at all. Check, in order:")
        print("  1. DUT is powered and running the firmware that pulses GPIO10")
        print("  2. GPIO10 is cabled to the controller's front-panel SMB TRIG input")
        print("  3. Trigger polarity -- try niscope.TriggerSlope.NEGATIVE in setup()")
