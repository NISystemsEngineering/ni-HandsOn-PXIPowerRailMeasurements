"""Basic COM5 connectivity test - just open it and listen for any data."""
import pyvisa
import time

print("Testing COM5 basic connectivity...")
print()

try:
    rm = pyvisa.ResourceManager()
    print("VISA resources found:")
    for resource in rm.list_resources():
        print(f"  {resource}")
    print()
    
    if "ASRL5::INSTR" not in rm.list_resources():
        print("ERROR: ASRL5::INSTR not found!")
        print("Available serial ports:")
        for r in rm.list_resources():
            if "ASRL" in r:
                print(f"  {r}")
        exit(1)
    
    print("Opening ASRL5::INSTR (COM5)...")
    ser = rm.open_resource("ASRL5::INSTR",
                           baud_rate=115200,
                           read_termination='\n',
                           timeout=5000)
    print("OK: COM5 opened successfully")
    print()
    
    print("Listening for 10 seconds (any baud rate mismatch will show as garbage)...")
    print("Press Ctrl+C to stop early")
    print()
    
    deadline = time.time() + 10.0
    got_data = False
    while time.time() < deadline:
        try:
            data = ser.read_raw()
            if data:
                got_data = True
                text = data.decode('ascii', errors='replace')
                print(f"[{time.time():.1f}] Received {len(data)} bytes:")
                print(f"  Raw: {data[:100]}")
                print(f"  Text: {repr(text[:100])}")
                print()
        except Exception as e:
            # Timeout is expected if no data
            if "Timeout" not in str(e):
                print(f"Error: {e}")
            time.sleep(0.1)
    
    if not got_data:
        print("WARNING: No data received in 10 seconds")
        print()
        print("Possible causes:")
        print("  1. DUT not powered or not running")
        print("  2. Wrong COM port (check Device Manager)")
        print("  3. DUT firmware not configured to output to UART")
        print("  4. Baud rate mismatch (should be 115200)")
    
    ser.close()
    rm.close()
    
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()
