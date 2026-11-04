"""
Diagnostic: open each instrument one at a time and report exactly what fails.

The addresses tested here are read from the BrownoutSweep constructor defaults, so
this validates the same configuration the real sweep will use. Run it after any
hardware or NI MAX change, and before a live demo.

Output is plain ASCII so it works in the default Windows console code page (cp1252).

If every instrument fails with timeouts or access violations, check that
"Using Breakpoints in C/C++/.NET Applications" is cleared in InstrumentStudio's
Configure Debug Session window. That setting routes driver calls through a separate
server process and is incompatible with the Python bindings.
"""

import sys

import nidcpower
import nifgen
import niscope
import pyvisa

from brownout_sweep import BrownoutSweep


def banner(text):
    print()
    print("=" * 78)
    print(text)
    print("=" * 78)


def check(label, resource, opener):
    """Attempt to open one instrument. Returns True on success."""
    print(f"  {label:<12} {resource:<18} ", end="", flush=True)
    try:
        info = opener(resource)
        print("OK   " + "  ".join(f"{k}={v}" for k, v in info.items()))
        return True
    except Exception as e:
        # Driver errors run to many lines; the first line carries the useful part.
        text = str(e).strip()
        first = text.splitlines()[0] if text else repr(e)
        print(f"FAIL {first}")
        return False


def open_scope(resource):
    with niscope.Session(resource_name=resource) as s:
        return {"model": s.instrument_model, "channels": s.channel_count}


def open_fgen(resource):
    with nifgen.Session(resource_name=resource) as s:
        return {"model": s.instrument_model, "channels": s.channel_count}


def open_smu(resource):
    with nidcpower.Session(resource_name=resource) as s:
        return {"model": s.instrument_model, "channels": s.channel_count}


def open_dut(resource):
    rm = pyvisa.ResourceManager()
    try:
        dut = rm.open_resource(resource, baud_rate=115200,
                               read_termination="\n", write_termination="\n")
        dut.close()
        return {"serial": "opened"}
    finally:
        rm.close()


def main():
    station = BrownoutSweep()

    banner("VISA resources visible to this system")
    rm = pyvisa.ResourceManager()
    try:
        for r in rm.list_resources():
            print(f"  {r}")
    finally:
        rm.close()

    banner("Opening each configured instrument")
    print(f"  {'Driver':<12} {'Resource':<18} Result")
    print("  " + "-" * 74)
    results = [
        check("NI-SCOPE", station.scope_resource, open_scope),
        check("NI-FGEN", station.fgen_resource, open_fgen),
        check("NI-DCPower", station.smu_resource, open_smu),
        check("DUT serial", station.dut_visa_resource, open_dut),
    ]

    banner("Summary")
    if all(results):
        print("  All instruments opened. brownout_sweep.py is ready to run.")
        return 0
    print(f"  {results.count(False)} of {len(results)} instruments failed.")
    print("  Fix the FAIL rows above before running brownout_sweep.py.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
