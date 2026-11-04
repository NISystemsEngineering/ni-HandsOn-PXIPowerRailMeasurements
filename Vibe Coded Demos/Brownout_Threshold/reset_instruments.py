"""Reset all instruments to known-good configuration."""
import nidaqmx
import nifgen
import niscope
import nidcpower
import numpy as np

from brownout_voltage_sweep import default_ripple_csv_path

print("\n" + "="*70)
print("RESETTING INSTRUMENTS TO KNOWN-GOOD CONFIGURATION")
print("="*70)

# 1. Reset and configure trigger routing
print("\n1. Configuring DAQmx trigger route...")
try:
    system = nidaqmx.system.System.local()
    try:
        system.disconnect_terms(
            "/CharlieKnapp-8881/TRIG_SMB",
            "/CharlieKnapp-8881/PXI_Trig0"
        )
    except:
        pass
    
    system.connect_terms(
        source_terminal="/CharlieKnapp-8881/TRIG_SMB",
        destination_terminal="/CharlieKnapp-8881/PXI_Trig0"
    )
    print("   OK: /CharlieKnapp-8881/TRIG_SMB -> /CharlieKnapp-8881/PXI_Trig0")
except Exception as e:
    print(f"   ERROR: {e}")
    exit(1)

# 2. Configure Arb
print("\n2. Configuring Arb (5433_Arb)...")
try:
    fgen = nifgen.Session("5433_Arb")
    
    # Load waveform (in-repo path; works wherever the hands-on tree is cloned)
    csv_path = default_ripple_csv_path()
    ripple = np.loadtxt(csv_path)
    print(f"   Loaded {len(ripple)} samples from CSV")
    
    # Configure ARB mode
    fgen.output_mode = nifgen.OutputMode.ARB
    handle = fgen.create_waveform(waveform_data_array=ripple)
    fgen.arb_sample_rate = 10.5e6
    fgen.configure_arb_waveform(waveform_handle=handle, gain=2.0, offset=0.0)
    fgen.output_impedance = 50.0
    
    # Configure BURST trigger
    fgen.trigger_mode = nifgen.TriggerMode.BURST
    fgen.start_trigger_type = nifgen.StartTriggerType.DIGITAL_EDGE
    fgen.digital_edge_start_trigger_source = "PXI_Trig0"
    fgen.digital_edge_start_trigger_edge = nifgen.StartTriggerDigitalEdgeEdge.RISING
    
    # Enable and initiate
    fgen.output_enabled = True
    fgen.initiate()
    
    print(f"   Output mode: {fgen.output_mode}")
    print(f"   Trigger mode: {fgen.trigger_mode}")
    print(f"   Sample rate: {fgen.arb_sample_rate / 1e6:.1f} MHz")
    print(f"   Gain: 2.0")
    print(f"   OK: Arb configured and armed")
    
    # Don't close - leave it armed
    
except Exception as e:
    print(f"   ERROR: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# 3. Configure Scope
print("\n3. Configuring Scope (5164_Scope)...")
try:
    scope = niscope.Session("5164_Scope")
    
    # Configure channels
    channels = "0,1"
    scope.configure_vertical(range=10.0, coupling=niscope.VerticalCoupling.DC)
    scope.channels[channels].configure_chan_characteristics(input_impedance=1e6, max_input_frequency=0)
    
    # Configure timing
    scope.configure_horizontal_timing(
        min_sample_rate=2.0e6,
        min_num_pts=int(3.571e-3 * 1.25 * 2.0e6),
        ref_position=5.0,
        num_records=1,
        enforce_realtime=True
    )
    
    # Configure DIGITAL trigger on PXI_Trig0
    scope.configure_trigger_digital(
        trigger_source="PXI_Trig0",
        slope=niscope.TriggerSlope.POSITIVE,
        holdoff=0.0,
        delay=0.0
    )
    
    print(f"   Trigger type: {scope.trigger_type}")
    print(f"   Trigger source: {scope.trigger_source}")
    print(f"   Sample rate: {scope.horz_sample_rate / 1e6:.1f} MS/s")
    print(f"   OK: Scope configured")
    
    # Don't close - leave it configured
    
except Exception as e:
    print(f"   ERROR: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# 4. Configure SMU
print("\n4. Configuring SMU (4147_SMU/0)...")
try:
    smu = nidcpower.Session("4147_SMU/0")
    smu.source_mode = nidcpower.SourceMode.SINGLE_POINT
    smu.output_function = nidcpower.OutputFunction.DC_VOLTAGE
    smu.sense = nidcpower.Sense.REMOTE
    smu.voltage_level = 3.5
    smu.current_limit = 0.5
    smu.voltage_level_range = 6.0
    smu.current_limit_range = 0.5
    smu.transient_response = nidcpower.TransientResponse.NORMAL
    
    smu.initiate()
    print(f"   Voltage: 3.5V")
    print(f"   Remote sense: {smu.sense}")
    print(f"   OK: SMU configured at 3.5V")
    
    # Don't close - leave it sourcing
    
except Exception as e:
    print(f"   ERROR: {e}")
    exit(1)

print("\n" + "="*70)
print("SUCCESS: All instruments configured and armed")
print("="*70)
print("\nInstruments are ready. Sessions left open.")
print("Run brownout_voltage_sweep.py to perform sweep.")
print("Or close this window to release sessions.")
print("\nPress Ctrl+C to stop and release sessions...")

try:
    import time
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n\nReleasing sessions...")
    try:
        fgen.abort()
        fgen.close()
    except:
        pass
    try:
        scope.abort()
        scope.close()
    except:
        pass
    try:
        smu.abort()
        smu.close()
    except:
        pass
    print("Done.")
