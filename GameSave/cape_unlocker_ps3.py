#!/usr/bin/env python3
"""
Cape Unlocker for AC Brotherhood PS3 SAV files (AC2_0.SAV)
==========================================================

SUPERSEDED (July 2026) by ../acb_facebookcape_unlocker.py, which handles PC
and PS3 (encrypted or decrypted) in one tool. This version assumes the cape
records live in the 4th frame ("Block 4"), which is only true for small fresh
saves; on played PS3 saves (14-16 frames) it reads the wrong frame. The
replacement locates the cape frame by content and validates the full record.

Unlocks the two Facebook-exclusive capes by searching for cape hashes in Block 4
and flipping ownership flags. Optionally changes the player name in Block 1.

PS3 SAV Format Differences from PC:
-----------------------------------
1. 8-byte PS3 prefix: [size 4B BE] [CRC32 4B BE]
2. Section headers: Fields 0-2 are big-endian, rest are little-endian
3. File padded with zeros to 307,200 bytes (0x4B000)
4. CRC32: poly=0x04C11DB7, init=0xBAE23CD0, xorout=0xFFFFFFFF, refin/out=true

Cape structure in Block 4 (identical to PC):
  [cape_hash 4B LE] [8 zeros] [0x0B marker] [ownership_flag 1B] [cape_id 1B] ...

Cape identification:
  Venetian Cape: Hash 0x4470F39F, ID 0x0E
  Medici Cape:   Hash 0xDD79A225, ID 0x11

Ownership flag is at hash_offset + 13, followed by cape_id at hash_offset + 14.
"""

import sys
import os
import struct
import argparse

# Import from existing tools
from lzss_decompressor_final import LZSSDecompressor
from lzss_compressor_final import compress_lzss_lazy


# ============================================================================
# PS3 CRC32 Checksum
# ============================================================================

def crc32_ps3(data: bytes) -> int:
    """
    Calculate CRC32 using PS3's custom parameters.

    Parameters:
        poly=0x04C11DB7
        init=0xBAE23CD0
        xorout=0xFFFFFFFF
        refin=true (reflect input bytes)
        refout=true (reflect output)

    Args:
        data: Bytes to checksum

    Returns:
        CRC32 checksum as 32-bit integer
    """
    crc = 0xBAE23CD0  # Custom initial value

    for byte in data:
        # Reflect input byte (reverse bits)
        byte = int('{:08b}'.format(byte)[::-1], 2)
        crc ^= (byte << 24)

        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF

    # Reflect output (reverse all 32 bits)
    crc = int('{:032b}'.format(crc)[::-1], 2)
    # XOR with final value
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF


def adler32(data: bytes) -> int:
    """
    Calculate Adler-32 checksum using AC Brotherhood's zero-seed variant.
    """
    MOD_ADLER = 65521
    s1 = 0
    s2 = 0

    for byte in data:
        s1 = (s1 + byte) % MOD_ADLER
        s2 = (s2 + s1) % MOD_ADLER

    return (s2 << 16) | s1


# ============================================================================
# Cape Definitions
# ============================================================================

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

# PS3 file size (padded)
PS3_FILE_SIZE = 307200  # 0x4B000


# ============================================================================
# Name Handling
# ============================================================================

def find_name_in_block1(data: bytes) -> tuple:
    """
    Find the player name in Block 1.

    Returns (offset, length, name) where offset is the start of the length field.
    Returns (None, None, None) if not found.
    """
    pos = 0
    while True:
        pos = data.find(NAME_MARKER, pos)
        if pos == -1:
            return None, None, None

        length_offset = pos + 3
        if length_offset + 4 > len(data):
            pos += 1
            continue

        name_length = struct.unpack('<I', data[length_offset:length_offset + 4])[0]

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
    """
    length_offset, old_length, old_name = find_name_in_block1(data)

    if length_offset is None:
        raise ValueError("Could not find name in Block 1")

    new_name_bytes = new_name.encode('utf-8')

    if len(new_name_bytes) > MAX_NAME_LENGTH:
        new_name_bytes = new_name_bytes[:MAX_NAME_LENGTH]
        print(f"WARNING: Name truncated to {MAX_NAME_LENGTH} characters")

    new_length = len(new_name_bytes)
    length_diff = new_length - old_length
    print(f"Name: \"{old_name}\" -> \"{new_name_bytes.decode('utf-8')}\" (length: {old_length} -> {new_length})")

    name_offset = length_offset + 4

    result = bytearray()
    result.extend(data[:length_offset])
    result.extend(struct.pack('<I', new_length))
    result.extend(new_name_bytes)
    result.extend(data[name_offset + old_length:])

    # Adjust internal size fields
    SIZE_FIELD_OFFSETS_1BYTE = [0x0E, 0x91]
    for offset in SIZE_FIELD_OFFSETS_1BYTE:
        if offset < len(result):
            old_val = result[offset]
            new_val = old_val + length_diff
            if 0 <= new_val <= 255:
                result[offset] = new_val
                print(f"  Size field at 0x{offset:02X}: 0x{old_val:02X} -> 0x{new_val:02X}")

    if 0x14 <= len(result):
        old_val = struct.unpack('<H', result[0x12:0x14])[0]
        new_val = old_val + length_diff
        if 0 <= new_val <= 65535:
            result[0x12:0x14] = struct.pack('<H', new_val)
            print(f"  Size field at 0x12 (2-byte): {old_val} -> {new_val}")

    return result


# ============================================================================
# PS3 SAV Block Parsing
# ============================================================================

def parse_ps3_sav_blocks(data: bytes) -> dict:
    """
    Parse PS3 SAV file and extract all 5 blocks.

    PS3 format has an 8-byte prefix before the standard SAV structure.
    Header fields 0-2 are big-endian, sizes are little-endian.
    """
    # Verify PS3 prefix
    if len(data) < 8:
        raise ValueError("File too small for PS3 SAV format")

    ps3_size = struct.unpack('>I', data[0:4])[0]
    ps3_checksum = struct.unpack('>I', data[4:8])[0]

    # SAV data starts after 8-byte prefix
    sav_data = data[8:]
    total_size = len(sav_data)

    # Block 1: 44-byte header, sizes at offset 0x20 (LE)
    b1_comp_size = struct.unpack('<I', sav_data[0x20:0x24])[0]
    b1_uncomp_size = struct.unpack('<I', sav_data[0x24:0x28])[0]
    b1_checksum = struct.unpack('<I', sav_data[0x28:0x2C])[0]
    b1_compressed = sav_data[44:44 + b1_comp_size]

    # Block 2: 44-byte header immediately after Block 1
    b2_header_offset = 44 + b1_comp_size
    b2_comp_size = struct.unpack('<I', sav_data[b2_header_offset + 0x20:b2_header_offset + 0x24])[0]
    b2_uncomp_size = struct.unpack('<I', sav_data[b2_header_offset + 0x24:b2_header_offset + 0x28])[0]
    b2_checksum = struct.unpack('<I', sav_data[b2_header_offset + 0x28:b2_header_offset + 0x2C])[0]
    b2_data_offset = b2_header_offset + 44
    b2_compressed = sav_data[b2_data_offset:b2_data_offset + b2_comp_size]

    # Block 3: Raw data with 4 regions
    b3_offset = b2_data_offset + b2_comp_size

    # Find all 4 region headers in Block 3
    # Pattern: [01] [size 3B LE] [00 00 80 00]
    block3_regions = []
    search_pos = b3_offset
    for region_num in range(4):
        while search_pos < total_size - 8:
            if (sav_data[search_pos] == 0x01 and
                sav_data[search_pos+4:search_pos+8] == b'\x00\x00\x80\x00'):
                region_size = struct.unpack('<I', sav_data[search_pos+1:search_pos+4] + b'\x00')[0]
                if 0 < region_size < 50000:
                    block3_regions.append((search_pos, region_size))
                    search_pos = search_pos + 8 + region_size + 5
                    break
            search_pos += 1

    if len(block3_regions) < 4:
        raise ValueError(f"Could not parse Block 3 headers, found {len(block3_regions)} regions")

    # Region 4's declared size equals Block 4's compressed size
    region4_offset, b4_comp_size = block3_regions[3]
    b3_end = region4_offset + 8 + 5
    b3_size = b3_end - b3_offset
    b3_raw = sav_data[b3_offset:b3_offset + b3_size]

    region4_offset_in_block3 = region4_offset - b3_offset

    # Block 4: LZSS compressed
    b4_offset = b3_offset + b3_size
    b4_compressed = sav_data[b4_offset:b4_offset + b4_comp_size]

    # Block 5: Rest of actual data (before padding)
    b5_offset = b4_offset + b4_comp_size
    # Find where actual data ends (last non-zero byte)
    actual_end = ps3_size
    b5_raw = sav_data[b5_offset:actual_end]

    return {
        'ps3_size': ps3_size,
        'ps3_checksum': ps3_checksum,
        'block1_header': sav_data[0:44],
        'block1_compressed': b1_compressed,
        'block2_header_offset': b2_header_offset,
        'block2_header': sav_data[b2_header_offset:b2_header_offset + 44],
        'block2_compressed': b2_compressed,
        'block3_raw': b3_raw,
        'block4_compressed': b4_compressed,
        'block5_raw': b5_raw,
        'region4_offset_in_block3': region4_offset_in_block3,
    }


def find_cape_in_block4(data: bytes, cape_hash: int, expected_id: int) -> int:
    """
    Find a cape in Block 4 by searching for its hash.

    Returns the offset of the ownership flag, or -1 if not found.
    """
    hash_bytes = struct.pack('<I', cape_hash)  # Little-endian
    pos = 0

    while True:
        pos = data.find(hash_bytes, pos)
        if pos == -1:
            return -1

        id_offset = pos + CAPE_ID_OFFSET
        if id_offset < len(data):
            actual_id = data[id_offset]
            if actual_id == expected_id:
                return pos + OWNERSHIP_FLAG_OFFSET

        pos += 1

    return -1


# ============================================================================
# Main Unlock Function
# ============================================================================

def unlock_capes_ps3(sav_path: str, output_path: str, verbose: bool = False,
                     new_name: str = None, skip_capes: bool = False) -> bool:
    """
    Unlock Facebook capes in a PS3 SAV file.
    """
    # Read input file
    with open(sav_path, 'rb') as f:
        sav_data = f.read()

    if verbose:
        print(f"Input: {sav_path} ({len(sav_data)} bytes)")

    # Verify PS3 checksum
    ps3_size = struct.unpack('>I', sav_data[0:4])[0]
    ps3_checksum_expected = struct.unpack('>I', sav_data[4:8])[0]
    ps3_checksum_actual = crc32_ps3(sav_data[8:8 + ps3_size])

    if ps3_checksum_expected != ps3_checksum_actual:
        print(f"WARNING: PS3 checksum mismatch!")
        print(f"  Expected: 0x{ps3_checksum_expected:08X}")
        print(f"  Actual:   0x{ps3_checksum_actual:08X}")

    # Parse SAV structure
    blocks = parse_ps3_sav_blocks(sav_data)

    if verbose:
        print(f"PS3 prefix: size={blocks['ps3_size']}, checksum=0x{blocks['ps3_checksum']:08X}")
        print(f"Block 1 compressed: {len(blocks['block1_compressed'])} bytes")
        print(f"Block 2 compressed: {len(blocks['block2_compressed'])} bytes")
        print(f"Block 3 raw: {len(blocks['block3_raw'])} bytes")
        print(f"Block 4 compressed: {len(blocks['block4_compressed'])} bytes")
        print(f"Block 5 raw: {len(blocks['block5_raw'])} bytes")

    # Decompress blocks
    decompressor = LZSSDecompressor()
    block1_decompressed = decompressor.decompress(blocks['block1_compressed'])
    block4_decompressed = decompressor.decompress(blocks['block4_compressed'])

    if verbose:
        print(f"Block 1 decompressed: {len(block1_decompressed)} bytes")
        print(f"Block 4 decompressed: {len(block4_decompressed)} bytes")

    # Track modifications
    block1_modified = False
    block4_modified = False

    # Handle name change
    block1_data = bytearray(block1_decompressed)
    if new_name is not None:
        block1_data = change_name_in_block1(block1_data, new_name)
        block1_modified = True

    # Make Block 4 mutable
    block4_data = bytearray(block4_decompressed)

    # Search for and unlock capes
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

    # Prepare modified blocks
    block3_raw = bytearray(blocks['block3_raw'])
    region4_offset = blocks['region4_offset_in_block3']

    # Recompress Block 1 if modified
    if block1_modified:
        if verbose:
            print("Recompressing Block 1...")
        block1_recompressed, _, _ = compress_lzss_lazy(bytes(block1_data))
        if verbose:
            print(f"Block 1 recompressed: {len(block1_recompressed)} bytes")

        # Build new Block 1 header (PS3 format: fields 0-2 BE, rest LE)
        block1_checksum = adler32(block1_recompressed)
        block1_header = bytearray()
        block1_header.extend(struct.pack('>I', 0x00000016))  # Field0 BE
        block1_header.extend(struct.pack('>I', 0x00FEDBAC))  # Field1 BE
        block1_header.extend(struct.pack('>I', len(block1_recompressed) + 32))  # Field2 BE
        block1_header.extend(struct.pack('<I', len(block1_data)))  # Field3 LE (uncomp size)
        block1_header.extend(struct.pack('<I', 0x57FBAA33))  # Magic1 LE
        block1_header.extend(struct.pack('<I', 0x1004FA99))  # Magic2 LE
        block1_header.extend(struct.pack('<I', 0x00020001))  # Magic3 LE
        block1_header.extend(struct.pack('<I', 0x01000080))  # Magic4 LE
        block1_header.extend(struct.pack('<I', len(block1_recompressed)))  # CompSize LE
        block1_header.extend(struct.pack('<I', len(block1_data)))  # UncompSize LE
        block1_header.extend(struct.pack('<I', block1_checksum))  # Checksum LE
    else:
        block1_header = blocks['block1_header']
        block1_recompressed = blocks['block1_compressed']

    # Recompress Block 4 if modified
    if block4_modified:
        if verbose:
            print("Recompressing Block 4...")
        block4_recompressed, _, _ = compress_lzss_lazy(bytes(block4_data))
        if verbose:
            print(f"Block 4 recompressed: {len(block4_recompressed)} bytes")

        # Patch Block 3's Region 4 header with new Block 4 size
        old_b4_size = struct.unpack('<I', bytes(block3_raw[region4_offset+1:region4_offset+4]) + b'\x00')[0]
        new_b4_size = len(block4_recompressed)
        if old_b4_size != new_b4_size:
            if verbose:
                print(f"Patching Block 3 Region 4 size: {old_b4_size} -> {new_b4_size}")
            size_bytes = struct.pack('<I', new_b4_size)[:3]
            block3_raw[region4_offset+1:region4_offset+4] = size_bytes

        # Update Adler32 checksum of Block 4 LZSS data
        old_checksum = struct.unpack('<I', bytes(block3_raw[region4_offset+9:region4_offset+13]))[0]
        new_checksum = adler32(block4_recompressed)
        if old_checksum != new_checksum:
            if verbose:
                print(f"Patching Block 4 checksum: 0x{old_checksum:08X} -> 0x{new_checksum:08X}")
            block3_raw[region4_offset+9:region4_offset+13] = struct.pack('<I', new_checksum)
    else:
        block4_recompressed = blocks['block4_compressed']

    # Build Block 2 header+data (may need field1 update)
    block2_header = bytearray(blocks['block2_header'])
    block2_compressed = blocks['block2_compressed']

    # Calculate size difference for Block 2 Field1
    old_b1_size = len(blocks['block1_compressed'])
    new_b1_size = len(block1_recompressed)
    old_b4_size = len(blocks['block4_compressed'])
    new_b4_size = len(block4_recompressed)
    total_size_diff = (new_b1_size - old_b1_size) + (new_b4_size - old_b4_size)

    if total_size_diff != 0:
        # Update Block 2 Field1 (remaining file size) - stored as BE in PS3
        old_field1 = struct.unpack('>I', block2_header[0:4])[0]
        new_field1 = old_field1 + total_size_diff
        if verbose:
            print(f"Patching Block 2 Field1: {old_field1} -> {new_field1}")
        block2_header[0:4] = struct.pack('>I', new_field1)

    # Assemble SAV payload (after PS3 prefix)
    sav_payload = bytearray()
    sav_payload.extend(block1_header)
    sav_payload.extend(block1_recompressed)
    sav_payload.extend(block2_header)
    sav_payload.extend(block2_compressed)
    sav_payload.extend(block3_raw)
    sav_payload.extend(block4_recompressed)
    sav_payload.extend(blocks['block5_raw'])

    # Calculate new PS3 prefix
    new_ps3_size = len(sav_payload)
    new_ps3_checksum = crc32_ps3(sav_payload)

    if verbose:
        print(f"New PS3 size: {new_ps3_size} (was {blocks['ps3_size']})")
        print(f"New PS3 checksum: 0x{new_ps3_checksum:08X}")

    # Build final output with PS3 prefix and padding
    output = bytearray()
    output.extend(struct.pack('>I', new_ps3_size))  # Size BE
    output.extend(struct.pack('>I', new_ps3_checksum))  # Checksum BE
    output.extend(sav_payload)

    # Pad to PS3 file size
    if len(output) < PS3_FILE_SIZE:
        output.extend(b'\x00' * (PS3_FILE_SIZE - len(output)))

    # Write output
    with open(output_path, 'wb') as f:
        f.write(output)

    print(f"\nOutput: {output_path} ({len(output)} bytes)")
    if block4_modified:
        print("Capes unlocked!")
    if block1_modified:
        print("Name changed!")

    return True


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Unlock Facebook capes and/or change player name in AC Brotherhood PS3 SAV files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s AC2_0.SAV                    # Unlock capes only
  %(prog)s AC2_0.SAV --name "Ezio"      # Unlock capes and change name
  %(prog)s AC2_0.SAV --name "Ezio" --skip-capes  # Change name only

PS3 SAV Format:
  - 8-byte prefix: [size 4B BE] [CRC32 4B BE]
  - Same block structure as PC but with mixed byte order
  - Padded with zeros to 307,200 bytes
        """)
    parser.add_argument('input', help='Input PS3 SAV file (e.g., AC2_0.SAV)')
    parser.add_argument('-o', '--output', help='Output SAV file (default: input with .unlocked.SAV)')
    parser.add_argument('-n', '--name', help='New player name (replaces "Desmond")')
    parser.add_argument('--skip-capes', action='store_true', help='Skip cape unlocking (only change name)')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: File not found: {args.input}")
        return 1

    if args.skip_capes and not args.name:
        print("ERROR: --skip-capes requires --name")
        return 1

    if args.output is None:
        base, ext = os.path.splitext(args.input)
        args.output = f"{base}.unlocked{ext}"

    try:
        unlock_capes_ps3(args.input, args.output, args.verbose,
                         new_name=args.name, skip_capes=args.skip_capes)
        return 0
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
