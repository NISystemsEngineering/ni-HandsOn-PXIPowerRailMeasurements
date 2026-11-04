"""Verify DAQmx trigger routing and instrument status."""
import nidaqmx
import nifgen
import niscope

print("\n" + "="*70)
print("TRIGGER ROUTING & INSTRUMENT STATUS CHECK")
print("="*70)

# Check DAQmx trigger route
print("\n1. Checking DAQmx trigger route...")
try:
    system = nidaqmx.system.System.local()
    
    # Try to query the route (this will fail if not connected)
    print("   Attempting to connect trigger route:")
    print("   /CharlieKnapp-8881/TRIG_SMB -> /CharlieKnapp-8881/PXI_Trig0")
    
    try:
        system.disconnect_terms(
            "/CharlieKnapp-8881/TRIG_SMB",
            "/CharlieKnapp-8881/PXI_Trig0"
        )
        print("   (Disconnected existing route)")
    except:
        pass
    
    system.connect_terms(
        source_terminal="/CharlieKnapp-8881/TRIG_SMB",
        destination_terminal="/CharlieKnapp-8881/PXI_Trig0"
    )
    print("   OK: Trigger route connected")
    
except Exception as e:
    print(f"   ERROR: {e}")

# Check Arb status
print("\n2. Checking Arb (5433_Arb) status...")
try:
    with nifgen.Session("5433_Arb") as fgen:
        print(f"   Output mode: {fgen.output_mode}")
        print(f"   Trigger mode: {fgen.trigger_mode}")
        print(f"   Sample rate: {fgen.arb_sample_rate / 1e6:.1f} MHz")
        print(f"   Output enabled: {fgen.output_enabled}")
        
        if fgen.output_mode != nifgen.OutputMode.ARB:
            print("   WARNING: Not in ARB mode!")
        if fgen.trigger_mode != nifgen.TriggerMode.BURST:
            print("   WARNING: Not in BURST trigger mode!")
            
except Exception as e:
    print(f"   ERROR: {e}")

# Check Scope status
print("\n3. Checking Scope (5164_Scope) status...")
try:
    with niscope.Session("5164_Scope") as scope:
        print(f"   Trigger type: {scope.trigger_type}")
        print(f"   Trigger source: {scope.trigger_source}")
        
        if "PXI_Trig0" not in str(scope.trigger_source):
            print("   WARNING: Not triggering on PXI_Trig0!")
            
except Exception as e:
    print(f"   ERROR: {e}")

print("\n" + "="*70)
print("RECOMMENDATIONS:")
print("="*70)
print("If issues found:")
print("  1. Rerun brownout_voltage_sweep.py to reconfigure instruments")
print("  2. Check that DUT GPIO10 is physically connected to TRIG_SMB")
print("  3. Verify DUT is transmitting BLE (scope should show bursts)")
print("="*70 + "\n")
