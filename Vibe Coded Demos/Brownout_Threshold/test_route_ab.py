"""
A/B proof that the Python-managed trigger route is what makes the scope fire.

Phase A: remove the SMB -> PXI_Trig0 route, then arm the scope. Expect a timeout.
Phase B: create the route from Python, then arm again. Expect a trigger.

Run this with the LabVIEW VI closed OR open -- routes are global to the chassis, so
disconnecting in phase A removes whatever created it. If phase A times out and phase B
triggers, the routing in BrownoutSweep.setup() is doing the work, not the VI.
"""

import time

import nidaqmx
import niscope

from brownout_sweep import BrownoutSweep

POLL_S = 6.0


def arm_and_wait(scope, label):
    """Arm the scope once and report whether a trigger arrived within POLL_S."""
    print(f"  {label:<34} ", end="", flush=True)
    with scope.initiate():
        start = time.time()
        status = scope.acquisition_status()
        while status != niscope.AcquisitionStatus.COMPLETE:
            if time.time() - start > POLL_S:
                print(f"NO TRIGGER  (waited {POLL_S:.0f}s)")
                return False
            time.sleep(0.01)
            status = scope.acquisition_status()
        print(f"TRIGGERED   (after {time.time() - start:.2f}s)")
        return True


if __name__ == "__main__":
    station = BrownoutSweep()
    system = nidaqmx.system.System.local()
    src, dst = station.trigger_route_source, station.trigger_route_dest

    print()
    print(f"route under test: {src}  ->  {dst}")
    print()

    # Configure the scope by hand, matching setup(), so this test controls the route
    # itself rather than having setup() create it.
    with niscope.Session(resource_name=station.scope_resource) as scope:
        scope.channels[station.scope_voltage_channel].configure_vertical(
            range=10.0, coupling=niscope.VerticalCoupling.DC, probe_attenuation=1.0
        )
        scope.configure_horizontal_timing(
            min_sample_rate=1_000_000, min_num_pts=10_000,
            ref_position=10.0, num_records=1, enforce_realtime=True,
        )
        scope.configure_trigger_digital(
            trigger_source=station.scope_trigger_source,
            slope=niscope.TriggerSlope.POSITIVE, holdoff=0.0, delay=0.0,
        )

        # ---- Phase A: no route ----
        print("Phase A -- route removed")
        try:
            system.disconnect_terms(source_terminal=src, destination_terminal=dst)
            print("  route disconnected")
        except Exception as e:
            print(f"  no route to remove ({str(e).strip().splitlines()[0][:50]})")
        a_triggered = arm_and_wait(scope, "scope armed with NO route:")

        # ---- Phase B: route created from Python ----
        print()
        print("Phase B -- route created from Python")
        system.connect_terms(source_terminal=src, destination_terminal=dst)
        print("  route connected")
        b_triggered = arm_and_wait(scope, "scope armed WITH Python route:")

        system.disconnect_terms(source_terminal=src, destination_terminal=dst)

    print()
    if not a_triggered and b_triggered:
        print("PROVEN: the scope only triggers when the route exists, and Python can")
        print("create it. BrownoutSweep.setup() does this, so the LabVIEW VI is no")
        print("longer needed.")
    elif a_triggered and b_triggered:
        print("INCONCLUSIVE: the scope triggered even with no route, so something else")
        print("is still driving PXI_Trig0 -- most likely the LabVIEW VI. Close it and")
        print("re-run to get a clean result.")
    else:
        print("Phase B did not trigger. The DUT may not be pulsing GPIO10 right now.")
