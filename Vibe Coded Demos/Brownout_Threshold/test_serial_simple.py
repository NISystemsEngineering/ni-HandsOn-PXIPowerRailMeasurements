"""Simple serial monitoring test without scope - just power DUT and listen."""
import pyvisa
import nidcpower
import time
import sys

SMU_RESOURCE = "4147_SMU/0"
SERIAL_RESOURCE = "ASRL5::INSTR"
VOLTAGE = float(sys.argv[1]) if len(sys.argv) > 1 else 3.40
LISTEN_TIME = int(sys.argv[2]) if len(sys.argv) > 2 else 15

print(f"\nSimple Serial Monitor Test")
print(f"  Voltage: {VOLTAGE} V")
print(f"  Listen time: {LISTEN_TIME} seconds")
print()

try:
    # Initialize SMU
    print("Setting up SMU...")
    smu = nidcpower.Session(SMU_RESOURCE)
    smu.source_mode = nidcpower.SourceMode.SINGLE_POINT
    smu.output_function = nidcpower.OutputFunction.DC_VOLTAGE
    smu.sense = nidcpower.Sense.REMOTE
    smu.voltage_level = VOLTAGE
    smu.current_limit = 0.5
    smu.voltage_level_range = 6.0
    smu.current_limit_range = 0.5
    smu.transient_response = nidcpower.TransientResponse.NORMAL
    
    print(f"Enabling SMU output at {VOLTAGE} V...")
    smu.initiate()
    time.sleep(1.0)
    
    voltage = smu.measure(nidcpower.MeasurementTypes.VOLTAGE)
    current = smu.measure(nidcpower.MeasurementTypes.CURRENT)
    print(f"  Measured: {voltage:.4f} V, {current*1000:.2f} mA")
    print()
    
    # Open serial
    print(f"Opening {SERIAL_RESOURCE}...")
    rm = pyvisa.ResourceManager()
    ser = rm.open_resource(SERIAL_RESOURCE,
                          baud_rate=115200,
                          read_termination='\n',
                          timeout=1000)
    print("  OK")
    print()
    
    print(f"Listening for {LISTEN_TIME} seconds...")
    print("=" * 70)
    
    start = time.time()
    total_chars = 0
    brownout_count = 0
    
    while time.time() - start < LISTEN_TIME:
        try:
            data = ser.read_raw()
            if data:
                text = data.decode('ascii', errors='replace')
                total_chars += len(text)
                
                # Print each line
                for line in text.splitlines():
                    if line.strip():
                        elapsed = time.time() - start
                        print(f"[{elapsed:6.2f}s] {line}")
                        
                        if "Brownout detector was triggered" in line:
                            brownout_count += 1
                            print("           ^^^ BROWNOUT DETECTED ^^^")
        except Exception as e:
            if "Timeout" not in str(e):
                print(f"Error: {e}")
            time.sleep(0.01)
    
    print("=" * 70)
    print()
    print(f"Summary:")
    print(f"  Total characters received: {total_chars}")
    print(f"  Brownout detections: {brownout_count}")
    print(f"  Voltage: {VOLTAGE} V")
    
    if total_chars == 0:
        print()
        print("  WARNING: No serial data received!")
        print("  Possible causes:")
        print("    - DUT firmware not running")
        print("    - UART not configured in firmware")
        print("    - Wrong COM port")
    
    # Clean up
    ser.close()
    rm.close()
    smu.abort()
    smu.close()
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

print("\nDone.")
