"""
Smoke test: open and configure every instrument, then close cleanly.

This exercises BrownoutSweep.setup() and teardown() without running a sweep, so
it verifies wiring and configuration in a couple of seconds instead of the many
minutes a full sweep takes. The SMU does source 3.3V to the DUT briefly, which
is the DUT's normal operating condition.
"""

from brownout_sweep import BrownoutSweep

if __name__ == "__main__":
    print()
    # No resource strings here on purpose -- the constructor defaults are the single
    # source of truth, so this test always exercises the same addresses the real
    # sweep will use.
    print("Opening all instrument sessions ...")
    with BrownoutSweep() as sweep:
        print("  setup() completed -- scope, arb, SMU, and DUT serial all configured.")

        # Prove the arb accepts gains from across the sweep range and can arm at each.
        # Gain can only be changed while generation is stopped, hence the abort first.
        for gain in (0.5, 3.0, 6.0):
            sweep._fgen.abort()
            sweep._fgen.arb_gain = gain
            sweep._fgen.initiate()
            print(f"  arb armed at gain {gain:.2f}")
        sweep._fgen.abort()

    print("  teardown() completed -- all sessions closed.")
    print()
    print("Setup path is good. Ready to run the full sweep.")
