#!/usr/bin/env python3
"""
SAV Serializer - Round-trip serialization for AC Brotherhood save files
========================================================================

DEPRECATED (July 2026): built on the fixed 5-block layout, which only matches
a small fresh save. Real saves hold 6-16 self-contained LZSS frames after
Blocks 1-2. Use ../acb_facebookcape_unlocker.py (frame-based splicing) instead.

Rebuilds a SAV file from decompressed/raw blocks with full header and checksum support.

File Layout:
    Block 1: 44-byte header + LZSS compressed data
    Block 2: 44-byte header + LZSS compressed data
    Block 3: Raw data (no header, no compression)
    Block 4: LZSS compressed data only (no header)
    Block 5: Raw data (no header, no compression)

Type System:
    The Scimitar/AnvilNext engine uses hash-based type identification.
    See docs/TYPE_SYSTEM_REFERENCE.md for complete type documentation.
"""

import struct
import sys
import os
import argparse

# Import LZSS compressor
from lzss import compress_with_debug as compress_lzss_lazy

# =============================================================================
# Scimitar Engine Type System - Hash Definitions
# =============================================================================
# These type hashes are used throughout the SAV and OPTIONS files for
# object serialization. Discovered via Ghidra decompilation of ACBSP.exe.

# Root/Base Types
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
    # Used for game state serialization in compact format
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
    # These are part of a family of 100+ types used for game state serialization
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

# =============================================================================
# Key Function Addresses (ACBSP.exe offsets from module base)
# =============================================================================
# These addresses are relative to the ACBSP module base (varies with ASLR).
# Example: If ACBSP loads at 0x00F30000, compressor is at 0x026BE140.

SERIALIZER_ADDRESSES = {
    # Type System Functions
    "TypeTableLookup":          0x01AEAF70,  # Looks up type descriptor by table ID
    "SerializeTypeReference":   0x00427530,  # Deserializes a typed reference (dual-mode: direct/indirect)
    "SerializeWithCustomFunc":  0x004274A0,  # Serializes with custom function pointer
    "SubObjectSerializer":      0x004268A0,  # Dispatches SubObject serialization
    "TypeRefIndirectHandler":   0x01AF6420,  # TYPE_REF indirect handler wrapper
    "TypeResolutionWithLookup": 0x01AE9390,  # Type resolution with descriptor chain lookup
    "TreeMapLookup":            0x01B1EEB0,  # Looks up entry by key in tree map
    "AssignmentHelper":         0x004253E0,  # Assignment helper for type handles
    "CleanupDestructor":        0x0041DC10,  # Cleanup/destructor for type handles

    # Deserialization System Functions (discovered via WinDbg TTD)
    "ObjectCreatorByTableID":   0x01AEB020,  # Creates/retrieves object instance by table ID
    "BufferDeserializer":       0x01AF6A40,  # Buffer reader with prefix dispatch (0x00/0x01/else)
    "ObjectInitWithLookup":     0x01AF2BB0,  # Object initialization via FUN_01AEAF70
    "DeserializationEntry1":    0x01AEF890,  # Higher-level deserialization entry point
    "DeserializationEntry2":    0x01AEF9D0,  # Alternative deserialization entry point
    "PassThroughWrapper":       0x01AF0490,  # Pass-through wrapper in deser chain
    "GeneratedFullDeserializer":0x00421110,  # Generated deserializer for full format (Blocks 2/4)

    # Serializer Helper Functions
    "SerializeBasicValue":      0x01B0A1F0,  # Serializes 4-byte basic types
    "SerializeBoolean":         0x01B09650,  # Serializes 1-byte boolean
    "SerializeSpecial":         0x01B09980,  # Serializes special field type
    "SerializeTypedRef":        0x01B099A0,  # Serializes with type hash
    "SerializeDynamic":         0x01B09620,  # Handles dynamic/variable properties
    "EndSerialization":         0x01B0D0C0,  # Finalizes object serialization
    "RegisterBaseClass":        0x01B17F90,  # Registers parent type (ManagedObject)
    "RegisterTypeName":         0x01B09E20,  # Registers type with name and hash

    # Object Serializers
    "WorldSerializer":          0x004976D0,  # Serializes World objects
    "SaveGameSerializer":       0x005E3560,  # Serializes SaveGame
    "SaveGameDeserializer":     0x005E3870,  # Deserializes SaveGame
    "MissionSaveDataSerializer":0x005FCE60,  # Serializes MissionSaveData
    "RewardFaultSerializer":    0x005FCB30,  # Serializes RewardFault
    "OPTIONSSerializer":        0x01BE02F0,  # Serializes OPTIONS struct
    "OPTIONSDeserializer":      0x01BE0370,  # Deserializes OPTIONS struct
    "PlayerOptionsSerializer":  0x00BCA460,  # Serializes PlayerOptions
    "PlayerOptionsSaveDataSer": 0x00BC9080,  # Serializes PlayerOptionsSaveData
    "PlayerOptionsElementSer":  0x005196A0,  # Serializes PlayerOptionsElement

    # Compression (same for OPTIONS and SAV files)
    "CompressionEntry":         0x0178E140,  # LZSS compression entry point
    "MatchFinder":              0x0178E0A0,  # Match finder function
}

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
    name = get_type_name(type_hash)
    return f"0x{type_hash:08X} ({name})"


def is_known_type(type_hash: int) -> bool:
    """
    Check if a type hash is in our known types dictionary.

    Args:
        type_hash: 32-bit type hash value

    Returns:
        True if type is known, False otherwise
    """
    return type_hash in TYPE_HASHES


# =============================================================================
# Compact Format Constants (Blocks 3, 5)
# =============================================================================
# 4-byte patterns: [prefix] [type_indicator] [table_id] [property_index]

COMPACT_PREFIX_TABLE_REF = 0x0803  # Fixed property reference
COMPACT_PREFIX_FIXED32 = 0x0502   # 4-byte fixed value
COMPACT_PREFIX_VARINT = 0x1405    # Variable-length integer
COMPACT_PREFIX_EXTENDED = 0x0C18  # Extended format with modifier

# =============================================================================
# File Format Constants
# =============================================================================

# Constants from game
GUID_LOW = 0x57FBAA33
GUID_HIGH = 0x1004FA99
MAGIC3 = 0x00020001
MAGIC4 = 0x01000080


def adler32(data: bytes) -> int:
    """
    Adler-32 checksum with ZERO SEED (game variant).
    Standard Adler-32 uses s1=1, s2=0; game uses s1=0, s2=0.
    """
    MOD_ADLER = 65521
    s1 = 0
    s2 = 0
    for byte in data:
        s1 = (s1 + byte) % MOD_ADLER
        s2 = (s2 + s1) % MOD_ADLER
    return (s2 << 16) | s1


def build_block1_header(compressed_data: bytes, uncompressed_size: int) -> bytes:
    """
    Build 44-byte header for Block 1.

    Field3 = compressed_size + 32 (verified from documentation)
    """
    compressed_size = len(compressed_data)
    checksum = adler32(compressed_data)

    header = struct.pack('<11I',
        0x00000016,              # Field1: Static value
        0x00FEDBAC,              # Field2: Magic marker
        compressed_size + 32,    # Field3: compressed_size + 32
        uncompressed_size,       # Field4: Uncompressed size
        GUID_LOW,                # Magic1 (GUID low)
        GUID_HIGH,               # Magic2 (GUID high)
        MAGIC3,                  # Magic3
        MAGIC4,                  # Magic4
        compressed_size,         # Compressed size
        uncompressed_size,       # Uncompressed size (duplicate)
        checksum                 # Checksum
    )
    return header


def calculate_block2_field4(block2_decompressed: bytes) -> int:
    """
    Calculate Block 2 Field4 from decompressed content.

    Field4 = value_at_offset_0x0E + 0x12 (18 decimal)

    CONFIRMED via WinDbg TTD (January 2025):
      The game calculates Field4 as: current_stream_position - buffer_start
      This equals total bytes consumed from decompressed data.

      In FUN_01B6F170 at offset +0x176f18b:
        mov eax, [esi+14h]    ; buffer_start
        mov edx, [esi+18h]    ; current_position
        sub edx, eax          ; Field4 = bytes consumed

    The formula value_at_0x0E + 0x12 works because:
      - 10 bytes null padding (0x00-0x09)
      - 4 bytes type hash (0x0A-0x0D)
      - 4 bytes size field at 0x0E
      = 18 bytes (0x12) fixed header + object data size

    Verified across 8 SAV files with 100% accuracy.

    Args:
        block2_decompressed: Decompressed Block 2 data

    Returns:
        Calculated Field4 value
    """
    if len(block2_decompressed) < 0x12:
        raise ValueError("Block 2 data too small to calculate Field4")

    val_0e = struct.unpack('<I', block2_decompressed[0x0E:0x12])[0]
    return val_0e + 0x12


def build_block2_header(compressed_data: bytes, uncompressed_size: int, remaining_file_size: int,
                        field4: int = None, block2_decompressed: bytes = None) -> bytes:
    """
    Build 44-byte header for Block 2.

    Field1 = remaining_file_size - 4
    Field4 = value_at_decompressed_offset_0x0E + 0x12

    Field4 calculation (CONFIRMED via TTD - January 2025):
      The game computes Field4 = stream_end - stream_start = bytes consumed.
      See calculate_block2_field4() for the exact assembly instructions.

      Formula: Field4 = struct.unpack('<I', decompressed[0x0E:0x12])[0] + 0x12
      Verified across 8 SAV files with 100% accuracy.

    Args:
        field4: If provided, use this value directly.
        block2_decompressed: If provided and field4 is None, calculate Field4 from this.
    """
    compressed_size = len(compressed_data)
    checksum = adler32(compressed_data)

    # Calculate field4 from decompressed content if not provided
    if field4 is None:
        if block2_decompressed is not None:
            field4 = calculate_block2_field4(block2_decompressed)
        else:
            # Legacy fallback - should not be reached in normal operation
            raise ValueError("Cannot calculate Field4: need either field4 value or block2_decompressed data")

    header = struct.pack('<11I',
        remaining_file_size - 4,  # Field1: remaining_file_size - 4
        0x00000001,               # Field2: Section number
        0x00CAFE00,               # Field3: Magic marker
        field4,                   # Field4: Size-related
        GUID_LOW,                 # Magic1 (GUID low)
        GUID_HIGH,                # Magic2 (GUID high)
        MAGIC3,                   # Magic3
        MAGIC4,                   # Magic4
        compressed_size,          # Compressed size
        uncompressed_size,        # Uncompressed size
        checksum                  # Checksum
    )
    return header


def find_region4_in_block3(block3_data: bytes) -> int:
    """
    Find Region 4's offset within Block 3 data.

    Block 3 contains 4 regions with headers:
      [01] [size 3B LE] [00 00 80 00] [00] [checksum 4B] [data...]

    Region 4 is special:
      - Its declared size = Block 4's compressed LZSS size
      - Its checksum = Adler32 of Block 4's compressed data
      - It only has 5 bytes of local data

    Returns:
        Offset of Region 4 within block3_data, or -1 if not found
    """
    pos = 0
    region_count = 0

    while pos < len(block3_data) - 8 and region_count < 4:
        # Look for region header pattern: [01] [size 3B] [00 00 80 00]
        if (block3_data[pos] == 0x01 and
            block3_data[pos+4:pos+8] == b'\x00\x00\x80\x00'):

            region_count += 1
            if region_count == 4:
                return pos

            # Parse size to skip to next region
            region_size = struct.unpack('<I', block3_data[pos+1:pos+4] + b'\x00')[0]
            # Move past: 8-byte header + region_size bytes + 5-byte gap
            pos = pos + 8 + region_size + 5
        else:
            pos += 1

    return -1


def update_block3_region4(block3_data: bytes, new_block4_size: int, block4_compressed: bytes) -> bytes:
    """
    Update Block 3's Region 4 header with new Block 4 size and checksum.

    Region 4 structure:
      0x00: Version (0x01)
      0x01: Size (24-bit LE) - Block 4 compressed size
      0x04: Flags (0x00008000)
      0x08: Prefix (0x00)
      0x09: Checksum (4 bytes) - Adler32 of Block 4 compressed data
      0x0D: Local data (5 bytes)

    Args:
        block3_data: Original Block 3 raw data
        new_block4_size: New Block 4 compressed size
        block4_compressed: New Block 4 compressed data (for checksum)

    Returns:
        Updated Block 3 data with corrected Region 4
    """
    block3 = bytearray(block3_data)

    r4_offset = find_region4_in_block3(block3)
    if r4_offset == -1:
        print("  WARNING: Could not find Region 4 in Block 3, skipping update")
        return bytes(block3)

    old_size = struct.unpack('<I', block3[r4_offset+1:r4_offset+4] + b'\x00')[0]
    old_checksum = struct.unpack('<I', block3[r4_offset+9:r4_offset+13])[0]

    # Update size (24-bit LE at offset +1)
    size_bytes = struct.pack('<I', new_block4_size)[:3]  # Take lower 3 bytes
    block3[r4_offset+1:r4_offset+4] = size_bytes

    # Update checksum (32-bit LE at offset +9)
    new_checksum = adler32(block4_compressed)
    block3[r4_offset+9:r4_offset+13] = struct.pack('<I', new_checksum)

    print(f"  Updated Region 4 at offset 0x{r4_offset:04X}:")
    print(f"    Size: {old_size} -> {new_block4_size}")
    print(f"    Checksum: 0x{old_checksum:08X} -> 0x{new_checksum:08X}")

    return bytes(block3)


class SavSerializer:
    """Serializer for AC Brotherhood SAV files."""

    def __init__(self):
        self.block1_decompressed = None
        self.block2_decompressed = None
        self.block3_raw = None
        self.block4_decompressed = None
        self.block5_raw = None
        self.block2_field4 = None  # Original Field4 from source SAV (for byte-perfect round-trip)

    def load_blocks(self, block1_path: str, block2_path: str, block3_path: str,
                    block4_path: str, block5_path: str):
        """Load all blocks from files."""
        with open(block1_path, 'rb') as f:
            self.block1_decompressed = f.read()
        with open(block2_path, 'rb') as f:
            self.block2_decompressed = f.read()
        with open(block3_path, 'rb') as f:
            self.block3_raw = f.read()
        with open(block4_path, 'rb') as f:
            self.block4_decompressed = f.read()
        with open(block5_path, 'rb') as f:
            self.block5_raw = f.read()

        print(f"Loaded blocks:")
        print(f"  Block 1: {len(self.block1_decompressed)} bytes (decompressed)")
        print(f"  Block 2: {len(self.block2_decompressed)} bytes (decompressed)")
        print(f"  Block 3: {len(self.block3_raw)} bytes (raw)")
        print(f"  Block 4: {len(self.block4_decompressed)} bytes (decompressed)")
        print(f"  Block 5: {len(self.block5_raw)} bytes (raw)")

    def serialize(self) -> bytes:
        """Serialize all blocks into a complete SAV file."""
        if any(b is None for b in [self.block1_decompressed, self.block2_decompressed,
                                    self.block3_raw, self.block4_decompressed, self.block5_raw]):
            raise ValueError("Not all blocks loaded")

        print("\nCompressing blocks...")

        # Compress Block 1
        print("  Compressing Block 1...")
        block1_compressed, _, s1_count1 = compress_lzss_lazy(self.block1_decompressed)
        print(f"    {len(self.block1_decompressed)} -> {len(block1_compressed)} bytes (S1: {s1_count1})")

        # Compress Block 2
        print("  Compressing Block 2...")
        block2_compressed, _, s1_count2 = compress_lzss_lazy(self.block2_decompressed)
        print(f"    {len(self.block2_decompressed)} -> {len(block2_compressed)} bytes (S1: {s1_count2})")

        # Compress Block 4
        print("  Compressing Block 4...")
        block4_compressed, _, s1_count4 = compress_lzss_lazy(self.block4_decompressed)
        print(f"    {len(self.block4_decompressed)} -> {len(block4_compressed)} bytes (S1: {s1_count4})")

        # CRITICAL: Update Block 3's Region 4 with new Block 4 compressed size
        # Region 4 declares Block 4's size and checksum - must match actual compressed data
        print("\nUpdating Block 3 Region 4...")
        block3_updated = update_block3_region4(
            self.block3_raw,
            len(block4_compressed),
            block4_compressed
        )

        # Recalculate remaining file size (Block 3 size unchanged, but verify)
        remaining_after_block2_header = (
            44 + len(block2_compressed) +
            len(block3_updated) +
            len(block4_compressed) +
            len(self.block5_raw)
        )

        print("\nBuilding headers...")

        # Build headers
        block1_header = build_block1_header(block1_compressed, len(self.block1_decompressed))
        block2_header = build_block2_header(block2_compressed, len(self.block2_decompressed),
                                           remaining_after_block2_header, field4=self.block2_field4,
                                           block2_decompressed=self.block2_decompressed)

        print(f"  Block 1 header: 44 bytes, checksum=0x{adler32(block1_compressed):08X}")
        print(f"  Block 2 header: 44 bytes, checksum=0x{adler32(block2_compressed):08X}")

        # Assemble file
        print("\nAssembling file...")
        output = bytearray()

        # Block 1: header + compressed
        output.extend(block1_header)
        output.extend(block1_compressed)
        print(f"  After Block 1: {len(output)} bytes (offset 0x{len(output):04X})")

        # Block 2: header + compressed
        output.extend(block2_header)
        output.extend(block2_compressed)
        print(f"  After Block 2: {len(output)} bytes (offset 0x{len(output):04X})")

        # Block 3: raw (with updated Region 4)
        output.extend(block3_updated)
        print(f"  After Block 3: {len(output)} bytes (offset 0x{len(output):04X})")

        # Block 4: compressed only (no header)
        output.extend(block4_compressed)
        print(f"  After Block 4: {len(output)} bytes (offset 0x{len(output):04X})")

        # Block 5: raw
        output.extend(self.block5_raw)
        print(f"  After Block 5: {len(output)} bytes (offset 0x{len(output):04X})")

        print(f"\nTotal file size: {len(output)} bytes")

        return bytes(output)


def compare_files(file1: bytes, file2: bytes, label1: str = "File 1", label2: str = "File 2"):
    """Compare two files and report differences."""
    print(f"\nComparing {label1} vs {label2}:")
    print(f"  {label1} size: {len(file1)} bytes")
    print(f"  {label2} size: {len(file2)} bytes")

    if len(file1) != len(file2):
        print(f"  SIZE MISMATCH: {len(file1)} vs {len(file2)} ({len(file1) - len(file2):+d})")

    if file1 == file2:
        print("  PERFECT MATCH!")
        return True

    # Find differences
    differences = []
    min_len = min(len(file1), len(file2))
    for i in range(min_len):
        if file1[i] != file2[i]:
            differences.append((i, file1[i], file2[i]))
            if len(differences) >= 20:
                break

    if differences:
        print(f"  Found {len(differences)}+ differences:")
        for offset, b1, b2 in differences[:10]:
            print(f"    0x{offset:04X}: {b1:02X} vs {b2:02X}")
        if len(differences) > 10:
            print(f"    ... and {len(differences) - 10} more")

    return False


def main():
    parser = argparse.ArgumentParser(description='SAV Serializer for AC Brotherhood save files')
    parser.add_argument('--block1', '-1', help='Block 1 decompressed file')
    parser.add_argument('--block2', '-2', help='Block 2 decompressed file')
    parser.add_argument('--block3', '-3', help='Block 3 raw file')
    parser.add_argument('--block4', '-4', help='Block 4 decompressed file')
    parser.add_argument('--block5', '-5', help='Block 5 raw file')
    parser.add_argument('--output', '-o', required=True, help='Output SAV file')
    parser.add_argument('--compare', '-c', help='Original SAV file to compare against')
    parser.add_argument('--auto', '-a', action='store_true',
                        help='Auto-detect block files in current directory')

    args = parser.parse_args()

    serializer = SavSerializer()

    if args.auto:
        # Auto-detect block files
        base_dir = os.path.dirname(os.path.abspath(__file__))
        args.block1 = os.path.join(base_dir, 'sav_block1_decompressed.bin')
        args.block2 = os.path.join(base_dir, 'sav_block2_decompressed.bin')
        args.block3 = os.path.join(base_dir, 'sav_block3_raw.bin')
        args.block4 = os.path.join(base_dir, 'sav_block4_decompressed.bin')
        args.block5 = os.path.join(base_dir, 'sav_block5_raw.bin')
        print("Auto-detecting block files...")

    # Validate all block files are provided
    if not all([args.block1, args.block2, args.block3, args.block4, args.block5]):
        print("ERROR: All block files must be provided (use --auto for auto-detection)")
        return 1

    # Check files exist
    for path in [args.block1, args.block2, args.block3, args.block4, args.block5]:
        if not os.path.exists(path):
            print(f"ERROR: File not found: {path}")
            return 1

    # Load blocks
    serializer.load_blocks(args.block1, args.block2, args.block3, args.block4, args.block5)

    # Calculate Field4 from Block 2 decompressed data (formula: val@0x0E + 0x12)
    serializer.block2_field4 = calculate_block2_field4(serializer.block2_decompressed)
    print(f"\nCalculated Field4 from Block 2: 0x{serializer.block2_field4:08X}")

    # Serialize
    output_data = serializer.serialize()

    # Write output
    with open(args.output, 'wb') as f:
        f.write(output_data)
    print(f"\nWrote: {args.output}")

    # Compare if requested
    if args.compare:
        if os.path.exists(args.compare):
            with open(args.compare, 'rb') as f:
                original = f.read()
            compare_files(output_data, original, "Generated", "Original")
        else:
            print(f"WARNING: Comparison file not found: {args.compare}")

    return 0


if __name__ == "__main__":
    exit(main())
