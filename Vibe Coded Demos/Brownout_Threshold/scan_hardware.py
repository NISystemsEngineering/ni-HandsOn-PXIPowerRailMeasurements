"""
Enumerate NI hardware via NI System Configuration.

Prints two lists: devices the config database knows about, and devices actually
reported present. A device that appears only in the first list is configured but
not physically reachable -- which is what makes the instrument drivers return
timeouts and nonsense errors.
"""

import nisyscfg
import nisyscfg.errors


def safe(resource, name, default=""):
    try:
        return str(getattr(resource, name, default) or default)
    except (AttributeError, nisyscfg.errors.LibraryError, Exception):
        return default


def safe_indexed(resource, name, default=""):
    try:
        values = getattr(resource, name)
        if values:
            return str(values[0] or default)
    except Exception:
        pass
    return default


def dump(label, require_present):
    print()
    print("=" * 96)
    print(f"{label}   (is_present filter = {require_present})")
    print("=" * 96)

    with nisyscfg.Session(target="localhost") as session:
        filt = session.create_filter()
        filt.is_ni_product = True
        filt.is_device = True
        if require_present:
            filt.is_present = True

        rows = []
        for r in session.find_hardware(filt):
            product = safe(r, "product_name")
            name = safe(r, "name")
            alias = safe_indexed(r, "expert_user_alias")
            serial = safe(r, "serial_number")
            try:
                slot = str(r.slot_number)
            except Exception:
                slot = ""
            rows.append((slot, alias, product, name, serial))

        print(f"{'Slot':<6} {'Alias':<24} {'Product':<26} {'Name':<16} {'Serial':<12}")
        print("-" * 96)
        for slot, alias, product, name, serial in sorted(rows, key=lambda x: x[0]):
            print(f"{slot:<6} {alias:<24} {product:<26} {name:<16} {serial:<12}")
        print(f"\n  {len(rows)} device(s)")
        return {(r[1] or r[3]) for r in rows}


if __name__ == "__main__":
    configured = dump("ALL CONFIGURED NI DEVICES", require_present=False)
    present = dump("DEVICES REPORTED PRESENT", require_present=True)

    print()
    print("=" * 96)
    print("CONFIGURED BUT NOT PRESENT  (these are your problem devices)")
    print("=" * 96)
    missing = configured - present
    if missing:
        for m in sorted(missing):
            print(f"  {m}")
    else:
        print("  none -- every configured device is physically present")
