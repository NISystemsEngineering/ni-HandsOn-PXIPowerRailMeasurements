"""
Verify the TRIG_SMB -> PXI_Trig0 backplane route can be created from Python.

This replaces the LabVIEW DAQmx Connect Terminals VI. The route must be live while
the scope is armed; the LabVIEW version tore it down on Panel Close, which leaves
PXI_Trig0 undriven and makes the scope time out.
"""

import nidaqmx
from nidaqmx.system import System

SOURCE = "/CharlieKnapp-8881/TRIG_SMB"
DEST = "/CharlieKnapp-8881/PXI_Trig0"

if __name__ == "__main__":
    system = System.local()

    print()
    print("DAQmx devices visible:")
    for dev in system.devices:
        print(f"  {dev.name:<24} {dev.product_type}")

    print()
    print(f"Connecting {SOURCE}  ->  {DEST}")
    try:
        system.connect_terms(
            source_terminal=SOURCE,
            destination_terminal=DEST,
        )
        print("  route created OK")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e).strip().splitlines()[0]}")
        raise

    print()
    print("Disconnecting route")
    try:
        system.disconnect_terms(
            source_terminal=SOURCE,
            destination_terminal=DEST,
        )
        print("  route removed OK")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e).strip().splitlines()[0]}")
        raise

    print()
    print("Route can be managed from Python. Safe to move this into setup()/teardown().")
