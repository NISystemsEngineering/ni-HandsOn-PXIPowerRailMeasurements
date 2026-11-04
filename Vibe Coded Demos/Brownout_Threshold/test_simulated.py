"""
Open all three modular-instrument sessions in SIMULATION mode.

If these pass while the same calls fail against real hardware, the Python code
and driver installation are both fine, and the failure is in the driver's
debug-session remoting layer (see nimi-python issue #906).
"""

import niscope
import nifgen
import nidcpower


def check(label, fn):
    print(f"  {label:<12} ", end="", flush=True)
    try:
        info = fn()
        print("OK   " + "  ".join(f"{k}={v}" for k, v in info.items()))
        return True
    except Exception as e:
        first = str(e).strip().splitlines()[0] if str(e).strip() else repr(e)
        print(f"FAIL {type(e).__name__}: {first}")
        return False


def scope():
    opts = "Simulate=1, DriverSetup=Model:5164; BoardType:PXIe"
    with niscope.Session(resource_name="sim_scope", options=opts) as s:
        s.channels["0"].configure_vertical(
            range=10.0, coupling=niscope.VerticalCoupling.DC, probe_attenuation=1.0
        )
        s.configure_horizontal_timing(
            min_sample_rate=1_000_000, min_num_pts=10_000,
            ref_position=10.0, num_records=1, enforce_realtime=True,
        )
        # The real reason we care: confirm the digital trigger call is valid.
        s.configure_trigger_digital(
            trigger_source="PXI_Trig0",
            slope=niscope.TriggerSlope.POSITIVE,
            holdoff=0.0, delay=0.0,
        )
        return {"model": s.instrument_model, "channels": s.channel_count}


def fgen():
    # NI-FGEN cannot simulate the PXIe-5433; this driver only offers 5421/5450/5451.
    # The 5451 is used as a stand-in so the sweep logic can be rehearsed offline.
    opts = "Simulate=1, DriverSetup=Model:5451; BoardType:PXIe"
    with nifgen.Session(resource_name="sim_fgen", options=opts) as s:
        s.output_mode = nifgen.OutputMode.FUNC
        s.configure_standard_waveform(
            waveform=nifgen.Waveform.SINE, amplitude=0.5,
            frequency=7000.0, dc_offset=0.0, start_phase=0.0,
        )
        return {"model": s.instrument_model, "channels": s.channel_count}


def smu():
    opts = "Simulate=1, DriverSetup=Model:4147; BoardType:PXIe"
    with nidcpower.Session(resource_name="sim_smu", options=opts) as s:
        s.source_mode = nidcpower.SourceMode.SINGLE_POINT
        s.output_function = nidcpower.OutputFunction.DC_VOLTAGE
        s.sense = nidcpower.Sense.REMOTE
        s.voltage_level = 3.3
        s.current_limit = 0.5
        return {"model": s.instrument_model, "channels": s.channel_count}


if __name__ == "__main__":
    print()
    print("Simulated session test")
    print("-" * 72)
    results = [
        check("NI-SCOPE", scope),
        check("NI-FGEN", fgen),
        check("NI-DCPower", smu),
    ]
    print("-" * 72)
    if all(results):
        print("All simulated sessions opened and configured successfully.")
        print("The Python code and driver install are correct.")
    else:
        print("A simulated session failed -- that would indicate a code or install problem.")
