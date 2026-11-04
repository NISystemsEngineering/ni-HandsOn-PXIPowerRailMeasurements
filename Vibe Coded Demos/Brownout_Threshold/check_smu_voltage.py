"""Check what voltage the SMU is actually delivering and compare to set point."""
import nidcpower
import time
import sys

SMU_RESOURCE = "4147_SMU/0"
TEST_VOLTAGE = float(sys.argv[1]) if len(sys.argv) > 1 else 3.40

print(f"\nChecking SMU voltage delivery at set point {TEST_VOLTAGE} V")
print(f"SMU Resource: {SMU_RESOURCE}")
print()

try:
    with nidcpower.Session(SMU_RESOURCE) as smu:
        print("Configuring SMU...")
        smu.source_mode = nidcpower.SourceMode.SINGLE_POINT
        smu.output_function = nidcpower.OutputFunction.DC_VOLTAGE
        smu.voltage_level_range = 6.0
        smu.voltage_level = TEST_VOLTAGE
        smu.current_limit = 0.5
        smu.current_limit_range = 0.5
        
        # Enable remote sense
        smu.sense = nidcpower.Sense.REMOTE
        print(f"  Remote sense: {smu.sense}")
        
        print(f"  Set voltage: {TEST_VOLTAGE} V")
        print(f"  Current limit: {smu.current_limit} A")
        print()
        
        print("Enabling output...")
        smu.initiate()
        time.sleep(0.5)
        
        print("\nMeasuring actual voltage and current...")
        voltage = smu.measure(nidcpower.MeasurementTypes.VOLTAGE)
        current = smu.measure(nidcpower.MeasurementTypes.CURRENT)
        
        print(f"\nResults:")
        print(f"  Voltage set point: {TEST_VOLTAGE:.4f} V")
        print(f"  Voltage measured:  {voltage:.4f} V")
        print(f"  Current measured:  {current*1000:.2f} mA")
        
        error = voltage - TEST_VOLTAGE
        print(f"\n  Voltage error: {error*1000:.2f} mV")
        
        if abs(error) > 0.050:
            print(f"\n  WARNING: Large voltage error! Check:")
            print(f"    - Remote sense connections")
            print(f"    - Cable resistance")
            print(f"    - Current compliance limit")
        
        if voltage < 3.0:
            print(f"\n  WARNING: Voltage < 3.0V - ESP32-C6 may not boot!")
            print(f"    ESP32-C6 typical min voltage: 3.0V")
            print(f"    Brownout detector threshold: 3.27V")
        elif voltage < 3.27:
            print(f"\n  NOTE: Voltage < 3.27V - below brownout detector")
            print(f"    DUT will likely be in continuous reset")
        
        time.sleep(0.5)
        
        print("\nDisabling output...")
        smu.abort()
        
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\nDone.")
