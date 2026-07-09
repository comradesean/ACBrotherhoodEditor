# SAV Blocks 3 and 5 Compact Format Specification

> **⚠ INVALIDATED (July 2026):** "Blocks 3 and 5" are not raw compact data.
> They are LZSS-COMPRESSED frames — every frame header carries an adler32 over
> its data, and all of them verify (56/56 across five PC/PS3 saves), with each
> frame decompressing to exactly 32 KB. The byte-level structures documented
> below (2-byte node prefixes, region layouts, growth buffers, "compact"
> records) were read from the compressed bytes and are compression artifacts.
> LZSS control bytes appear every 8 tokens, which is also what made 4-byte
> hashes seem to appear, vanish, or mutate between saves. Runtime observations
> made in the debugger (e.g. Judy Array structures in memory during load) may
> still be genuine, but no file-offset claim in this document should be used.
> This file is kept as a record of the investigation only.

> **Investigation Status: BREAKTHROUGH** (December 30, 2024)
>
> **FOUND:** The compact format uses **Judy Arrays** for property storage! FUN_01b25230 at
> offset `+0x1725230` is a confirmed Judy Array encoder that hits during Block 3/5 loading.
> The 2-byte prefixes (0x1500, 0x1809, etc.) are Judy node type markers, not protobuf-style
> wire types. See HANDOFF_SAV_DESERIALIZERS.md for complete session notes.
>
> **December 30, 2024 Update - Nested Header Semantics:**
> - Block 3 Region 4 is a **cross-block reference** to Block 4 (declared size = Block 4's compressed size)
> - Block 5 Region 2 contains **pre-allocated growth space** (+2,049 bytes beyond declared)
> - Inter-region gaps: Block 3 uses 5-byte format `[type][value_16 LE][20 00]`, Block 5 uses 4-byte format `[00][value_8][20 00]`

## Overview

Blocks 3 and 5 in AC Brotherhood SAV files use a compact binary format for serializing game object properties. Unlike Blocks 2 and 4 which use LZSS compression with raw type hashes, these blocks use table ID lookup for type resolution, resulting in more compact property references.

## Block Structure Summary

| Property | Block 3 | Block 5 |
|----------|---------|---------|
| File size | 7,972 bytes | 6,266 bytes |
| Compression | Uncompressed | Uncompressed |
| Nested headers | 4 | 2 |
| TABLE_REF count | 80 | 10 |
| Structure | Complex nested | Simple sequential |
| Primary markers | TABLE_REF, 1C04 | FIXED32, VARINT |

## Nested Header Discovery (December 2024)

**Key Finding:** Both blocks contain multiple nested headers/objects, not single monolithic structures. Each header follows the pattern:

```
01 XX XX XX 00 00 80 00
|  |        |
|  |        +- Flags: 0x00800000
|  +---------- Size: 24-bit little-endian
+------------- Version: 0x01
```

### Block 3 Structure (7,972 bytes)

Block 3 contains **4 nested headers** with distinct data regions:

| Header | Offset | Header Bytes | Declared Size | Data Region | Actual Size |
|--------|--------|--------------|---------------|-------------|-------------|
| 1 | 0x0000 | `01 39 0e 00 00 00 80 00` | 3,641 bytes | 0x0008-0x0E40 | 3,641 bytes |
| 2 | 0x0E46 | `01 55 07 00 00 00 80 00` | 1,877 bytes | 0x0E4E-0x15A2 | 1,877 bytes |
| 3 | 0x15A8 | `01 62 09 00 00 00 80 00` | 2,402 bytes | 0x15B0-0x1F11 | 2,402 bytes |
| 4 | 0x1F17 | `01 66 08 00 00 00 80 00` | 2,150 bytes | 0x1F1F-0x1F23 | 5 bytes |

**All Headers Are Valid:** All 4 headers have version byte 0x01 and flags 0x00800000.

**Inter-Region Gaps (5 bytes each):**
| Gap | Offset | Bytes | Format |
|-----|--------|-------|--------|
| 1->2 | 0x0E41-0x0E45 | `04 74 62 20 00` | `[type][value_16 LE][terminator 0x20 0x00]` |
| 2->3 | 0x15A3-0x15A7 | `00 00 28 20 00` | `[type][value_16 LE][terminator 0x20 0x00]` |
| 3->4 | 0x1F12-0x1F16 | `00 00 a7 20 00` | `[type][value_16 LE][terminator 0x20 0x00]` |

**Region Characteristics:**
- **Region 1**: Heavy TABLE_REF usage (72 of 80 total), 62 PREFIX_1C04, core CompactType_5E objects
- **Region 2**: PhysicalInventoryItem refs + type metadata, type hash 0xA1A85298, 17 PREFIX_173C
- **Region 3**: Numeric counters, game statistics (29.8% VARINT, 25% FIXED32)
- **Region 4**: **Cross-block size reference to Block 4** - only 5 bytes of local data

**CRITICAL - Region 4 Cross-Block Relationship (CONFIRMED):**

Region 4 is physically located inside Block 3, but its header declares a size that references Block 4:

| Property | Value |
|----------|-------|
| Region 4 location | Block 3 offset 0x1F17 (header) / 0x1F1F (data) |
| Header declared size | 2,150 bytes |
| Region 4 actual data | 5 bytes: `00 27 a6 62 20` |
| Block 4 compressed size | 2,150 bytes (EXACT MATCH) |

**Mechanism:** The declared size in Region 4's header (2,150 bytes) tells the game engine how much LZSS-compressed data to read from Block 4. The 5-byte local content (`00 27 a6 62 20`) is inventory metadata/descriptor. This establishes Block 4 as the "data payload" for Region 4, creating a structural link between Block 3 (compact format metadata) and Block 4 (LZSS-compressed inventory items).

**Why this is NOT coincidental:**
- 2,150 is not a round number (0x866 hex)
- Block 4 has no header - its size must be determined externally
- Region 4 is positioned immediately before Block 4 in the file
- The relationship is: Region 4 "owns" Block 4's inventory data

**File Size Verification:**
- 4 headers: 4 x 8 = 32 bytes
- 3 inter-region gaps: 3 x 5 = 15 bytes
- Data: 3,641 + 1,877 + 2,402 + 5 = 7,925 bytes
- Total: 32 + 15 + 7,925 = 7,972 bytes (matches file size)

### Block 5 Structure (6,266 bytes) - DETAILED ANALYSIS

Block 5 contains **2 nested headers** (simpler than Block 3):

| Region | Offset | Declared | Actual | Content |
|--------|--------|----------|--------|---------|
| Header 1 | 0x0000 | 8 | 8 | Version 0x01, size 1,879, flags 0x00800000 |
| Region 1 | 0x0008 | 1,879 | 1,879 | PropertyReference root bindings |
| Gap | 0x0760-0x0763 | 4 | 4 | Inter-region separator (`00 e5 20 00`) |
| Header 2 | 0x0764 | 8 | 8 | Version 0x01, size 2,317, flags 0x00800000 |
| Region 2 | 0x076C | 2,317 | 4,366 | Extended data + growth buffer |

**Region Characteristics:**
- Symmetric TABLE_REF distribution: exactly 5 per region (10 total)
- Both regions end with `20 00` terminator (LZSS stream terminator)
- Both regions contain PropertyReference bindings
- Both blocks use identical header format: version 0x01, 24-bit size, flags 0x00800000

**CRITICAL - Region 2 Growth Buffer:**
Region 2's actual size (4,366 bytes) exceeds its declared size (2,317 bytes) by **2,049 bytes**. This excess is **pre-allocated growth space** that allows the game to add PropertyReference data without reallocating the entire block.

#### Growth Buffer Discovery

| Property | Value |
|----------|-------|
| Size | 2,049 bytes |
| Location | 0x1079-0x187A |
| PropertyReference hashes | At least 1 (at 0x10A4) |
| TABLE_REF occurrences | At least 1 (at 0x12F1) |
| Purpose | Pre-allocated for ~50 new bindings during gameplay |

The growth buffer is not empty - it contains at least one PropertyReference hash and one TABLE_REF, suggesting it may hold template data or previously-used bindings.

#### Symmetric TABLE_REF Distribution

Block 5 has exactly **5 TABLE_REFs per region** (10 total), showing a more balanced structure than Block 3:

**Region 1 TABLE_REFs:**

| # | Offset | Table ID | Property ID | Notes |
|---|--------|----------|-------------|-------|
| 1 | 0x0113 | 0xE1 | 0x19 | Early in region |
| 2 | 0x01D0 | 0x95 | 0x14 | |
| 3 | 0x02F2 | 0x17 | 0x3C | |
| 4 | 0x037F | 0x14 | 0x05 | |
| 5 | 0x0456 | 0x19 | 0x07 | |

**Region 2 TABLE_REFs:**

| # | Offset | Table ID | Property ID | Notes |
|---|--------|----------|-------------|-------|
| 6 | 0x0DFF | 0x17 | 0x3C | Declared area |
| 7 | 0x0E07 | 0xDB | 0x17 | Declared area |
| 8 | 0x0E8C | 0x14 | 0x05 | Declared area |
| 9 | 0x0F13 | 0x19 | 0x07 | Declared area |
| 10 | 0x12F1 | 0x14 | 0x05 | **Within growth buffer** |

#### PropertyReference Locations (3 total)

| # | File Offset | Location | Notes |
|---|-------------|----------|-------|
| 1 | 0x002D | Region 1 preamble | Root binding |
| 2 | 0x07FE | Region 2 early | Extended binding |
| 3 | 0x10A4 | Within growth buffer | Template/reserved |

### Block 5 PropertyReference Storage - DECODED

Block 5 stores **3 PropertyReferences** embedded in Judy Array data:

| Property | Value |
|----------|-------|
| Count | 3 |
| Hash | 0x0984415E |
| Format | Judy Array embedded (NOT TYPE_REF markers) |
| Storage | Different from Blocks 2/4 (compact format) |

**Cross-Block Binding Architecture:**

| Block | Count | Format | Purpose |
|-------|-------|--------|---------|
| Block 2 | 21 | 65-byte entries | Game state bindings (missions, rewards) |
| Block 4 | 182 | Double-hash pairs | 1:1 binding per Format 1 inventory item |
| **Block 5** | **3** | **Judy Array embedded** | **Compact format bindings** |
| **Total** | **206** | | |

**Key Findings:**
- Block 5's 3 PropertyReferences likely represent **category-level bindings** for Block 4 inventory
- Region 2's +2,049 byte growth buffer allows dynamic addition of new PropertyReference bindings
- Reference ID = 0x00000000 for all entries (embedded metadata, same as Blocks 2/4)
- The format differs from Blocks 2/4: embedded in Judy node structure rather than TYPE_REF markers

#### Cross-Block Binding Architecture

Block 5 serves as the PropertyReference binding hub for Block 4 inventory items:

```
Block 5 Region 1 -----> Block 4 Format 1 items (182)
                        |
                        +-- Root bindings for stackable items
                        +-- Category-level property references

Block 5 Region 2 -----> Block 4 Format 2 items (182)
                        |
                        +-- Extended bindings for complex items
                        +-- Variable-length item metadata

Growth buffer --------> Dynamic additions during gameplay
                        |
                        +-- Pre-allocated for ~50 new bindings
                        +-- Contains at least 1 active PropertyRef
```

#### Header Comparison: Block 5 vs Block 3

| Property | Block 5 | Block 3 |
|----------|---------|---------|
| Region count | 2 | 4 |
| Header validity | Both valid (0x01) | All 4 valid (0x01) |
| TABLE_REF distribution | Symmetric (5 each) | Concentrated in Region 1 (72 of 80) |
| Growth buffer | Yes (Region 2) | No (Region 4 is cross-block ref) |
| Inter-region gaps | 1 gap (4 bytes) | 3 gaps (5 bytes each) |
| Total size | 6,266 bytes | 7,972 bytes |

### Size Field Semantics

**Declared sizes match actual data sizes** (excluding inter-region gaps and headers):

- **Block 3 Regions 1-3**: Declared sizes match actual data sizes exactly
- **Block 3 Region 4**: Declared size (2,150) encodes **external reference** = Block 4 compressed size, actual data = 5 bytes
- **Block 5 Region 1**: Declared size matches actual data size
- **Block 5 Region 2**: +2,049 byte excess beyond declared = **pre-allocated growth buffer**

### Inter-Region Gap Structure

**Block 3** uses a consistent **5-byte** gap format:

```
[type_byte] [value_16 LE] [terminator_16 = 0x20 0x00]
```

| Gap | Bytes | Type | Value (decimal) |
|-----|-------|------|-----------------|
| Block 3: 1->2 | `04 74 62 20 00` | 0x04 | 25,204 |
| Block 3: 2->3 | `00 00 28 20 00` | 0x00 | 10,240 |
| Block 3: 3->4 | `00 00 a7 20 00` | 0x00 | 42,752 |

**Block 5** uses a shorter **4-byte** gap format:

```
[00] [value_8] [terminator_16 = 0x20 0x00]
```

| Gap | Bytes | Format |
|-----|-------|--------|
| Block 5: 1->2 | `00 e5 20 00` | 4 bytes (no 16-bit value field) |

The terminator `20 00` is the same as the LZSS stream terminator.

### Structural Diagram

```
Block 3 (7,972 bytes):
+----------------------------------------------------+
| Header 1 (0x0000-0x0007): 01 39 0e 00 00 00 80 00  |
+----------------------------------------------------+
| Region 1 (0x0008-0x0E40): Primary CompactType_5E   |
|   72 TABLE_REFs, 62 PREFIX_1C04                    |
+-----------------------------------------+----------+
| Gap (0x0E41-0x0E45): 04 74 62 20 00             5b |
+-----------------------------------------+----------+
| Header 2 (0x0E46-0x0E4D): 01 55 07 00 00 00 80 00  |
+----------------------------------------------------+
| Region 2 (0x0E4E-0x15A2): Item References          |
|   PhysicalInventoryItem hash, 17 PREFIX_173C       |
+-----------------------------------------+----------+
| Gap (0x15A3-0x15A7): 00 00 28 20 00             5b |
+-----------------------------------------+----------+
| Header 3 (0x15A8-0x15AF): 01 62 09 00 00 00 80 00  |
+----------------------------------------------------+
| Region 3 (0x15B0-0x1F11): Numeric Counters         |
|   29.8% VARINT, 25% FIXED32                        |
+-----------------------------------------+----------+
| Gap (0x1F12-0x1F16): 00 00 a7 20 00             5b |
+-----------------------------------------+----------+
| Header 4 (0x1F17-0x1F1E): 01 66 08 00 00 00 80 00  |
+----------------------------------------------------+
| Region 4 (0x1F1F-0x1F23): Block 4 Reference        |
|   Declared=2150 (=Block 4 size), Actual=5 bytes    |
+----------------------------------------------------+

Block 5 (6,266 bytes):
+----------------------------------------------------+
| Header 1 (0x0000-0x0007): 01 57 07 00 00 00 80 00  |
+----------------------------------------------------+
| Region 1 (0x0008-0x075F): PropertyReference Data   |
|   5 TABLE_REFs, PropertyReference hash             |
+-----------------------------------------+----------+
| Gap (0x0760-0x0763): 00 e5 20 00                4b |
+-----------------------------------------+----------+
| Header 2 (0x0764-0x076B): 01 0D 09 00 00 00 80 00  |
+----------------------------------------------------+
| Region 2 (0x076C-0x187A): Extended Data + Buffer   |
|   5 TABLE_REFs, +2049 bytes growth space           |
+----------------------------------------------------+
```

### Region Ordering Pattern

The compact format blocks follow a consistent organization:

**Primary data -> Cross-references -> Numeric data -> External references**

- Region 1 always contains the densest object structure
- Later regions contain auxiliary data or references
- Final region may be a trailer/cross-block pointer (Block 3) or growth buffer (Block 5)

### Region Purpose Map

| Block | Region | Content | Key Characteristics |
|-------|--------|---------|---------------------|
| Block 3 | 1 | CompactType_5E objects (World state) | 72 TABLE_REFs, 62 PREFIX_1C04 |
| Block 3 | 2 | PhysicalInventoryItem refs + type metadata | PhysicalInventoryItem hash 0xA1A85298, 17 PREFIX_173C |
| Block 3 | 3 | Numeric counters, game statistics | 29.8% VARINT, highest numeric density |
| Block 3 | 4 | **Cross-block pointer to Block 4** | Declared=2150 (=Block 4 size), Actual=5 bytes |
| Block 5 | 1 | PropertyReference bindings | 5 TABLE_REFs |
| Block 5 | 2 | Extended PropertyReference + growth buffer | 5 TABLE_REFs, +2049 bytes reserved |

### Type Hashes Found in Compact Format

The following type hashes appear in the compact format data regions:

| Hash | Type Name | Location |
|------|-----------|----------|
| `0xA1A85298` | PhysicalInventoryItem | Block 3 regions 2, 3; Block 5 region 2 |
| `0xF7D44F07` | Unknown type | Block 3 region 2 at offset 0x0E60 |
| `0x0984415E` | PropertyReference | Multiple regions |

## Judy Array Storage System

**Key Discovery (December 2024):** The compact format uses **Judy Arrays** - a highly efficient sparse array data structure - for property storage. This was identified via:

1. Breakpoint `bp ACBSP+0x1725230` hitting during Block 3/5 loading
2. The embedded string `"JudyLMallocSizes = 3, 5, 7, 11, 15, 23, 32, 47, 64, Leaf1 = 25"`
3. Call stack showing connection to FUN_01AEAF70 (table ID lookup)

### Judy Array Encoder: FUN_01b25230

| Property | Value |
|----------|-------|
| Ghidra VA | `0x01B25230` |
| Offset | `+0x1725230` |
| Purpose | Normalize/encode Judy array nodes for serialization |
| Input | 8-byte structure with type tag at +0x07 |
| Output | Canonical type codes (0x08-0x1C range) |

### 8-Byte Value Structure

The encoder processes values in this format:

```
Offset  Size  Description
+0x00   4     Data pointer or immediate value
+0x04   3     Additional data/flags
+0x07   1     Type tag (0x0B-0x1C for processing)
```

### Judy Node Type Mapping

The encoder normalizes input types 0x0B-0x1C to output types:

| Input | Output | Judy Node Type |
|-------|--------|----------------|
| 0x0B | 0x15 | Linear leaf (2-byte keys + 4-byte values) |
| 0x0C | 0x16 | Linear leaf (3-byte keys + 4-byte values) |
| 0x0D | recursive | Index lookup |
| 0x0E | 0x15 | Bitmap branch (2-byte) |
| 0x0F | 0x16 | Bitmap branch (3-byte) |
| 0x10 | recursive | Bitmap lookup |
| 0x11 | 0x15 | Full 256-element array (2-byte) |
| 0x12 | 0x16 | Full 256-element array (3-byte) |
| 0x13 | recursive | Index lookup into array |
| 0x14 | 0x1C | Variable-size leaf |
| 0x15 | 0x16/0x19 | Passthrough or conversion |
| 0x16 | 0x1A | Packed 3-byte leaf |
| 0x17 | varies | Conditional handling |
| 0x18 | 0x08 | Null/empty leaf |
| 0x19 | 0x09 | Null/empty branch |
| 0x1A | 0x0A | Null marker |
| 0x1B | 0x18 | 2-element lookup |
| 0x1C | decrement | Shrink operation |

## Complete Judy Node Prefix Census

The following table provides a complete census of all Judy node prefixes found in Blocks 3 and 5:

| Prefix | Block 3 | Block 5 | Total | Purpose |
|--------|---------|---------|-------|---------|
| `14 05` | 83 | 58 | 141 | Variable-length integer (VARINT) |
| `08 03` | 80 | 10 | 90 | TABLE_REF (type table + property) |
| `05 02` | 75 | 66 | 141 | 32-bit fixed value (FIXED32) |
| `1c 04` | 62 | 1 | 63 | Variable-size leaf |
| `12 00` | 47 | 34 | 81 | Linear leaf variant |
| `15 00` | 44 | 11 | 55 | Linear leaf (VALUE_1500) |
| `17 3c` | 32 | 32 | 64 | Conditional handling |
| `19 07` | 31 | 34 | 65 | Null/empty branch |
| `16 e1` | 22 | 21 | 43 | 3-byte key leaf |
| `18 09` | 19 | 0 | 19 | Null/empty leaf |
| `0c 18` | 14 | 0 | 14 | Unknown Judy type |
| `10 06` | 11 | 0 | 11 | Unknown Judy type |
| `18 3d` | 2 | 0 | 2 | Rare 0x18xx variant |
| `18 16` | 1 | 0 | 1 | Rare 0x18xx variant |
| `18 23` | 1 | 0 | 1 | Rare 0x18xx variant |

### Prefix Distribution Analysis

**Block 3 Dominant Patterns:**
- TABLE_REF (`08 03`) concentrated in Region 1 (72 of 80)
- PREFIX_1C04 appears exclusively in structured object data
- VARINT widely distributed across all regions

**Block 5 Characteristics:**
- Symmetric TABLE_REF distribution (5 per region)
- No `18 09`, `0c 18`, or `10 06` prefixes (simpler structure)
- Higher proportion of FIXED32 values

### High-Frequency Non-Judy Patterns (Block 5)

These appear to be nibble-encoded table IDs or property references:

| Pattern | Count | Notes |
|---------|-------|-------|
| `02 4F` | 61 | Most common non-Judy pattern |
| `02 3B` | 36 | Second most common |
| `01 D0` | 14 | Third most common |

These patterns may represent inline property references or compact value encodings.

### Helper Functions

| Function | Ghidra VA | Purpose |
|----------|-----------|---------|
| FUN_01b1ea70 | `0x01B1EA70` | Allocate 0x2a (42) element array |
| FUN_01b1eac0 | `0x01B1EAC0` | Allocate 0x24 (36) element array |
| FUN_01b1ebc0 | `0x01B1EBC0` | Allocate smaller arrays |
| FUN_01b1d880 | `0x01B1D880` | Free/deallocate memory |
| FUN_01b24720 | `0x01B24720` | Multi-type encoder (types 0x14, 0x17, 0x18, 0x1b, 0x1c) |
| FUN_01b249a0 | `0x01B249A0` | 3-byte key encoder (types 0x15, 0x19) |
| FUN_01b1e7b0 | `0x01B1E7B0` | Allocation helper for 3-byte key encoding |
| FUN_01b61640 | `0x01B61640` | Search/lookup in Judy structure |
| FUN_01b1d990 | `0x01B1D990` | Population count / bit manipulation |

### FUN_01b24720 - Multi-type Judy Encoder

**Location:** Ghidra VA `0x01B24720`, offset `+0x1724720`

Called by FUN_01b25230 for types 0x14, 0x17, 0x18, 0x1b, 0x1c.

**Function signature:**
```c
uint FUN_01b24720(ushort *param_1, uint *param_2, uint *param_3, ushort param_4, int param_5)
// param_1: Output buffer for 2-byte keys
// param_2: Output buffer for 4-byte values
// param_3: Input 8-byte Judy node structure
// param_4: Prefix mask to OR with keys
// param_5: Context object (counter at +0x24)
```

**Type handling:**

| Type | Name | Entry Count | Key Size | Behavior |
|------|------|-------------|----------|----------|
| 0x14 | Linear leaf (variable) | `[+4] + 1` | 1 byte | Variable count, reads bytes from data area |
| 0x17 | Bitmap branch | up to 256 | 2 bytes | Iterates bitmap, uses popcount for slot counts |
| 0x18 | Single entry leaf | 1 | 2 bytes | Direct copy: key from `[+4]`, value from `[+0]` |
| 0x1b | 2-element leaf | 2 | 1 byte | Count = `type - 0x19` |
| 0x1c | 3-element leaf | 3 | 1 byte | Count = `type - 0x19` |
| default | (0x15, 0x16, 0x19, 0x1a) | - | - | Returns 0 (not handled) |

### FUN_01b249a0 - 3-byte Key Judy Encoder

**Location:** Ghidra VA `0x01B249A0`, offset `+0x17249a0`

Called by FUN_01b25230 for types 0x15 and 0x19.

**Function signature:**
```c
uint FUN_01b249a0(byte *param_1, uint *param_2, uint *param_3, uint param_4, int param_5)
// param_1: Output buffer for 3-byte keys
// param_2: Output buffer for 4-byte values
// param_3: Input 8-byte Judy node structure
// param_4: Passed to FUN_01b1e7b0 (allocation helper)
// param_5: Context object (counter at +0x24)
```

**Type handling:**

| Type | Name | Entry Count | Key Size | Behavior |
|------|------|-------------|----------|----------|
| 0x15 | Linear leaf | `[+4] + 1` | 3 bytes | Calls FUN_01b1e7b0, copies values |
| 0x19 | Single 3-byte entry | 1 | 3 bytes | XOR masking, writes 3 bytes to output |
| other | - | - | - | Returns 0 |

### Confirmed 8-byte Judy Node Structure

```
Offset  Size  Description
+0x00   4     Data pointer (AND with 0xFFFFFFF8 to extract address)
+0x04   1     Count field or key data byte
+0x05   2     Additional flags/data
+0x07   1     Type tag (0x14-0x1C range)
```

### Serialized Output Format

The encoders produce:
```
[type_byte] [count/flags] [keys...] [values...]
```

- Keys are 1-byte, 2-byte, or 3-byte depending on type
- Keys are OR'd with a prefix mask (param_4)
- Values are always 4-byte dwords
- Both functions call `FUN_01b1d880` to deallocate source nodes after encoding

### Mapping to Binary Prefixes

The 2-byte prefixes in Block 3/5 data map to these encoder outputs:

| Prefix | Type Byte | Second Byte | Encoder Function |
|--------|-----------|-------------|------------------|
| `14 XX` | 0x14 | count-1 | FUN_01b24720 |
| `15 XX` | 0x15 | count-1 | FUN_01b249a0 |
| `17 XX` | 0x17 | bitmap info | FUN_01b24720 |
| `18 XX` | 0x18 | key high byte | FUN_01b24720 |
| `19 XX` | 0x19 | key byte 2 | FUN_01b249a0 |
| `1b XX` | 0x1b | flags | FUN_01b24720 |
| `1c XX` | 0x1c | flags | FUN_01b24720 |

### Data Table References

The functions reference lookup tables for array sizes:

| Address | Purpose |
|---------|---------|
| `DAT_02557951` | Size table for type 0x14 |
| `DAT_02557935` | Deallocation size table |
| `DAT_02557a54` | Size table for bitmap (type 0x17) |
| `DAT_02557999` | Size table for type 0x15 |
| `DAT_0255796d` | Deallocation size for type 0x15 |

### Call Chain (from TTD trace)

```
FUN_01AEAF70 (Table ID lookup)
  → ... intermediate functions ...
    → FUN_01AFBB00
      → FUN_01AFCA01
        → FUN_01B268F1
          → FUN_01B25D66 (caller)
            → FUN_01B25230 (Judy Array encoder)
```

### Deserializer

**Updated Finding (December 2024):** Blocks 3 and 5 are NOT processed through the main block deserializer vtable dispatch. Instead, they are processed as **PropertyData** through `FUN_01b11a50`.

The PropertyData handler checks the version byte at the start of the data:
- Version `0x01`: Routes to `FUN_01b702e0` or `FUN_01b70450`
- Version `0x02`: Routes to `FUN_01b70380` or `FUN_01b704f0`
- Version `0x03`: Routes to `FUN_01b71200` or `FUN_01b709a0`

Since Blocks 3 and 5 start with version byte `0x01`, they are handled by the Version 1 handlers.

**FUN_01b70450 Field Reading Sequence:**

`FUN_01b70450` reads three fields via vtable dispatch to populate a PropertyDataObject:
1. "PackedInfo" via vtable[38] → stored at +0x08
2. "ObjectID" via vtable[39] → stored at +0x0C
3. "PropertyID" via vtable[33] → stored at +0x04

**Previous Understanding (Partially Incorrect):**
- The Raw deserializer (`FUN_01712660`) was previously thought to handle these blocks
- TTD tracing confirmed this is NOT the entry point for Blocks 3/5

**Note:** The magic values `0x11FACE11` and `0x21EFFE22` are OPTIONS file section markers, not SAV block format identifiers. SAV blocks use different content formats (see below).

### Table ID Lookup System

The compact format uses table IDs to reference types. The lookup is performed by `FUN_01AEAF70`:

**Call chain:** `FUN_01AEAF70` -> `FUN_01AEAD60` -> `FUN_01AEA0B0`

**Table ID Encoding** (from `type_descriptor[+4]`):
```c
raw_value = type_desc[+4] & 0xC3FFFFFF;
table_id = raw_value - 1;
bucket_index = table_id >> 14;       // Upper bits = bucket
entry_index = table_id & 0x3FFF;     // Lower 14 bits = entry (max 16383)
address = table[bucket * 12] + entry * 16;
```

**Table structure** (at `[manager + 0x98]`):
- Count at `[manager + 0x9E]` (masked with 0x3FFF)
- Each bucket: 12 bytes (3 dwords)
- Each entry: 16 bytes (4 dwords)

## Block Header Format (8 bytes)

Both blocks use the same header structure at each nested level:

```
Offset  Size  Description
0x00    1     Version (always 0x01)
0x01    3     Data size (little-endian 24-bit)
0x04    4     Flags (always 0x00800000)
```

### Header Examples

```
Block 3 Header 1: 01 39 0E 00 00 00 80 00
                  |  |        |
                  |  |        +- Flags: 0x00800000
                  |  +---------- Size: 0x0E39 (3641)
                  +------------- Version: 0x01

Block 5 Header 1: 01 57 07 00 00 00 80 00
                  |  |        |
                  |  |        +- Flags: 0x00800000
                  |  +---------- Size: 0x0757 (1879)
                  +------------- Version: 0x01
```

## Preamble Region

Following each 8-byte header, there is a preamble region that extends until the first TABLE_REF (0x0803) pattern. The preamble contains:

- Object descriptors
- Type references (including PropertyReference 0x0984415E)
- Initial value definitions

### Block 3 Preamble (70 bytes, 0x08-0x4E)

```
0008: 00 3d 64 0f e1 20 22 6c 9f 0e 00 c0 00 b6 6c a5
0018: 72 00 a1 00 24 0b 01 11 cd de 4c 09 b8 f2 00 00
0028: 11 c1 05 e3 a9 bf ce 90 00 6a 07 11 01 00 08 0b
0038: 50 79 1e 32 56 07 2a 4e 03 61 2e 41 6f 6a 5b ef
0048: 01 87 d8 ad b1 60
```

### Block 5 Preamble (267 bytes, 0x08-0x113)

Contains PropertyReference hash (0x0984415E) at offset 0x002D, along with multiple VARINT_1405 and VALUE prefixes.

## Compact Format Prefixes

The data region uses 2-byte prefixes to indicate data types:

### Primary Prefixes

| Prefix | Name | Description | Block 3 Count | Block 5 Count |
|--------|------|-------------|---------------|---------------|
| 0x0803 | TABLE_REF | Table ID + Property Index reference | 80 | 10 |
| 0x1405 | VARINT | Variable-length integer prefix | 83 | 58 |
| 0x0502 | FIXED32 | 32-bit fixed value | 75 | 66 |
| 0x1500 | VALUE_15 | 32-bit value (6 bytes total) | 44 | 11 |
| 0x1200 | VALUE_12 | 32-bit value (6 bytes total) | 47 | 34 |

### Secondary Prefixes

| Prefix | Name | Block 3 Count | Block 5 Count |
|--------|------|---------------|---------------|
| 0x1C04 | PREFIX_1C04 | 62 | 1 |
| 0x173C | PREFIX_173C | 32 | 32 |
| 0x1907 | PREFIX_1907 | 31 | 34 |
| 0x16E1 | PREFIX_16E1 | 22 | 21 |
| 0x1809 | PREFIX_1809 | 19 | 0 |
| 0x0C18 | EXTENDED | 14 | 0 |
| 0x1006 | PREFIX_1006 | 11 | 0 |

#### PREFIX_1C04 Sub-Type Distribution (Block 3)

The byte following PREFIX_1C04 acts as a sub-type discriminator:

| Sub-Type | Count | Purpose (Hypothesis) |
|----------|-------|----------------------|
| 0x0B (11) | 23 | Small signed/unsigned integers (most common) |
| 0x0A (10) | 15 | Small signed/unsigned integers |
| 0x25 (37) | 10 | Type reference or property ID |
| 0x08 (8) | 5 | Boolean or byte values |
| 0x24 (36) | 5 | Type reference or property ID |
| 0x23 (35) | 2 | Special marker |
| 0x14 (20) | 1 | Special marker |
| 0x21 (33) | 1 | Special marker |

#### PREFIX_173C Clustering (Block 3)

PREFIX_173C exhibits notable clustering behavior:

- Appears at only **two locations** in Block 3: offset `0x1117` and `0x1C60`
- Dense clusters with minimal intervening bytes suggest **array elements** or **repeated structures**
- The pattern `17 3C 00 00 00 00` at offset `0x116F` may indicate a **null/terminator** encoding

## TABLE_REF Format (0x0803)

The most important prefix for understanding the compact format:

```
08 03 [table_id] [prop_id]

08 03 = Prefix (field 1, varint + value 3)
table_id = 1-byte table ID (maps to type hash)
prop_id = 1-byte property index within the type
```

### Example

```
08 03 5E B6 = TABLE_REF(table=0x5E, prop=0xB6)
```

This references property 0xB6 (182) of the type mapped to table ID 0x5E (94).

## Table ID Catalog

### Block 3 Table IDs

| Table ID | Decimal | References | Property Range | Unique Props |
|----------|---------|------------|----------------|--------------|
| 0x08 | 8 | 1 | 0x00 | 1 |
| 0x14 | 20 | 3 | 0x05-0xC2 | 2 |
| 0x17 | 23 | 2 | 0x3C | 1 |
| 0x19 | 25 | 2 | 0x07 | 1 |
| 0x3B | 59 | 1 | 0xC9 | 1 |
| 0x5B | 91 | 4 | 0x03-0xB6 | 4 |
| 0x5D | 93 | 1 | 0xAA | 1 |
| 0x5E | 94 | 63 | 0x01-0xD9 | 42 |
| 0xDB | 219 | 2 | 0x17 | 1 |
| 0xFB | 251 | 1 | 0x0B | 1 |

### Block 5 Table IDs

| Table ID | Decimal | References | Property Range | Unique Props |
|----------|---------|------------|----------------|--------------|
| 0x14 | 20 | 3 | 0x05 | 1 |
| 0x17 | 23 | 2 | 0x3C | 1 |
| 0x19 | 25 | 2 | 0x07 | 1 |
| 0x95 | 149 | 1 | 0x14 | 1 |
| 0xDB | 219 | 1 | 0x17 | 1 |
| 0xE1 | 225 | 1 | 0x19 | 1 |

### Known Table ID Mappings

From binary analysis of ACBSP.exe (see type_table_analysis.json):

| Table ID | Type Hash | Type Name | Props |
|----------|-----------|-----------|-------|
| 0x08 (8) | 0xC9A5839D | CompactType_08 | 22 |
| 0x0B (11) | 0x82A2AEE0 | CompactType_0B | 22 |
| 0x16 (22) | 0x2DAD13E3 | PlayerOptionsElement | - |
| 0x20 (32) | 0xFBB63E47 | World | 14 |
| 0x38 (56) | 0xFA1AA549 | CompactType_38 | 22 |
| 0x3B (59) | 0xFC6EDE2A | CompactType_3B | 22 |
| 0x4F (79) | 0xF49BFD86 | CompactType_4F | 22 |
| 0x5B (91) | 0xC8761736 | CompactType_5B | 22 |
| **0x5E (94)** | **0x0DEBED19** | **CompactType_5E** | **22** |
| 0x5F (95) | 0x938F78BA | CompactType_5F | 22 |

Note: Compact types all inherit from CommonParent (0x7E42F87F) and have 22 properties each.

## Marker Bytes

Single-byte markers appear between TABLE_REF sequences to indicate values or flags:

| Marker | Block 3 Count | Block 5 Count | Likely Meaning |
|--------|---------------|---------------|----------------|
| 0x6D | 41 | 32 | Boolean TRUE or value 1 |
| 0xDB | 35 | 28 | Boolean FALSE or value 0 |
| 0xCD | 19 | 11 | Unknown flag/separator |

### Marker Pattern

Markers typically follow immediately after a TABLE_REF:

```
08 03 5E C1 DB 08 03 5E CA
           ^^ MARKER_DB after prop 0xC1

08 03 5E 96 6D 08 03 5E BB
           ^^ MARKER_6D after prop 0x96
```

## Table 0x5E Deep Analysis

Table 0x5E is the dominant type in Block 3 with 63 references across 42 unique properties:

### Property Groups

| Range | Count | Description |
|-------|-------|-------------|
| 0x01, 0x05 | 2 | Early properties |
| 0x34-0x35 | 2 | Mid-range group 1 |
| 0x37-0x38, 0x3A | 3 | Mid-range group 2 |
| 0x6C | 1 | Isolated property |
| 0x90, 0x96 | 2 | High-range start |
| 0x9D-0x9E | 2 | Status group |
| 0xA0-0xAD | 12 | Primary data block |
| 0xAF | 1 | Gap property |
| 0xB2-0xB8 | 7 | Secondary data block |
| 0xBB, 0xBE, 0xC1, 0xC4, 0xCA | 5 | Flags/config |
| 0xD0, 0xD3, 0xD6, 0xD9 | 4 | End group |

### Complete Property Index List (Reference Data)

The following 42 unique property indices were observed for Table 0x5E in Block 3:

```
0x01, 0x05, 0x34, 0x35, 0x37, 0x38, 0x3A, 0x6C,
0x90, 0x96, 0x9D, 0x9E, 0xA0, 0xA2, 0xA3, 0xA4,
0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xAB, 0xAC,
0xAD, 0xAF, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6, 0xB7,
0xB8, 0xBB, 0xBE, 0xC1, 0xC4, 0xCA, 0xD0, 0xD3,
0xD6, 0xD9
```

**Nibble Distribution Statistics:**
- Low nibbles (prop_id & 0x0F): All 16 values present (0x0-0xF)
- High nibbles (prop_id >> 4): 8 values present (0, 3, 6, 9, A, B, C, D)

**Note:** The nibble extraction code for these property indices has NOT been located in Ghidra analysis. The distribution pattern is documented here as observational data only. See "Future Research" section for investigation status.

## Value Prefixes

### VALUE_1500 Format

```
15 00 [4 bytes little-endian value]

Example: 15 00 08 A5 10 A6 = value 0xA610A508
```

Total: 6 bytes

### VALUE_1200 Format

```
12 00 [4 bytes little-endian value]

Example: 12 00 05 E9 EA E2 = value 0xE2EAE905
```

Total: 6 bytes

Note: The first byte after prefix (0x08 or 0x05) appears to be part of the encoding, not a separate field.

## Data Stream Structure

After the preamble, the data region consists of interleaved:

1. **Property References**: TABLE_REF patterns pointing to specific type properties
2. **Value Markers**: Single bytes indicating boolean/flag values
3. **Prefixed Values**: 2-byte prefix + data for typed values
4. **Raw Data Bytes**: Additional value data between structured entries

### Example Trace (Block 3, offset 0x4E)

```
004E: TABLE_REF(table=0x5B, prop=0x8A)
0052: TABLE_REF(table=0x5E, prop=0xB6)
0056: BYTE(0x8D)
0057: TABLE_REF(table=0x5E, prop=0x90)
005B: TABLE_REF(table=0x5E, prop=0x96)
005F: MARKER_6D
0060: TABLE_REF(table=0x5E, prop=0xBB)
0064: TABLE_REF(table=0x5E, prop=0xBE)
0068: TABLE_REF(table=0x5E, prop=0xC1)
006C: MARKER_DB
006D: TABLE_REF(table=0x5E, prop=0xCA)
```

## Block Content Hypothesis

Based on structural analysis:

### Block 3 (7,972 bytes)

- **4 nested headers** with distinct data regions
- Heavy use of Table 0x5E suggests a large game object with many properties
- High TABLE_REF density (80 total) indicates complex nested object structure
- PREFIX_1C04 prevalence (62 occurrences) suggests specific data type handling
- Region 1 contains most TABLE_REFs (72 of 80) - core object data
- Region 3 has highest VARINT density - numeric/counter data
- Likely contains: Mission state, inventory, or world object data

### Block 5 (6,266 bytes)

- **2 nested headers** (simpler structure)
- Fewer TABLE_REFs (10 total) suggests more direct value storage
- Symmetric distribution (5 per region) indicates balanced structure
- Balanced VARINT/FIXED32 usage suggests numeric data
- Region 2 excess space (2,049 bytes) may be growth buffer
- Likely contains: Player stats, game progress, or configuration data

## Comparison to Blocks 2/4

| Aspect | Blocks 1/2/4 (Full Format) | Blocks 3/5 (Compact Format) |
|--------|----------------------------|----------------------------|
| Compression | LZSS compressed | Uncompressed |
| Type encoding | Raw 4-byte hashes | 1-byte table IDs |
| Property encoding | Offset-based | Index-based |
| Size | 283 / 32KB / 32KB (decompressed) | 7.9KB / 6.3KB |
| Format deserializer | `FUN_01711ab0` (Block 2) | PropertyData via `FUN_01b11a50` |
| Content header | 10 null bytes + type hash | Version prefix (0x01) + size + flags |
| Entry point | vtable[10] dispatch | PropertyData version dispatch |
| Structure | Single header | Multiple nested headers |
| TABLE_REF usage | N/A (uses type hashes) | Heavy (Block 3) / Light (Block 5) |

## Note: TYPE_REF Dispatcher (Full Format Only)

> **IMPORTANT CLARIFICATION:** The function `FUN_01af6a40` (TYPE_REF dispatcher) is used
> exclusively by the **full format** (Blocks 1, 2, 4), **NOT** by the compact format
> described in this document.
>
> The TYPE_REF dispatcher:
> 1. Reads a prefix byte (0x00, 0x01, or >= 0x02)
> 2. All code paths call `FUN_01aeb020` which takes **4-byte TYPE HASHES**
>
> The compact format (Blocks 3, 5) uses a completely different mechanism:
> - **Judy arrays** with nibble-encoded table IDs via `FUN_01AEAF70`
> - **TABLE_REF** patterns (`08 03 [table_id] [prop_id]`)
>
> See `docs/TYPE_SYSTEM_REFERENCE.md` for details on the full format TYPE_REF dispatcher.

## Implementation Notes

### Reading TABLE_REF

```python
def read_table_ref(data, pos):
    if data[pos] == 0x08 and data[pos+1] == 0x03:
        table_id = data[pos+2]
        prop_id = data[pos+3]
        return (table_id, prop_id), pos+4
    return None, pos
```

### Reading VALUE_1500

```python
def read_value_1500(data, pos):
    if data[pos] == 0x15 and data[pos+1] == 0x00:
        value = struct.unpack('<I', data[pos+2:pos+6])[0]
        return value, pos+6
    return None, pos
```

## Known Type Hashes (Reference)

From `sav_parser.py` TYPE_HASHES dictionary:

| Hash | Type Name |
|------|-----------|
| 0xFBB63E47 | World |
| 0x2DAD13E3 | PlayerOptionsElement |
| 0x0984415E | PropertyReference |
| 0xA1A85298 | PhysicalInventoryItem |
| 0xBDBE3B52 | SaveGame |
| 0x5FDACBA0 | SaveGameDataObject |

## Future Research

### Current Status: Judy Array Encoder Found

**December 30, 2024 - BREAKTHROUGH:**

Found `FUN_01b25230` - a Judy Array encoder that HITS during Block 3/5 loading!

The compact format is NOT protobuf-style encoding. It's **serialized Judy array nodes**. The 2-byte prefixes are Judy node type markers.

### Confirmed Understanding

1. **Judy Arrays** are used for property storage in Blocks 3/5
2. **FUN_01b25230** at `+0x1725230` is the node encoder/normalizer
3. **Type codes 0x0B-0x1C** are intermediate node types that get normalized
4. **Output types 0x08-0x1C** are canonical serialized node types
5. **Call chain** goes through FUN_01AEAF70 (table ID lookup) → encoder
6. **Nested headers** - Block 3 has 4 valid headers, Block 5 has 2 valid headers
7. **Inter-region gaps** - Block 3: 5-byte format, Block 5: 4-byte format (both end with `20 00` terminator)
8. **All headers valid** - Both blocks use version 0x01, flags 0x00800000

### Remaining Tasks

#### High Priority

1. ~~**Trace FUN_01b24720** - This writes type 0x15/0x18 output data~~ **DONE** - Multi-type encoder for 0x14, 0x17, 0x18, 0x1b, 0x1c
2. ~~**Trace FUN_01b249a0** - This writes type 0x16/0x19 output data~~ **DONE** - 3-byte key encoder for 0x15, 0x19
3. **Examine caller at +0x1725d66** - Understand value structure population
4. **Build Judy array deserializer** - Parse the binary stream using node types
5. **Investigate nested header semantics** - Why 4 headers in Block 3, 2 in Block 5?

#### Medium Priority

6. **Map TABLE_REF to Judy** - How does `08 03 [table_id] [prop_id]` interact with Judy nodes?
7. **Understand preamble** - The 70-byte (Block 3) / 267-byte (Block 5) preambles
8. **Cross-reference Judy sizes** - "3, 5, 7, 11, 15, 23, 32, 47, 64" allocation sizes
9. **Decode high-frequency patterns** - `02 4F`, `02 3B`, `01 D0` in Block 5

#### Lower Priority

10. **Table ID to type hash mapping** - Complete the 0x5E, 0x5B, etc. mappings
11. **Cross-block references** - How Blocks 3/5 relate to Blocks 2/4
12. **Size field semantics** - Why the 5-byte offset pattern?

### Key Breakpoints

```
# Judy Array encoder (CONFIRMED TO HIT)
bp ACBSP+0x1725230 ".printf \"Type=%02x Data=%08x\\n\", byte([ebx+7]), dwo(ebx); g"

# Value encoders (need to trace)
bp ACBSP+0x1724720  # FUN_01b24720 - type 0x15/0x18 encoder
bp ACBSP+0x17249a0  # FUN_01b249a0 - type 0x16/0x19 encoder

# Allocation functions
bp ACBSP+0x171ea70  # FUN_01b1ea70 - allocate 42 elements
bp ACBSP+0x171eac0  # FUN_01b1eac0 - allocate 36 elements

# Search functions
bp ACBSP+0x1761640  # FUN_01b61640 - Judy search
bp ACBSP+0x1761680  # FUN_01b61680 - Judy search variant

# Call chain analysis
bp ACBSP+0x1725d66  # Immediate caller return address
bp ACBSP+0x17268f1  # Higher-level caller
```

### Previously Traced Functions (PropertyData Path)

These were traced but are NOT the compact format path:

| Function | Purpose | Result |
|----------|---------|--------|
| FUN_01b702e0 | Version 1 initializer | Just sets vtable/flags |
| FUN_01b70450 | Version 1 field reader | Reads via vtable dispatch |
| FUN_01b6f150 | Stream byte reader | Single byte read |
| FUN_01af6a40 | TYPE_REF dispatcher | Uses 4-byte hashes (full format only) |

The PropertyData handlers appear to be for a different serialization path, not Judy arrays.

## File Locations

- Block 3 test file: `/tmp/compact_analysis/sav_block3_raw.bin`
- Block 5 test file: `/tmp/compact_analysis/sav_block5_raw.bin`
- Parser implementation: `/mnt/f/ClaudeHole/assassinscreedsave/sav_parser.py`
