# Assassin's Creed Brotherhood SAV File Format Specification

**The Definitive Reference for SAV File Format**

**Version:** 1.0
**Date:** December 28, 2025
**Platform:** PC (Windows, 32-bit)
**Engine:** Scimitar Engine
**Status:** Complete Specification

> **⚠ MAJOR CORRECTION (July 2026):** the 5-block topology this specification
> assumes (Block 3 with 4 regions, Block 4 at a fixed position, Block 5 as raw
> trailing data) is a special case: it matches only small fresh saves. In
> general, everything after Block 2 is a sequence of N self-contained LZSS
> frames (`[0x01][comp_size 3B LE][00 00 80 00][1 byte][adler32 4B LE][data]`,
> each exactly 32 KB decompressed; N is 6 fresh, 14-16 played), and content
> must be located by decompressing frames, not by position. Sections here
> describing "Block 3"/"Block 5" raw bytes were analyses of LZSS-compressed
> data (compression artifacts). Block 1/Block 2 header layouts, checksums,
> the type system, and decompressed-content analyses remain valid. See
> SAV_BLOCKS_OVERVIEW.md for the corrected structure summary.

---

## Table of Contents

1. [Overview](#1-overview)
2. [SAV File Structure](#2-sav-file-structure)
   - [Five-Block Layout](#21-five-block-layout)
   - [Block Headers](#22-block-headers)
   - [Footer Format](#23-footer-format)
3. [LZSS Compression Layer](#3-lzss-compression-layer)
   - [Encoding Types](#31-encoding-types)
   - [Bit Layouts](#32-bit-layouts)
   - [Terminator Sequence](#33-terminator-sequence)
   - [2-Byte Zero Prefix](#34-2-byte-zero-prefix)
   - [Match Length Encoding](#35-match-length-encoding)
4. [Compression Algorithm Details](#4-compression-algorithm-details)
   - [Lazy Matching](#41-lazy-matching)
   - [Adjustment Formulas](#42-adjustment-formulas)
   - [Match Finder Behavior](#43-match-finder-behavior)
   - [Tie-Breaking Rules](#44-tie-breaking-rules)
5. [Decompressed Content Format](#5-decompressed-content-format)
   - [Tagged Binary Format](#51-tagged-binary-format)
   - [Type Hash System](#52-type-hash-system)
   - [Field Structures](#53-field-structures)
   - [Block Contents](#54-block-contents)
6. [Checksums](#6-checksums)
7. [Key Addresses](#7-key-addresses)
8. [Tools](#8-tools)
9. [Python Code Examples](#9-python-code-examples)
10. [Appendix: Field Types Reference](#appendix-field-types-reference)
    - [String Extraction Results](#1-string-extraction-results)
    - [Block 2 Field Type Distribution](#2-block-2-field-type-distribution)
    - [Block 4 Field Type Distribution](#3-block-4-field-type-distribution)
    - [Field Patterns and Observations](#4-field-patterns-and-observations)
    - [Technical Notes](#5-technical-notes)
    - [Full Offset Lists](#appendix-full-offset-lists)

---

## Quick Reference: Type Hashes

### Core Type Hashes

| Hash | Name | Block(s) | Purpose |
|------|------|----------|---------|
| `0x7E42F87F` | CommonParent | All | Root base class (786 refs) |
| `0xBB96607D` | ManagedObject | All | Managed object base (192 derived) |
| `0xBDBE3B52` | SaveGame | 1 | Root save object |
| `0xFBB63E47` | World | 2, 3 | Game world state (Table ID 0x20) |
| `0x5FDACBA0` | SaveGameDataObject | 2 | Save data container |
| `0x5ED7B213` | MissionSaveData | 2 | Mission progress tracking |
| `0x12DE6C4C` | RewardFault | 2 | Reward/unlock data |
| `0x0984415E` | PropertyReference | 2, 4 | Property binding (461 refs) |
| `0xA1A85298` | PhysicalInventoryItem | 4 | Inventory items (364 instances) |
| `0x2DAD13E3` | PlayerOptionsElement | 3 | Player options (Table ID 0x16) |

### Compact Format Table IDs (Blocks 3/5)

| Table ID | Type Hash | Type Name | Properties |
|----------|-----------|-----------|------------|
| `0x20` | `0xFBB63E47` | World | 111 refs in code |
| `0x16` | `0x2DAD13E3` | PlayerOptionsElement | Player settings |
| `0x5E` | `0x0DEBED19` | CompactType_5E | 22 properties |

---

## 1. Overview

### What Are SAV Files?

SAV files are game save files for Assassin's Creed Brotherhood on PC. Each save slot corresponds to one SAV file containing the complete game state: player profile, mission progress, inventory, and world data.

### File Locations

```
%USERPROFILE%\Documents\Assassin's Creed Brotherhood\SAVES\
    ACBROTHERHOODSAVEGAME0.SAV    <- Save slot 0
    ACBROTHERHOODSAVEGAME1.SAV    <- Save slot 1
    ACBROTHERHOODSAVEGAME2.SAV    <- Save slot 2
    ...
```

### Purpose

SAV files store:
- **Player Profile** - Character name, save metadata
- **Game State** - Mission progress, unlocks, flags
- **World Data** - Compact binary world state
- **Inventory** - All 364 inventory items with properties
- **Additional Data** - Compact binary format (purpose unknown)

### Compression Accuracy

The tools in this repository achieve:
- **OPTIONS files**: 100% byte-for-byte accuracy
- **SAV files**: 100% byte-for-byte accuracy

Both file types use the **exact same LZSS compressor function** (confirmed via WinDbg TTD tracing).

---

## 2. SAV File Structure

### 2.1 Five-Block Layout

SAV files contain exactly **5 blocks** with varying formats:

```
ACBROTHERHOODSAVEGAME0.SAV (example: 18,503 bytes)
+-- Block 1 (Header+LZSS) --> 283 bytes   [SaveGame - Player Profile]
+-- Block 2 (Header+LZSS) --> 32,768 bytes [AssassinSaveGameData - Game State]
+-- Block 3 (Raw)         --> 7,972 bytes  [World - Compact Format]
+-- Block 4 (LZSS only)   --> 32,768 bytes [PhysicalInventoryItem - 364 items]
+-- Block 5 (Raw)         --> 6,266 bytes  [Unknown - Compact Format]
```

| Block | Offset | Compressed Size | Decompressed Size | Compression | Type Hash | Content |
|-------|--------|-----------------|-------------------|-------------|-----------|---------|
| 1 | 0x0000 | 44 + 173 | 283 | LZSS | 0xBDBE3B52 | Player profile |
| 2 | 0x00D9 | 44 + 1854 | 32,768 | LZSS | 0x94D6F8F1 | Game state |
| 3 | Dynamic | 7,972 | 7,972 | None | 0xFBB63E47 | World data |
| 4 | Dynamic | 2,150 | 32,768 | LZSS | 0xA1A85298 | Inventory |
| 5 | end-6266 | 6,266 | 6,266 | None | Unknown | Additional data |

**Notes:**
- Block 3/4/5 offsets are calculated dynamically based on Block 2 compressed size
- Block 5 is always the last 6,266 bytes of the file
- Block 4 has no header (LZSS data only)

### 2.2 Block Headers

#### 44-Byte Header Structure

Blocks 1 and 2 have 44-byte headers. Block 4 has no header.

```
Offset | Size | Field            | Block 1       | Block 2
-------|------|------------------|---------------|----------------
0x00   | 4    | Field1           | 0x00000016    | remaining-4
0x04   | 4    | Field2           | 0x00FEDBAC    | 0x00000001
0x08   | 4    | Marker           | 0x000000CD    | 0x00CAFE00
0x0C   | 4    | Field4           | uncompressed  | see formula
0x10   | 4    | Magic1           | 0x57FBAA33    | 0x57FBAA33
0x14   | 4    | Magic2           | 0x1004FA99    | 0x1004FA99
0x18   | 4    | Magic3           | 0x00020001    | 0x00020001
0x1C   | 4    | Magic4           | 0x01000080    | 0x01000080
0x20   | 4    | Compressed Size  | varies        | varies
0x24   | 4    | Uncompressed Size| 283           | 32768
0x28   | 4    | Checksum         | Adler-32      | Adler-32
```

#### Header Field Calculations

**Block 1:**
- Field1 = `0x00000016` (constant)
- Field2 = `0x00FEDBAC` (constant)
- Field3 (Marker) = `compressed_size + 32`
- Field4 = `uncompressed_size`

**Block 2:**
- Field1 = `remaining_file_size - 4`
- Field2 = `0x00000001`
- Field3 (Marker) = `0x00CAFE00`
- Field4 = Complex encoding (see below)

#### Block 2 Field4 Calculation (CONFIRMED via TTD - January 2025)

**Field4 = total bytes consumed from decompressed Block 2 data**

This was confirmed via WinDbg Time-Travel Debugging by tracing the exact instruction that computes Field4.

**Calculation in FUN_01B6F170 (offset +0x176f18b):**
```asm
mov eax, [esi+14h]    ; EAX = buffer_start
mov edx, [esi+18h]    ; EDX = current_position (after serialization)
sub edx, eax          ; EDX = current_position - buffer_start = Field4
```

**Practical Formula for Serialization:**
```python
Field4 = struct.unpack('<I', decompressed[0x0E:0x12])[0] + 0x12
```

**Why this works:**

The decompressed Block 2 data has this structure:
| Offset | Size | Content |
|--------|------|---------|
| 0x00 | 10 bytes | Null padding |
| 0x0A | 4 bytes | Type hash (0x94D6F8F1 = AssassinSaveGameData) |
| 0x0E | 4 bytes | Object data size |
| 0x12 | varies | Object data |

Total fixed header = 10 + 4 + 4 = 18 bytes (0x12)

Therefore: `Field4 = 0x12 + value_at_offset_0x0E`

**Verified Values (100% accuracy across 8 SAV files):**

| Save File | Field4 | Value at 0x0E | 0x12 + Value |
|-----------|--------|---------------|--------------|
| FRESH.SAV | 0x0003F1D6 | 0x0003F1C4 | 0x0003F1D6 ✓ |
| CAPE_0%.SAV | 0x0003F21A | 0x0003F208 | 0x0003F21A ✓ |
| CAPE_100%.SAV | 0x0008AC49 | 0x0008AC37 | 0x0008AC49 ✓ |

**Key Functions:**
| Function | Address | Purpose |
|----------|---------|---------|
| `FUN_01B6F170` | `0x01B6F170` | Computes Field4 via `sub edx, eax` |
| `FUN_00425360` | `0x00425360` | Buffer descriptor setter (receives Field4) |
| `FUN_01AFD600` | `0x01AFD600` | Main serializer orchestrator |

### 2.3 Footer Format

SAV files do not have a dedicated footer. Block 5 ends at the file's end.

### 2.4 Region Structure (Blocks 3-5)

**Discovery:** Blocks 3 and 5 (and the relationship with Block 4) use a **Region** structure with checksums.

#### Region Format

Each region within Blocks 3 and 5 has:

```
Offset | Size | Field           | Description
-------|------|-----------------|----------------------------------
0x00   | 1    | Version         | Always 0x01
0x01   | 3    | Size            | 24-bit LE data size
0x04   | 4    | Flags           | Always 0x00008000
0x08   | 1    | Prefix          | Always 0x00
0x09   | 4    | Checksum        | Zero-seed Adler32 of data
0x0D   | N    | Data            | Region data (N = Size - 5)
```

#### Block 3 Region Layout

Block 3 contains **4 regions**:

| Region | Purpose | Typical Size |
|--------|---------|--------------|
| 1 | World data | ~3,670 bytes |
| 2 | Additional data | ~2,300 bytes |
| 3 | Additional data | ~2,300 bytes |
| 4 | **Block 4 reference** | 5 bytes local + size declaration |

**Critical:** Region 4's **declared size** equals Block 4's **compressed LZSS size**. The checksum in Region 4's prefix is the Adler32 of Block 4's LZSS data.

#### Cross-Block Reference (Region 4 → Block 4)

```
Block 3 Region 4:
  [01] [size 3B] [00 00 80 00] [00] [checksum 4B] [5 bytes local data]
       ↑                             ↑
       Block 4 LZSS size             Adler32 of Block 4 LZSS data

Block 4:
  [LZSS compressed data - size declared in Region 4]
```

When modifying Block 4:
1. Recompress Block 4 data
2. Update Region 4's size field (bytes 1-3) with new compressed size
3. Update Region 4's checksum (bytes 9-12) with Adler32 of new LZSS data

---

## 3. LZSS Compression Layer

The game uses an LZSS (Lempel-Ziv-Storer-Szymanski) compression variant with three encoding types. The same compressor is used for both OPTIONS and SAV files.

### 3.1 Encoding Types

| Type | Bits | Condition | Description |
|------|------|-----------|-------------|
| **Literal** | 9 | N/A | Flag 0 + 8-bit byte |
| **Short Match** | 12 | Length 2-5, offset <= 256 | Flag 1, type 0, 2-bit length, 8-bit offset |
| **Long Match** | 18+ | Length >= 2, any offset | Flag 1, type 1, 16-bit encoding, optional extension bytes |

### 3.2 Bit Layouts

#### Literal (9 bits)

```
[0][byte:8]
 |    |
 |    +-- Raw byte value
 +-- Flag = 0 (literal)
```

#### Short Match (12 bits)

```
[1][0][length-2:2][offset-1:8]
 |  |      |           |
 |  |      |           +-- Offset encoded as (offset - 1)
 |  |      +-- Length encoded as (length - 2), values 0-3 = lengths 2-5
 |  +-- Type = 0 (short match)
 +-- Flag = 1 (match)
```

**Constraints:**
- Length: 2-5 bytes
- Offset: 1-256 bytes

#### Long Match (18+ bits)

```
[1][1][16-bit encoding][extension bytes...]
 |  |        |                |
 |  |        |                +-- Optional, for lengths >= 10
 |  |        +-- Combined offset/length encoding
 |  +-- Type = 1 (long match)
 +-- Flag = 1 (match)
```

**16-bit Encoding:**
- Bits 0-12: Offset (13 bits, max 8191)
- Bits 13-15: Length - 2 (3 bits, values 0-7 = lengths 2-9)

For lengths >= 10, extension bytes follow:
- Each extension byte adds to the length
- Value 0 indicates more bytes follow
- Final byte is non-zero

### 3.3 Terminator Sequence

The LZSS stream ends with a special terminator:

```
Two 1-bits followed by 0x20 0x00
```

This encodes as a long match with distance = 0, which signals end of stream. The decompressor must check for this before attempting to copy.

### 3.4 2-Byte Zero Prefix

**Critical Implementation Detail:**

Input data is prefixed with `0x00 0x00` in the compression buffer. Encoding starts at position 2.

This means:
- Positions 0-1 in the buffer contain `0x00 0x00`
- Actual input data starts at position 2
- Matches cannot reference the prefix (positions 0-1)

**Prefix Constraint:** Enforce with `max_offset = min(max_offset, pos - 2)`. This affects files ending with long runs of zeros.

### 3.5 Match Length Encoding

The game supports matches up to **2048 bytes** for highly repetitive SAV data.

#### Extension Byte Encoding

For long matches with length >= 10:

```
Base length from 16-bit encoding: 9 (maximum in 3 bits)
Extension bytes add to this base:
  - Extension byte 0x00: Add 255, more bytes follow
  - Extension byte 0xNN: Add NN, no more bytes

Length 2048 = 9 + (7 * 255) + 254
Encoded as: 7 zero bytes followed by 0xFE
```

| Length | Extension Bytes |
|--------|-----------------|
| 2-9 | None |
| 10-263 | Single byte |
| 264-518 | `0x00` + byte |
| 519-773 | `0x00 0x00` + byte |
| ... | ... |
| 2048 | `0x00 0x00 0x00 0x00 0x00 0x00 0x00 0xFE` |

**Important:** The `max_match_length` parameter should be set to 2048 bytes to match game behavior.

---

## 4. Compression Algorithm Details

The game uses a **lazy matching compressor** with **context-aware length bias** for short/near matches. This was discovered through WinDbg time-travel debugging of function `026be140`.

### 4.1 Lazy Matching

Instead of immediately encoding the best match found at the current position, the compressor:
1. Finds the best match at the current position
2. Looks ahead to find the best match at the next position
3. Compares them using an adjustment formula
4. Decides whether to take the current match or skip it (encode as literal)

### 4.2 Adjustment Formulas

The core algorithm uses a **counter** variable to bias the decision:

```python
counter = 1  # Default bias

# Bonus for short near matches
if (2 <= current_match.length <= 5) and (current_match.offset <= 256):
    counter = 2  # Give bonus for short near matches

# Check next match (lookahead)
if (2 <= current_match.length <= 5) and (current_match.offset <= 256):
    if (2 <= next_match.length <= 5) and (next_match.offset <= 256):
        counter += 2  # Both are short+near

if (2 <= next_match.length <= 5) and (next_match.offset <= 256):
    counter -= 1  # Reduce bonus if next is also short

counter = max(counter, 1)  # Minimum 1

# Decision: take current match or skip it?
if next_match.length < (current_match.length + counter):
    encode_match(current_match)  # Take current
else:
    encode_literal()  # Skip current, try next position
```

#### Transition Rules Summary

| Current | Next | Counter Calculation |
|---------|------|---------------------|
| Long | Long | 1 (default) |
| Long | Short | 1 - 1 = 1 (min enforced) |
| Short | Long | 2 (short bonus) |
| Short | Short | 2 + 2 - 1 = 3 |

**Where "Short" means:** length 2-5 AND offset <= 256

### 4.3 Match Finder Behavior

#### Backward Scanning

The match finder scans backward from `pos-1` down to `max(0, pos-max_offset)`:
- Uses strict `>` comparison to prefer the first (most recent) match found
- For equal-length matches, prefers closer offsets

#### First Byte Forced Literal

The game always encodes the first input byte as a literal, regardless of any matches found. This simplifies initialization.

#### Offset Encoding Asymmetry

- **Short matches:** Encode `offset - 1` in file; decoder adds +1
- **Long matches:** Encode `offset` directly in file; decoder uses as-is

This asymmetry was discovered through SAV file analysis.

#### Minimum Offset Rules

- Long matches require offset >= 1
- Short matches allow offset = 1 for RLE (run-length encoding) of repeated bytes

### 4.4 Tie-Breaking Rules

These rules were verified through WinDbg TTD analysis of function `026be140`:

#### Assembly Locations

| Address | Purpose | Key Instructions |
|---------|---------|------------------|
| `026be201` | Initial bias check | Sets counter = 2 for short+near |
| `026be252` | Lookahead call | Calls match finder for next pos |
| `026be263` | Lookahead analysis | Checks both current+next conditions |
| `026be286` | Bonus addition | Adds counter when both short+near |
| `026be291` | Next match penalty | Decrements if next is short+near |
| `026be2a4` | Minimum enforcement | Forces counter >= 1 |
| `026be2ae` | Final decision | Compares and branches |

#### The Decision

```assembly
026be2ae 8b550c          mov     edx,dword ptr [ebp+0Ch]  ; current_length
026be2b1 03d1            add     edx,ecx                   ; + counter
026be2b3 3bc2            cmp     eax,edx                   ; next_length < adjusted?
026be2b5 723f            jb      026be2f6                  ; If yes: take match
                                                           ; If no: skip (literal)
```

#### Cost-Benefit Analysis

Reject matches where `match_cost >= literal_cost` (9 bits per literal). When costs are equal, prefer literals.

---

## 5. Decompressed Content Format

Blocks 1, 2, and 4 use **protobuf-style tagged binary serialization**. Blocks 3 and 5 use a compact binary format (not fully understood).

### 5.1 Tagged Binary Format

#### Field Marker Pattern

```
[TAG:1] [00:1] [0B:1] [type-specific data...]
```

All field markers follow the pattern `XX 00 0B` where `XX` is the type tag.

### 5.2 Type Hash System

Type and property names are hashed using **CRC32**:

```python
import zlib
hash_value = zlib.crc32(b"SaveGame") & 0xFFFFFFFF  # 0xBDBE3B52
```

#### Confirmed Type Hashes

| Hash | Type Name | Block | Purpose |
|------|-----------|-------|---------|
| 0xBDBE3B52 | SaveGame | 1 | Player profile |
| 0x94D6F8F1 | AssassinSaveGameData | 2 | Game state |
| 0xA1A85298 | PhysicalInventoryItem | 4 | Inventory item |
| 0xBB96607D | ManagedObject | Base | Base type |
| 0xFBB63E47 | World | 3 | World data |

#### Confirmed Property Hashes

| Hash | Property Name | Occurrences | Context |
|------|---------------|-------------|---------|
| 0x0984415E | **Entity** | 1,200+ | Base type for all game objects |
| 0xF8206AF7 | **IColor** | 87 | Color interface property |
| 0x85C817C3 | **Material** | 79 | Material/texture reference |

### 5.3 Field Structures

#### Wire Types

| Wire | Name | Size | Description |
|------|------|------|-------------|
| 0 | Varint | 1-10 bytes | Variable-length integer |
| 1 | Fixed64 | 8 bytes | 64-bit fixed value |
| 2 | Length-delimited | 4 + N bytes | Length prefix (u32 LE) + payload |
| 5 | Fixed32 | 4 bytes | 32-bit fixed value |

#### Property Entry Structure (32 bytes)

Properties in the EXE type descriptors follow a 32-byte structure (found at VA 0x027ECDC0):

```
+0x00: reserved (8 bytes)
+0x08: flags (4 bytes) - typically 0x02000001
+0x0C: property_hash (4 bytes)
+0x10: nested_type_ref (4 bytes) - 0 for primitives, hash for nested
+0x14: type_info (2 bytes) - encodes type:
       0x0007 = primitive (int/float/bool)
       0x001A = array
       0x0012 = object reference
       0x001D = complex nested
+0x16: unknown (2 bytes)
+0x18: struct_offset (4 bytes)
+0x1C: reserved (4 bytes)
```

This structure is identical between OPTIONS and SAV file descriptors.

#### Field Type Catalog

| Type | Name | Structure | Description |
|------|------|-----------|-------------|
| 0x07 | Integer+Hash | `[value:4] [11 00 00 00] [hash:4]` | Integer with type reference |
| 0x12 | Complex64 | `[hash:4] [subtype:4] [nested...]` | Complex nested structure |
| 0x15 | Integer | `[value:4]` | Simple 32-bit integer |
| 0x19 | Container | `[count:4] [container_hash:4] [child_hash:4]` | Array/list structure |
| 0x1A | String | `[length:4] [UTF-8] [null]` | Length-prefixed string |
| 0x1D | Variant | `[variant:1] [data...]` | Wrapper with mode selector |

#### String Example

```
Offset 0x009F: 1A 00 0B 07 00 00 00 44 65 73 6D 6F 6E 64 00
               |        |           D  e  s  m  o  n  d  \0
               |        +-- length = 7 (little-endian u32)
               +-- marker: 1A 00 0B

Result: "Desmond"
```

### 5.4 Block Contents

#### Block 1: SaveGame (283 bytes)

- 12 field markers
- Contains player name "Desmond" at offset 0x009F
- Type hash 0xBDBE3B52
- Descriptor shows 92 properties (only 12 serialized)

##### Block 1 Complete Field Map

| Field | Offset | Type | Value | Nested Hash |
|-------|--------|------|-------|-------------|
| 0 | 0x0024 | 0x07 | 22 | 0x2578300E |
| 1 | 0x0039 | 0x07 | 16702380 (0x00FEDBAC) | 0xF5C71F6B |
| 2 | 0x004E | 0x07 | 6 | 0xBB6621D2 |
| 3 | 0x0063 | 0x07 | 351759 | 0x28550876 |
| 4 | 0x0078 | 0x07 | 0 | - |
| 5 | 0x008D | 0x00 | (separator) | - |
| 6 | 0x009F | 0x1A | "Desmond" | - |
| 7 | 0x00BC | 0x12 | 2376877923 | uint64: 6907056868397715093 |
| 8 | 0x00D1 | 0x12 | 0 | uint64: 3950429234 |
| 9 | 0x00E6 | 0x07 | 1 | 0x28F5132B |
| 10 | 0x00FB | 0x07 | 0 | 0x8C00191B |
| 11 | 0x0110 | 0x07 | 1689788455 | - |

##### Block 1 Hex Evidence

```
Leading zeros: 10 bytes (0x0000-0x0009)
Data starts at: 0x000A with type hash 52 3B BE BD

Field 0 @ 0x0024 - Type 0x07:
  07 00 0B 16 00 00 00 11 00 00 00 0E 30 78 25
  ^marker  ^value=22   ^separator   ^hash=0x2578300E

Field 6 @ 0x009F - Type 0x1A (String):
  1A 00 0B 07 00 00 00 44 65 73 6D 6F 6E 64 00
  ^marker  ^len=7      D  e  s  m  o  n  d  \0

Field 7 @ 0x00BC - Type 0x12 (Complex):
  12 00 0B 63 47 AC 8D 11 00 00 00 95 8E 44 6C A0 CB DA 5F
  ^marker  ^value       ^separator  ^uint64
```

#### Block 2: AssassinSaveGameData (32,768 bytes)

- ~750 field markers
- Single monolithic object (type hash appears only once at header)
- Type hash 0x94D6F8F1
- Contains game state, mission progress
- 2 type_19 containers
- 18 type_1D variants
- 26 type_12 structures

##### Block 2 Header Structure (36 bytes)

| Offset | Size | Value | Description |
|--------|------|-------|-------------|
| 0x00 | 10 | 00 00 ... | Leading zeros |
| 0x0A | 4 | 0x94D6F8F1 | Type hash |
| 0x0E | 4 | 0x0003F208 | Size indicator (258568) |
| 0x12 | 4 | 0x0003F1B8 | Secondary size (258488) |
| 0x16 | 4 | 0x00000011 | Separator indicator |
| 0x1A | 4 | 0xBF4C2013 | First property hash |

##### Block 2 Field Type Distribution

| Type | Count | Purpose |
|------|-------|---------|
| 0x00 | 425 | Separator/Padding |
| 0x07 | 268 | Integer fields |
| 0x12 | 26 | Complex64 fields |
| 0x1D | 18 | Variant/Optional |
| 0x19 | 2 | Container |

##### Block 2 Type 0x1D Variant Distribution

| Variant | Count | Structure |
|---------|-------|-----------|
| 0x00 | 4 | Simple |
| 0x01 | 1 | Array |
| 0x0A | 4 | Fixed |
| 0x0B | 9 | Complex |

#### Block 3: World (7,972 bytes)

- Compact binary format (not tagged)
- Type hash 0xFBB63E47
- Structure not fully understood

##### Compact Format Encoding

The compact format uses a 4-byte encoding pattern:

```
[Field_Tag] [Type_Indicator] [Table_ID] [Property_Index]
    1 byte      1 byte         1 byte      1 byte
```

**Components:**
- **Field Tag (byte 0)**: Protobuf-style field tag = (field_number << 3) | wire_type
- **Type Indicator (byte 1)**: Encoding type
  - `0x02`: Length-delimited / nested message
  - `0x03`: Fixed-size / embedded type reference
  - `0x06`: Extended type reference
- **Table ID (byte 2)**: Type index (0x20-0x90 range observed) - resolved via `FUN_01AEAF70`
- **Property Index (byte 3)**: Property within the type

##### Serialization Flag and TYPE_REF Encoding

The first byte after type resolution indicates the serialization mode:
- **0x00**: Direct type lookup - Type by table ID (next 4 bytes are the ID), resolved via `FUN_01aeaf70` directly
- **Non-zero**: Indirect type lookup - Resolves through descriptor chain via `FUN_01af6420` → `FUN_01ae9390` → `FUN_01aeaf70`

**TYPE_REF Dual Encoding Mode:**

The TYPE_REF serializer (`FUN_00427530` at `0x00427530`) implements two encoding paths:

| First Byte | Path | Function Chain |
|------------|------|----------------|
| `0x00` | Direct lookup | `FUN_01aeaf70(type_hash, 0)` |
| `!= 0x00` | Indirect lookup | `FUN_01af6420` → `FUN_01ae9390` → `FUN_01aeaf70` |

**Binary Format:**
```
Direct:   [00] [4-byte type hash]  -> FUN_01aeaf70 lookup
Indirect: [XX] [4-byte hash]       -> Descriptor chain lookup (XX != 0)
```

**Helper Functions:**
- `FUN_01AF6420` (0x01AF6420): TYPE_REF indirect handler wrapper
- `FUN_01AE9390` (0x01AE9390): Type resolution with descriptor chain lookup
- `FUN_01B1EEB0`: Tree map lookup by key
- `FUN_004253E0`: Assignment helper
- `FUN_0041DC10`: Cleanup/destructor

##### Block 3 Primary Pattern

- **Pattern**: `08 03 5E XX`
- **Occurrences**: 63 in Block 3
- **Property range**: 0x01 - 0xD9 (217+ properties)
- **Associated hash**: 0xFBB63E47
- **Type descriptor VA**: 0x027E46E0

#### Block 4: PhysicalInventoryItem (32,768 bytes)

- ~1,094 field markers
- **Array of 364 PhysicalInventoryItem objects**
- Type hash 0xA1A85298 appears 364 times (once per item)
- Contains inventory items with timestamps
- 98 type_19 containers
- 204 type_1D variants
- 369 type_12 structures
- Entity hash (0x0984415E) nested in nearly all items

**Note:** Block 4 has NO header - LZSS data starts directly.

##### Block 4 Field Type Distribution

| Type | Count | Purpose |
|------|-------|---------|
| 0x12 | 369 | Complex64 - dominant |
| 0x07 | 368 | Integer fields |
| 0x1D | 219 | Variant/Optional |
| 0x19 | 98 | Container structures |

##### Item Size Distribution

The 364 inventory items have varying sizes based on their properties:

| Size | Count | Description |
|------|-------|-------------|
| 69 bytes | 145 | Standard item |
| 158 bytes | 84 | Medium item |
| 22 bytes | 55 | Minimal item |
| 66 bytes | 36 | Small variant |
| 25 bytes | 36 | Minimal variant |

##### Item Header Structure

Each item starts with:
- Type hash (4 bytes): 0xA1A85298
- Field1 (4 bytes): Often 0x32 (50)
- Field2 (4 bytes): Often 0x2A (42)
- Field3 (4 bytes): Often 0x11 (17)
- Variable field data

##### Parsing Strategy

To parse Block 4 as an array:
1. Find all occurrences of type hash 0xA1A85298
2. Each occurrence marks an item boundary
3. Parse fields between boundaries using tagged format rules

##### Timestamp Evidence

Unix timestamp **1607889367** found multiple times:
- Converts to: December 13, 2020 21:29:27 UTC
- Represents item acquisition/modification times

#### Block 5: Unknown (6,266 bytes)

- Compact binary format (not tagged)
- Always last 6,266 bytes of file
- Structure not fully understood

##### Block 5 Primary Pattern

- **Pattern**: `19 02 4F XX`
- **Occurrences**: 61 in Block 5
- **Property range**: 0x52 - 0xB6

##### Common Table IDs (Both Compact Blocks)

| Table ID | Prefix Pattern | Block 3 Props | Block 5 Props | Notes |
|----------|---------------|---------------|---------------|-------|
| 0x3B | 05 02 3B | 0x08-0xFE | 0x19-0xF0 | High property count |
| 0x38 | 05 02 38 | 0x4C-0xE0 | 0x4C-0xF0 | Shared type |
| 0x37 | 3A 03 37 | 0x05-0xB5 | 0x05-0xB5 | Identical ranges |
| 0x54 | 31 03 54 | 0x00-0x4F | 0x00-0x4F | Identical ranges |
| 0x5B | 08 03 5B | 0x03-0xB6 | N/A | Block 3 only |

##### Observed Table ID Range

```
0x20, 0x21, 0x22, 0x25, 0x27, 0x28, 0x2A, 0x2C, 0x2E,
0x30, 0x31, 0x32, 0x37, 0x38, 0x3A, 0x3B, 0x3D, 0x3F,
0x40, 0x42, 0x43, 0x44, 0x48, 0x4A, 0x4C, 0x4D, 0x4E,
0x4F, 0x50, 0x51, 0x52, 0x53, 0x54, 0x55, 0x56, 0x58,
0x5A, 0x5B, 0x5C, 0x5D, 0x5E, 0x5F, 0x60, 0x61, 0x64,
0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x6C, 0x6D, 0x6E,
0x70, 0x72, 0x76, 0x78, 0x7A, 0x7E, 0x7F, 0x80
```

##### Key Table IDs and Usage (from Ghidra Analysis)

| Table ID | References | Function | Purpose |
|----------|------------|----------|---------|
| 0x20 | 111 | FUN_004701E0 | Fundamental/common type (52 refs in one function) |
| 0x3B | 4 | FUN_0040B1B0, FUN_004A5900 | Unknown |
| 0x4F | 1 | FUN_00488640 | Used in Block 5 |
| 0x5E | 0 | (encoded differently) | Used in Block 3 |
| 0x21 | 2 | FUN_00487AA0 | Unknown |
| 0x25 | 1 | FUN_00487AA0 | Unknown |
| 0x27 | 1 | FUN_0046DF80 | Unknown |

---

## 6. Checksums

SAV files use **Adler-32 with zero seed**, a non-standard variant:

```python
def adler32_zero_seed(data: bytes) -> int:
    """
    Adler-32 with zero seed (game variant).
    Standard Adler-32 uses s1=1, s2=0; game uses s1=0, s2=0.
    """
    MOD_ADLER = 65521
    s1 = 0  # NON-STANDARD (normally 1)
    s2 = 0

    for byte in data:
        s1 = (s1 + byte) % MOD_ADLER
        s2 = (s2 + s1) % MOD_ADLER

    return (s2 << 16) | s1
```

| Property | Standard Adler-32 | AC Brotherhood |
|----------|-------------------|----------------|
| Initial s1 | 1 | 0 |
| Initial s2 | 0 | 0 |
| Empty input result | 0x00000001 | 0x00000000 |

The checksum is calculated on the **uncompressed** data and stored in the block header at offset 0x28.

---

## 7. Key Addresses

The same LZSS compressor is used for **both OPTIONS and SAV files**. Confirmed via WinDbg TTD tracing.

### Address Mapping

**CRITICAL:** WinDbg runtime addresses must be converted to Ghidra static addresses:

| Base | Description | Value |
|------|-------------|-------|
| WinDbg runtime | Module base (varies with ASLR) | Example: `0x00F30000` |
| Ghidra static | Default analysis base | `0x00400000` |

**Conversion formula:** `Ghidra VA = 0x400000 + WinDbg offset`

**Example:** WinDbg `ACBSP+0x1711ab0` = Ghidra `0x01B11AB0`

### Function Offsets (from ACBSP module base)

| Offset | Ghidra Address | Purpose |
|--------|----------------|---------|
| `+0x178E140` | `0x01B8E140` | Compression entry point |
| `+0x178E0A0` | `0x01B8E0A0` | Match finder function |
| `+0x178E463` | `0x01B8E463` | Long match encoding |
| `+0x0046D430` | `0x0046D430` | **SAV Block Parser** - main block iteration |

**Note:** Runtime addresses vary with ASLR. Use offset from module base:
- If ACBSP loads at `0x00F30000`: compressor is at `0x026BE140`
- If ACBSP loads at `0x00AB0000`: compressor is at `0x0223E140`

### Block Parser Function (FUN_0046d430)

The main SAV block parsing function at Ghidra VA `0x0046d430`:

**Header Validation:**
- Validates SAV file header at offsets 0x00 and 0x04:
  - `magic1 = 0x16` (constant)
  - `magic2 = 0xFEDBAC` (constant)
- Reads total data size from offset 0x08
- Block data starts at offset 0x0C

**Block Iteration:**
- Block object array pointer: SaveSlot+0x3C
- Block count: SaveSlot+0x42 (masked with 0x3FFF)
- Each block prefixed with 4-byte size field
- Dispatches to format-specific deserializer via vtable[10]

**SaveSlot Structure (partial):**

| Offset | Size | Purpose |
|--------|------|---------|
| +0x3C | 4 | Block object array pointer |
| +0x42 | 2 | Block count (& 0x3FFF mask) |
| +0x44 | 6 | Various flags |

Block objects are 0x488 bytes each.

### SAV Decompressed Block Content Format

**Important:** SAV blocks do NOT have 8-byte magic headers inside the decompressed data. The magic values (`0x00CAFE00`, `0x11FACE11`, `0x21EFFE22`) appear in the **outer 44-byte block headers**, not as inner format markers after decompression.

#### Full Format Blocks (1, 2, 4 - LZSS Compressed)

After LZSS decompression, the block content starts with:

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 10 bytes | Null padding (`00 00 00 00 00 00 00 00 00 00`) |
| 0x0A | 4 bytes | Type hash (little-endian) |
| 0x0E | varies | Serialized object data |

**Block Type Hashes:**

| Block | Type Hash | Type Name |
|-------|-----------|-----------|
| 1 | `0xBDBE3B52` | SaveGame |
| 2 | `0x94D6F8F1` | AssassinSaveGameData |
| 4 | `0xA1A85298` | PhysicalInventoryItem (first of 364) |

#### Compact Format Blocks (3, 5 - Uncompressed)

These blocks are NOT LZSS compressed. Their content starts with:

| Offset | Size | Description |
|--------|------|-------------|
| 0x00 | 1 byte | Version prefix (`0x01`) |
| 0x01 | 3 bytes | Size field (24-bit little-endian) |
| 0x04 | 4 bytes | Flags (`0x00800000`) |
| 0x08 | varies | Nibble-encoded table IDs and property data |

### OPTIONS Section Magic Values (NOT for SAV Blocks)

The magic values `0x11FACE11` and `0x21EFFE22` are **OPTIONS file specific**:

| Magic | Used In | Location |
|-------|---------|----------|
| `0x11FACE11` | OPTIONS Section 2 | Field3 (offset 0x08) in 44-byte header |
| `0x21EFFE22` | OPTIONS Section 3 | Field3 (offset 0x08) in 44-byte header |

These identify OPTIONS section types, not SAV block content formats.

### SAV Block Header Field3 Values

Only Blocks 1 and 2 have 44-byte headers with Field3 values. Blocks 3, 4, and 5 do NOT have 44-byte headers.

| Block | File Offset | Field3 Value | Notes |
|-------|-------------|--------------|-------|
| 1 | 0x0008 | `0x000000CD` | SaveGame root - small-value format (similar to OPTIONS Section 1's `0xC5`) |
| 2 | 0x00E1 | `0x00CAFE00` | Game state - themed marker (CAFE00 deserializer at `FUN_01B11AB0`) |
| 3 | N/A | No header | Raw compact format - no 44-byte header |
| 4 | N/A | No header | LZSS data only - no 44-byte header |
| 5 | N/A | No header | Raw compact format - no 44-byte header |

**Field3 Value Patterns:**
- Small values (`0xC5`, `0xCD`) are used for "simple" sections/blocks (OPTIONS Section 1, SAV Block 1)
- Themed markers (`0x00CAFE00`, `0x11FACE11`, `0x21EFFE22`) are used for data sections

This is in the **outer** block header structure, not the decompressed content.

### Block Deserializer Functions

| Ghidra VA | Purpose |
|-----------|---------|
| `0x01B11AB0` | **CAFE00 Deserializer** - validates type==1 && magic==0x00CAFE00, skips 8-byte header |
| `0x01712660` | Raw/compact format reader (Blocks 3, 5) |
| `0x01711320` | Property deserializer (reads type hashes and data) |
| `0x01AFD600` | **Main deserializer orchestrator** - called by CAFE00 deserializer |
| `0x01B0A740` | Object extraction/deserialization |
| `0x01B08CE0` | **ObjectInfo metadata parser** - extracts SerializerVersion, ClassVersion, ObjectName, etc. |
| `0x01B6F730` | Creates stream reader object (0x38 bytes) |
| `0x01B49250` | Creates parser object (0x1058 bytes, vtable at 0x02555C60) |
| `0x01AEDD90` | Pushes parser state onto stack (0x12d8 bytes) |
| `0x01B7A1D0` | OPTIONS magic detector (0x57FBAA33, 0x1004FA99) |
| `0x01B7B190` | Decompresses OPTIONS-style headers (32KB chunks) |

**Note:** `0x00425360` is a buffer descriptor setter, NOT a parser. Avoid confusing it with deserializers.

### Stream Reader Architecture (December 2024)

The deserialization system uses a layered stream reader architecture:

#### Stream Reader Object (0x38 bytes)

**Factory:** `FUN_01B6F730` - Allocates and initializes stream reader
**Constructor:** `FUN_01B6F590` - Sets vtable at `0x02556168`

| Offset | Size | Purpose |
|--------|------|---------|
| +0x00 | 4 | Vtable pointer (0x02556168) |
| +0x04 | 4 | Flags |
| +0x08 | 4 | Unknown |
| +0x0C | 4 | Unknown |
| +0x10 | 4 | Unknown |
| +0x14 | 4 | Buffer base pointer |
| +0x18 | 4 | Current read position |
| +0x1C | 4 | Buffer size/limit |
| +0x30 | 4 | Mode flag |
| +0x34 | 1 | Additional flags |

#### Stream Reader Vtable (0x02556168)

Key methods for reading/writing:

| Offset | Slot | Function | Purpose |
|--------|------|----------|---------|
| 0x24 | 9 | `0x01B6F150` | **Read single byte** - `*dest = *stream++` |
| 0x3C | 15 | `0x01B6F370` | **Write single byte** - `*stream++ = byte` |

**FUN_01B6F150** (byte reader):
```c
*param_2 = **(byte **)(this + 0x18);  // Read byte from current position
*(int *)(this + 0x18) += 1;            // Advance position
```

### Parser Object Architecture

**Factory:** `FUN_01B49250` - Creates 0x1058 byte parser object
**Vtable:** `0x02555C60`

#### Parser Vtable (0x02555C60) - Extended

| Offset | Slot | Function | Purpose |
|--------|------|----------|---------|
| 0x00 | 0 | `0x01B49B10` | Constructor/base |
| 0x08 | 2 | `0x01B48770` | BeginElement |
| 0x10 | 4 | `0x01B487A0` | EndElement |
| 0x50 | 20 | `0x01B48FB0` | Read type hash ("T") |
| 0x54 | 21 | `0x01B48E90` | Read ObjectName |
| 0x84 | 33 | `0x01B48C10` | Read ClassID |
| 0x8C | 35 | `0x01B48C00` | Read Version |
| 0x98 | 38 | `0x01B48B70` | **Read PackedInfo** → dispatches to stream reader |
| 0x9C | 39 | `0x01B48E70` | Read ObjectID |

**FUN_01B48B70** → **FUN_01B49430** (Parser Dispatcher):
- Routes read/write operations to underlying stream reader
- Maintains counter state at `parser + 8 + index*8`
- Checks mode flag at `parser + 4` to select read vs write path

### TYPE_REF Dispatcher (FUN_01AF6A40)

**Purpose:** Dispatches type references based on prefix byte in full format data.

**Important:** This dispatcher uses **4-byte type hashes**, NOT nibble-encoded table IDs. It handles Blocks 1, 2, and 4 (full format), not Blocks 3 and 5 (compact format).

```c
prefix = read_byte();
switch (prefix) {
    case 0x00:  // Full object with nested deserialization
        skip(1);
        type_hash = read_uint32();
        object = FUN_01aeb020(type_hash, 0);  // Lookup by hash
        // ... recursive deserialization
        break;

    case 0x01:  // Type reference with validation
        sub_type = read_byte();
        type_hash = read_uint32();
        if (validator != NULL) {
            validator->vtable[3](type_hash);  // Validate type
        }
        object = FUN_01aeb020(type_hash, 0);
        FUN_01ae64f0(type_hash, param_2, sub_type);
        break;

    default:    // >= 0x02: Simple object reference
        skip(1);
        type_hash = read_uint32();
        object = FUN_01aeb020(type_hash, 0);
        break;
}
```

### Type Lookup System

Two parallel lookup paths exist:

| Function | Input | Purpose | Used By |
|----------|-------|---------|---------|
| `FUN_01AEAF70` | Table ID (small int) | Direct table lookup | Compact format (Blocks 3, 5) |
| `FUN_01AEB020` | Type hash (4 bytes) | Hash-based lookup | Full format (Blocks 1, 2, 4) |

Both converge on **FUN_01AEAD60** (core lookup):

```
FUN_01AEAF70 (table ID) ──┐
                          ├──> FUN_01AEAD60 ──> FUN_01AEA0B0 (actual lookup)
FUN_01AEB020 (type hash) ─┘
```

#### FUN_01AEB020 (Type Hash Lookup)

- Wraps FUN_01AEAD60 with locking
- Lock at `manager + 0x7C`
- Returns null singleton if both params are 0

#### FUN_01AEAD60 (Core Lookup)

- Manages type descriptor table at `manager + 0x98`
- Count at `manager + 0x9E` (masked 0x3FFF)
- Each bucket: 12 bytes (base ptr, unknown, entry index)
- Each entry: 16 bytes
- Entry index calculation: `entry_addr = bucket_base + (entry_index << 4)`

### Type Descriptors in EXE

| Type Hash | Type Name | Serializer VA | Descriptor VA |
|-----------|-----------|---------------|---------------|
| 0xBDBE3B52 | SaveGame | 0x005E3560 | 0x027ECFC8 |
| 0x94D6F8F1 | AssassinSaveGameData | 0x01710EC0 | 0x02973688 |
| 0xA1A85298 | PhysicalInventoryItem | 0x00E6E570 | 0x028830D0 |
| 0xBB96607D | ManagedObject (Base) | - | Multiple |
| 0xFBB63E47 | World | - | 0x027E46E0 |

### Related Strings in EXE (.rdata)

| String | VA |
|--------|-----|
| "SaveGame" | 0x023F1408 |
| "SaveGameManager" | 0x023E7510 |
| "SaveGameDataObject" | 0x023F13F4 |
| "SaveGameWriter::WriteFile" | 0x023F1490 |
| "SaveGameWriter::ReadFile" | 0x023F14F8 |
| "GameStateData" | 0x0240740C |
| "MissionHistory" | 0x023F1A94 |
| "SaveGameData" | 0x0249EC82 |
| "SaveGameComponent" | 0x023FB218 |
| "ProfileData" | 0x0253DDFA |
| "ACBROTHERHOODSAVEGAME" | 0x02411ecc |
| "OPTIONS" | 0x023f14e8 |
| "save:SAVES" | 0x023f1474 |

### SaveGame I/O System

The game uses a layered architecture for save file operations:

1. **SaveGameManager** - High-level orchestration
2. **SaveGame I/O Class** - File read/write/delete operations
3. **Block Deserializers** - Format-specific content parsing (Full Format and Compact Format handlers)

#### SaveGameManager Class

**Constructor:** `FUN_0046dcc0` (Ghidra VA)

Creates a ~0x360 byte object containing:
- Multiple vtables for different interfaces
- Sub-objects at offsets 0x188, 0x19c, 0x1b0, 0x1c4, 0x1d8, 0x1ec, 0x200, 0x214, 0x228, 0x23c, 0x250, 0x264
- SaveGame I/O object pointer at offset 0x28c

**Callers:** `FUN_0046dea0`, `FUN_0046df80`, `FUN_0046f6b0` - Main save system entry points

#### SaveGame I/O Class

**Factory:** `FUN_005e49d0` - Allocates 0x18 bytes, calls constructor
**Constructor:** `FUN_009ca3e0` - Initializes vtable at 0x02411f30

#### SaveGame I/O Vtable (0x02411f30)

| Slot | Address | Method | Purpose |
|------|---------|--------|---------|
| 0 | `0x009ca550` | **Destructor** | Cleans up array at +0x4, frees memory |
| 1 | `0x009ca250` | **WriteSavegame** | Writes `ACBROTHERHOODSAVEGAME{slot}.` via WriteFile |
| 2 | `0x009ca290` | **ReadSavegame** | Reads `ACBROTHERHOODSAVEGAME{slot}.` via ReadFile |
| 3 | `0x009ca2d0` | **WriteOptions** | Writes `OPTIONS` via WriteFile |
| 4 | `0x009ca2f0` | **ReadOptions** | Reads `OPTIONS` via ReadFile |
| 5 | `0x009ca430` | Stub | Returns false (`XOR AL,AL`) |
| 6 | `0x009ca440` | Stub | Returns true (`MOV AL,1`) |
| 7 | `0x009ca450` | Stub | Empty (`RET`) |
| 8 | `0x009ca310` | **DeleteSavegame** | Calls `DeleteFileW` + cleanup loop |
| 9 | `0x005e4990` | **CheckAssassinSav** | Checks if `assassin.sav` exists |
| 10 | `0x009ca460` | Stub | Returns true |
| 11 | `0x009ca470` | Stub | Returns 0 |
| 12 | `0x009ca480` | Stub | Empty |
| 13 | `0x009ca490` | Stub | Empty (pops 4 bytes) |
| 14 | `0x009ca4a0` | Stub | Empty |
| 15 | `0x009ca4b0` | Stub | Empty |

#### File I/O Functions (Low-Level)

| Function | Purpose |
|----------|---------|
| `FUN_005e4b10` | **SaveGameWriter::ReadFile** - Raw disk read into buffer |
| `FUN_005e4860` | **SaveGameWriter::WriteFile** - Raw disk write from buffer |

**Important:** These are pure I/O utility functions. They read/write raw bytes from/to disk. The actual SAV block structure parsing and content deserialization happens in separate functions AFTER the raw file is loaded into memory.

#### Deserialization Flow (Complete)

```
SaveGameManager callers (0046dea0, 0046df80, 0046f6b0)
    |
    +-- FUN_0046dcc0 (SaveGameManager constructor)
            |
            +-- FUN_005e49d0 (Create SaveGame I/O object)
                    |
                    +-- FUN_009ca3e0 (Initialize vtable)
                            |
                            +-- Vtable slot 2: FUN_009ca290 (ReadSavegame)
                                    |
                                    +-- FUN_005e4b10 (Raw file read)
                                            |
                                            v
                                    [Raw SAV data in memory]
                                            |
                                    FUN_0046d430 (Block Parser)
                                            |
                                    +-- vtable[10] dispatch per block:
                                        +-- FUN_01711ab0 (Full format - Blocks 1, 2, 4)
                                        +-- FUN_01712660 (Compact format - Blocks 3, 5)
```

**Note:** The SAV block deserializers read the 10-byte null padding + type hash format (full format) or the compact format with version prefix. The 11FACE11 and 21EFFE22 handlers are used for OPTIONS file sections, not SAV blocks.

#### Serialization Framework (TLS-based)

The engine uses a generic Thread Local Storage (TLS) based serialization system:

| Function | Purpose |
|----------|---------|
| `FUN_01b18000` | Creates 8-byte serialization context, links to manager |
| `FUN_01b02320` | TLS context manager - accesses slot pool at `TLS[0x18] + index * 0xF0` |
| `FUN_01b021d0` | Empty stub (actual work done via virtual dispatch) |
| `FUN_01b042c0` | Low-level context linking |

The serialization context object (8 bytes) has vtable `0x0041d5d0` (`PTR_FUN_023e5bb0`).

#### Investigation Status

**COMPLETE:** The SAV loading system has been fully traced. The block parser (`FUN_0046d430`) and all format-specific deserializers have been identified.

### Property Hashes Found in Block 1

These property hashes were identified in the SAV file and located in ACBSP.exe:

| Property Hash | VA in .data | Notes |
|---------------|-------------|-------|
| 0xBB6621D2 | 0x027ECDFC | Preceded by flags 0x02000001 |
| 0x28550876 | 0x027ECE1C | Preceded by flags 0x02000001 |
| 0x7111FCC2 | 0x027ECE7C | Followed by nested type 0xFBB63E47 |
| 0x6C448E95 | 0x027ECE9C | Followed by nested type 0x5FDACBA0 |
| 0xEB76C432 | 0x027ECEBC | Preceded by flags 0x02000001 |
| 0x28F5132B | 0x027ECEDC | Preceded by flags 0x02000001 |
| 0x8C00191B | 0x027ECEFC | Preceded by flags 0x02000001 |

### Compression Statistics Counters

The compressor tracks five counters at these stack offsets:

| Offset | Purpose |
|--------|---------|
| `[ebp-24h]` | Matches taken via lookahead decision |
| `[ebp-30h]` | Literals encoded |
| `[ebp-20h]` | Short match encoding (length 2-5, offset <= 256) |
| `[ebp-1Ch]` | Medium match encoding |
| `[ebp-18h]` | Long match encoding (length > 9) |

### WinDbg Verification Commands

```windbg
# Set breakpoint at decision point
bp 026be2ae

# When hit, check values
dd ebp+0c L1  ; Current match length
dd ebp+8 L1   ; Counter value
dd ebp-64 L1  ; Next match length

# Verify calculation
? (dwo(ebp+0c) + dwo(ebp+8))  ; Adjusted length
```

### Type Descriptor System (Compact Format)

The compact format in Blocks 3 and 5 uses a **Type Descriptor Table** system for efficient serialization of game objects.

#### Table ID Lookup Function

**`FUN_01AEAF70`** (ACBSP+0x1AEAF70)
- Takes a Table ID, returns pointer to type descriptor
- This is how the compact format resolves types at runtime

#### Serialization Functions

| Function | Address | Signature | Purpose |
|----------|---------|-----------|---------|
| `FUN_00427530` | 0x00427530 | `(type_hash, object_offset, type_descriptor_ptr)` | Serialize type reference (dual-mode: direct/indirect) |
| `FUN_004274a0` | 0x004274A0 | `(type_hash, serializer_func, object_offset, type_descriptor_ptr)` | Serialize with custom function |
| `FUN_01af6420` | 0x01AF6420 | `(param_1, param_2, param_3)` | TYPE_REF indirect handler wrapper |
| `FUN_01ae9390` | 0x01AE9390 | `(param_3, param_2, descriptor_offset, global_ref, 0)` | Type resolution with descriptor chain lookup |
| `FUN_01b1eeb0` | 0x01B1EEB0 | `(tree_map, key, flags)` | Tree map lookup by key |
| `FUN_004253e0` | 0x004253E0 | `(...)` | Assignment helper for type handles |
| `FUN_0041dc10` | 0x0041DC10 | `(...)` | Cleanup/destructor for type handles |

#### World Object Serializer

**`FUN_004976D0`** - World object serializer
- Reads fields at offsets 0x18-0x44
- Uses World hash 0xFBB63E47 for 9 type references (0x4C-0x6C)
- Uses hash 0x0984415E (Entity) at offset 0x70

#### Type Hash Frequency

| Hash | Occurrences | Name |
|------|-------------|------|
| 0xFBB63E47 | 22 | World |
| 0x824A23BA | 21 | Unknown |
| 0x7E42F87F | 17 | Unknown |
| 0xF8206AF7 | 15 | Unknown (IColor?) |
| 0xBB96607D | 10 | ManagedObject |
| 0x0984415E | - | Entity/Base type |

#### Ghidra Project Location

- **Project**: `/mnt/f/ClaudeHole/ghidra_project/SAVAnalysis`
- **Analysis Script**: `/mnt/f/ClaudeHole/assassinscreedsave/ghidra_type_table_analysis.py`

---

## 8. Tools

### sav_parser.py

Parses SAV files and extracts all 5 blocks.

```bash
python sav_parser.py ACBROTHERHOODSAVEGAME0.SAV
```

**Output files:**
- `sav_block1_decompressed.bin` - Block 1 (283 bytes)
- `sav_block2_decompressed.bin` - Block 2 (32KB)
- `sav_block3_raw.bin` - Block 3 (7,972 bytes)
- `sav_block4_decompressed.bin` - Block 4 (32KB)
- `sav_block5_raw.bin` - Block 5 (6,266 bytes)

### sav_serializer.py

Rebuilds a SAV file from extracted blocks.

```bash
# Auto-detect blocks in current directory
python sav_serializer.py --auto -o output.sav

# With comparison against original
python sav_serializer.py --auto -o output.sav --compare original.sav
```

### lzss_decompressor_final.py

Decompresses LZSS-compressed data.

```bash
# Decompress OPTIONS file (all 3 sections)
python lzss_decompressor_final.py OPTIONS.bin

# Decompress specific section
python lzss_decompressor_final.py OPTIONS.bin 2
```

### lzss_compressor_final.py

Compresses data using LZSS with lazy matching.

```bash
python lzss_compressor_final.py input.bin output.bin
```

**Key parameters:**
- `max_match_length` defaults to 2048 bytes to match game behavior
- Implements full lazy matching with context-aware bias

### sav_tagged_parser.py

Parses the tagged binary format in SAV blocks 1, 2, and 4.

```bash
# Parse single block
python sav_tagged_parser.py sav_block1_decompressed.bin

# Parse all standard blocks
python sav_tagged_parser.py --all
```

---

## 9. Python Code Examples

### 9.1 Helper Functions

```python
def uint32_le(data, pos):
    """Read little-endian uint32"""
    return int.from_bytes(data[pos:pos+4], 'little')

def uint64_le(data, pos):
    """Read little-endian uint64"""
    return int.from_bytes(data[pos:pos+8], 'little')
```

### 9.2 Field Scanner Template

```python
def scan_fields(data):
    fields = []
    pos = 0

    # Skip leading zeros
    while pos < len(data) and data[pos] == 0:
        pos += 1

    # Find field markers
    while pos + 3 < len(data):
        if data[pos+1] == 0x00 and data[pos+2] == 0x0B:
            field_type = data[pos]
            pos += 3

            # Dispatch to type handler
            if field_type == 0x1A:
                field, pos = parse_string(data, pos)
            elif field_type == 0x07:
                field, pos = parse_int_hash(data, pos)
            elif field_type == 0x12:
                field, pos = parse_complex(data, pos)
            else:
                pos += 4  # Skip unknown

            fields.append(field)
        else:
            pos += 1

    return fields
```

### 9.3 Type Handlers

#### String (0x1A)

```python
def parse_string(data, pos):
    length = uint32_le(data, pos)
    pos += 4
    string = data[pos:pos+length-1].decode('utf-8')
    pos += length  # includes null terminator
    return {'type': 'string', 'value': string}, pos
```

#### Integer + Hash (0x07)

```python
def parse_int_hash(data, pos):
    value = uint32_le(data, pos)
    pos += 4

    # Check for nested hash
    if data[pos:pos+4] == b'\x11\x00\x00\x00':
        pos += 4
        hash_val = uint32_le(data, pos)
        pos += 4
        return {'type': 'keyed_int', 'value': value, 'hash': hash_val}, pos

    return {'type': 'int', 'value': value}, pos
```

#### Complex (0x12)

```python
def parse_complex(data, pos):
    value = uint32_le(data, pos)
    pos += 4

    if data[pos:pos+4] == b'\x11\x00\x00\x00':
        pos += 4
        value64 = uint64_le(data, pos)
        pos += 8
        return {'type': 'complex', 'value': value, 'value64': value64}, pos

    return {'type': 'int', 'value': value}, pos
```

### 9.4 Safe Parser Wrapper

```python
def safe_parse(data):
    try:
        fields = scan_fields(data)
        return {'success': True, 'fields': fields}
    except Exception as e:
        return {'success': False, 'error': str(e), 'partial_fields': []}
```

---

## Appendix A: LZSS Stream Markers

| Marker | Value | Description |
|--------|-------|-------------|
| Start | `06 00 E1 00` | Beginning of LZSS stream |
| End | `20 00` | Terminator |

---

## Appendix B: Confidence Levels

### B.1 Component Confidence Table

| Component | Confidence | Evidence Quality | Tested? |
|-----------|------------|------------------|---------|
| File structure (5 blocks) | **HIGH** | File sizes verified | Yes |
| LZSS decompression | **HIGH** | Parser works | Yes |
| LZSS compression | **HIGH** | Byte-perfect match | Yes |
| Checksum (Adler-32) | **HIGH** | Round-trip verified | Yes |
| Block 1 header | **HIGH** | Parser verified | Yes |
| Block 2 header | **HIGH** | Parser verified | Yes |
| Block 2 Field4 high bits | **HIGH** | region_count/2 verified | Yes |
| Block 2 Field4 low bits | **LOW** | Unknown formula | No |
| Field marker `[XX 00 0B]` | **HIGH** | Hex verified | Yes |
| 12 fields in Block 1 | **HIGH** | Pattern count | Yes |
| SaveGame hash 0xBDBE3B52 | **HIGH** | Hex + EXE match | Yes |
| String field (0x1A) | **HIGH** | "Desmond" verified | Yes |
| CRC32 hash algorithm | **HIGH** | Type names match | Yes |
| Lazy matching algorithm | **HIGH** | WinDbg verified | Yes |
| Type 0x07 structure | **MEDIUM** | Partially verified | Partial |
| Type 0x12 structure | **MEDIUM** | Small sample | Partial |
| [11 00 00 00] separator | **MEDIUM** | Not always present | Partial |
| 92 properties in SaveGame | **MEDIUM** | EXE data, not SAV | No |
| Compact format = varint | **LOW** | Statistics only | No |
| Compact format = protobuf | **LOW** | Decoding failed | Disproven |
| Property hash meanings | **LOW** | Hashes found, names unknown | No |
| Block 3/5 content | **UNKNOWN** | No analysis succeeded | No |

### B.2 Critical Unanswered Questions

The following questions remain unresolved from the SAV file investigation:

1. **What determines field boundaries?**
   - Is there always padding between fields?
   - Is there a length prefix we're missing?
   - Does each type have fixed size?

2. **What is the relationship between EXE property count (92) and SAV field count (12)?**
   - Are fields optional?
   - Is Block 1 a subset of SaveGame type?
   - Are some properties in other blocks?

3. **What are Blocks 3 and 5?**
   - Are they even part of the save system?
   - Different type? Different engine?
   - Optional data?

4. **Is the [11 00 00 00] pattern a type indicator or separator?**
   - Some fields have it, some don't
   - What does 0x11 mean in this context?

5. **Can we modify the save and have the game accept it?**
   - Checksum recalculation needed?
   - Any other validation?

---

## Appendix C: Revision History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | December 28, 2025 | Initial consolidated specification |
| 1.1 | December 28, 2025 | Incorporated content from 9 research documents; added Block 1 complete field map, Block 2/4 type distributions, EXE addresses and strings |
| 1.2 | December 28, 2025 | Added Type Descriptor System section with Ghidra analysis findings: table ID lookup function, serialization functions, world object serializer, type hash frequency, and Ghidra project location |

---

## Appendix D: Source Documents

This specification consolidates information from:
- CLAUDE.md (project overview and compression format)
- docs/MASTER_SPECIFICATION.md (SAV structure reference)
- docs/README_2.md (detailed SAV format specification)
- docs/final_correct_tiebreaking.md (lazy matching algorithm)
- docs/real_compressor_analysis.md (compressor reverse engineering)
- docs/README.md (documentation index)

**Research documents (now archived in SAV_RESEARCH_ARCHIVE.md):**
- SAV_ANALYSIS_SUMMARY.md - TL;DR summary and patterns
- SAV_BLOCKS_2_4_COMPLETE_ANALYSIS.md - Block 4 array details, item sizes, type distributions
- SAV_COMPACT_FORMAT_ANALYSIS.md - Compact format type indicators, table IDs
- SAV_DESCRIPTOR_ANALYSIS_REPORT.md - Property entry structure, EXE addresses, serializer functions
- SAV_HASH_CROSSREF_REPORT.md - Hash cross-reference between SAV and EXE
- SAV_HEX_PATTERNS.md - Complete Block 1 hex dump with field annotations
- SAV_INVESTIGATION_REVIEW.md - Confidence levels, unanswered questions
- SAV_QUICK_REFERENCE.md - Python parsing templates
- SAV_STATUS_REPORT.md - Consolidated status and tool inventory

---

*This specification is for educational and modding purposes. All information derived from reverse engineering of legally owned software.*

---

## Appendix: Field Types Reference

Documentation of field types and string extraction from Assassin's Creed Brotherhood SAV file blocks.

### Overview

SAV files contain 5 blocks, with blocks 1, 2, and 4 using a tagged binary format with field markers `[Type] [00] [0B]`. This appendix catalogs all field types found and their distributions.

#### Block Summary

| Block | Size | Markers Found | Strings | Purpose |
|-------|------|---------------|---------|---------|
| Block 1 | 283 bytes | 12 | 1 | Player profile/identity |
| Block 2 | 32,768 bytes | 1,401 | 0 | Game state/mission data |
| Block 4 | 32,768 bytes | 1,113 | 0 | Extended game state |

---

### 1. String Extraction Results

#### Block 1 Strings

Block 1 contains player identification data including one string field:

| Offset | Length | Value | Context |
|--------|--------|-------|---------|
| 0x009F | 7 | "Desmond" | Player/character name |

**Raw hex at 0x009F:**
```
1a 00 0b 07 00 00 00 44 65 73 6d 6f 6e 64 00
[marker ] [length   ] [D  e  s  m  o  n  d  \0]
```

#### Block 2 Strings

**No Type 0x1A (String) markers found in Block 2.**

Block 2 contains 1,401 field markers but no string fields. The data consists primarily of:
- Integer/hash fields (Type 0x07)
- Separator/padding markers (Type 0x00)
- Object references (Types 0x43, 0xC0, 0xC3)

#### Block 4 Strings

**No Type 0x1A (String) markers found in Block 4.**

Block 4 contains 1,113 field markers but no string fields. The data consists primarily of:
- Complex64/Object references (Type 0x12)
- Integer/hash fields (Type 0x07)
- Nested/variant structures (Type 0x1D)
- Array/container fields (Type 0x19)

---

### 2. Block 2 Field Type Distribution

#### Type Summary Table

| Type | Name | Count | Offset Range | Description |
|------|------|-------|--------------|-------------|
| 0x00 | Separator/Padding | 425 | 0x0112 - 0x7FE0 | Field separators or padding bytes |
| 0x06 | Unknown_06 | 3 | 0x02FA - 0x47E6 | Unknown purpose |
| 0x07 | Integer + Hash | 268 | 0x0024 - 0x7FFC | Integer values with optional property hash |
| 0x12 | Complex64/Object Reference | 26 | 0x00A6 - 0x45FB | 64-bit object references |
| 0x13 | Unknown_13 | 3 | 0x0039 - 0x49EF | Unknown purpose |
| 0x16 | Unknown_16 | 5 | 0x0231 - 0x4B41 | Unknown purpose |
| 0x17 | Unknown_17 | 2 | 0x02A9 - 0x038B | Unknown purpose |
| 0x19 | Array/Container | 2 | 0x0060 - 0x01E9 | Array or container structure |
| 0x1D | Nested/Variant | 18 | 0x0079 - 0x4B68 | Nested or variant data structures |
| 0x42 | Unknown_42 | 1 | 0x46A4 | Single occurrence |
| 0x43 | ObjectRef | 314 | 0x045D - 0x4039 | Object reference with hash (variants 0x21, 0x24) |
| 0x9D | Unknown_9D | 5 | 0x01A0 - 0x49CD | Unknown purpose |
| 0xC0 | StateValue | 171 | 0x0493 - 0x4710 | State/value field (variants 0x00, 0x20) |
| 0xC3 | ObjectRefFlagged | 157 | 0x046F - 0x4027 | Flagged object reference (0x43 with high bit) |
| 0xFD | Unknown_FD | 1 | 0x4B60 | Single occurrence |

**Total: 15 distinct field types, 1,401 markers**

#### Detailed Type Analysis

##### Type 0x00 (Separator/Padding) - 425 occurrences

Appears to be field separators or padding between data structures.

**Sample offsets (first 20):**
```
0x0112, 0x0124, 0x0178, 0x018A, 0x0258, 0x02C4, 0x02D6, 0x02E8, 0x033A, 0x03A6,
0x03B8, 0x03CA, 0x40D5, 0x4116, 0x4157, 0x4198, 0x41D9, 0x421A, 0x425B, 0x429C
```

**Sample values:**
- 0x0112: value=0x00000E00
- 0x0124: value=0x00006601
- 0x0178: value=0x00000E01

---

##### Type 0x07 (Integer + Hash) - 268 occurrences

Standard integer fields, often followed by property hash (subtype 0x11).

**Structure:** `[07 00 0B] [value:4] [subtype:4] [property_hash:4]`

**Sample offsets (first 20):**
```
0x0024, 0x00FD, 0x026A, 0x027F, 0x0294, 0x034C, 0x0361, 0x0376, 0x4722, 0x4B94,
0x4BCD, 0x4BFC, 0x4C35, 0x4C64, 0x4C9D, 0x4CCC, 0x4D05, 0x4D34, 0x4D6D, 0x4D9C
```

**Sample values:**
- 0x0024: value=0x00000000, subtype=0x185
- 0x026A: value=0x00000000, subtype=0x11, property_hash=0xF44B5195
- 0x027F: value=0x00000000, subtype=0x11, property_hash=0x5DEBF8DE

---

##### Type 0x12 (Complex64/Object Reference) - 26 occurrences

64-bit object references or complex values.

**Structure:** `[12 00 0B] [hash:4] [subtype:4] [extension:8]`

**Sample offsets:**
```
0x00A6, 0x00E8, 0x0163, 0x021C, 0x03F5, 0x40E7, 0x4128, 0x4169, 0x41AA, 0x41EB,
0x422C, 0x426D, 0x42AE, 0x42EF, 0x4330, 0x4371, 0x43B2, 0x43F3, 0x4434, 0x4475,
0x44B6, 0x44F7, 0x4538, 0x4579, 0x45BA, 0x45FB
```

**Sample values:**
- 0x00A6: value=0x8A79EC26, subtype=0xFB
- 0x00E8: value=0x8A79EC27, subtype=0x11
- 0x0163: value=0x8A79EC28, subtype=0x0E

---

##### Type 0x19 (Array/Container) - 2 occurrences

Array or container structures with element counts.

**Structure:** `[19 00 0B] [count:4] [element_type:4] [data...]`

**Offsets:**
- 0x0060: count=0 (empty array)
- 0x01E9: count=1 (single element)

---

##### Type 0x1D (Nested/Variant) - 18 occurrences

Variant markers with sub-type indicators.

**Marker format:** `[1D] [variant] [0B] [count:1] [inner_data...]`

**Variants observed:** 0x0A (all 18 occurrences)

**Sample offsets:**
```
0x0079, 0x00BB, 0x0136, 0x0202, 0x0431, 0x4061, 0x407E, 0x40A9, 0x4762, 0x4778,
0x478E, 0x47A4, 0x47BA, 0x47D0, 0x4A3A, 0x4AA4, 0x4AD3, 0x4B68
```

---

##### Type 0x43 (ObjectRef) - 314 occurrences

Object reference fields containing hash pointers. Part of a 98-byte repeating record structure.

**Structure:** `[43] [Variant] [0B] [00] [0E] [00 00 00] [Hash:4] [Zero:6]`

**Total field size:** 18 bytes

**Variants:**
- `0x24` (157 occurrences): Class/type reference, always hash `0x75758A0E`
- `0x21` (157 occurrences): Instance/property reference, always hash `0x309E9CEF`

**Sample raw bytes:**
- 0x045D: `43 24 0b 00 0e 00 00 00 0e 8a 75 75 00 00 00 00 00 00`
- 0x0481: `43 21 0b 00 0e 00 00 00 ef 9c 9e 30 00 00 00 00 00 00`

---

##### Type 0xC0 (StateValue) - 171 occurrences

State/value fields. Relationship: `0xC0 = 0x40 | 0x80` (high bit set on base type 0x40).

**Structure:** `[C0] [Variant] [0B] [00] [SubType] [00 00 00] [Value:4] [Padding:6]`

**Total field size:** 18 bytes

**Variants:**
- `0x20` (157 occurrences): State value field in record structure
  - SubType=0x00, Value usually 0x00000000
  - Exception: Record 156 has value 0x19 (25 decimal)
- `0x00` (14 occurrences): Hash reference field (separate section at 0x4614+)
  - SubType=0x0E, contains unique hash values

**Sample raw bytes:**
- 0x0493: `c0 20 0b 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00` (state=0)
- 0x4614: `c0 00 0b 00 0e 00 00 00 52 ac 5e 7d 00 00 00 00 00 00` (hash ref)

---

##### Type 0xC3 (ObjectRefFlagged) - 157 occurrences

Flagged object reference. Relationship: `0xC3 = 0x43 | 0x80` (high bit set on base type 0x43).

**Structure:** `[C3] [22] [0B] [00] [0E] [00 00 00] [Hash:4] [Zero:6]`

**Total field size:** 18 bytes

**Variant:** Only `0x22` observed (all 157 occurrences)

**Hash:** Always `0x768CAE23` (parent/container reference)

**Sample raw bytes:**
- 0x046F: `c3 22 0b 00 0e 00 00 00 23 ae 8c 76 00 00 00 00 00 00`

---

### 3. Block 4 Field Type Distribution

#### Type Summary Table

| Type | Name | Count | Offset Range |
|------|------|-------|--------------|
| 0x00 | Separator/Padding | 7 | 0x39B4 - 0x3B5C |
| 0x03 | Unknown_03 | 17 | 0x7499 - 0x75B9 |
| 0x06 | Unknown_06 | 22 | 0x0753 - 0x73F7 |
| 0x07 | Integer + Hash | 368 | 0x00F2 - 0x7CDF |
| 0x12 | Complex64/Object Reference | 369 | 0x0024 - 0x7FE8 |
| 0x13 | Unknown_13 | 8 | 0x0827 - 0x7603 |
| 0x16 | Unknown_16 | 3 | 0x3A67 - 0x3B35 |
| 0x19 | Array/Container | 98 | 0x0122 - 0x7C9C |
| 0x1D | Nested/Variant | 204 | 0x00DC - 0x7CF4 |
| 0x55 | Unknown_55 | 1 | 0x7398 |
| 0x78 | Unknown_78 | 1 | 0x73A0 |
| 0x97 | Unknown_97 | 7 | 0x07A8 - 0x7422 |
| 0x9D | Unknown_9D | 3 | 0x3972 - 0x3BDD |
| 0xAF | Unknown_AF | 4 | 0x070A - 0x526F |
| 0xE5 | Unknown_E5 | 1 | 0x7490 |

**Total: 15 distinct field types, 1,113 markers**

---

### 4. Field Patterns and Observations

#### Common Sequences

##### Block 2 Game Object Records (0x045D - 0x4077)

A **98-byte repeating record structure** appears exactly 157 times, representing game objects (likely missions, collectibles, or progress markers).

**Complete Record Layout (98 bytes):**
```
Offset   Size  Type       Description
------   ----  ----       -----------
+0x00    18    0x43/0x24  Class/type reference (hash: 0x75758A0E)
+0x12    18    0xC3/0x22  Parent/container reference (hash: 0x768CAE23)
+0x24    18    0x43/0x21  Instance/property reference (hash: 0x309E9CEF)
+0x36    18    0xC0/0x20  State value (usually 0x00000000)
+0x48    26    (footer)   Record terminator/size descriptor
------   --
Total    98    bytes
```

**Record Footer Structure (26 bytes):**
```
Offset  Size  Value       Description
------  ----  -----       -----------
+0x00   4     0x9BD7FCBE  Record type hash
+0x04   4     0x00000050  Record size (80 = 72 + 8)
+0x08   4     0x00000048  Data size (72 = 4 x 18 bytes)
+0x0C   4     0x0000000E  SubType indicator
+0x10   4     0xF977547D  Property hash
+0x14   6     0x00...     Zero padding
```

**Field Structure (18 bytes each):**
```
[Type:1] [Variant:1] [0x0B:1] [0x00:1] [SubType:1] [0x00:3] [Hash/Value:4] [Padding:6]
```

**Interpretation:**
- All 157 records share identical type hashes, suggesting they are instances of the same object class
- The state value (0xC0/0x20) varies per record (156 are 0x00, one is 0x19)
- Likely represents: mission objectives, collectibles, synchronization points, or challenges
- The footer confirms the 72-byte data portion (4 x 18-byte fields)

##### Block 2 State Array Pattern (0x4B78 - 0x7FE0)

Regular 0x31-byte intervals containing:
```
[00 00 0B] [padding]
[07 00 0B] [integer value]
```
Total: 256 entries (0x100), suggesting a lookup table or state array.

#### Block Header Analysis

**Block 1 Header (first field at 0x0024):**
- Type hash: 0xBDBE3B52 ("SaveGame")
- Contains player identity fields

**Block 2 Header (first field at 0x0024):**
- Type hash: 0x94D6F8F1 ("GameState")
- Contains game progress and mission data

**Block 4 Header (first field at 0x0024):**
- Type hash: 0xA1A85298 ("ExtendedState")
- Contains extended save data

#### Notable Field Hashes

Property hashes seen in Block 1 (with speculative names):

| Hash | Possible Purpose |
|------|------------------|
| 0x2578300E | Unknown field 1 |
| 0xF5C71F6B | Unknown field 2 |
| 0xBB6621D2 | Unknown field 3 |
| 0x28550876 | Unknown field 4 |
| 0x28F5132B | Unknown field 5 |
| 0x8C00191B | Unknown field 6 |

Property hashes seen in Block 2:

| Hash | Occurrences | Possible Purpose |
|------|-------------|------------------|
| 0xF44B5195 | 2 | Game state flag |
| 0x5DEBF8DE | 2 | Game state flag |

#### Block 2 Record Structure Hashes

Constant hashes found in the 157 game object records (0x045D - 0x4077):

| Hash | Field | Context |
|------|-------|---------|
| 0x75758A0E | 0x43/0x24 | Class/type reference (all 157 records identical) |
| 0x768CAE23 | 0xC3/0x22 | Parent/container reference (all 157 records identical) |
| 0x309E9CEF | 0x43/0x21 | Instance/property reference (all 157 records identical) |
| 0x9BD7FCBE | Footer | Record type hash (all 157 footers identical) |
| 0xF977547D | Footer | Record property hash (all 157 footers identical) |

**Note:** The identical hashes across all records suggest these are 157 instances of the same game object type, differentiated only by their state value (0xC0/0x20 field).

---

### 5. Technical Notes

#### Marker Format Reference

**Standard marker:** `[Type:1] [00] [0B]`
- Type 0x00-0x3F use standard format
- Type > 0x3F may use `[Type:1] [Variant:1] [0B]` format

**Type 0x1D variant markers:** `[1D] [Variant] [0B]`
- Variant 0x00: Simple wrapper
- Variant 0x01: Array wrapper
- Variant 0x0A: Fixed-size structure
- Variant 0x0B: Complex structure with index

#### Extended Type System (Types 0x40+)

For types with the high bit set (0x80+), the type byte encodes relationships:

| Type | Base | Flag | Description |
|------|------|------|-------------|
| 0x43 | 0x43 | - | Object reference (base type) |
| 0xC3 | 0x43 | 0x80 | Flagged object reference (0x43 OR 0x80) |
| 0xC0 | 0x40 | 0x80 | State/value field (0x40 OR 0x80) |

**Variant Byte Patterns:**

For types 0x43, 0xC0, 0xC3, the second byte indicates the variant:

| Variant | Types | Meaning |
|---------|-------|---------|
| 0x00 | 0xC0 | Hash reference mode |
| 0x20 | 0xC0 | State value mode (in records) |
| 0x21 | 0x43 | Instance/property reference |
| 0x22 | 0xC3 | Parent/container reference |
| 0x24 | 0x43 | Class/type reference |

**Note:** Variants 0x20-0x24 are clustered around 0x20 (32 decimal), suggesting a base value with small offsets.

#### Subtype Indicators

After the value field, a 4-byte subtype indicates field continuation:
- 0x00000000: Field ends
- 0x00000011 (0x11): Property hash follows (4 bytes)
- 0x0000000E (0x0E): Length-delimited or reference data
- 0x00000012 (0x12): Extended 64-bit data follows

---

### Appendix: Full Offset Lists

#### Block 1 All Field Offsets

| Type | Offsets |
|------|---------|
| 0x00 | 0x008D |
| 0x07 | 0x0024, 0x0039, 0x004E, 0x0063, 0x0078, 0x00E6, 0x00FB, 0x0110 |
| 0x12 | 0x00BC, 0x00D1 |
| 0x1A | 0x009F |

#### Block 2 Type 0x43 Full Offset List (314 entries)

<details>
<summary>Click to expand</summary>

```
0x045D, 0x0481, 0x04BF, 0x04E3, 0x0521, 0x0545, 0x0583, 0x05A7, 0x05E5, 0x0609,
0x0647, 0x066B, 0x06A9, 0x06CD, 0x070B, 0x072F, 0x076D, 0x0791, 0x07CF, 0x07F3,
0x0831, 0x0855, 0x0893, 0x08B7, 0x08F5, 0x0919, 0x0957, 0x097B, 0x09B9, 0x09DD,
0x0A1B, 0x0A3F, 0x0A7D, 0x0AA1, 0x0ADF, 0x0B03, 0x0B41, 0x0B65, 0x0BA3, 0x0BC7,
0x0C05, 0x0C29, 0x0C67, 0x0C8B, 0x0CC9, 0x0CED, 0x0D2B, 0x0D4F, 0x0D8D, 0x0DB1,
0x0DEF, 0x0E13, 0x0E51, 0x0E75, 0x0EB3, 0x0ED7, 0x0F15, 0x0F39, 0x0F77, 0x0F9B,
0x0FD9, 0x0FFD, 0x103B, 0x105F, 0x109D, 0x10C1, 0x10FF, 0x1123, 0x1161, 0x1185,
0x11C3, 0x11E7, 0x1225, 0x1249, 0x1287, 0x12AB, 0x12E9, 0x130D, 0x134B, 0x136F,
0x13AD, 0x13D1, 0x140F, 0x1433, 0x1471, 0x1495, 0x14D3, 0x14F7, 0x1535, 0x1559,
0x1597, 0x15BB, 0x15F9, 0x161D, 0x165B, 0x167F, 0x16BD, 0x16E1, 0x171F, 0x1743,
0x1781, 0x17A5, 0x17E3, 0x1807, 0x1845, 0x1869, 0x18A7, 0x18CB, 0x1909, 0x192D,
0x196B, 0x198F, 0x19CD, 0x19F1, 0x1A2F, 0x1A53, 0x1A91, 0x1AB5, 0x1AF3, 0x1B17,
0x1B55, 0x1B79, 0x1BB7, 0x1BDB, 0x1C19, 0x1C3D, 0x1C7B, 0x1C9F, 0x1CDD, 0x1D01,
0x1D3F, 0x1D63, 0x1DA1, 0x1DC5, 0x1E03, 0x1E27, 0x1E65, 0x1E89, 0x1EC7, 0x1EEB,
0x1F29, 0x1F4D, 0x1F8B, 0x1FAF, 0x1FED, 0x2011, 0x204F, 0x2073, 0x20B1, 0x20D5,
0x2113, 0x2137, 0x2175, 0x2199, 0x21D7, 0x21FB, 0x2239, 0x225D, 0x229B, 0x22BF,
0x22FD, 0x2321, 0x235F, 0x2383, 0x23C1, 0x23E5, 0x2423, 0x2447, 0x2485, 0x24A9,
0x24E7, 0x250B, 0x2549, 0x256D, 0x25AB, 0x25CF, 0x260D, 0x2631, 0x266F, 0x2693,
0x26D1, 0x26F5, 0x2733, 0x2757, 0x2795, 0x27B9, 0x27F7, 0x281B, 0x2859, 0x287D,
0x28BB, 0x28DF, 0x291D, 0x2941, 0x297F, 0x29A3, 0x29E1, 0x2A05, 0x2A43, 0x2A67,
0x2AA5, 0x2AC9, 0x2B07, 0x2B2B, 0x2B69, 0x2B8D, 0x2BCB, 0x2BEF, 0x2C2D, 0x2C51,
0x2C8F, 0x2CB3, 0x2CF1, 0x2D15, 0x2D53, 0x2D77, 0x2DB5, 0x2DD9, 0x2E17, 0x2E3B,
0x2E79, 0x2E9D, 0x2EDB, 0x2EFF, 0x2F3D, 0x2F61, 0x2F9F, 0x2FC3, 0x3001, 0x3025,
0x3063, 0x3087, 0x30C5, 0x30E9, 0x3127, 0x314B, 0x3189, 0x31AD, 0x31EB, 0x320F,
0x324D, 0x3271, 0x32AF, 0x32D3, 0x3311, 0x3335, 0x3373, 0x3397, 0x33D5, 0x33F9,
0x3437, 0x345B, 0x3499, 0x34BD, 0x34FB, 0x351F, 0x355D, 0x3581, 0x35BF, 0x35E3,
0x3621, 0x3645, 0x3683, 0x36A7, 0x36E5, 0x3709, 0x3747, 0x376B, 0x37A9, 0x37CD,
0x380B, 0x382F, 0x386D, 0x3891, 0x38CF, 0x38F3, 0x3931, 0x3955, 0x3993, 0x39B7,
0x39F5, 0x3A19, 0x3A57, 0x3A7B, 0x3AB9, 0x3ADD, 0x3B1B, 0x3B3F, 0x3B7D, 0x3BA1,
0x3BDF, 0x3C03, 0x3C41, 0x3C65, 0x3CA3, 0x3CC7, 0x3D05, 0x3D29, 0x3D67, 0x3D8B,
0x3DC9, 0x3DED, 0x3E2B, 0x3E4F, 0x3E8D, 0x3EB1, 0x3EEF, 0x3F13, 0x3F51, 0x3F75,
0x3FB3, 0x3FD7, 0x4015, 0x4039
```
</details>

#### Block 2 Type 0x07 Full Offset List (268 entries)

<details>
<summary>Click to expand</summary>

```
0x0024, 0x00FD, 0x026A, 0x027F, 0x0294, 0x034C, 0x0361, 0x0376, 0x4722, 0x4B94,
0x4BCD, 0x4BFC, 0x4C35, 0x4C64, 0x4C9D, 0x4CCC, 0x4D05, 0x4D34, 0x4D6D, 0x4D9C,
0x4DD5, 0x4E04, 0x4E3D, 0x4E6C, 0x4EA5, 0x4ED4, 0x4F0D, 0x4F3C, 0x4F75, 0x4FA4,
0x4FDD, 0x500C, 0x5045, 0x5074, 0x50AD, 0x50DC, 0x5115, 0x5144, 0x517D, 0x51AC,
0x51E5, 0x5214, 0x524D, 0x527C, 0x52B5, 0x52E4, 0x531D, 0x534C, 0x5385, 0x53B4,
0x53ED, 0x541C, 0x5455, 0x5484, 0x54BD, 0x54EC, 0x5525, 0x5554, 0x558D, 0x55BC,
0x55F5, 0x5624, 0x565D, 0x568C, 0x56C5, 0x56F4, 0x572D, 0x575C, 0x5795, 0x57C4,
0x57FD, 0x582C, 0x5865, 0x5894, 0x58CD, 0x58FC, 0x5935, 0x5964, 0x599D, 0x59CC,
0x5A05, 0x5A34, 0x5A6D, 0x5A9C, 0x5AD5, 0x5B04, 0x5B3D, 0x5B6C, 0x5BA5, 0x5BD4,
0x5C0D, 0x5C3C, 0x5C75, 0x5CA4, 0x5CDD, 0x5D0C, 0x5D45, 0x5D74, 0x5DAD, 0x5DDC,
0x5E15, 0x5E44, 0x5E7D, 0x5EAC, 0x5EE5, 0x5F14, 0x5F4D, 0x5F7C, 0x5FB5, 0x5FE4,
0x601D, 0x604C, 0x6085, 0x60B4, 0x60ED, 0x611C, 0x6155, 0x6184, 0x61BD, 0x61EC,
0x6225, 0x6254, 0x628D, 0x62BC, 0x62F5, 0x6324, 0x635D, 0x638C, 0x63C5, 0x63F4,
0x642D, 0x645C, 0x6495, 0x64C4, 0x64FD, 0x652C, 0x6565, 0x6594, 0x65CD, 0x65FC,
0x6635, 0x6664, 0x669D, 0x66CC, 0x6705, 0x6734, 0x676D, 0x679C, 0x67D5, 0x6804,
0x683D, 0x686C, 0x68A5, 0x68D4, 0x690D, 0x693C, 0x6975, 0x69A4, 0x69DD, 0x6A0C,
0x6A45, 0x6A74, 0x6AAD, 0x6ADC, 0x6B15, 0x6B44, 0x6B7D, 0x6BAC, 0x6BE5, 0x6C14,
0x6C4D, 0x6C7C, 0x6CB5, 0x6CE4, 0x6D1D, 0x6D4C, 0x6D85, 0x6DB4, 0x6DED, 0x6E1C,
0x6E55, 0x6E84, 0x6EBD, 0x6EEC, 0x6F25, 0x6F54, 0x6F8D, 0x6FBC, 0x6FF5, 0x7024,
0x705D, 0x708C, 0x70C5, 0x70F4, 0x712D, 0x715C, 0x7195, 0x71C4, 0x71FD, 0x722C,
0x7265, 0x7294, 0x72CD, 0x72FC, 0x7335, 0x7364, 0x739D, 0x73CC, 0x7405, 0x7434,
0x746D, 0x749C, 0x74D5, 0x7504, 0x753D, 0x756C, 0x75A5, 0x75D4, 0x760D, 0x763C,
0x7675, 0x76A4, 0x76DD, 0x770C, 0x7745, 0x7774, 0x77AD, 0x77DC, 0x7815, 0x7844,
0x787D, 0x78AC, 0x78E5, 0x7914, 0x794D, 0x797C, 0x79B5, 0x79E4, 0x7A1D, 0x7A4C,
0x7A85, 0x7AB4, 0x7AED, 0x7B1C, 0x7B55, 0x7B84, 0x7BBD, 0x7BEC, 0x7C25, 0x7C54,
0x7C8D, 0x7CBC, 0x7CF5, 0x7D24, 0x7D5D, 0x7D8C, 0x7DC5, 0x7DF4, 0x7E2D, 0x7E5C,
0x7E95, 0x7EC4, 0x7EFD, 0x7F2C, 0x7F65, 0x7F94, 0x7FCD, 0x7FFC
```
</details>

---

*Content merged from SAV_FIELD_MAPPING.md - December 2025*
