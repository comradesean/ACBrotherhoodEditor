#!/usr/bin/env python3
"""
Assassin's Creed Brotherhood Savegame Parser
============================================

DEPRECATED (July 2026): this parser hardcodes the fixed 5-block layout below,
which is only what a small fresh save looks like. Real saves hold 6-16
self-contained LZSS frames after Blocks 1-2, so on played saves this extracts
the wrong data. Use ../acb_facebookcape_unlocker.py, which enumerates the
frames and locates content by decompressing them.

Parser for ACBROTHERHOODSAVEGAME0.SAV files.

File Structure:
--------------
| Block | Offset     | Size      | Type                        |
|-------|------------|-----------|-----------------------------|
| 1 Hdr | 0x0000     | 44 bytes  | Standard header             |
| 1 Data| 0x002C     | variable  | LZSS → 283 bytes            |
| 2 Hdr | 0x00D9     | 44 bytes  | Standard header (0x00CAFE00)|
| 2 Data| 0x0105     | variable  | LZSS → 32KB                 |
| 3     | dynamic    | variable  | Uncompressed (4 nested regions)  |
| 4     | dynamic    | variable  | LZSS (no header) → ~32KB    |
| 5     | dynamic    | variable  | Uncompressed (2 nested regions)  |

Block 3 contains 4 nested regions with headers (01 XX XX XX 00 00 80 00).
Region 4's declared size = Block 4's compressed size (cross-block reference).
Block 5 starts immediately after Block 4 and extends to end of file.

Header Structure (44 bytes, 11 x 4-byte fields):
-----------------------------------------------
0x00: Field1 (version or size)
0x04: Field2 (magic 0x00FEDBAC for block 1, section num for others)
0x08: Field3 (marker - 0xC5, 0x00CAFE00, etc.)
0x0C: Field4 (uncompressed size or other)
0x10-0x17: GUID (0x1004FA9957FBAA33)
0x18: Magic3 (0x00020001)
0x1C: Magic4 (0x01000080)
0x20: Compressed size
0x24: Uncompressed size
0x28: Adler-32 checksum (zero seed)
"""

import sys
import os
import struct
import argparse
import json
from lzss import LZSSDecompressor


def adler32(data: bytes) -> int:
    """
    Calculate Adler-32 checksum using AC Brotherhood's non-standard variant.

    The game uses Adler-32 with ZERO SEED (s1=0, s2=0) instead of the
    standard Adler-32 seed (s1=1, s2=0).

    Args:
        data: Bytes to checksum

    Returns:
        Adler-32 checksum as 32-bit integer (zero seed variant)
    """
    MOD_ADLER = 65521
    s1 = 0  # NON-STANDARD: standard Adler-32 uses s1=1
    s2 = 0

    for byte in data:
        s1 = (s1 + byte) % MOD_ADLER
        s2 = (s2 + s1) % MOD_ADLER

    return (s2 << 16) | s1


# =============================================================================
# Scimitar Engine Type System - Hash Definitions
# =============================================================================
# These type hashes are used throughout the SAV and OPTIONS files for
# object serialization. Discovered via Ghidra decompilation of ACBSP.exe.

TYPE_HASHES = {
    # Root/Base Types
    0x7E42F87F: "CommonParent",      # ROOT base class (all types inherit)
    0xBB96607D: "ManagedObject",     # Base for managed objects (16-byte base, 192 derived types)

    # Save Game Types
    0xBDBE3B52: "SaveGame",          # Top-level save container (12 properties)
    0x5FDACBA0: "SaveGameDataObject",# Mission/save data container
    0x5ED7B213: "MissionSaveData",   # Mission-specific save data
    0x12DE6C4C: "RewardFault",       # Ubisoft Connect reward/action fault tracking

    # World Types
    0xFBB63E47: "World",             # Main world object type (Table ID 0x20, 14 properties)

    # Property System Types
    0x0984415E: "PropertyReference", # Property accessor/reference (461 code refs)
    0x18B8C0DE: "ValueBind",         # Property value binding (always paired with PropertyReference)
    0xC0A01091: "LinkBind",          # Property link binding (optional, pairs with ValueBind)
    0xF8206AF7: "SubObject",         # Embedded object marker (38 properties use this type)

    # Container Types
    0xA9E0C685: "ContainerType",     # Container/array storage
    0x11598A66: "CollectionType",    # Havok physics collection (self-referential root)

    # OPTIONS Types (used in OPTIONS file sections)
    0x1C0637AB: "OPTIONS",           # Global game settings (21 properties, 112 bytes)
    0xDCCBD617: "LanguageSettings",  # OPTIONS property 0 (16 bytes inline)
    0x569CD276: "AudioSettings",     # OPTIONS property 1 (16 bytes inline)
    0x9E293373: "VideoSettings",     # OPTIONS property 2 (16 bytes inline)

    # Player Options Types (per-save player settings)
    0xCAC5F9B3: "PlayerOptions",           # Per-save player options (48 bytes)
    0x7879288E: "PlayerOptionsSaveData",   # Player save data container (76 bytes, 10 properties)
    0x2DAD13E3: "PlayerOptionsElement",    # Element type for collections (Table ID 22, 48 bytes)
    0xE9DDD041: "AbstractElementBase",     # Abstract parent for PlayerOptionsElement

    # Additional Types
    0xA1A85298: "PhysicalInventoryItem",   # Inventory item type
    0x85C817C3: "PropertyHash",            # Common property identifier
    0xC69A7F31: "Unknown_C69A7F31",        # Rare type (1 code ref)
    0x21C2D472: "Unknown_21C2D472",        # Referenced in serialization

    # Compact Serialization Types (Blocks 3/5)
    # All inherit from CommonParent (0x7E42F87F), have 22 properties each
    0x0DEBED19: "CompactType_5E",          # Table ID 0x5E (94), 63 refs in Block 3
    0xC8761736: "CompactType_5B",          # Table ID 0x5B (91), 4 refs in Block 3
    0xFC6EDE2A: "CompactType_3B",          # Table ID 0x3B (59)
    0xFA1AA549: "CompactType_38",          # Table ID 0x38 (56)
    0x82A2AEE0: "CompactType_0B",          # Table ID 0x0B (11)
    0xC9A5839D: "CompactType_08",          # Table ID 0x08 (8)
    0x9A87FC51: "CompactType_5A",          # Table ID 0x5A (90)
    0xE3E58C35: "CompactType_5C",          # Table ID 0x5C (92)
    0x7AECDD8F: "CompactType_5D",          # Table ID 0x5D (93)
    0x938F78BA: "CompactType_5F",          # Table ID 0x5F (95)
    0xE488482C: "CompactType_60",          # Table ID 0x60 (96)
    0xF49BFD86: "CompactType_4F",          # Table ID 0x4F (79)
}

# Table ID to Type Hash mapping
# Used in compact format (Blocks 3, 5) for type resolution
TABLE_ID_TO_TYPE = {
    0x20: 0xFBB63E47,  # World (14 properties)
    0x16: 0x2DAD13E3,  # PlayerOptionsElement (Table ID 22, 48 bytes)

    # Compact serialization types (all inherit from CommonParent, 22 properties each)
    0x5E: 0x0DEBED19,  # CompactType_5E (dominant in Block 3 with 63 refs)
    0x5B: 0xC8761736,  # CompactType_5B (4 refs in Block 3)
    0x3B: 0xFC6EDE2A,  # CompactType_3B (43 refs, property range 0x08-0xFE)
    0x38: 0xFA1AA549,  # CompactType_38 (11 refs, property range 0x03-0xDF)
    0x0B: 0x82A2AEE0,  # CompactType_0B (27 refs, property range 0x03-0xFC)
    0x08: 0xC9A5839D,  # CompactType_08 (12 refs, property range 0x00-0xF6)

    # Additional compact types in the same family
    0x5A: 0x9A87FC51,  # CompactType_5A
    0x5C: 0xE3E58C35,  # CompactType_5C
    0x5D: 0x7AECDD8F,  # CompactType_5D
    0x5F: 0x938F78BA,  # CompactType_5F
    0x60: 0xE488482C,  # CompactType_60
    0x4F: 0xF49BFD86,  # CompactType_4F
}

# Compact format prefixes (Blocks 3, 5)
COMPACT_PREFIX_TABLE_REF = 0x0803   # Fixed property reference
COMPACT_PREFIX_FIXED32 = 0x0502    # 4-byte fixed value
COMPACT_PREFIX_VARINT = 0x1405     # Variable-length integer
COMPACT_PREFIX_EXTENDED = 0x0C18   # Extended format with modifier


# =============================================================================
# Type Lookup Helper Functions
# =============================================================================

def get_type_name(type_hash: int) -> str:
    """
    Look up type name from hash.

    Args:
        type_hash: 32-bit type hash value

    Returns:
        Type name string, or hex representation if unknown
    """
    return TYPE_HASHES.get(type_hash, f"Unknown_0x{type_hash:08X}")


def get_type_from_table_id(table_id: int) -> tuple:
    """
    Look up type information from compact format table ID.

    Args:
        table_id: Table ID from compact format (e.g., 0x20 for World)

    Returns:
        Tuple of (type_hash, type_name) or (None, None) if unknown
    """
    type_hash = TABLE_ID_TO_TYPE.get(table_id)
    if type_hash is not None:
        return (type_hash, get_type_name(type_hash))
    return (None, None)


def format_type_info(type_hash: int) -> str:
    """
    Format type hash with name for debug output.

    Args:
        type_hash: 32-bit type hash value

    Returns:
        Formatted string like "0xBDBE3B52 (SaveGame)"
    """
    name = TYPE_HASHES.get(type_hash)
    if name:
        return f"0x{type_hash:08X} ({name})"
    return f"0x{type_hash:08X}"


def is_known_type(type_hash: int) -> bool:
    """
    Check if a type hash is in our known types dictionary.

    Args:
        type_hash: 32-bit type hash value

    Returns:
        True if type is known, False otherwise
    """
    return type_hash in TYPE_HASHES


def print_known_types():
    """Print all known type hashes and their names."""
    print("=" * 80)
    print("Known Type Hashes")
    print("=" * 80)
    print()

    # Group by category
    categories = {
        "Root/Base Types": [0x7E42F87F, 0xBB96607D],
        "Save Game Types": [0xBDBE3B52, 0x5FDACBA0, 0x5ED7B213, 0x12DE6C4C],
        "World Types": [0xFBB63E47],
        "Property System Types": [0x0984415E, 0x18B8C0DE, 0xC0A01091, 0xF8206AF7],
        "Container Types": [0xA9E0C685, 0x11598A66],
        "OPTIONS Types": [0x1C0637AB, 0xDCCBD617, 0x569CD276, 0x9E293373],
        "Player Options Types": [0xCAC5F9B3, 0x7879288E, 0x2DAD13E3, 0xE9DDD041],
        "Additional Types": [0xA1A85298, 0x85C817C3, 0xC69A7F31, 0x21C2D472],
    }

    for category, hashes in categories.items():
        print(f"{category}:")
        print("-" * 40)
        for h in hashes:
            if h in TYPE_HASHES:
                print(f"  0x{h:08X}  {TYPE_HASHES[h]}")
        print()

    print("Table ID to Type Mapping:")
    print("-" * 40)
    for table_id, type_hash in TABLE_ID_TO_TYPE.items():
        print(f"  Table 0x{table_id:02X} -> {format_type_info(type_hash)}")
    print()

    print(f"Total known types: {len(TYPE_HASHES)}")
    print("=" * 80)


def scan_for_type_hashes(data: bytes, label: str = "Block") -> list:
    """
    Scan binary data for known type hashes and return matches.

    Args:
        data: Binary data to scan
        label: Label for output (e.g., "Block 2")

    Returns:
        List of tuples (offset, type_hash, type_name)
    """
    found_types = []
    for i in range(len(data) - 3):
        # Read 4 bytes as little-endian uint32
        val = struct.unpack('<I', data[i:i+4])[0]
        if val in TYPE_HASHES:
            found_types.append((i, val, TYPE_HASHES[val]))
    return found_types


def print_found_types(found_types: list, max_display: int = 10):
    """Print found type hashes with their offsets."""
    if not found_types:
        print("  No known type hashes found")
        return

    # Group by type
    by_type = {}
    for offset, type_hash, type_name in found_types:
        key = (type_hash, type_name)
        if key not in by_type:
            by_type[key] = []
        by_type[key].append(offset)

    print(f"  Found {len(found_types)} type hash occurrences ({len(by_type)} unique types):")
    for (type_hash, type_name), offsets in sorted(by_type.items(), key=lambda x: -len(x[1])):
        if len(offsets) <= 3:
            offset_str = ', '.join(f'0x{o:04X}' for o in offsets)
        else:
            offset_str = f"0x{offsets[0]:04X}, 0x{offsets[1]:04X}, ... ({len(offsets)} total)"
        print(f"    {type_name:25s} (0x{type_hash:08X}) at {offset_str}")


class SavHeader:
    """Represents a 44-byte header from the savegame file"""

    def __init__(self, data: bytes, offset: int):
        """Parse header from 44 bytes"""
        if len(data) < 44:
            raise ValueError(f"Header data too short: {len(data)} bytes")

        self.offset = offset

        # Parse all 11 fields (4 bytes each)
        self.field1 = struct.unpack('<I', data[0x00:0x04])[0]
        self.field2 = struct.unpack('<I', data[0x04:0x08])[0]
        self.field3 = struct.unpack('<I', data[0x08:0x0C])[0]
        self.field4 = struct.unpack('<I', data[0x0C:0x10])[0]

        # GUID (8 bytes as two 4-byte values)
        self.guid_low = struct.unpack('<I', data[0x10:0x14])[0]
        self.guid_high = struct.unpack('<I', data[0x14:0x18])[0]

        self.magic3 = struct.unpack('<I', data[0x18:0x1C])[0]
        self.magic4 = struct.unpack('<I', data[0x1C:0x20])[0]
        self.compressed_size = struct.unpack('<I', data[0x20:0x24])[0]
        self.uncompressed_size = struct.unpack('<I', data[0x24:0x28])[0]
        self.checksum = struct.unpack('<I', data[0x28:0x2C])[0]

    def __repr__(self):
        return (f"SavHeader(offset=0x{self.offset:04X}, "
                f"field1=0x{self.field1:08X}, field2=0x{self.field2:08X}, "
                f"field3=0x{self.field3:08X}, field4=0x{self.field4:08X}, "
                f"guid=0x{self.guid_high:08X}{self.guid_low:08X}, "
                f"compressed={self.compressed_size}, uncompressed={self.uncompressed_size}, "
                f"checksum=0x{self.checksum:08X})")

    def validate_checksum(self, compressed_data: bytes) -> bool:
        """Validate checksum against compressed data"""
        calculated = adler32(compressed_data)
        return calculated == self.checksum


def parse_savegame(filepath: str, output_dir: str = None, scan_types: bool = False):
    """
    Parse AC Brotherhood savegame file and extract all blocks

    Args:
        filepath: Path to ACBROTHERHOODSAVEGAME0.SAV
        output_dir: Directory to write output files (defaults to same dir as input)
        scan_types: If True, scan blocks for known type hashes

    Returns:
        Dictionary with parse results
    """
    if not os.path.exists(filepath):
        return {'success': False, 'error': f"File not found: {filepath}"}

    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(filepath))

    with open(filepath, 'rb') as f:
        data = f.read()

    total_size = len(data)
    print("=" * 80)
    print("AC Brotherhood Savegame Parser")
    print("=" * 80)
    print(f"\nFile: {filepath}")
    print(f"Total size: {total_size:,} bytes (0x{total_size:X})")
    print()

    decompressor = LZSSDecompressor()
    results = {}

    # =========================================================================
    # BLOCK 1: Header + LZSS compressed data
    # =========================================================================
    print("BLOCK 1 (Player Profile)")
    print("-" * 80)

    block1_header_offset = 0x0000
    block1_header_data = data[block1_header_offset:block1_header_offset + 44]
    block1_header = SavHeader(block1_header_data, block1_header_offset)

    print(f"Header at offset: 0x{block1_header_offset:04X}")
    print(f"  Field1:           0x{block1_header.field1:08X}")
    print(f"  Field2 (magic):   0x{block1_header.field2:08X}")
    print(f"  Field3 (marker):  0x{block1_header.field3:08X}")
    print(f"  Field4:           0x{block1_header.field4:08X}")
    print(f"  GUID:             0x{block1_header.guid_high:08X}{block1_header.guid_low:08X}")
    print(f"  Magic3:           0x{block1_header.magic3:08X}")
    print(f"  Magic4:           0x{block1_header.magic4:08X}")
    print(f"  Compressed size:  {block1_header.compressed_size} bytes")
    print(f"  Uncompressed size: {block1_header.uncompressed_size} bytes")
    print(f"  Checksum:         0x{block1_header.checksum:08X}")

    # Extract and decompress block 1 data
    block1_data_offset = 0x002C
    block1_compressed = data[block1_data_offset:block1_data_offset + block1_header.compressed_size]

    print(f"\nCompressed data at: 0x{block1_data_offset:04X}")
    print(f"Compressed size:    {len(block1_compressed)} bytes")

    # Validate checksum
    checksum_valid = block1_header.validate_checksum(block1_compressed)
    calculated_checksum = adler32(block1_compressed)
    print(f"Checksum validation: {'PASS' if checksum_valid else 'FAIL'}")
    print(f"  Expected:  0x{block1_header.checksum:08X}")
    print(f"  Calculated: 0x{calculated_checksum:08X}")

    # Decompress
    block1_decompressed = decompressor.decompress(block1_compressed)
    print(f"\nDecompressed size:  {len(block1_decompressed)} bytes")
    print(f"Expected size:      {block1_header.uncompressed_size} bytes")
    print(f"Size match:         {'PASS' if len(block1_decompressed) == block1_header.uncompressed_size else 'FAIL'}")

    # Save block 1
    output_file = os.path.join(output_dir, "sav_block1_decompressed.bin")
    with open(output_file, 'wb') as f:
        f.write(block1_decompressed)
    print(f"Output: {output_file}")

    # Show sample
    print("\nSample (first 32 bytes):")
    for i in range(0, min(32, len(block1_decompressed)), 16):
        hex_str = ' '.join(f'{b:02x}' for b in block1_decompressed[i:i+16])
        print(f"  {i:04x}: {hex_str}")

    # Scan for type hashes if requested
    if scan_types:
        print("\nType hash scan:")
        found_types = scan_for_type_hashes(block1_decompressed, "Block 1")
        print_found_types(found_types)

    results['block1'] = {
        'header': block1_header,
        'decompressed': block1_decompressed,
        'checksum_valid': checksum_valid
    }

    # =========================================================================
    # BLOCK 2: Header + LZSS compressed data
    # =========================================================================
    print("\n" + "=" * 80)
    print("BLOCK 2 (Game State)")
    print("-" * 80)

    # Calculate Block 2 header offset dynamically based on Block 1 size
    # Block 2 header immediately follows Block 1 compressed data
    block2_header_offset = block1_data_offset + block1_header.compressed_size
    block2_header_data = data[block2_header_offset:block2_header_offset + 44]
    block2_header = SavHeader(block2_header_data, block2_header_offset)

    print(f"Header at offset: 0x{block2_header_offset:04X}")
    print(f"  Field1:           0x{block2_header.field1:08X}")
    print(f"  Field2:           0x{block2_header.field2:08X}")
    print(f"  Field3 (marker):  0x{block2_header.field3:08X}")
    print(f"  Field4:           0x{block2_header.field4:08X}")
    print(f"  GUID:             0x{block2_header.guid_high:08X}{block2_header.guid_low:08X}")
    print(f"  Magic3:           0x{block2_header.magic3:08X}")
    print(f"  Magic4:           0x{block2_header.magic4:08X}")
    print(f"  Compressed size:  {block2_header.compressed_size} bytes")
    print(f"  Uncompressed size: {block2_header.uncompressed_size} bytes")
    print(f"  Checksum:         0x{block2_header.checksum:08X}")

    # Extract and decompress block 2 data
    # Block 2 data immediately follows Block 2 header (44 bytes after header start)
    block2_data_offset = block2_header_offset + 44
    block2_compressed = data[block2_data_offset:block2_data_offset + block2_header.compressed_size]

    print(f"\nCompressed data at: 0x{block2_data_offset:04X}")
    print(f"Compressed size:    {len(block2_compressed)} bytes")

    # Validate checksum
    checksum_valid = block2_header.validate_checksum(block2_compressed)
    calculated_checksum = adler32(block2_compressed)
    print(f"Checksum validation: {'PASS' if checksum_valid else 'FAIL'}")
    print(f"  Expected:  0x{block2_header.checksum:08X}")
    print(f"  Calculated: 0x{calculated_checksum:08X}")

    # Decompress
    block2_decompressed = decompressor.decompress(block2_compressed)
    print(f"\nDecompressed size:  {len(block2_decompressed)} bytes")
    print(f"Expected size:      {block2_header.uncompressed_size} bytes")
    print(f"Size match:         {'PASS' if len(block2_decompressed) == block2_header.uncompressed_size else 'FAIL'}")

    # Save block 2
    output_file = os.path.join(output_dir, "sav_block2_decompressed.bin")
    with open(output_file, 'wb') as f:
        f.write(block2_decompressed)
    print(f"Output: {output_file}")

    # Show sample
    print("\nSample (first 32 bytes):")
    for i in range(0, min(32, len(block2_decompressed)), 16):
        hex_str = ' '.join(f'{b:02x}' for b in block2_decompressed[i:i+16])
        print(f"  {i:04x}: {hex_str}")

    # Scan for type hashes if requested
    if scan_types:
        print("\nType hash scan:")
        found_types = scan_for_type_hashes(block2_decompressed, "Block 2")
        print_found_types(found_types)

    results['block2'] = {
        'header': block2_header,
        'decompressed': block2_decompressed,
        'checksum_valid': checksum_valid
    }

    # =========================================================================
    # BLOCK 3: Uncompressed data (follows Block 2 compressed data)
    # =========================================================================
    print("\n" + "=" * 80)
    print("BLOCK 3 (Uncompressed)")
    print("-" * 80)

    # Calculate offset dynamically from Block 2
    block3_offset = block2_data_offset + block2_header.compressed_size

    # Parse Block 3's nested headers to find Region 4 which declares Block 4's size
    # Block 3 has 4 nested headers with pattern: 01 XX XX XX 00 00 80 00
    block3_regions = []
    search_pos = block3_offset
    for region_num in range(4):
        # Find next header with pattern: version=0x01, size (3 bytes), 00 00 80 00
        while search_pos < total_size - 8:
            if (data[search_pos] == 0x01 and
                data[search_pos+4:search_pos+8] == b'\x00\x00\x80\x00'):
                region_size = struct.unpack('<I', data[search_pos+1:search_pos+4] + b'\x00')[0]
                if 0 < region_size < 50000:  # Sanity check
                    block3_regions.append((search_pos, region_size))
                    # Move past this header + data + 5-byte gap
                    search_pos = search_pos + 8 + region_size + 5
                    break
            search_pos += 1

    # Region 4's declared size equals Block 4's compressed size (cross-block reference)
    if len(block3_regions) >= 4:
        region4_offset, block4_compressed_size = block3_regions[3]
        # Block 3 ends after Region 4 header (8 bytes) + Region 4 data (5 bytes)
        # Region 4 only has 5 bytes of local data, not the declared size
        block3_end = region4_offset + 8 + 5  # header + 5-byte local data
        block3_size = block3_end - block3_offset
    else:
        # Fallback to old hardcoded value if header parsing fails
        print("WARNING: Could not parse Block 3 headers, using fallback size")
        block3_size = 7972
        block4_compressed_size = None

    block3_data = data[block3_offset:block3_offset + block3_size]

    print(f"Offset: 0x{block3_offset:04X}")
    print(f"Size:   {len(block3_data):,} bytes")

    # Save block 3
    output_file = os.path.join(output_dir, "sav_block3_raw.bin")
    with open(output_file, 'wb') as f:
        f.write(block3_data)
    print(f"Output: {output_file}")

    # Show sample
    print("\nSample (first 32 bytes):")
    for i in range(0, min(32, len(block3_data)), 16):
        hex_str = ' '.join(f'{b:02x}' for b in block3_data[i:i+16])
        print(f"  {i:04x}: {hex_str}")

    # Scan for type hashes if requested (Block 3 uses compact format)
    if scan_types:
        print("\nType hash scan (compact format block):")
        found_types = scan_for_type_hashes(block3_data, "Block 3")
        print_found_types(found_types)

    results['block3'] = {
        'raw': block3_data
    }

    # =========================================================================
    # BLOCK 4: LZSS compressed (no header) - between Block 3 and Block 5
    # Block 4 size is declared in Block 3 Region 4's header
    # =========================================================================
    print("\n" + "=" * 80)
    print("BLOCK 4 (LZSS - No Header)")
    print("-" * 80)

    # Block 4 starts immediately after Block 3
    block4_offset = block3_offset + block3_size

    # Use the size from Block 3 Region 4 if available
    if block4_compressed_size is not None:
        block4_size = block4_compressed_size
    else:
        # Fallback: search for Block 5 header to determine Block 4 end
        block5_offset = None
        for i in range(block4_offset + 100, total_size - 8):
            if (data[i] == 0x01 and
                data[i+4:i+8] == b'\x00\x00\x80\x00'):
                region_size = struct.unpack('<I', data[i+1:i+4] + b'\x00')[0]
                if 0 < region_size < 10000:
                    block5_offset = i
                    break
        if block5_offset is None:
            # Last resort fallback
            block5_offset = total_size - 6266
        block4_size = block5_offset - block4_offset

    block4_compressed = data[block4_offset:block4_offset + block4_size]

    # Calculate Block 5 offset (immediately after Block 4)
    block5_offset = block4_offset + block4_size
    block5_size = total_size - block5_offset

    print(f"Compressed data at: 0x{block4_offset:04X}")
    print(f"Compressed size:    {len(block4_compressed)} bytes")

    # Decompress
    block4_decompressed = decompressor.decompress(block4_compressed)
    print(f"Decompressed size:  {len(block4_decompressed)} bytes")

    # Save block 4
    output_file = os.path.join(output_dir, "sav_block4_decompressed.bin")
    with open(output_file, 'wb') as f:
        f.write(block4_decompressed)
    print(f"Output: {output_file}")

    # Show sample
    print("\nSample (first 32 bytes):")
    for i in range(0, min(32, len(block4_decompressed)), 16):
        hex_str = ' '.join(f'{b:02x}' for b in block4_decompressed[i:i+16])
        print(f"  {i:04x}: {hex_str}")

    # Scan for type hashes if requested
    if scan_types:
        print("\nType hash scan:")
        found_types = scan_for_type_hashes(block4_decompressed, "Block 4")
        print_found_types(found_types)

    results['block4'] = {
        'decompressed': block4_decompressed,
        'offset': block4_offset,
        'compressed_size': block4_size
    }

    # =========================================================================
    # BLOCK 5: Uncompressed data (immediately follows Block 4)
    # Size is variable - calculated as remaining bytes after Block 4
    # =========================================================================
    print("\n" + "=" * 80)
    print("BLOCK 5 (Uncompressed)")
    print("-" * 80)

    # block5_offset and block5_size already calculated after Block 4
    block5_data = data[block5_offset:block5_offset + block5_size]

    print(f"Offset: 0x{block5_offset:04X}")
    print(f"Size:   {len(block5_data):,} bytes")

    # Save block 5
    output_file = os.path.join(output_dir, "sav_block5_raw.bin")
    with open(output_file, 'wb') as f:
        f.write(block5_data)
    print(f"Output: {output_file}")

    # Show sample
    print("\nSample (first 32 bytes):")
    for i in range(0, min(32, len(block5_data)), 16):
        hex_str = ' '.join(f'{b:02x}' for b in block5_data[i:i+16])
        print(f"  {i:04x}: {hex_str}")

    # Scan for type hashes if requested (Block 5 uses compact format)
    if scan_types:
        print("\nType hash scan (compact format block):")
        found_types = scan_for_type_hashes(block5_data, "Block 5")
        print_found_types(found_types)

    results['block5'] = {
        'raw': block5_data
    }

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 80)
    print("PARSING SUMMARY")
    print("=" * 80)
    print(f"\nBlock 1: {len(block1_decompressed):,} bytes decompressed (checksum: {'PASS' if results['block1']['checksum_valid'] else 'FAIL'})")
    print(f"Block 2: {len(block2_decompressed):,} bytes decompressed (checksum: {'PASS' if results['block2']['checksum_valid'] else 'FAIL'})")
    print(f"Block 3: {len(block3_data):,} bytes raw")
    print(f"Block 4: {len(block4_decompressed):,} bytes decompressed")
    print(f"Block 5: {len(block5_data):,} bytes raw")

    total_parsed = (44 + len(block1_compressed) +
                    44 + len(block2_compressed) +
                    len(block3_data) +
                    len(block4_compressed) +
                    len(block5_data))
    print(f"\nTotal bytes parsed: {total_parsed:,} / {total_size:,} ({total_parsed/total_size*100:.1f}%)")

    print("\n" + "=" * 80)
    print("SUCCESS: All blocks extracted")
    print("=" * 80)

    results['success'] = True
    return results


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='AC Brotherhood Savegame Parser',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Output files:
  sav_block1_decompressed.bin - Block 1 (283 bytes - player profile)
  sav_block2_decompressed.bin - Block 2 (32KB - game state)
  sav_block3_raw.bin          - Block 3 (variable - uncompressed, compact format)
  sav_block4_decompressed.bin - Block 4 (~32KB - inventory items)
  sav_block5_raw.bin          - Block 5 (variable - uncompressed, compact format)

Examples:
  python sav_parser.py ACBROTHERHOODSAVEGAME0.SAV
  python sav_parser.py ACBROTHERHOODSAVEGAME0.SAV --scan-types
  python sav_parser.py --types
"""
    )

    parser.add_argument('savefile', nargs='?', help='Path to SAV file to parse')
    parser.add_argument('--types', '-t', action='store_true',
                        help='Print all known type hashes and exit')
    parser.add_argument('--scan-types', '-s', action='store_true',
                        help='Scan blocks for known type hashes during parsing')
    parser.add_argument('--output-dir', '-o', type=str, default=None,
                        help='Output directory for extracted blocks')

    args = parser.parse_args()

    # Handle --types flag
    if args.types:
        print_known_types()
        return 0

    # Require savefile if not using --types
    if not args.savefile:
        parser.print_help()
        return 0

    result = parse_savegame(args.savefile, output_dir=args.output_dir, scan_types=args.scan_types)

    if not result.get('success', False):
        print(f"ERROR: {result.get('error', 'Unknown error')}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
