#!/usr/bin/env python3
"""
Cape Unlocker for AC Brotherhood SAV files
==========================================

SUPERSEDED (July 2026) by ../acb_facebookcape_unlocker.py. This version
assumes the cape records live in the 4th frame ("Block 4"), which is only
true for small fresh saves; on played saves (6-16 frames) it reads the wrong
frame. The replacement locates the cape frame by content and validates the
full record structure.

Unlocks the two Facebook-exclusive capes by searching for cape hashes in Block 4
and flipping ownership flags. Optionally changes the player name in Block 1.

Cape structure in Block 4:
  [cape_hash 4B] [8 zeros] [0x0B marker] [ownership_flag 1B] [cape_id 1B] ...

Cape identification:
  Venetian Cape: Hash 0x4470F39F, ID 0x0E
  Medici Cape:   Hash 0xDD79A225, ID 0x11

Ownership flag is at hash_offset + 13, followed by cape_id at hash_offset + 14.

Name structure in Block 1:
  [1A] [00 0B] [length 4B LE] [string bytes]
  Default name is "Desmond" (7 bytes)
"""

import sys
import os
import struct
import argparse

# Import from existing tools
from lzss_decompressor_final import LZSSDecompressor
from lzss_compressor_final import compress_lzss_lazy
from sav_serializer import adler32

# Cape definitions: (hash, expected_id, name)
CAPE_DEFINITIONS = [
    (0x4470F39F, 0x0E, "Venetian Cape"),
    (0xDD79A225, 0x11, "Medici Cape"),
]

# Ownership flag is at hash_offset + 13, cape_id at hash_offset + 14
OWNERSHIP_FLAG_OFFSET = 13
CAPE_ID_OFFSET = 14

# Name string marker pattern in Block 1: [1A] [00 0B] [length 4B] [string]
NAME_MARKER = bytes([0x1A, 0x00, 0x0B])


def find_name_in_block1(data: bytes) -> tuple:
    """
    Find the player name in Block 1.

    Returns (offset, length, name) where offset is the start of the length field.
    Returns (None, None, None) if not found.
    """
    # Search for the name marker pattern
    pos = 0
    while True:
        pos = data.find(NAME_MARKER, pos)
        if pos == -1:
            return None, None, None

        # Length field is after the 3-byte marker
        length_offset = pos + 3
        if length_offset + 4 > len(data):
            pos += 1
            continue

        name_length = struct.unpack('<I', data[length_offset:length_offset + 4])[0]

        # Sanity check - name should be reasonable length
        if 1 <= name_length <= 64:
            name_offset = length_offset + 4
            if name_offset + name_length <= len(data):
                name = data[name_offset:name_offset + name_length].decode('utf-8', errors='replace')
                return length_offset, name_length, name

        pos += 1

    return None, None, None


MAX_NAME_LENGTH = 17  # Game limit


def change_name_in_block1(data: bytearray, new_name: str) -> bytearray:
    """
    Change the player name in Block 1.

    Args:
        data: Block 1 decompressed data
        new_name: New player name (max 17 characters)

    Returns modified Block 1 data.

    Block 1 contains internal size fields at offsets 0x0E and 0x91 that must be
    adjusted when the name length changes. These are cumulative size fields that
    include the name string in their calculation.
    """
    length_offset, old_length, old_name = find_name_in_block1(data)

    if length_offset is None:
        raise ValueError("Could not find name in Block 1")

    new_name_bytes = new_name.encode('utf-8')

    # Enforce max length
    if len(new_name_bytes) > MAX_NAME_LENGTH:
        new_name_bytes = new_name_bytes[:MAX_NAME_LENGTH]
        print(f"WARNING: Name truncated to {MAX_NAME_LENGTH} characters")

    new_length = len(new_name_bytes)
    length_diff = new_length - old_length
    print(f"Name: \"{old_name}\" -> \"{new_name_bytes.decode('utf-8')}\" (length: {old_length} -> {new_length})")

    # Build new Block 1 data with name replaced
    name_offset = length_offset + 4

    result = bytearray()
    result.extend(data[:length_offset])  # Everything before length field
    result.extend(struct.pack('<I', new_length))  # New length
    result.extend(new_name_bytes)  # New name
    result.extend(data[name_offset + old_length:])  # Everything after old name

    # Adjust internal size fields by the length difference
    # These fields are cumulative sizes that include the name string
    # Single-byte size fields
    SIZE_FIELD_OFFSETS_1BYTE = [0x0E, 0x91]
    for offset in SIZE_FIELD_OFFSETS_1BYTE:
        if offset < len(result):
            old_val = result[offset]
            new_val = old_val + length_diff
            if 0 <= new_val <= 255:
                result[offset] = new_val
                print(f"  Size field at 0x{offset:02X}: 0x{old_val:02X} -> 0x{new_val:02X}")

    # 2-byte size field at 0x12
    if 0x14 <= len(result):
        old_val = struct.unpack('<H', result[0x12:0x14])[0]
        new_val = old_val + length_diff
        if 0 <= new_val <= 65535:
            result[0x12:0x14] = struct.pack('<H', new_val)
            print(f"  Size field at 0x12 (2-byte): {old_val} -> {new_val}")

    return result


def parse_sav_blocks(data: bytes) -> dict:
    """
    Parse SAV file and extract all 5 blocks.

    Block 3 has 4 regions with header pattern: [01] [size 3B] [00 00 80 00]
    Region 4's declared size equals Block 4's compressed size.
    """
    total_size = len(data)

    # Block 1: 44-byte header at offset 0, then compressed data
    block1_compressed_size = struct.unpack('<I', data[0x20:0x24])[0]
    block1_compressed = data[0x2C:0x2C + block1_compressed_size]

    # Block 2: 44-byte header immediately after Block 1
    block2_header_offset = 0x2C + block1_compressed_size
    block2_compressed_size = struct.unpack('<I', data[block2_header_offset + 0x20:block2_header_offset + 0x24])[0]
    block2_data_offset = block2_header_offset + 44
    block2_compressed = data[block2_data_offset:block2_data_offset + block2_compressed_size]

    # Block 3: Raw data with 4 regions
    block3_offset = block2_data_offset + block2_compressed_size

    # Find all 4 region headers in Block 3
    block3_regions = []
    search_pos = block3_offset
    for region_num in range(4):
        while search_pos < total_size - 8:
            if (data[search_pos] == 0x01 and
                data[search_pos+4:search_pos+8] == b'\x00\x00\x80\x00'):
                region_size = struct.unpack('<I', data[search_pos+1:search_pos+4] + b'\x00')[0]
                if 0 < region_size < 50000:
                    block3_regions.append((search_pos, region_size))
                    # Move past header + data + 5-byte gap
                    search_pos = search_pos + 8 + region_size + 5
                    break
            search_pos += 1

    # Region 4's declared size equals Block 4's compressed size
    if len(block3_regions) >= 4:
        region4_offset, block4_compressed_size = block3_regions[3]
        # Block 3 ends after Region 4 header (8 bytes) + 5-byte local data
        block3_end = region4_offset + 8 + 5
        block3_size = block3_end - block3_offset
    else:
        raise ValueError(f"Could not parse Block 3 headers, found {len(block3_regions)} regions")

    block3_raw = data[block3_offset:block3_offset + block3_size]

    # Calculate Region 4's offset within Block 3 (for later patching)
    region4_offset_in_block3 = region4_offset - block3_offset

    # Block 4: LZSS compressed, size from Region 4's declared value
    block4_offset = block3_offset + block3_size
    block4_compressed = data[block4_offset:block4_offset + block4_compressed_size]

    # Block 5: Rest of file
    block5_offset = block4_offset + block4_compressed_size
    block5_raw = data[block5_offset:]

    return {
        'block1_compressed': block1_compressed,
        'block2_compressed': block2_compressed,
        'block3_raw': block3_raw,
        'block4_compressed': block4_compressed,
        'block5_raw': block5_raw,
        'region4_offset_in_block3': region4_offset_in_block3,
    }


def find_cape_in_block4(data: bytes, cape_hash: int, expected_id: int) -> int:
    """
    Find a cape in Block 4 by searching for its hash.

    Returns the offset of the ownership flag, or -1 if not found.
    Verifies the cape_id at hash_offset + 14 matches expected_id.
    """
    hash_bytes = struct.pack('<I', cape_hash)
    pos = 0

    while True:
        pos = data.find(hash_bytes, pos)
        if pos == -1:
            return -1

        # Check if cape_id matches at expected offset
        id_offset = pos + CAPE_ID_OFFSET
        if id_offset < len(data):
            actual_id = data[id_offset]
            if actual_id == expected_id:
                # Found it! Return ownership flag offset
                return pos + OWNERSHIP_FLAG_OFFSET

        pos += 1

    return -1


def unlock_capes(sav_path: str, output_path: str, verbose: bool = False,
                 new_name: str = None, skip_capes: bool = False) -> bool:
    """
    Unlock Facebook capes in a SAV file by searching for cape hashes.
    Optionally change the player name.

    Args:
        sav_path: Input SAV file path
        output_path: Output SAV file path
        verbose: Enable verbose output
        new_name: New player name (optional)
        skip_capes: Skip cape unlocking (only change name)
    """
    # Read input file
    with open(sav_path, 'rb') as f:
        sav_data = f.read()

    if verbose:
        print(f"Input: {sav_path} ({len(sav_data)} bytes)")

    # Parse SAV structure
    blocks = parse_sav_blocks(sav_data)

    block1_compressed = blocks['block1_compressed']
    block2_compressed = blocks['block2_compressed']
    block3_raw = bytearray(blocks['block3_raw'])  # Make mutable for patching
    block4_compressed = blocks['block4_compressed']
    block5_raw = blocks['block5_raw']
    region4_offset = blocks['region4_offset_in_block3']

    if verbose:
        print(f"Block 1 compressed: {len(block1_compressed)} bytes")
        print(f"Block 2 compressed: {len(block2_compressed)} bytes")
        print(f"Block 3 raw: {len(block3_raw)} bytes")
        print(f"Block 4 compressed: {len(block4_compressed)} bytes")
        print(f"Block 5 raw: {len(block5_raw)} bytes")

    # Decompress blocks
    decompressor = LZSSDecompressor()
    block1_decompressed = decompressor.decompress(block1_compressed)
    block4_decompressed = decompressor.decompress(block4_compressed)

    if verbose:
        print(f"Block 1 decompressed: {len(block1_decompressed)} bytes")
        print(f"Block 4 decompressed: {len(block4_decompressed)} bytes")

    # Track what we modify
    block1_modified = False
    block4_modified = False

    # Handle name change if requested
    block1_data = bytearray(block1_decompressed)
    if new_name is not None:
        block1_data = change_name_in_block1(block1_data, new_name)
        block1_modified = True

    # Make Block 4 mutable
    block4_data = bytearray(block4_decompressed)

    # Search for and unlock each cape (unless skipped)
    if not skip_capes:
        all_unlocked = True

        for cape_hash, cape_id, cape_name in CAPE_DEFINITIONS:
            flag_offset = find_cape_in_block4(block4_data, cape_hash, cape_id)

            if flag_offset == -1:
                print(f"ERROR: {cape_name} not found in Block 4!")
                print(f"  Hash: 0x{cape_hash:08X}, Expected ID: 0x{cape_id:02X}")
                all_unlocked = False
                continue

            current_value = block4_data[flag_offset]

            if current_value == 0x01:
                print(f"{cape_name}: Already unlocked (offset 0x{flag_offset:04X})")
            else:
                print(f"{cape_name}: 0x{current_value:02X} -> 0x01 (offset 0x{flag_offset:04X})")
                block4_data[flag_offset] = 0x01
                block4_modified = True

        if not all_unlocked:
            print("\nWARNING: Some capes could not be found. Proceeding with partial unlock.")

    # Check if anything changed
    if not block1_modified and not block4_modified:
        print("\nNo changes needed.")
        return True

    # Track size changes for Block 2 Field1 update
    total_size_diff = 0

    # Handle Block 1 (recompress if modified)
    if block1_modified:
        if verbose:
            print("Recompressing Block 1...")
        block1_recompressed, _, _ = compress_lzss_lazy(bytes(block1_data))
        if verbose:
            print(f"Block 1 recompressed: {len(block1_recompressed)} bytes (was {len(block1_compressed)})")

        # Build new Block 1 header
        block1_checksum = adler32(block1_recompressed)
        block1_header = struct.pack('<11I',
            0x00000016,              # Field1: Static value
            0x00FEDBAC,              # Field2: Magic marker
            len(block1_recompressed) + 32,  # Field3: compressed_size + 32
            len(block1_data),        # Field4: Uncompressed size
            0x57FBAA33,              # Magic1 (GUID low)
            0x1004FA99,              # Magic2 (GUID high)
            0x00020001,              # Magic3
            0x01000080,              # Magic4
            len(block1_recompressed),  # Compressed size
            len(block1_data),        # Uncompressed size (duplicate)
            block1_checksum          # Checksum
        )
        block1_header_and_data = block1_header + block1_recompressed
        total_size_diff += len(block1_recompressed) - len(block1_compressed)
    else:
        # Keep original Block 1
        block1_header_and_data = sav_data[0:0x2C + len(block1_compressed)]

    # Handle Block 4 (recompress if modified)
    if block4_modified:
        if verbose:
            print("Recompressing Block 4...")
        block4_recompressed, _, _ = compress_lzss_lazy(bytes(block4_data))
        if verbose:
            print(f"Block 4 recompressed: {len(block4_recompressed)} bytes (was {len(block4_compressed)})")

        # Patch Block 3's Region 4 header with new Block 4 size
        old_b4_size = struct.unpack('<I', bytes(block3_raw[region4_offset+1:region4_offset+4]) + b'\x00')[0]
        new_b4_size = len(block4_recompressed)
        if old_b4_size != new_b4_size:
            if verbose:
                print(f"Patching Block 3 Region 4 size: {old_b4_size} -> {new_b4_size}")
            size_bytes = struct.pack('<I', new_b4_size)[:3]
            block3_raw[region4_offset+1:region4_offset+4] = size_bytes

        # Update the Adler32 checksum of Block 4 LZSS data
        old_checksum = struct.unpack('<I', bytes(block3_raw[region4_offset+9:region4_offset+13]))[0]
        new_checksum = adler32(block4_recompressed)
        if old_checksum != new_checksum:
            if verbose:
                print(f"Patching Block 4 checksum: 0x{old_checksum:08X} -> 0x{new_checksum:08X}")
            block3_raw[region4_offset+9:region4_offset+13] = struct.pack('<I', new_checksum)

        total_size_diff += len(block4_recompressed) - len(block4_compressed)
    else:
        block4_recompressed = block4_compressed

    # Get Block 2 header+data (preserved from original)
    block2_start = 0x2C + len(block1_compressed)
    block2_header_and_data = bytearray(sav_data[block2_start:block2_start + 44 + len(block2_compressed)])

    # Patch Block 2 header Field1 (remaining file size) if file size changed
    if total_size_diff != 0:
        old_field1 = struct.unpack('<I', block2_header_and_data[0:4])[0]
        new_field1 = old_field1 + total_size_diff
        if verbose:
            print(f"Patching Block 2 Field1: {old_field1} -> {new_field1}")
        block2_header_and_data[0:4] = struct.pack('<I', new_field1)

    # Assemble output file
    output = bytearray()
    output.extend(block1_header_and_data)
    output.extend(block2_header_and_data)
    output.extend(block3_raw)
    output.extend(block4_recompressed)
    output.extend(block5_raw)

    # Write output
    with open(output_path, 'wb') as f:
        f.write(output)

    print(f"Output: {output_path} ({len(output)} bytes)")
    if block4_modified:
        print("Capes unlocked!")
    if block1_modified:
        print("Name changed!")

    return True


def main():
    parser = argparse.ArgumentParser(
        description='Unlock Facebook capes and/or change player name in AC Brotherhood SAV files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s save.SAV                    # Unlock capes only
  %(prog)s save.SAV --name "Ezio"      # Unlock capes and change name
  %(prog)s save.SAV --name "Ezio" --skip-capes  # Change name only
        """)
    parser.add_argument('input', help='Input SAV file')
    parser.add_argument('-o', '--output', help='Output SAV file (default: input with .unlocked.SAV)')
    parser.add_argument('-n', '--name', help='New player name (replaces "Desmond")')
    parser.add_argument('--skip-capes', action='store_true', help='Skip cape unlocking (only change name)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: File not found: {args.input}")
        return 1

    # Validate: if skip-capes, must have name
    if args.skip_capes and not args.name:
        print("ERROR: --skip-capes requires --name")
        return 1

    # Default output name
    if args.output is None:
        base, ext = os.path.splitext(args.input)
        args.output = f"{base}.unlocked{ext}"

    try:
        unlock_capes(args.input, args.output, args.verbose,
                     new_name=args.name, skip_capes=args.skip_capes)
        return 0
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
