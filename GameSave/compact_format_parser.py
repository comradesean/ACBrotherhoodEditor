#!/usr/bin/env python3
"""
Assassin's Creed Brotherhood - Compact Format Parser
=====================================================

INVALID (July 2026): "Blocks 3 and 5" are not raw compact data — they are
LZSS-COMPRESSED frames (each decompressing to exactly 32 KB, verified against
the adler32 checksums stored in every frame header). This parser reads the
compressed bytes directly, so the structures it reports (node prefixes,
regions, growth buffers) are compression artifacts, not file structures.
Runtime findings from the debugger (e.g. Judy Arrays in memory during load)
may still hold, but no byte-level conclusion from this parser should be
trusted. Kept for historical reference only.

Parser for SAV file Blocks 3 and 5 which use a compact binary format
with Judy Array node serialization and table-based type resolution.

Key Discovery (December 2024):
-----------------------------
The compact format uses **Judy Arrays** for property storage. The 2-byte
prefixes (0x1500, 0x1809, etc.) are Judy node type markers, not protobuf-style
wire types. This was confirmed via TTD debugging of FUN_01b25230.

Format Overview:
---------------
- 8-byte header per region (version, size, flags)
- Multiple nested regions in each block
- 5-byte inter-region gaps ending with 0x2000 terminator
- Judy array node serialization for property data

Judy Node Types:
---------------
| Type | Encoder | Key Size | Entry Count | Format |
|------|---------|----------|-------------|--------|
| 0x14 | FUN_01b24720 | 1 byte | [+4] + 1 | Linear leaf (variable) |
| 0x15 | FUN_01b249a0 | 3 bytes | [+4] + 1 | Linear leaf |
| 0x17 | FUN_01b24720 | 2 bytes | bitmap | Bitmap branch (up to 256) |
| 0x18 | FUN_01b24720 | 2 bytes | 1 | Single entry leaf |
| 0x19 | FUN_01b249a0 | 3 bytes | 1 | Single 3-byte entry |
| 0x1b | FUN_01b24720 | 1 byte | 2 | 2-element leaf |
| 0x1c | FUN_01b24720 | 1 byte | 3 | 3-element leaf |

Usage:
------
    python compact_format_parser.py references/sav_block3_raw.bin
    python compact_format_parser.py references/sav_block5_raw.bin --verbose
    python compact_format_parser.py references/sav_block3_raw.bin --regions --judy
"""

import sys
import os
import struct
import argparse
import json
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any, Union
from enum import Enum, auto


# =============================================================================
# Constants and Enums
# =============================================================================

class PrefixType(Enum):
    """Known compact format prefix types"""
    TABLE_REF = 0x0803      # Table ID + Property Index
    VARINT = 0x1405         # Variable-length integer
    FIXED32 = 0x0502        # 32-bit fixed value
    VALUE_15 = 0x1500       # 32-bit value (type 0x15)
    VALUE_12 = 0x1200       # 32-bit value (type 0x12)
    EXTENDED_1C = 0x1C04    # Extended value encoding
    ARRAY_ELEM = 0x173C     # Array element marker
    TYPE_REF_10 = 0x1006    # Type reference
    PREFIX_1809 = 0x1809    # Extended marker
    PREFIX_1907 = 0x1907    # Unknown prefix
    PREFIX_16E1 = 0x16E1    # Unknown prefix
    PREFIX_0C18 = 0x0C18    # Extended format
    # Judy node types
    JUDY_14 = 0x14          # Linear leaf (variable count, 1-byte keys)
    JUDY_15 = 0x15          # Linear leaf (3-byte keys)
    JUDY_17 = 0x17          # Bitmap branch
    JUDY_18 = 0x18          # Single entry leaf (2-byte key)
    JUDY_19 = 0x19          # Single 3-byte entry
    JUDY_1B = 0x1B          # 2-element leaf
    JUDY_1C = 0x1C          # 3-element leaf
    UNKNOWN = 0x0000


class JudyNodeType(Enum):
    """Judy array node types from FUN_01b24720 and FUN_01b249a0"""
    LINEAR_1BYTE_VAR = 0x14    # Variable count, 1-byte keys
    LINEAR_3BYTE = 0x15        # Variable count, 3-byte keys
    BITMAP_2BYTE = 0x17        # Bitmap branch, 2-byte keys
    SINGLE_2BYTE = 0x18        # Single entry, 2-byte key
    SINGLE_3BYTE = 0x19        # Single entry, 3-byte key
    LEAF_2ELEM = 0x1B          # 2-element leaf
    LEAF_3ELEM = 0x1C          # 3-element leaf


# Table ID to Type Hash mapping (104 entries from table_id_hash_simple.json)
TABLE_ID_TO_TYPE = {
    0x00: (0x87BFB8DB, "CompactType_00"),
    0x01: (0x5B0885B7, "CompactType_01"),
    0x02: (0x95DE1A76, "CompactType_02"),
    0x03: (0x6EC3C146, "CompactType_03"),
    0x04: (0x1039317E, "CompactType_04"),
    0x05: (0x0B1CA4FF, "CompactType_05"),
    0x06: (0x08999B6B, "CompactType_06"),
    0x07: (0xE45C13C1, "CompactType_07"),
    0x08: (0xC9A5839D, "CompactType_08"),
    0x09: (0x723C7DFD, "CompactType_09"),
    0x0A: (0xC438CAAA, "CompactType_0A"),
    0x0B: (0x82A2AEE0, "CompactType_0B"),
    0x0C: (0x885FD270, "CompactType_0C"),
    0x0D: (0x9ED73EC7, "CompactType_0D"),
    0x0E: (0xB01D2FBC, "CompactType_0E"),
    0x0F: (0x635ED6FD, "CompactType_0F"),
    0x10: (0x21389788, "CompactType_10"),
    0x11: (0x7C0A22D2, "CompactType_11"),
    0x12: (0x5E9D4672, "CompactType_12"),
    0x13: (0x9464A1DF, "CompactType_13"),
    0x14: (0xCE77DEA9, "CompactType_14"),
    0x15: (0xF34AE634, "CompactType_15"),
    0x16: (0x0AFD89DC, "PlayerOptionsElement"),
    0x17: (0x6FEB4D3E, "CompactType_17"),
    0x18: (0x1BD6AF74, "CompactType_18"),
    0x19: (0x7EC06B96, "CompactType_19"),
    0x1A: (0xFE52CE42, "CompactType_1A"),
    0x1B: (0x1EAE1A27, "CompactType_1B"),
    0x1C: (0xEEFD3C62, "CompactType_1C"),
    0x1D: (0x8178B0FC, "CompactType_1D"),
    0x1E: (0x35A73BF9, "CompactType_1E"),
    0x1F: (0xD17B9E84, "CompactType_1F"),
    0x20: (0x1B2159BE, "CompactType_20"),
    0x21: (0xC30FCF3C, "CompactType_21"),
    0x22: (0xB2AC9ECF, "CompactType_22"),
    0x23: (0xEEA84BEB, "CompactType_23"),
    0x24: (0xA387B867, "CompactType_24"),
    0x25: (0x07F84685, "CompactType_25"),
    0x26: (0x04B26A6F, "CompactType_26"),
    0x27: (0x649B330F, "CompactType_27"),
    0x28: (0xB17CA151, "CompactType_28"),
    0x29: (0xFDDE216B, "CompactType_29"),
    0x2A: (0x2EF0DC94, "CompactType_2A"),
    0x2B: (0x0A0EF2AB, "CompactType_2B"),
    0x2C: (0x0DF38019, "CompactType_2C"),
    0x2D: (0xB3423CBF, "CompactType_2D"),
    0x2E: (0x79985A47, "CompactType_2E"),
    0x2F: (0xBE427635, "CompactType_2F"),
    0x30: (0x969057FD, "CompactType_30"),
    0x31: (0xC31A6D47, "CompactType_31"),
    0x32: (0x0DC752FA, "CompactType_32"),
    0x33: (0xF04DFE62, "CompactType_33"),
    0x34: (0xC38E48D7, "CompactType_34"),
    0x35: (0xEAAC8DA8, "CompactType_35"),
    0x36: (0x33D71609, "CompactType_36"),
    0x37: (0x5949EFD9, "CompactType_37"),
    0x38: (0xFA1AA549, "CompactType_38"),
    0x39: (0x8FC5A10C, "CompactType_39"),
    0x3A: (0x3C4C3BD2, "CompactType_3A"),
    0x3B: (0xFC6EDE2A, "CompactType_3B"),
    0x3C: (0xF5718FB1, "CompactType_3C"),
    0x3D: (0xE051FC8F, "CompactType_3D"),
    0x3E: (0x83BA68A2, "CompactType_3E"),
    0x3F: (0x6D2E5F10, "CompactType_3F"),
    0x40: (0x762B59C4, "CompactType_40"),
    0x41: (0x252E9992, "CompactType_41"),
    0x42: (0xB507DD42, "CompactType_42"),
    0x43: (0xE27BFE05, "CompactType_43"),
    0x44: (0x4DAC6313, "CompactType_44"),
    0x45: (0xAF9F222E, "CompactType_45"),
    0x46: (0xE4181084, "CompactType_46"),
    0x47: (0x289AD354, "CompactType_47"),
    0x48: (0x8D474522, "CompactType_48"),
    0x49: (0x144E1498, "CompactType_49"),
    0x4A: (0x6349240E, "CompactType_4A"),
    0x4B: (0xFD2DB1AD, "CompactType_4B"),
    0x4C: (0x8A2A813B, "CompactType_4C"),
    0x4D: (0x1323D081, "CompactType_4D"),
    0x4E: (0x6424E017, "CompactType_4E"),
    0x4F: (0xF49BFD86, "CompactType_4F"),
    0x50: (0x839CCD10, "CompactType_50"),
    0x51: (0xE35B44F5, "CompactType_51"),
    0x52: (0x945C7463, "CompactType_52"),
    0x53: (0x0D5525D9, "CompactType_53"),
    0x54: (0x7A52154F, "CompactType_54"),
    0x55: (0xE43680EC, "CompactType_55"),
    0x56: (0x9331B07A, "CompactType_56"),
    0x57: (0x0A38E1C0, "CompactType_57"),
    0x58: (0x7D3FD156, "CompactType_58"),
    0x59: (0xED80CCC7, "CompactType_59"),
    0x5A: (0x9A87FC51, "CompactType_5A"),
    0x5B: (0xC8761736, "CompactType_5B"),
    0x5C: (0xE3E58C35, "CompactType_5C"),
    0x5D: (0x7AECDD8F, "CompactType_5D"),
    0x5E: (0x0DEBED19, "CompactType_5E"),
    0x5F: (0x938F78BA, "CompactType_5F"),
    0x60: (0xE488482C, "CompactType_60"),
    0x61: (0xE2A997E4, "CompactType_61"),
    0x62: (0x7BA0C65E, "CompactType_62"),
    0x63: (0x0CA7F6C8, "CompactType_63"),
    0x64: (0x92C3636B, "CompactType_64"),
    0x65: (0xE5C453FD, "CompactType_65"),
    0x66: (0x06337DCC, "CompactType_66"),
    0x67: (0x78A90B6B, "CompactType_67"),
    # Additional table IDs found in save files (beyond the 104 verified entries)
    0x95: (0x00000000, "Unknown_95"),
    0xDB: (0x00000000, "Unknown_DB"),
    0xE1: (0x00000000, "Unknown_E1"),
    0xFB: (0x00000000, "Unknown_FB"),
}

# Marker byte meanings
MARKER_TRUE = 0x6D   # Boolean TRUE or value 1
MARKER_FALSE = 0xDB  # Boolean FALSE or value 0
MARKER_CD = 0xCD     # Unknown separator/flag

# Known type hashes
TYPE_HASHES = {
    0xA1A85298: "PhysicalInventoryItem",
    0xF7D44F07: "Unknown_F7D44F07",
    0x0984415E: "PropertyReference",
    0xFBB63E47: "World",
    0x2DAD13E3: "PlayerOptionsElement",
    0xBDBE3B52: "SaveGame",
    0x5FDACBA0: "SaveGameDataObject",
}


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class CompactHeader:
    """8-byte compact format header"""
    version: int        # 1 byte - always 0x01
    data_size: int      # 3 bytes - little-endian 24-bit
    flags: int          # 4 bytes - always 0x00800000
    raw_bytes: bytes    # Original 8 bytes
    offset: int = 0     # Offset in file

    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> Optional['CompactHeader']:
        """Parse header from data at offset. Returns None if invalid."""
        if offset + 8 > len(data):
            return None
        raw = data[offset:offset + 8]
        version = raw[0]
        data_size = raw[1] | (raw[2] << 8) | (raw[3] << 16)
        flags = struct.unpack('<I', raw[4:8])[0]

        # Validate: version must be 0x01, flags must be 0x00800000
        if version != 0x01 or flags != 0x00800000:
            return None

        return cls(version=version, data_size=data_size, flags=flags,
                   raw_bytes=raw, offset=offset)

    def __str__(self):
        return f"Header(offset=0x{self.offset:04X}, version={self.version}, size={self.data_size}, flags=0x{self.flags:08X})"


@dataclass
class Region:
    """A data region within a compact format block"""
    index: int                  # Region number (1-based)
    header: CompactHeader       # 8-byte header
    data_start: int             # Start offset of data (after header)
    data_end: int               # End offset of data
    actual_size: int            # Actual data size
    gap_after: Optional[bytes]  # 5-byte gap after this region (if any)
    gap_offset: int = 0         # Offset of gap
    is_cross_block_ref: bool = False  # True if declared size >> actual size

    @property
    def declared_size(self) -> int:
        return self.header.data_size

    @property
    def size_delta(self) -> int:
        """Difference between actual and declared size"""
        return self.actual_size - self.declared_size


@dataclass
class InterRegionGap:
    """5-byte gap between regions"""
    offset: int
    type_byte: int
    value: int          # 16-bit little-endian value
    terminator: int     # Should be 0x0020 (LZSS terminator)
    raw_bytes: bytes

    @classmethod
    def parse(cls, data: bytes, offset: int) -> Optional['InterRegionGap']:
        """Parse 5-byte gap at offset. Returns None if not a valid gap."""
        if offset + 5 > len(data):
            return None
        raw = data[offset:offset + 5]
        type_byte = raw[0]
        value = raw[1] | (raw[2] << 8)
        terminator = raw[3] | (raw[4] << 8)

        # Terminator must be 0x0020 (stored as 20 00 in LE)
        if terminator != 0x0020:
            return None

        return cls(offset=offset, type_byte=type_byte, value=value,
                   terminator=terminator, raw_bytes=raw)

    def __str__(self):
        return f"Gap(offset=0x{self.offset:04X}, type=0x{self.type_byte:02X}, value={self.value})"


@dataclass
class JudyNode:
    """Parsed Judy array node"""
    offset: int
    node_type: int          # 0x14-0x1C
    count: int              # Number of entries
    keys: List[int]         # Key values (1, 2, or 3 bytes each)
    values: List[int]       # 4-byte dword values
    raw_bytes: bytes
    key_size: int           # 1, 2, or 3 bytes per key

    def __str__(self):
        return f"JudyNode(type=0x{self.node_type:02X}, count={self.count}, keys={self.keys[:3]}..., values={[hex(v) for v in self.values[:3]]}...)"


@dataclass
class TableRef:
    """TABLE_REF entry (0x0803 prefix)"""
    offset: int
    table_id: int
    property_id: int
    type_hash: Optional[int] = None
    type_name: Optional[str] = None

    def __post_init__(self):
        if self.table_id in TABLE_ID_TO_TYPE:
            self.type_hash, self.type_name = TABLE_ID_TO_TYPE[self.table_id]


@dataclass
class ExtendedValue:
    """Extended value entry (0x1C04 prefix)"""
    offset: int
    subtype: int
    value: Any
    raw_bytes: bytes


@dataclass
class ArrayElement:
    """Array element entry (0x173C prefix)"""
    offset: int
    element_type: int
    value: Any
    raw_bytes: bytes


@dataclass
class FixedValue:
    """Fixed 32-bit value (0x1500, 0x1200, 0x0502 prefixes)"""
    offset: int
    prefix: int
    value: int
    raw_bytes: bytes


@dataclass
class ParsedEntry:
    """Generic parsed entry wrapper"""
    offset: int
    prefix: int
    prefix_type: PrefixType
    data: Any
    size: int  # Total bytes consumed
    region_index: int = 0  # Which region this entry belongs to


@dataclass
class CompactBlock:
    """Fully parsed compact format block"""
    regions: List[Region]
    entries: List[ParsedEntry]
    raw_data: bytes
    judy_nodes: List[JudyNode] = field(default_factory=list)

    # Statistics
    table_refs: List[TableRef] = field(default_factory=list)
    extended_values: List[ExtendedValue] = field(default_factory=list)
    array_elements: List[ArrayElement] = field(default_factory=list)
    fixed_values: List[FixedValue] = field(default_factory=list)
    unknown_regions: List[Tuple[int, int, bytes]] = field(default_factory=list)

    @property
    def header(self) -> Optional[CompactHeader]:
        """Return first region's header for compatibility"""
        return self.regions[0].header if self.regions else None


# =============================================================================
# Parser Class
# =============================================================================

class CompactFormatParser:
    """Parser for AC Brotherhood compact format blocks"""

    def __init__(self, verbose: bool = False, show_judy: bool = False):
        self.verbose = verbose
        self.show_judy = show_judy
        self.stats = {
            'table_refs': 0,
            'extended_1c04': 0,
            'array_173c': 0,
            'value_1500': 0,
            'value_1200': 0,
            'fixed32_0502': 0,
            'varint_1405': 0,
            'type_ref_1006': 0,
            'prefix_1809': 0,
            'prefix_1907': 0,
            'prefix_1902': 0,
            'prefix_16e1': 0,
            'judy_nodes': 0,
            'unknown': 0,
            'markers': {'0x6D': 0, '0xDB': 0, '0xCD': 0},
        }
        self.current_region = 0

    def find_region_headers(self, data: bytes) -> List[Tuple[int, CompactHeader]]:
        """
        Find all 8-byte headers in the data.
        Pattern: 01 XX XX XX 00 00 80 00

        Returns list of (offset, header) tuples.
        """
        headers = []
        pos = 0
        while pos < len(data) - 8:
            header = CompactHeader.parse(data, pos)
            if header:
                headers.append((pos, header))
                # Skip past header and look for next one
                # Don't skip the entire declared size since it may not be accurate
                pos += 8
            else:
                pos += 1
        return headers

    def find_inter_region_gaps(self, data: bytes) -> List[InterRegionGap]:
        """
        Find all 5-byte inter-region gaps ending with 20 00 terminator.

        Gap format: [type_byte] [value_16 LE] [20 00]
        """
        gaps = []
        pos = 0
        while pos < len(data) - 5:
            gap = InterRegionGap.parse(data, pos)
            if gap:
                gaps.append(gap)
                pos += 5
            else:
                pos += 1
        return gaps

    def detect_regions(self, data: bytes) -> List[Region]:
        """
        Detect all regions in the block based on headers and gaps.

        Returns list of Region objects with header info and boundaries.
        """
        headers = self.find_region_headers(data)
        gaps = self.find_inter_region_gaps(data)

        if not headers:
            return []

        regions = []

        for i, (offset, header) in enumerate(headers):
            data_start = offset + 8  # Data starts after 8-byte header

            # Find end of this region
            if i + 1 < len(headers):
                # Next header exists - find gap before it
                next_header_offset = headers[i + 1][0]
                # Look for gap ending at next header
                gap_after = None
                gap_offset = 0
                for gap in gaps:
                    # Gap should be 5 bytes before next header (with possible header bytes in between)
                    if gap.offset + 5 <= next_header_offset and gap.offset + 13 >= next_header_offset:
                        gap_after = gap.raw_bytes
                        gap_offset = gap.offset
                        break

                if gap_after:
                    data_end = gap_offset
                else:
                    data_end = next_header_offset
            else:
                # Last region - extends to end of file
                data_end = len(data)
                gap_after = None
                gap_offset = 0

            actual_size = data_end - data_start

            # Check for cross-block reference (declared >> actual)
            is_cross_block_ref = header.data_size > actual_size * 10

            region = Region(
                index=i + 1,
                header=header,
                data_start=data_start,
                data_end=data_end,
                actual_size=actual_size,
                gap_after=gap_after,
                gap_offset=gap_offset,
                is_cross_block_ref=is_cross_block_ref
            )
            regions.append(region)

        return regions

    def parse(self, data: bytes) -> CompactBlock:
        """
        Parse a complete compact format block.

        Args:
            data: Raw block data (Block 3 or Block 5)

        Returns:
            CompactBlock with all parsed entries
        """
        # Detect all regions
        regions = self.detect_regions(data)

        if self.verbose:
            print(f"Detected {len(regions)} regions")
            for region in regions:
                print(f"  {region.header}")
                print(f"    Data: 0x{region.data_start:04X} - 0x{region.data_end:04X} ({region.actual_size} bytes)")
                if region.is_cross_block_ref:
                    print(f"    ** CROSS-BLOCK REFERENCE ** (declared={region.declared_size}, actual={region.actual_size})")

        # Parse entries from each region
        all_entries = []
        judy_nodes = []

        for region in regions:
            self.current_region = region.index

            if region.is_cross_block_ref:
                # Don't try to parse cross-block reference regions
                if self.verbose:
                    print(f"\nSkipping Region {region.index} (cross-block reference)")
                continue

            pos = region.data_start

            while pos < region.data_end - 1:
                # Try to parse Judy node first
                judy_node, consumed = self._parse_judy_node(data, pos)
                if judy_node:
                    judy_nodes.append(judy_node)
                    self.stats['judy_nodes'] += 1
                    if self.show_judy:
                        print(f"  0x{pos:04X}: {judy_node}")
                    pos += consumed
                    continue

                # Fall back to entry parsing
                entry, consumed = self._parse_entry(data, pos)
                if entry:
                    entry.region_index = region.index
                    all_entries.append(entry)
                    pos += consumed
                else:
                    # Skip unknown byte
                    pos += 1
                    self.stats['unknown'] += 1

        # Build result
        block = CompactBlock(
            regions=regions,
            entries=all_entries,
            raw_data=data,
            judy_nodes=judy_nodes
        )

        # Categorize entries
        for entry in all_entries:
            if entry.prefix_type == PrefixType.TABLE_REF:
                block.table_refs.append(entry.data)
            elif entry.prefix_type == PrefixType.EXTENDED_1C:
                block.extended_values.append(entry.data)
            elif entry.prefix_type == PrefixType.ARRAY_ELEM:
                block.array_elements.append(entry.data)
            elif entry.prefix_type in (PrefixType.VALUE_15, PrefixType.VALUE_12, PrefixType.FIXED32):
                block.fixed_values.append(entry.data)

        return block

    def _parse_judy_node(self, data: bytes, pos: int) -> Tuple[Optional[JudyNode], int]:
        """
        Try to parse a Judy array node at the given position.

        Judy nodes have format: [type_byte] [count/flags] [keys...] [values...]

        Returns (JudyNode, bytes_consumed) or (None, 0) if not a Judy node.
        """
        if pos >= len(data) - 1:
            return None, 0

        type_byte = data[pos]

        # Type 0x14: Linear leaf with variable count, 1-byte keys
        if type_byte == 0x14:
            return self._parse_judy_type_14(data, pos)

        # Type 0x15: Linear leaf with 3-byte keys
        if type_byte == 0x15:
            return self._parse_judy_type_15(data, pos)

        # Type 0x17: Bitmap branch with 2-byte keys
        if type_byte == 0x17:
            return self._parse_judy_type_17(data, pos)

        # Type 0x18: Single entry leaf with 2-byte key
        if type_byte == 0x18:
            return self._parse_judy_type_18(data, pos)

        # Type 0x19: Single 3-byte entry
        if type_byte == 0x19:
            return self._parse_judy_type_19(data, pos)

        # Type 0x1B: 2-element leaf with 1-byte keys
        if type_byte == 0x1B:
            return self._parse_judy_type_1b(data, pos)

        # Type 0x1C: 3-element leaf with 1-byte keys
        if type_byte == 0x1C:
            return self._parse_judy_type_1c(data, pos)

        return None, 0

    def _parse_judy_type_14(self, data: bytes, pos: int) -> Tuple[Optional[JudyNode], int]:
        """
        Parse type 0x14: Linear leaf with variable count, 1-byte keys
        Format: 14 [count-1] [key0] [key1]... [val0_4bytes] [val1_4bytes]...

        Note: The second byte encodes count-1, so actual count = byte + 1
        """
        if pos + 2 > len(data):
            return None, 0

        count_minus_1 = data[pos + 1]
        count = count_minus_1 + 1

        # Calculate expected size: 2 (header) + count*1 (keys) + count*4 (values)
        expected_size = 2 + count + count * 4
        if pos + expected_size > len(data):
            return None, 0

        keys = []
        values = []
        offset = pos + 2

        # Read 1-byte keys
        for i in range(count):
            keys.append(data[offset + i])
        offset += count

        # Read 4-byte values
        for i in range(count):
            val = struct.unpack('<I', data[offset:offset + 4])[0]
            values.append(val)
            offset += 4

        consumed = offset - pos
        raw = data[pos:pos + consumed]

        return JudyNode(
            offset=pos,
            node_type=0x14,
            count=count,
            keys=keys,
            values=values,
            raw_bytes=raw,
            key_size=1
        ), consumed

    def _parse_judy_type_15(self, data: bytes, pos: int) -> Tuple[Optional[JudyNode], int]:
        """
        Parse type 0x15: Linear leaf with 3-byte keys
        Format: 15 [count-1] [key0_3bytes] [key1_3bytes]... [val0_4bytes] [val1_4bytes]...
        """
        if pos + 2 > len(data):
            return None, 0

        count_minus_1 = data[pos + 1]
        count = count_minus_1 + 1

        # Calculate expected size: 2 (header) + count*3 (keys) + count*4 (values)
        expected_size = 2 + count * 3 + count * 4
        if pos + expected_size > len(data):
            return None, 0

        keys = []
        values = []
        offset = pos + 2

        # Read 3-byte keys (little-endian)
        for i in range(count):
            key = data[offset] | (data[offset + 1] << 8) | (data[offset + 2] << 16)
            keys.append(key)
            offset += 3

        # Read 4-byte values
        for i in range(count):
            val = struct.unpack('<I', data[offset:offset + 4])[0]
            values.append(val)
            offset += 4

        consumed = offset - pos
        raw = data[pos:pos + consumed]

        return JudyNode(
            offset=pos,
            node_type=0x15,
            count=count,
            keys=keys,
            values=values,
            raw_bytes=raw,
            key_size=3
        ), consumed

    def _parse_judy_type_17(self, data: bytes, pos: int) -> Tuple[Optional[JudyNode], int]:
        """
        Parse type 0x17: Bitmap branch with 2-byte keys
        Format: 17 [bitmap_byte] [keys...] [values...]

        The bitmap byte indicates which entries are present.
        This is a more complex format - for now we'll parse a simpler variant.
        """
        if pos + 3 > len(data):
            return None, 0

        # Second byte contains info about the structure
        info_byte = data[pos + 1]

        # Simple heuristic: treat as having few elements
        # The real format uses population count on bitmap
        count = min(info_byte & 0x0F, 8) if info_byte else 1
        if count == 0:
            count = 1

        # Calculate expected size: 2 (header) + count*2 (keys) + count*4 (values)
        expected_size = 2 + count * 2 + count * 4
        if pos + expected_size > len(data):
            return None, 0

        keys = []
        values = []
        offset = pos + 2

        # Read 2-byte keys
        for i in range(count):
            key = data[offset] | (data[offset + 1] << 8)
            keys.append(key)
            offset += 2

        # Read 4-byte values
        for i in range(count):
            val = struct.unpack('<I', data[offset:offset + 4])[0]
            values.append(val)
            offset += 4

        consumed = offset - pos
        raw = data[pos:pos + consumed]

        return JudyNode(
            offset=pos,
            node_type=0x17,
            count=count,
            keys=keys,
            values=values,
            raw_bytes=raw,
            key_size=2
        ), consumed

    def _parse_judy_type_18(self, data: bytes, pos: int) -> Tuple[Optional[JudyNode], int]:
        """
        Parse type 0x18: Single entry leaf with 2-byte key
        Format: 18 [key_high] [key_low] (implicitly 0) [value_4bytes]

        Actually the format seems to be: 18 [key_byte] [value_4bytes]
        Where key is the second byte directly.
        """
        if pos + 6 > len(data):
            return None, 0

        # Key is in the second byte (with possible extension)
        key = data[pos + 1]

        # Value starts at offset 2
        val = struct.unpack('<I', data[pos + 2:pos + 6])[0]

        return JudyNode(
            offset=pos,
            node_type=0x18,
            count=1,
            keys=[key],
            values=[val],
            raw_bytes=data[pos:pos + 6],
            key_size=2
        ), 6

    def _parse_judy_type_19(self, data: bytes, pos: int) -> Tuple[Optional[JudyNode], int]:
        """
        Parse type 0x19: Single 3-byte entry
        Format: 19 [key_byte2] [key_byte1] [key_byte0] [value_4bytes]

        Total: 8 bytes (1 type + 3 key + 4 value)
        """
        if pos + 8 > len(data):
            return None, 0

        # 3-byte key (little-endian)
        key = data[pos + 1] | (data[pos + 2] << 8) | (data[pos + 3] << 16)

        # 4-byte value
        val = struct.unpack('<I', data[pos + 4:pos + 8])[0]

        return JudyNode(
            offset=pos,
            node_type=0x19,
            count=1,
            keys=[key],
            values=[val],
            raw_bytes=data[pos:pos + 8],
            key_size=3
        ), 8

    def _parse_judy_type_1b(self, data: bytes, pos: int) -> Tuple[Optional[JudyNode], int]:
        """
        Parse type 0x1B: 2-element leaf with 1-byte keys
        Format: 1B [flags] [key0] [key1] [val0_4bytes] [val1_4bytes]

        Total: 2 + 2 + 8 = 12 bytes
        """
        if pos + 12 > len(data):
            return None, 0

        flags = data[pos + 1]
        keys = [data[pos + 2], data[pos + 3]]
        values = [
            struct.unpack('<I', data[pos + 4:pos + 8])[0],
            struct.unpack('<I', data[pos + 8:pos + 12])[0]
        ]

        return JudyNode(
            offset=pos,
            node_type=0x1B,
            count=2,
            keys=keys,
            values=values,
            raw_bytes=data[pos:pos + 12],
            key_size=1
        ), 12

    def _parse_judy_type_1c(self, data: bytes, pos: int) -> Tuple[Optional[JudyNode], int]:
        """
        Parse type 0x1C: 3-element leaf with 1-byte keys
        Format: 1C [flags] [key0] [key1] [key2] [val0_4bytes] [val1_4bytes] [val2_4bytes]

        Total: 2 + 3 + 12 = 17 bytes
        """
        if pos + 17 > len(data):
            return None, 0

        flags = data[pos + 1]
        keys = [data[pos + 2], data[pos + 3], data[pos + 4]]
        values = [
            struct.unpack('<I', data[pos + 5:pos + 9])[0],
            struct.unpack('<I', data[pos + 9:pos + 13])[0],
            struct.unpack('<I', data[pos + 13:pos + 17])[0]
        ]

        return JudyNode(
            offset=pos,
            node_type=0x1C,
            count=3,
            keys=keys,
            values=values,
            raw_bytes=data[pos:pos + 17],
            key_size=1
        ), 17

    def _find_first_table_ref(self, data: bytes) -> int:
        """Find offset of first TABLE_REF (0x0803) pattern"""
        for i in range(8, len(data) - 1):
            if data[i] == 0x08 and data[i+1] == 0x03:
                return i
        return 8  # Default to right after header

    def _parse_entry(self, data: bytes, pos: int) -> Tuple[Optional[ParsedEntry], int]:
        """
        Parse a single entry at the given position.

        Returns:
            Tuple of (ParsedEntry or None, bytes consumed)
        """
        if pos >= len(data) - 1:
            return None, 0

        # Read 2-byte prefix as big-endian (first byte is type indicator)
        b0 = data[pos]
        b1 = data[pos + 1]

        # TABLE_REF: 08 03 [table_id] [prop_id]
        if b0 == 0x08 and b1 == 0x03:
            return self._parse_table_ref(data, pos)

        # EXTENDED_1C: 1C 04 [subtype] [data...]
        if b0 == 0x1C and b1 == 0x04:
            return self._parse_extended_1c(data, pos)

        # ARRAY_ELEM: 17 3C [type] [data...]
        if b0 == 0x17 and b1 == 0x3C:
            return self._parse_array_element(data, pos)

        # VALUE_15: 15 00 [4-byte value]
        if b0 == 0x15 and b1 == 0x00:
            return self._parse_value_15(data, pos)

        # VALUE_12: 12 00 [4-byte value]
        if b0 == 0x12 and b1 == 0x00:
            return self._parse_value_12(data, pos)

        # FIXED32: 05 02 [4-byte value]
        if b0 == 0x05 and b1 == 0x02:
            return self._parse_fixed32(data, pos)

        # VARINT: 14 05 [varint...]
        if b0 == 0x14 and b1 == 0x05:
            return self._parse_varint(data, pos)

        # TYPE_REF: 10 06 [table_id] [data...]
        if b0 == 0x10 and b1 == 0x06:
            return self._parse_type_ref(data, pos)

        # PREFIX_1809: 18 09 [data...]
        if b0 == 0x18 and b1 == 0x09:
            return self._parse_prefix_1809(data, pos)

        # PREFIX_1907: 19 07 [data...]
        if b0 == 0x19 and b1 == 0x07:
            return self._parse_prefix_1907(data, pos)

        # PREFIX_0C18: 0C 18 [data...]
        if b0 == 0x0C and b1 == 0x18:
            return self._parse_prefix_0c18(data, pos)

        # PREFIX_1013: 10 13 [data...]
        if b0 == 0x10 and b1 == 0x13:
            return self._parse_prefix_1013(data, pos)

        # PREFIX_1830: 18 30 [data...]
        if b0 == 0x18 and b1 == 0x30:
            return self._parse_prefix_1830(data, pos)

        # PREFIX_140E: 14 0E [data...]
        if b0 == 0x14 and b1 == 0x0E:
            return self._parse_prefix_140e(data, pos)

        # PREFIX_1902: 19 02 [data...] (frequent in Block 5)
        if b0 == 0x19 and b1 == 0x02:
            return self._parse_prefix_1902(data, pos)

        # PREFIX_16E1: 16 E1 [data...]
        if b0 == 0x16 and b1 == 0xE1:
            return self._parse_prefix_16e1(data, pos)

        # Check for single-byte markers
        b = data[pos]
        if b == MARKER_TRUE:
            self.stats['markers']['0x6D'] += 1
            return ParsedEntry(
                offset=pos, prefix=b, prefix_type=PrefixType.UNKNOWN,
                data={'marker': 'TRUE', 'value': 1}, size=1
            ), 1
        elif b == MARKER_FALSE:
            self.stats['markers']['0xDB'] += 1
            return ParsedEntry(
                offset=pos, prefix=b, prefix_type=PrefixType.UNKNOWN,
                data={'marker': 'FALSE', 'value': 0}, size=1
            ), 1
        elif b == MARKER_CD:
            self.stats['markers']['0xCD'] += 1
            return ParsedEntry(
                offset=pos, prefix=b, prefix_type=PrefixType.UNKNOWN,
                data={'marker': 'CD', 'value': None}, size=1
            ), 1

        return None, 1

    def _parse_table_ref(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse TABLE_REF: 08 03 [table_id] [prop_id]"""
        if pos + 4 > len(data):
            return None, 0

        table_id = data[pos + 2]
        prop_id = data[pos + 3]

        ref = TableRef(offset=pos, table_id=table_id, property_id=prop_id)
        self.stats['table_refs'] += 1

        if self.verbose:
            type_info = f" ({ref.type_name})" if ref.type_name else ""
            print(f"  0x{pos:04X}: TABLE_REF table=0x{table_id:02X}{type_info}, prop=0x{prop_id:02X}")

        return ParsedEntry(
            offset=pos, prefix=0x0803, prefix_type=PrefixType.TABLE_REF,
            data=ref, size=4
        ), 4

    def _parse_extended_1c(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse EXTENDED_1C: 1C 04 [subtype] [data...]"""
        if pos + 3 > len(data):
            return None, 0

        subtype = data[pos + 2]
        consumed = 3
        value = None

        # Decode based on subtype
        if subtype == 0x08:  # 1-byte value
            if pos + 4 <= len(data):
                value = data[pos + 3]
                consumed = 4
        elif subtype in (0x0A, 0x0B):  # 2-byte value
            if pos + 5 <= len(data):
                value = struct.unpack('<H', data[pos + 3:pos + 5])[0]
                consumed = 5
        elif subtype in (0x24, 0x25, 0x21, 0x23):  # Type/property reference (variable)
            # Read until we hit another prefix or marker
            end = pos + 3
            while end < len(data) and end < pos + 8:
                b = data[end]
                if b in (0x08, 0x1C, 0x17, 0x15, 0x12, 0x14, 0x10, 0x18, 0x19, 0x0C):
                    break
                if b in (MARKER_TRUE, MARKER_FALSE, MARKER_CD):
                    break
                end += 1
            value = data[pos + 3:end]
            consumed = end - pos
        else:
            # Unknown subtype - read 2 more bytes
            if pos + 5 <= len(data):
                value = struct.unpack('<H', data[pos + 3:pos + 5])[0]
                consumed = 5

        ext = ExtendedValue(
            offset=pos, subtype=subtype, value=value,
            raw_bytes=data[pos:pos + consumed]
        )
        self.stats['extended_1c04'] += 1

        if self.verbose:
            print(f"  0x{pos:04X}: EXTENDED_1C subtype=0x{subtype:02X}, value={value}")

        return ParsedEntry(
            offset=pos, prefix=0x1C04, prefix_type=PrefixType.EXTENDED_1C,
            data=ext, size=consumed
        ), consumed

    def _parse_array_element(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse ARRAY_ELEM: 17 3C [type] [data...]"""
        if pos + 3 > len(data):
            return None, 0

        elem_type = data[pos + 2]
        consumed = 3
        value = None

        # Decode based on element type
        if elem_type == 0x00:  # Null/terminator
            if pos + 6 <= len(data):
                value = struct.unpack('<I', data[pos + 3:pos + 7])[0]
                consumed = 7
            else:
                consumed = 3
        elif elem_type == 0x08:  # 1-byte value
            if pos + 4 <= len(data):
                value = data[pos + 3]
                consumed = 4
        elif elem_type == 0x1A:  # Property reference
            if pos + 5 <= len(data):
                value = struct.unpack('<H', data[pos + 3:pos + 5])[0]
                consumed = 5
        elif elem_type in (0x0A, 0x0B, 0x0E):  # 2-byte values
            if pos + 5 <= len(data):
                value = struct.unpack('<H', data[pos + 3:pos + 5])[0]
                consumed = 5
        else:
            # Unknown - try 2-byte read
            if pos + 5 <= len(data):
                value = struct.unpack('<H', data[pos + 3:pos + 5])[0]
                consumed = 5

        elem = ArrayElement(
            offset=pos, element_type=elem_type, value=value,
            raw_bytes=data[pos:pos + consumed]
        )
        self.stats['array_173c'] += 1

        if self.verbose:
            print(f"  0x{pos:04X}: ARRAY_ELEM type=0x{elem_type:02X}, value={value}")

        return ParsedEntry(
            offset=pos, prefix=0x173C, prefix_type=PrefixType.ARRAY_ELEM,
            data=elem, size=consumed
        ), consumed

    def _parse_value_15(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse VALUE_15: 15 00 [4-byte value]"""
        if pos + 6 > len(data):
            return None, 0

        value = struct.unpack('<I', data[pos + 2:pos + 6])[0]

        fv = FixedValue(
            offset=pos, prefix=0x1500, value=value,
            raw_bytes=data[pos:pos + 6]
        )
        self.stats['value_1500'] += 1

        if self.verbose:
            print(f"  0x{pos:04X}: VALUE_15 = 0x{value:08X}")

        return ParsedEntry(
            offset=pos, prefix=0x1500, prefix_type=PrefixType.VALUE_15,
            data=fv, size=6
        ), 6

    def _parse_value_12(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse VALUE_12: 12 00 [4-byte value]"""
        if pos + 6 > len(data):
            return None, 0

        value = struct.unpack('<I', data[pos + 2:pos + 6])[0]

        fv = FixedValue(
            offset=pos, prefix=0x1200, value=value,
            raw_bytes=data[pos:pos + 6]
        )
        self.stats['value_1200'] += 1

        if self.verbose:
            print(f"  0x{pos:04X}: VALUE_12 = 0x{value:08X}")

        return ParsedEntry(
            offset=pos, prefix=0x1200, prefix_type=PrefixType.VALUE_12,
            data=fv, size=6
        ), 6

    def _parse_fixed32(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse FIXED32: 05 02 [4-byte value]"""
        if pos + 6 > len(data):
            return None, 0

        value = struct.unpack('<I', data[pos + 2:pos + 6])[0]

        fv = FixedValue(
            offset=pos, prefix=0x0502, value=value,
            raw_bytes=data[pos:pos + 6]
        )
        self.stats['fixed32_0502'] += 1

        if self.verbose:
            print(f"  0x{pos:04X}: FIXED32 = 0x{value:08X}")

        return ParsedEntry(
            offset=pos, prefix=0x0502, prefix_type=PrefixType.FIXED32,
            data=fv, size=6
        ), 6

    def _parse_varint(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse VARINT: 14 05 [varint...]"""
        if pos + 3 > len(data):
            return None, 0

        # Read varint starting at pos+2
        value, varint_len = self._read_varint(data, pos + 2)
        consumed = 2 + varint_len

        self.stats['varint_1405'] += 1

        if self.verbose:
            print(f"  0x{pos:04X}: VARINT = {value}")

        return ParsedEntry(
            offset=pos, prefix=0x1405, prefix_type=PrefixType.VARINT,
            data={'value': value, 'raw': data[pos:pos + consumed]}, size=consumed
        ), consumed

    def _parse_type_ref(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse TYPE_REF: 10 06 [table_id] [data...]"""
        if pos + 4 > len(data):
            return None, 0

        table_id = data[pos + 2]
        extra = data[pos + 3] if pos + 3 < len(data) else 0

        self.stats['type_ref_1006'] += 1

        if self.verbose:
            print(f"  0x{pos:04X}: TYPE_REF table=0x{table_id:02X}, extra=0x{extra:02X}")

        return ParsedEntry(
            offset=pos, prefix=0x1006, prefix_type=PrefixType.TYPE_REF_10,
            data={'table_id': table_id, 'extra': extra}, size=4
        ), 4

    def _parse_prefix_1809(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse PREFIX_1809: 18 09 [data...]"""
        if pos + 4 > len(data):
            return None, 0

        value = struct.unpack('<H', data[pos + 2:pos + 4])[0]

        self.stats['prefix_1809'] += 1

        if self.verbose:
            print(f"  0x{pos:04X}: PREFIX_1809 = 0x{value:04X}")

        return ParsedEntry(
            offset=pos, prefix=0x1809, prefix_type=PrefixType.PREFIX_1809,
            data={'value': value}, size=4
        ), 4

    def _parse_prefix_1907(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse PREFIX_1907: 19 07 [data...]"""
        if pos + 4 > len(data):
            return None, 0

        value = struct.unpack('<H', data[pos + 2:pos + 4])[0]

        self.stats['prefix_1907'] += 1

        if self.verbose:
            print(f"  0x{pos:04X}: PREFIX_1907 = 0x{value:04X}")

        return ParsedEntry(
            offset=pos, prefix=0x1907, prefix_type=PrefixType.PREFIX_1907,
            data={'value': value}, size=4
        ), 4

    def _parse_prefix_0c18(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse PREFIX_0C18: 0C 18 [data...]"""
        if pos + 4 > len(data):
            return None, 0

        value = struct.unpack('<H', data[pos + 2:pos + 4])[0]

        if self.verbose:
            print(f"  0x{pos:04X}: PREFIX_0C18 = 0x{value:04X}")

        return ParsedEntry(
            offset=pos, prefix=0x0C18, prefix_type=PrefixType.PREFIX_0C18,
            data={'value': value}, size=4
        ), 4

    def _parse_prefix_1013(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse PREFIX_1013: 10 13 [data...]"""
        if pos + 4 > len(data):
            return None, 0

        value = struct.unpack('<H', data[pos + 2:pos + 4])[0]

        if self.verbose:
            print(f"  0x{pos:04X}: PREFIX_1013 = 0x{value:04X}")

        return ParsedEntry(
            offset=pos, prefix=0x1013, prefix_type=PrefixType.UNKNOWN,
            data={'value': value}, size=4
        ), 4

    def _parse_prefix_1830(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse PREFIX_1830: 18 30 [data...]"""
        if pos + 4 > len(data):
            return None, 0

        value = struct.unpack('<H', data[pos + 2:pos + 4])[0]

        if self.verbose:
            print(f"  0x{pos:04X}: PREFIX_1830 = 0x{value:04X}")

        return ParsedEntry(
            offset=pos, prefix=0x1830, prefix_type=PrefixType.UNKNOWN,
            data={'value': value}, size=4
        ), 4

    def _parse_prefix_140e(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse PREFIX_140E: 14 0E [data...]"""
        if pos + 4 > len(data):
            return None, 0

        value = struct.unpack('<H', data[pos + 2:pos + 4])[0]

        if self.verbose:
            print(f"  0x{pos:04X}: PREFIX_140E = 0x{value:04X}")

        return ParsedEntry(
            offset=pos, prefix=0x140E, prefix_type=PrefixType.UNKNOWN,
            data={'value': value}, size=4
        ), 4

    def _parse_prefix_1902(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse PREFIX_1902: 19 02 [data...]"""
        if pos + 4 > len(data):
            return None, 0

        value = struct.unpack('<H', data[pos + 2:pos + 4])[0]

        if self.verbose:
            print(f"  0x{pos:04X}: PREFIX_1902 = 0x{value:04X}")

        self.stats['prefix_1902'] += 1

        return ParsedEntry(
            offset=pos, prefix=0x1902, prefix_type=PrefixType.UNKNOWN,
            data={'value': value}, size=4
        ), 4

    def _parse_prefix_16e1(self, data: bytes, pos: int) -> Tuple[ParsedEntry, int]:
        """Parse PREFIX_16E1: 16 E1 [data...]"""
        if pos + 4 > len(data):
            return None, 0

        value = struct.unpack('<H', data[pos + 2:pos + 4])[0]

        if self.verbose:
            print(f"  0x{pos:04X}: PREFIX_16E1 = 0x{value:04X}")

        self.stats['prefix_16e1'] += 1

        return ParsedEntry(
            offset=pos, prefix=0x16E1, prefix_type=PrefixType.UNKNOWN,
            data={'value': value}, size=4
        ), 4

    def _read_varint(self, data: bytes, pos: int) -> Tuple[int, int]:
        """
        Read a variable-length integer (protobuf-style).

        Returns:
            Tuple of (value, bytes consumed)
        """
        result = 0
        shift = 0
        consumed = 0

        while pos + consumed < len(data):
            b = data[pos + consumed]
            result |= (b & 0x7F) << shift
            consumed += 1
            if (b & 0x80) == 0:
                break
            shift += 7
            if consumed > 5:  # Max 5 bytes for 32-bit varint
                break

        return result, consumed

    def print_stats(self):
        """Print parsing statistics"""
        print("\n" + "=" * 60)
        print("PARSING STATISTICS")
        print("=" * 60)
        print(f"  TABLE_REF (0x0803):     {self.stats['table_refs']:4d}")
        print(f"  EXTENDED_1C (0x1C04):   {self.stats['extended_1c04']:4d}")
        print(f"  ARRAY_ELEM (0x173C):    {self.stats['array_173c']:4d}")
        print(f"  VALUE_15 (0x1500):      {self.stats['value_1500']:4d}")
        print(f"  VALUE_12 (0x1200):      {self.stats['value_1200']:4d}")
        print(f"  FIXED32 (0x0502):       {self.stats['fixed32_0502']:4d}")
        print(f"  VARINT (0x1405):        {self.stats['varint_1405']:4d}")
        print(f"  TYPE_REF (0x1006):      {self.stats['type_ref_1006']:4d}")
        print(f"  PREFIX_1809:            {self.stats['prefix_1809']:4d}")
        print(f"  PREFIX_1907:            {self.stats['prefix_1907']:4d}")
        print(f"  PREFIX_1902:            {self.stats['prefix_1902']:4d}")
        print(f"  PREFIX_16E1:            {self.stats['prefix_16e1']:4d}")
        print(f"  Judy nodes:             {self.stats['judy_nodes']:4d}")
        print(f"  Unknown bytes:          {self.stats['unknown']:4d}")
        print()
        print("  Markers:")
        for marker, count in self.stats['markers'].items():
            print(f"    {marker}: {count:4d}")
        print("=" * 60)


# =============================================================================
# Analysis Functions
# =============================================================================

def analyze_regions(block: CompactBlock):
    """Analyze region structure"""
    print("\n" + "=" * 60)
    print("REGION ANALYSIS")
    print("=" * 60)

    print(f"\nTotal regions: {len(block.regions)}")

    for region in block.regions:
        print(f"\n--- Region {region.index} ---")
        print(f"  Header offset:  0x{region.header.offset:04X}")
        print(f"  Data range:     0x{region.data_start:04X} - 0x{region.data_end:04X}")
        print(f"  Declared size:  {region.declared_size:,} bytes")
        print(f"  Actual size:    {region.actual_size:,} bytes")
        print(f"  Size delta:     {region.size_delta:+d} bytes")

        if region.is_cross_block_ref:
            print(f"  ** CROSS-BLOCK REFERENCE **")
            print(f"     Declared size likely refers to external block data")

        if region.gap_after:
            gap = InterRegionGap.parse(block.raw_data, region.gap_offset)
            if gap:
                print(f"  Gap after:      {gap}")
                print(f"     Raw bytes:   {gap.raw_bytes.hex()}")


def analyze_judy_nodes(block: CompactBlock):
    """Analyze Judy array nodes"""
    print("\n" + "=" * 60)
    print("JUDY NODE ANALYSIS")
    print("=" * 60)

    if not block.judy_nodes:
        print("\nNo Judy nodes parsed")
        return

    # Group by type
    by_type = {}
    for node in block.judy_nodes:
        if node.node_type not in by_type:
            by_type[node.node_type] = []
        by_type[node.node_type].append(node)

    print(f"\nTotal Judy nodes: {len(block.judy_nodes)}")
    print(f"Node types found: {len(by_type)}")

    for node_type in sorted(by_type.keys()):
        nodes = by_type[node_type]
        print(f"\n  Type 0x{node_type:02X}: {len(nodes)} nodes")

        # Show sample
        for node in nodes[:3]:
            keys_str = ', '.join(f'0x{k:X}' for k in node.keys[:4])
            if len(node.keys) > 4:
                keys_str += '...'
            vals_str = ', '.join(f'0x{v:X}' for v in node.values[:4])
            if len(node.values) > 4:
                vals_str += '...'
            print(f"    0x{node.offset:04X}: keys=[{keys_str}] values=[{vals_str}]")


def analyze_table_refs(block: CompactBlock):
    """Analyze TABLE_REF distribution"""
    print("\n" + "=" * 60)
    print("TABLE_REF ANALYSIS")
    print("=" * 60)

    # Group by table ID
    by_table = {}
    for ref in block.table_refs:
        if ref.table_id not in by_table:
            by_table[ref.table_id] = []
        by_table[ref.table_id].append(ref)

    print(f"\nTotal TABLE_REFs: {len(block.table_refs)}")
    print(f"Unique tables: {len(by_table)}")
    print()

    for table_id in sorted(by_table.keys()):
        refs = by_table[table_id]
        props = sorted(set(r.property_id for r in refs))
        type_name = refs[0].type_name or "Unknown"

        print(f"Table 0x{table_id:02X} ({type_name}): {len(refs)} refs")
        print(f"  Properties: {', '.join(f'0x{p:02X}' for p in props[:10])}", end='')
        if len(props) > 10:
            print(f" ... ({len(props)} total)")
        else:
            print()


def analyze_extended_values(block: CompactBlock):
    """Analyze EXTENDED_1C value distribution"""
    print("\n" + "=" * 60)
    print("EXTENDED_1C (0x1C04) ANALYSIS")
    print("=" * 60)

    # Group by subtype
    by_subtype = {}
    for ext in block.extended_values:
        if ext.subtype not in by_subtype:
            by_subtype[ext.subtype] = []
        by_subtype[ext.subtype].append(ext)

    print(f"\nTotal EXTENDED_1C values: {len(block.extended_values)}")
    print(f"Unique subtypes: {len(by_subtype)}")
    print()

    for subtype in sorted(by_subtype.keys()):
        values = by_subtype[subtype]
        print(f"Subtype 0x{subtype:02X}: {len(values)} occurrences")

        # Show sample values
        sample = values[:3]
        for v in sample:
            print(f"    0x{v.offset:04X}: value={v.value}")


def analyze_array_elements(block: CompactBlock):
    """Analyze ARRAY_ELEM distribution"""
    print("\n" + "=" * 60)
    print("ARRAY_ELEM (0x173C) ANALYSIS")
    print("=" * 60)

    if not block.array_elements:
        print("\nNo array elements found")
        return

    # Group by offset clusters
    elements = sorted(block.array_elements, key=lambda e: e.offset)

    print(f"\nTotal array elements: {len(block.array_elements)}")

    # Find clusters (elements within 100 bytes of each other)
    clusters = []
    current_cluster = [elements[0]]

    for i in range(1, len(elements)):
        if elements[i].offset - current_cluster[-1].offset < 100:
            current_cluster.append(elements[i])
        else:
            clusters.append(current_cluster)
            current_cluster = [elements[i]]
    clusters.append(current_cluster)

    print(f"Clusters found: {len(clusters)}")

    for i, cluster in enumerate(clusters):
        start = cluster[0].offset
        end = cluster[-1].offset
        print(f"\n  Cluster {i+1}: offset 0x{start:04X} - 0x{end:04X} ({len(cluster)} elements)")

        # Group by type
        by_type = {}
        for elem in cluster:
            if elem.element_type not in by_type:
                by_type[elem.element_type] = []
            by_type[elem.element_type].append(elem)

        for elem_type in sorted(by_type.keys()):
            elems = by_type[elem_type]
            print(f"    Type 0x{elem_type:02X}: {len(elems)} elements")


def export_to_json(block: CompactBlock, output_path: str):
    """Export parsed block to JSON"""
    data = {
        'regions': [],
        'judy_nodes': [],
        'table_refs': [],
        'extended_values': [],
        'array_elements': [],
        'fixed_values': []
    }

    # Export regions
    for region in block.regions:
        region_data = {
            'index': region.index,
            'header_offset': region.header.offset,
            'data_start': region.data_start,
            'data_end': region.data_end,
            'declared_size': region.declared_size,
            'actual_size': region.actual_size,
            'is_cross_block_ref': region.is_cross_block_ref
        }
        if region.gap_after:
            region_data['gap'] = {
                'offset': region.gap_offset,
                'bytes': region.gap_after.hex()
            }
        data['regions'].append(region_data)

    # Export Judy nodes
    for node in block.judy_nodes:
        data['judy_nodes'].append({
            'offset': node.offset,
            'type': node.node_type,
            'count': node.count,
            'key_size': node.key_size,
            'keys': node.keys,
            'values': node.values
        })

    # Export table refs
    for ref in block.table_refs:
        data['table_refs'].append({
            'offset': ref.offset,
            'table_id': ref.table_id,
            'property_id': ref.property_id,
            'type_name': ref.type_name
        })

    # Export extended values
    for ext in block.extended_values:
        val = ext.value
        if isinstance(val, bytes):
            val = val.hex()
        data['extended_values'].append({
            'offset': ext.offset,
            'subtype': ext.subtype,
            'value': val
        })

    # Export array elements
    for elem in block.array_elements:
        data['array_elements'].append({
            'offset': elem.offset,
            'element_type': elem.element_type,
            'value': elem.value
        })

    # Export fixed values
    for fv in block.fixed_values:
        data['fixed_values'].append({
            'offset': fv.offset,
            'prefix': fv.prefix,
            'value': fv.value
        })

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2)

    print(f"\nExported to: {output_path}")


# =============================================================================
# Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='AC Brotherhood Compact Format Parser',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python compact_format_parser.py references/sav_block3_raw.bin
  python compact_format_parser.py references/sav_block5_raw.bin --verbose
  python compact_format_parser.py references/sav_block3_raw.bin --regions --judy
  python compact_format_parser.py references/sav_block3_raw.bin --json output.json
"""
    )

    parser.add_argument('input', help='Input block file (Block 3 or Block 5)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Print each parsed entry')
    parser.add_argument('--analyze', '-a', action='store_true',
                        help='Show detailed analysis of parsed data')
    parser.add_argument('--regions', '-r', action='store_true',
                        help='Show region breakdown with headers and gaps')
    parser.add_argument('--judy', '-j', action='store_true',
                        help='Show Judy node decoding with keys and values')
    parser.add_argument('--json', type=str, metavar='FILE',
                        help='Output structured JSON to file')

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: File not found: {args.input}")
        return 1

    with open(args.input, 'rb') as f:
        data = f.read()

    print("=" * 60)
    print("AC Brotherhood Compact Format Parser")
    print("=" * 60)
    print(f"\nInput: {args.input}")
    print(f"Size: {len(data):,} bytes")

    # Parse
    parser_obj = CompactFormatParser(verbose=args.verbose, show_judy=args.judy)
    block = parser_obj.parse(data)

    # Print region info
    if block.regions:
        print(f"\nRegions found: {len(block.regions)}")
        for region in block.regions:
            status = " [CROSS-BLOCK REF]" if region.is_cross_block_ref else ""
            print(f"  Region {region.index}: 0x{region.data_start:04X}-0x{region.data_end:04X} "
                  f"({region.actual_size:,} bytes){status}")

    print(f"\nEntries parsed: {len(block.entries)}")
    print(f"Judy nodes parsed: {len(block.judy_nodes)}")

    # Print stats
    parser_obj.print_stats()

    # Region analysis
    if args.regions:
        analyze_regions(block)

    # Judy node analysis
    if args.judy:
        analyze_judy_nodes(block)

    # Detailed analysis
    if args.analyze:
        analyze_table_refs(block)
        analyze_extended_values(block)
        analyze_array_elements(block)

    # JSON export
    if args.json:
        export_to_json(block, args.json)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  Regions:          {len(block.regions)}")
    print(f"  Judy nodes:       {len(block.judy_nodes)}")
    print(f"  TABLE_REFs:       {len(block.table_refs)}")
    print(f"  Extended values:  {len(block.extended_values)}")
    print(f"  Array elements:   {len(block.array_elements)}")
    print(f"  Fixed values:     {len(block.fixed_values)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
