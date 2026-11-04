"""
TestStand Integration Example for Brownout Sweep

This file shows how to call the BrownoutSweep module from NI TestStand using
the Python Adapter. It demonstrates the three-step pattern (Setup/Main/Cleanup)
that maps to TestStand's execution model.

In TestStand, you would typically create three Python steps:
1. Setup Step: Calls teststand_setup()
2. Main Step: Calls teststand_run_sweep()
3. Cleanup Step: Calls teststand_teardown()

The sweep object is stored in TestStand's Locals or FileGlobals container so
it persists across steps.
"""

from typing import Optional

from brownout_sweep import BrownoutSweep

# Global to hold the sweep object between TestStand steps
# In TestStand, you'd use Locals.BrownoutSweep or FileGlobals.BrownoutSweep instead
_sweep_instance = None


def teststand_setup(
    scope_resource: Optional[str] = None,
    fgen_resource: Optional[str] = None,
    smu_resource: Optional[str] = None,
    dut_visa_resource: Optional[str] = None,
    supply_voltage: Optional[float] = None,
    supply_current_limit: Optional[float] = None,
) -> dict:
    """
    TestStand Setup Step: Initialize instruments.
    
    In TestStand:
    - Module: teststand_example.py
    - Function: teststand_setup
    - Parameters: Pass from TestStand Locals/FileGlobals
    - Return: Store in Locals.SetupStatus (dict with 'success' and 'message' keys)
    
    Every argument is optional. Anything left as None falls back to the
    BrownoutSweep constructor default, which is the single source of truth for this
    station's addresses -- so defaults are never duplicated here and cannot drift
    out of sync with the class.
    
    Args:
        scope_resource: NI-SCOPE resource name
        fgen_resource: NI-FGEN resource name
        smu_resource: NI-DCPower SMU resource name with channel
        dut_visa_resource: DUT UART VISA resource
        supply_voltage: DUT supply voltage (V)
        supply_current_limit: SMU current limit (A)
    
    Returns:
        Dict with 'success' (bool) and 'message' (str) keys
    """
    global _sweep_instance
    
    try:
        # Forward only the arguments TestStand actually supplied; the rest keep the
        # class defaults.
        overrides = {
            "scope_resource": scope_resource,
            "fgen_resource": fgen_resource,
            "smu_resource": smu_resource,
            "dut_visa_resource": dut_visa_resource,
            "supply_voltage": supply_voltage,
            "supply_current_limit": supply_current_limit,
        }
        _sweep_instance = BrownoutSweep(
            **{k: v for k, v in overrides.items() if v is not None}
        )
        _sweep_instance.setup()
        
        return {
            'success': True,
            'message': 'Instruments initialized successfully'
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Setup failed: {str(e)}'
        }


def teststand_run_sweep(
    gain_start: float,
    gain_stop: float,
    gain_step: float,
    trials_per_gain: int,
    scope_timeout_s: float = 10.0,
) -> dict:
    """
    TestStand Main Step: Run brownout sweep.
    
    In TestStand:
    - Module: teststand_example.py
    - Function: teststand_run_sweep
    - Parameters: Pass from TestStand Locals
    - Return: Store in Locals.SweepResults
    
    Args:
        gain_start: First arb gain, must be > 0
        gain_stop: Last arb gain
        gain_step: Gain increment
        trials_per_gain: Number of trials per gain
        scope_timeout_s: Scope trigger timeout (seconds)
    
    Returns:
        Dict with:
        - 'success' (bool): Whether sweep completed
        - 'message' (str): Status message
        - 'results' (list): List of dicts, one per gain, each with:
            - 'gain' (float): Arb gain
            - 'total_trials' (int): Number of trials
            - 'tripped_count' (int): Number of trips
            - 'trip_fraction' (float): Trip probability (0.0-1.0)
            - 'mean_ripple_vpp' / 'mean_ripple_vrms' / 'mean_ripple_dbv' (float):
              ripple actually measured at the rail, since the coupling network
              makes commanded gain an unreliable stand-in for amplitude
            - 'mean_rail_min' (float): Mean lowest rail voltage seen (V)
            - 'trials' (list): Per-trial dicts with the same measurement fields
    """
    global _sweep_instance
    
    if _sweep_instance is None:
        return {
            'success': False,
            'message': 'Setup not called or failed',
            'results': []
        }
    
    try:
        # Run the sweep
        results = _sweep_instance.run_sweep(
            gain_start=gain_start,
            gain_stop=gain_stop,
            gain_step=gain_step,
            trials_per_gain=trials_per_gain,
            scope_timeout_s=scope_timeout_s,
        )
        
        # Convert dataclasses to dicts for TestStand
        results_dicts = []
        for gain_result in results:
            results_dicts.append({
                'gain': gain_result.gain,
                'total_trials': gain_result.total_trials,
                'tripped_count': gain_result.tripped_count,
                'trip_fraction': gain_result.trip_fraction,
                'mean_ripple_vpp': gain_result.mean_ripple_vpp,
                'mean_ripple_vrms': gain_result.mean_ripple_vrms,
                'mean_ripple_dbv': gain_result.mean_ripple_dbv,
                'mean_rail_min': gain_result.mean_rail_min,
                'trials': [
                    {
                        'gain': t.gain,
                        'trial_index': t.trial_index,
                        'tripped': t.tripped,
                        'timestamp': t.timestamp.isoformat(),
                        'ripple_vpp': t.ripple_vpp,
                        'ripple_vrms': t.ripple_vrms,
                        'ripple_dbv': t.ripple_dbv,
                        'rail_min': t.rail_min,
                        'rail_max': t.rail_max,
                    }
                    for t in gain_result.trials
                ]
            })
        
        return {
            'success': True,
            'message': f'Sweep completed: {len(results)} gains tested',
            'results': results_dicts
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Sweep failed: {str(e)}',
            'results': []
        }


def teststand_teardown() -> dict:
    """
    TestStand Cleanup Step: Close instrument sessions.
    
    In TestStand:
    - Module: teststand_example.py
    - Function: teststand_teardown
    - Parameters: None
    - Return: Store in Locals.TeardownStatus (dict with 'success' and 'message' keys)
    
    Returns:
        Dict with 'success' (bool) and 'message' (str) keys
    """
    global _sweep_instance
    
    if _sweep_instance is None:
        return {
            'success': True,
            'message': 'No sweep instance to clean up'
        }
    
    try:
        _sweep_instance.teardown()
        _sweep_instance = None
        
        return {
            'success': True,
            'message': 'Instruments closed successfully'
        }
        
    except Exception as e:
        return {
            'success': False,
            'message': f'Teardown warning: {str(e)}'
        }


# ============================================================================
# Example: Standalone Test of TestStand Functions
# ============================================================================

def test_teststand_workflow():
    """
    Test the TestStand workflow functions locally (without TestStand).
    
    This demonstrates how the three functions work together and validates
    that they return the expected data structures.
    """
    print("Testing TestStand workflow functions...")
    print()
    
    # Step 1: Setup
    # Called with no arguments so it uses the station defaults from BrownoutSweep.
    # A real TestStand sequence would pass values in from Locals/FileGlobals.
    print("1. Setup")
    setup_result = teststand_setup()
    print(f"   Success: {setup_result['success']}")
    print(f"   Message: {setup_result['message']}")
    print()
    
    if not setup_result['success']:
        print("Setup failed, aborting test")
        return
    
    # Step 2: Run Sweep
    print("2. Run Sweep")
    sweep_result = teststand_run_sweep(
        gain_start=3.0,
        gain_stop=5.0,  # Short sweep for testing
        gain_step=1.0,
        trials_per_gain=5,  # Few trials for testing
    )
    print(f"   Success: {sweep_result['success']}")
    print(f"   Message: {sweep_result['message']}")
    print(f"   Results: {len(sweep_result['results'])} gains tested")
    print()
    
    if sweep_result['success']:
        # Print summary
        print("   Summary:")
        for result in sweep_result['results']:
            print(f"     gain {result['gain']:.2f} "
                  f"({result['mean_ripple_dbv']:.2f} dBV, "
                  f"{result['mean_ripple_vpp']*1e3:.1f} mVpp): "
                  f"{result['trip_fraction']:.1%} trip rate "
                  f"({result['tripped_count']}/{result['total_trials']})")
        print()
    
    # Step 3: Teardown
    print("3. Teardown")
    teardown_result = teststand_teardown()
    print(f"   Success: {teardown_result['success']}")
    print(f"   Message: {teardown_result['message']}")
    print()
    
    print("TestStand workflow test complete!")


if __name__ == "__main__":
    test_teststand_workflow()
