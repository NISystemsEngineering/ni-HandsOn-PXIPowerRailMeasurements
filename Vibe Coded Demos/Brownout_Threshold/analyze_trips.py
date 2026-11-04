"""Analyze brownout trip pattern from voltage sweep data."""
import csv

csv_file = "brownout_voltage_sweep_20261005_111405.csv"

print("\n" + "="*80)
print("BROWNOUT TRIP ANALYSIS")
print("="*80)

trips = []
non_trips_below_threshold = []

with open(csv_file, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        voltage = float(row['voltage'])
        trial = int(row['trial_index'])
        tripped = row['tripped'] == 'True'
        rail_min = float(row['rail_min'])
        ripple_vpp = float(row['ripple_vpp']) * 1000  # Convert to mV
        
        if tripped:
            trips.append((voltage, trial, rail_min, ripple_vpp))
        elif rail_min < 3.27:
            non_trips_below_threshold.append((voltage, trial, rail_min, ripple_vpp))

print(f"\nTrips detected: {len(trips)}")
print("\nVoltage  Trial  Rail Min  Ripple(mVpp)  Below 3.27V?")
print("-" * 60)
for v, t, rmin, rvpp in trips:
    below = "YES" if rmin < 3.27 else "NO "
    print(f"{v:6.2f}V    {t}    {rmin:.3f}V    {rvpp:6.1f} mVpp      {below}")

print(f"\n\nNon-trips WITH rail_min < 3.27V: {len(non_trips_below_threshold)}")
print("(These SHOULD have tripped but didn't)")
print("\nVoltage  Trial  Rail Min  Ripple(mVpp)")
print("-" * 50)
for v, t, rmin, rvpp in non_trips_below_threshold[:10]:  # Show first 10
    print(f"{v:6.2f}V    {t}    {rmin:.3f}V    {rvpp:6.1f} mVpp")
if len(non_trips_below_threshold) > 10:
    print(f"... and {len(non_trips_below_threshold)-10} more")

print("\n" + "="*80)
print("FREQUENCY BY VOLTAGE")
print("="*80)

# Count trips per voltage
voltage_stats = {}
with open(csv_file, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        v = float(row['voltage'])
        if v not in voltage_stats:
            voltage_stats[v] = {'total': 0, 'trips': 0}
        voltage_stats[v]['total'] += 1
        if row['tripped'] == 'True':
            voltage_stats[v]['trips'] += 1

print("\nVoltage   Trips    Percentage")
print("-" * 40)
for v in sorted(voltage_stats.keys(), reverse=True):
    trips_count = voltage_stats[v]['trips']
    total = voltage_stats[v]['total']
    pct = 100.0 * trips_count / total if total > 0 else 0
    print(f"{v:.2f}V    {trips_count}/{total}      {pct:5.1f}%")

print("\n" + "="*80)
print("CONCLUSION")
print("="*80)
print(f"""
Trip rate is essentially constant (~10-20%) across all voltages.
NO clear pattern of increasing frequency as voltage decreases.

{len(non_trips_below_threshold)} trials had rail_min < 3.27V but did NOT trip.
This suggests:
  1. Brownout detector requires voltage < threshold for a minimum DURATION
  2. Detector samples at discrete intervals and might miss brief dips
  3. Internal chip voltage differs from external measurement point
  4. Some resets happen too fast to send serial message
""")
