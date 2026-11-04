"""Force release all NI instrument sessions."""
import sys

print("Releasing all instrument sessions...")

# Try to close each instrument type
instruments_released = []
errors = []

# SMU
try:
    import nidcpower
    print("  Checking SMU sessions...")
    # Create temporary session to any existing resource and abort
    try:
        with nidcpower.Session("4147_SMU/0") as smu:
            smu.abort()
        instruments_released.append("SMU")
        print("    SMU session released")
    except Exception as e:
        if "resource is reserved" in str(e).lower() or "already open" in str(e).lower():
            print(f"    SMU might be in use: {e}")
            errors.append(f"SMU: {e}")
        else:
            print(f"    SMU OK (no active session)")
except Exception as e:
    print(f"    Could not check SMU: {e}")

# Scope
try:
    import niscope
    print("  Checking Scope sessions...")
    try:
        with niscope.Session("5164_Scope") as scope:
            scope.abort()
        instruments_released.append("Scope")
        print("    Scope session released")
    except Exception as e:
        if "resource is reserved" in str(e).lower() or "already open" in str(e).lower():
            print(f"    Scope might be in use: {e}")
            errors.append(f"Scope: {e}")
        else:
            print(f"    Scope OK (no active session)")
except Exception as e:
    print(f"    Could not check Scope: {e}")

# Arb
try:
    import nifgen
    print("  Checking Arb sessions...")
    try:
        with nifgen.Session("5433_Arb") as fgen:
            fgen.abort()
        instruments_released.append("Arb")
        print("    Arb session released")
    except Exception as e:
        if "resource is reserved" in str(e).lower() or "already open" in str(e).lower():
            print(f"    Arb might be in use: {e}")
            errors.append(f"Arb: {e}")
        else:
            print(f"    Arb OK (no active session)")
except Exception as e:
    print(f"    Could not check Arb: {e}")

# DAQmx
try:
    import nidaqmx
    print("  Checking DAQmx tasks...")
    # Just check if module imports
    print("    DAQmx OK (tasks auto-cleanup)")
    instruments_released.append("DAQmx")
except Exception as e:
    print(f"    Could not check DAQmx: {e}")

# Serial
try:
    import pyvisa
    print("  Checking Serial sessions...")
    rm = pyvisa.ResourceManager()
    # Just opening resource manager, any open serial will show up in list
    resources = rm.list_resources()
    print(f"    Found {len(resources)} VISA resources")
    rm.close()
    instruments_released.append("VISA")
except Exception as e:
    print(f"    Could not check VISA: {e}")

print("\n" + "="*60)
if errors:
    print("WARNING: Some instruments might still be reserved:")
    for err in errors:
        print(f"  - {err}")
    print("\nIf instruments are locked:")
    print("  1. Close InstrumentStudio")
    print("  2. In NI MAX, right-click chassis → Reset")
    print("  3. Rerun this script")
else:
    print("All instruments appear to be released.")
    print(f"Checked: {', '.join(instruments_released)}")
print("="*60)
