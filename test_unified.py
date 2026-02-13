"""Integration test for the unified device scanner pipeline."""
from GUI.device_scanner import scan_for_ipods
import logging
logging.basicConfig(level=logging.DEBUG)


results = scan_for_ipods()
if not results:
    print("NO IPODS FOUND")
else:
    for ipod in results:
        pid = hex(ipod.usb_pid) if ipod.usb_pid else "None"
        guid = ipod.firewire_guid or "None"
        gb = bytes.fromhex(guid) if guid != "None" else None
        hash_ready = "YES" if gb and len(gb) == 8 else "NO"
        missing = "MISSING"

        print()
        print("=" * 50)
        print(f"Display:      {ipod.display_name}")
        print(f"Model #:      {ipod.model_number or 'unknown'}")
        print(f"Serial:       {ipod.serial}")
        print(f"USB PID:      {pid}")
        print(f"FW GUID:      {guid}")
        print(f"Firmware:     {ipod.firmware}")
        print(f"Method:       {ipod.identification_method}")
        print(f"Hash scheme:  {ipod.hashing_scheme}")
        print(f"Disk:         {ipod.disk_size_gb:.1f} GB ({ipod.free_space_gb:.1f} GB free)")
        gb_str = gb.hex() if gb else missing
        gb_len = len(gb) if gb else 0
        print(f"GUID bytes:   {gb_str} ({gb_len} bytes)")
        print(f"HASH58 ready: {hash_ready}")
        print("=" * 50)

    # Also test get_firewire_id with the pre-discovered GUID
    print()
    print("--- Testing get_firewire_id() ---")
    from iTunesDB_Writer.device import get_firewire_id

    ipod = results[0]

    # Test 1: With pre-discovered GUID (should skip all probing)
    fwid = get_firewire_id(ipod.path, known_guid=ipod.firewire_guid)
    print(f"get_firewire_id(known_guid): {fwid.hex()} ({len(fwid)} bytes)")

    # Test 2: Without pre-discovered GUID (should use device tree)
    fwid2 = get_firewire_id(ipod.path)
    print(f"get_firewire_id(probing):    {fwid2.hex()} ({len(fwid2)} bytes)")

    assert fwid == fwid2, "GUID mismatch!"
    print("GUIDs match!")
