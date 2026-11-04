"""Test serial communication at a specific voltage and gain to verify brownout detection."""
import time
import sys
import niscope
from brownout_voltage_sweep import BrownoutVoltageSweep

VOLTAGE = float(sys.argv[1]) if len(sys.argv) > 1 else 3.25
GAIN = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
TRIALS = int(sys.argv[3]) if len(sys.argv) > 3 else 5

print(f"\nTesting serial communication:")
print(f"  Voltage: {VOLTAGE} V")
print(f"  Gain: {GAIN}")
print(f"  Trials: {TRIALS}")
print()

with BrownoutVoltageSweep(fixed_arb_gain=GAIN, dut_serial_timeout_ms=3000) as sweep:
    sweep._smu.voltage_level = VOLTAGE
    time.sleep(0.1)
    
    for trial in range(TRIALS):
        print(f"Trial {trial+1}:")
        sweep._flush_serial()
        
        # Trigger one burst
        with sweep._scope.initiate():
            start = time.time()
            while sweep._scope.acquisition_status() != niscope.AcquisitionStatus.COMPLETE:
                if time.time() - start > 5:
                    print("  ERROR: Scope timeout")
                    sys.exit(1)
                time.sleep(0.005)
        
        # Now read ALL serial data for 3 seconds and show it
        print("  Reading serial for 3s...")
        text = ""
        deadline = time.time() + 3.0
        while time.time() < deadline:
            try:
                chunk = sweep._dut_serial.read_raw().decode("ascii", errors="replace")
                text += chunk
                if chunk:
                    print(f"    Got {len(chunk)} chars")
            except Exception:
                pass
        
        print(f"  Total serial data: {len(text)} characters")
        if "Brownout detector was triggered" in text:
            print("  ✓ BROWNOUT DETECTED")
        else:
            print("  - No brownout")
        
        if text:
            print(f"  First 200 chars: {repr(text[:200])}")
        else:
            print("  (no serial data received)")
        print()
        
        time.sleep(0.2)

print("\nSerial communication test complete.")
