"""
Verify that the hash72 in the test database is correct for its content.
"""

from iTunesDB_Writer.hash72 import _compute_itunesdb_sha1, _hash_extract, _hash_generate


TEST_ITDB = r"C:\Users\JohnG\Music\testing\iPod_Control\iTunes\iTunesDB"
CLEAN_ITDB = r"C:\Users\JohnG\Music\cleanipod\iPod_Control\iTunes\iTunesDB"


def verify_hash72(itdb_path: str, label: str):
    """Verify hash72 signature in a database."""
    print(f"\n{'=' * 70}")
    print(f"Verifying hash72 in {label}")
    print('=' * 70)

    with open(itdb_path, 'rb') as f:
        data = bytearray(f.read())

    # Check signature format
    signature = data[0x72:0x72 + 46]
    print(f"\nSignature at 0x72 (first 16 bytes): {signature[:16].hex()}")
    print(f"Signature prefix: 0x{signature[0]:02X} 0x{signature[1]:02X}")

    if signature[0] != 0x01 or signature[1] != 0x00:
        print("ERROR: Invalid signature prefix (expected 0x01 0x00)")
        return False

    # Extract rndpart from signature
    rndpart = signature[2:14]
    encrypted = signature[14:46]
    print(f"rndpart: {rndpart.hex()}")
    print(f"encrypted: {encrypted.hex()}")

    # Compute SHA1 of database with proper fields zeroed
    sha1 = _compute_itunesdb_sha1(data)
    print(f"\nSHA1 of database (with fields zeroed): {sha1.hex()}")

    # Try to extract IV and verify
    result = _hash_extract(bytes(signature), sha1)
    if result is None:
        print("WARNING: Could not extract IV from signature")
        print("This might mean the signature is for different content")
    else:
        iv, extracted_rndpart = result
        print(f"\nExtracted IV: {iv.hex()}")
        print(f"Extracted rndpart: {extracted_rndpart.hex()}")

        # Verify by regenerating
        regenerated = _hash_generate(sha1, iv, rndpart)
        if regenerated == signature:
            print("\n✓ Signature verification PASSED - hash72 is correct!")
            return True
        else:
            print("\n✗ Signature verification FAILED")
            print(f"Expected:    {signature.hex()}")
            print(f"Regenerated: {regenerated.hex()}")
            return False

    return False


def compare_hash_info():
    """Compare hash info between clean and test databases."""
    print("\n" + "=" * 70)
    print("COMPARING HASH INFO")
    print("=" * 70)

    with open(CLEAN_ITDB, 'rb') as f:
        clean_data = bytearray(f.read())

    with open(TEST_ITDB, 'rb') as f:
        test_data = bytearray(f.read())

    # Extract rndpart and IV from clean database
    clean_sig = clean_data[0x72:0x72 + 46]
    clean_sha1 = _compute_itunesdb_sha1(clean_data)
    clean_result = _hash_extract(bytes(clean_sig), clean_sha1)

    test_sig = test_data[0x72:0x72 + 46]
    test_sha1 = _compute_itunesdb_sha1(test_data)
    test_result = _hash_extract(bytes(test_sig), test_sha1)

    print("\nCLEAN database:")
    print(f"  SHA1: {clean_sha1.hex()}")
    if clean_result:
        print(f"  IV: {clean_result[0].hex()}")
        print(f"  rndpart: {clean_result[1].hex()}")
    else:
        print("  Could not extract hash info")

    print("\nTEST database:")
    print(f"  SHA1: {test_sha1.hex()}")
    if test_result:
        print(f"  IV: {test_result[0].hex()}")
        print(f"  rndpart: {test_result[1].hex()}")
    else:
        print("  Could not extract hash info")

    # Check if IV and rndpart match
    if clean_result and test_result:
        if clean_result[0] == test_result[0]:
            print("\n✓ IV matches between databases!")
        else:
            print("\n✗ IV DIFFERENT between databases!")
            print("  This is WRONG - IV should be copied from reference!")

        if clean_result[1] == test_result[1]:
            print("✓ rndpart matches between databases!")
        else:
            print("✗ rndpart DIFFERENT between databases")
            print("  This might be okay if we're regenerating")


if __name__ == "__main__":
    # Verify clean database
    verify_hash72(CLEAN_ITDB, "CLEAN")

    # Verify test database
    verify_hash72(TEST_ITDB, "TEST")

    # Compare hash info
    compare_hash_info()
