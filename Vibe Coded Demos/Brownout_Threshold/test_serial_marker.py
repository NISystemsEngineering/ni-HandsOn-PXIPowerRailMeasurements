"""Dump raw DUT serial traffic while bursting ripple at a high gain.

Confirms what the firmware actually prints on a brownout reset, so BROWNOUT_MARKER in
brownout_sweep.py can be checked against reality rather than assumed. Worth running
after any firmware change: a marker that no longer matches produces a silent all-zero
trip curve, which looks like a measurement result rather than a bug.
"""
import time
import niscope
import pyvisa
from brownout_sweep import BrownoutSweep, BROWNOUT_MARKER

GAIN = 6.0
TRIALS = 3

with BrownoutSweep() as sweep:
    print(f"Armed. gain={GAIN}, watching serial for {TRIALS} trials.\n")
    sweep._fgen.abort()
    sweep._fgen.arb_gain = GAIN
    sweep._fgen.initiate()

    for trial in range(TRIALS):
        sweep._flush_serial()

        with sweep._scope.initiate():
            start = time.time()
            while sweep._scope.acquisition_status() != niscope.AcquisitionStatus.COMPLETE:
                if time.time() - start > 10:
                    raise TimeoutError("scope did not trigger")
                time.sleep(0.005)

        text = ""
        deadline = time.time() + 3.0
        while time.time() < deadline:
            try:
                text += sweep._dut_serial.read_raw().decode("ascii", errors="replace")
            except pyvisa.errors.VisaIOError:
                break

        print(f"--- trial {trial}: {len(text)} chars ---")
        print(repr(text))
        print(f"marker present: {BROWNOUT_MARKER in text}\n")
        time.sleep(0.5)
