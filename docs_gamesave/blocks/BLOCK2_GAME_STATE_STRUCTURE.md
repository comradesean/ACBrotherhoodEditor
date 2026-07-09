# Block 2 Game State Structure

> **Note (July 2026):** the Block 2 analysis in this document is valid (it was
> performed on correctly decompressed data). Any mentions of "Block 3",
> "Block 4", or "Block 5" use the deprecated 5-block naming — those are LZSS
> frames located by content — and cross-references to Block 3/5 "compact" or
> "Judy Array" raw content were derived from compressed bytes (artifacts).
> See SAV_BLOCKS_OVERVIEW.md for the corrected structure.

## Overview

Block 2 is the main game state block in Assassin's Creed Brotherhood SAV files. It is LZSS compressed and decompresses to exactly 32,768 bytes (32 KB).

**SAV File Location:**
- Header offset: 0x00D9 (44 bytes)
- Compressed data offset: 0x0105
- Typical compressed size: ~1,854 bytes

**Header Markers:**
- Field2: 0x00000001
- Field3: 0x00CAFE00 (distinguishes from Block 1's 0x000000CD)

---

## Type Hash Summary

Block 2 contains the following serialized types:

| Type | Hash | Count | Offset Range |
|------|------|-------|--------------|
| PropertyReference | 0x0984415E | 21 | 0x40E1 - 0x45F5 |
| MissionSaveData | 0x5ED7B213 | 3 | 0x00B1 - 0x00CE |
| SaveGameDataObject | 0x5FDACBA0 | 2 | 0x00DE - 0x00E2 |
| RewardFault | 0x12DE6C4C | 2 | 0x0196 - 0x019A |
| World | 0xFBB63E47 | 2 | 0x0212 - 0x0216 |

---

## Block Layout

```
0x0000 - 0x0015  Header (22 bytes)
0x0016 - 0x0097  Root object intro section
0x0098 - 0x00B0  Pre-MissionSaveData section
0x00B1 - 0x00CD  MissionSaveData entries (3 instances)
0x00CE - 0x00D9  Bridge section
0x00DA - 0x0127  SaveGameDataObject region
0x0128 - 0x0191  Intermediate region
0x0192 - 0x01B3  RewardFault region
0x01B4 - 0x020D  Post RewardFault section
0x020E - 0x03E7  World data (2 World instances)
0x03E8 - 0x40D7  *** COLLECTIBLES ARRAY (157 entries) ***  [DECODED]
0x40D8 - 0x460F  PropertyReference array (21 entries)
0x4610 - 0x4B85  Intermediate data region
0x4B86 - 0x7FFF  *** ENTITY ARRAY (130 entries) ***  [DECODED]
```

### Block 2 Understanding Summary

| Section | Offset | Size | Entries | Status |
|---------|--------|------|---------|--------|
| Leading zeros | 0x00-0x09 | 10 | - | Complete |
| Root type | 0x0A-0x15 | 12 | 1 | Complete |
| Properties | 0x16-0x03E7 | ~3,500 | ~150 | Partial |
| **Collectibles array** | **0x03E8-0x40D7** | **15,600** | **157** | **DECODED** |
| PropertyReference | 0x40D8-0x460F | ~1,400 | 21 | Partial |
| **Entity array** | **0x4B86-0x7FFF** | **13,433** | **130** | **DECODED** |

**Overall inner layer understanding: ~85%** (improved from 70% with entity array discovery)

---

## Header Section (0x0000 - 0x0015)

| Offset | Size | Value | Description |
|--------|------|-------|-------------|
| 0x00 | 10 | `00 00 00 00 00 00 00 00 00 00` | Leading zeros (padding) |
| 0x0A | 4 | `0x94D6F8F1` | Root type hash |
| 0x0E | 4 | `0x0003F208` | Size/offset value 1 (258,568) |
| 0x12 | 4 | `0x0003F1B8` | Size/offset value 2 (258,488) |

---

## Serialization Pattern

Type entries follow a consistent pattern:

```
[prefix] 00 00 00 [type_hash] [type_hash] 00 00 [flags] [data...]
```

**Prefix values:**
- `0x11`: Type reference (most common)
- `0x12`: Secondary type reference
- `0x0E`: Property value
- `0x0B`: Property marker
- `0x17`: Extended property

**Double-hash pattern:**
Types are serialized with the hash appearing twice:
```
11 00 00 00 [hash4] [hash4] 00 00 [flags2] ...
```

This pattern allows the deserializer to verify type consistency.

---

## MissionSaveData (0x5ED7B213)

**Purpose:** Stores mission-specific save data, including checkpoint information and mission state.

**Locations:**
- 0x00B1 (first occurrence, hash repeated at 0x00B5)
- 0x00CE (third occurrence)

**Entry Structure:**
```
Offset  Content
0x00    13 b2 d7 5e  - MissionSaveData hash (LE)
0x04    13 b2 d7 5e  - MissionSaveData hash repeated
0x08    00 00        - Flags
0x0A    1d 0a        - Entry type marker
0x0C    0b           - Subtype marker
0x0D    01           - Boolean/count
0x0E    01 00 00 00  - Data field
        ...          - Additional mission data (zeros in fresh save)
```

**Sample (0x00B1):**
```
0x00B1: 13 b2 d7 5e 13 b2 d7 5e 00 00 1d 0a 0b 01 01 00
0x00C1: 00 00 00 00 00 00 00 00 00 00 00 00 00 13 b2 d7
```

---

## SaveGameDataObject (0x5FDACBA0)

**Purpose:** Container for save game data objects, wrapping mission data and player state.

**Locations:**
- 0x00DE (first occurrence)
- 0x00E2 (second occurrence, hash repeated)

**Entry Structure:**
```
Offset  Content
0x00    a0 cb da 5f  - SaveGameDataObject hash (LE)
0x04    a0 cb da 5f  - Hash repeated
0x08    00 00        - Flags
0x0A    12 00        - Entry type marker
0x0C    0b           - Property marker
0x0D    27 ec 79 8a  - Reference ID
        ...          - Referenced data
```

**Sample (0x00DE):**
```
0x00DE: a0 cb da 5f a0 cb da 5f 00 00 12 00 0b 27 ec 79
0x00EE: 8a 11 00 00 00 4c b5 e5 44 00 00 00 00 00 00 07
```

---

## RewardFault (0x12DE6C4C)

**Purpose:** Tracks Ubisoft Connect / Uplay reward status and fault states.

**Locations:**
- 0x0196 (first occurrence)
- 0x019A (second occurrence, hash repeated)

**Entry Structure:**
```
Offset  Content
0x00    4c 6c de 12  - RewardFault hash (LE)
0x04    4c 6c de 12  - Hash repeated
0x08    00 00        - Flags
0x0A    9d 0a        - Entry type marker
0x0C    0b 01        - Property marker with count
0x0E    00 00 00 00  - Fault state (zeros = no faults)
        ...          - Additional fault tracking data
```

**Sample (0x0196):**
```
0x0196: 4c 6c de 12 4c 6c de 12 00 00 9d 0a 0b 01 00 00
0x01A6: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 56 00
```

---

## World (0xFBB63E47)

**Purpose:** Main world object containing map state, player position references, and world properties.

**Locations:**
- 0x0212 (first occurrence)
- 0x0216 (second occurrence, hash repeated)

**Entry Structure:**
```
Offset  Content
0x00    47 3e b6 fb  - World hash (LE)
0x04    47 3e b6 fb  - Hash repeated
0x08    00 00        - Flags
0x0A    12 00        - Entry type marker
0x0C    0b           - Property marker
0x0D    63 47 ac 8d  - World instance ID
        ...          - World properties
```

**World Data Region (0x020E - 0x03E7):**
The World entries span approximately 474 bytes and contain nested property references including:
- Property hash 0x11854ADA
- Property hash 0x7ACF45C6
- Property hash 0xF44B5195
- Property hash 0x5DEBF8DE
- Property hash 0xD92D49F7
- Property hash 0xD4C878C7

**Sample (0x0212):**
```
0x0212: 47 3e b6 fb 47 3e b6 fb 00 00 12 00 0b 63 47 ac
0x0222: 8d de 00 00 00 90 dd c7 8a 6d f7 9a 1f 00 00 16
```

---

## PropertyReference Array (0x0984415E) - DECODED

**Purpose:** Array of property references used for binding game state values to runtime objects. These 21 entries represent game state bindings for missions, rewards, and other dynamic game elements.

**Location:** 0x40D8 - 0x460F
**Count:** 21 entries
**Entry Size:** 65 bytes (0x41)
**Preceded by:** Hash 0xAF605F1F (array container marker)

### Entry Structure (65 bytes)

Each entry follows a uniform structure for binding game values:

```
Offset  Size  Content                    Description
------  ----  -------------------------  -----------------------------------
0x00    1     00                         Padding
0x01    4     11 00 00 00                Prefix marker (0x11 = type ref)
0x05    4     1f 5f 60 af                Container hash 0xAF605F1F
0x09    4     5e 41 84 09                PropertyReference hash (0x0984415E LE)
0x0D    2     00 00                      Type markers
0x0F    2     12 00                      Entry type marker
0x11    1     0b                         Property marker
0x12    4     00 00 00 00                Reference ID (always zero = embedded)
0x16    18    [zeros]                    Reserved bytes
0x28    4     63 6a 1c 62                Secondary hash 0x621C6A63
0x2C    4     [varies]                   Size/count value
0x30    4     [varies]                   Data value
0x34-40 13    [zeros/padding]            Entry padding
```

**Key Observations:**
- **Uniform 65-byte spacing** between all PropertyReference entries
- **Reference ID = 0x00000000** for all entries (embedded metadata pattern)
- **Container hash 0xAF605F1F** precedes the entire array
- **Secondary hash 0x621C6A63** appears within each entry (often at +0x28)

### Cross-Block Architecture

PropertyReferences in Block 2 use the same hash (0x0984415E) as those in Block 4 and Block 5:

| Block | Count | Format | Purpose |
|-------|-------|--------|---------|
| Block 2 | 21 | 65-byte entries | Game state bindings (missions, rewards) |
| Block 4 | 182 | Double-hash pairs | 1:1 binding per Format 1 inventory item |
| Block 5 | 3 | Judy Array embedded | Compact format bindings |
| **Total** | **206** | | |

All PropertyReference entries across all blocks use **Reference ID = 0x00000000**, indicating they store embedded metadata rather than external references.

---

## Collectibles Array (0x03E8 - 0x40D7) - DECODED

**Purpose:** Array storing the collected/uncollected state for all feathers and flags in the game.

**Size:** 15,600 bytes (47.6% of Block 2)
**Entry Count:** 157 slots (matches AC Brotherhood: 100 feathers + 57 flags)
**Entry Size:** ~99 bytes each (67-byte header + 157 x ~99 bytes per entry)
**Format:** Full format serialization (4-byte type hashes, byte-aligned fields)

### Entry Structure (98 bytes)

Each collectible entry consists of 4 fields (18 bytes each) plus a 26-byte footer:

| Offset | Size | Field | Hash | Purpose |
|--------|------|-------|------|---------|
| +0x00 | 18 | Field 0 | 0x75758A0E | Class/type reference (unified collectible type) |
| +0x12 | 18 | Field 1 | 0x768CAE23 | Parent/container (links to World object) |
| +0x24 | 18 | Field 2 | 0x309E9CEF | Instance/property reference (slot ID) |
| +0x36 | 18 | Field 3 | varies | State value (0x00 = uncollected) |
| +0x48 | 26 | Footer | 0x9BD7FCBE | Record type hash |

### Field Format (18 bytes each)

```
[Type:1] [Variant:1] [0x0B:1] [0x00:1] [SubType:1] [0x00:3] [Hash/Value:4] [Padding:6]
```

**Field Type Markers:**
| Marker | Variant | Meaning |
|--------|---------|---------|
| 0x43 | 0x24 | ObjectRef - class reference |
| 0x43 | 0x21 | ObjectRef - property reference |
| 0xC3 | 0x22 | ObjectRefFlagged - flagged object reference |
| 0xC0 | 0x20 | StateValue - state field |

### State Values

| Value | Count | Meaning |
|-------|-------|---------|
| 0x00 | 156 entries | Uncollected / Not obtained |
| 0x19 (25) | 1 entry | Special marker (story-required or milestone) |

### Key Hashes in Collectibles Array

| Hash | Count | Purpose |
|------|-------|---------|
| 0x75758A0E | 157 | Class/type reference (unified collectible type) |
| 0x768CAE23 | 157 | Parent/container (links to World object at 0x0212) |
| 0x309E9CEF | 157 | Instance/property reference (unique slot ID) |
| 0x9BD7FCBE | 157 | Record type footer (confirms entry type) |
| 0xF977547D | 157 | Property hash (state property) |

### World Object Relationship

```
World object (0x0212)
  +-- Property reference 0x768CAE23
     +-- 157 collectible slots (0x03E8-0x40D7)
```

The parent reference in each collectible entry (0x768CAE23) links back to the World object at offset 0x0212.

### Editing Collectibles

To mark collectible N as found:
1. Calculate state field offset: `0x03E8 + 67 + (N x 99) + 0x36 + 8`
2. Change 4-byte value from `0x00000000` to non-zero (e.g., `0x00000001`)
3. Recompress Block 2 with LZSS
4. Rebuild SAV file

**Note:** Cannot add/remove entries (fixed count of 157)

---

## Entity Array (0x4B86 - 0x7FFF) - DECODED

**Purpose:** Array storing synchronization point states (likely the 130 sync points available in AC Brotherhood).

### Overview

| Property | Value |
|----------|-------|
| Location | 0x4B86 - 0x7FFF |
| Entry size | 104 bytes (perfectly uniform) |
| Entry count | 130 entities |
| Total size | 13,433 bytes (41% of Block 2) |

### Entry Layout (104 bytes)

| Offset | Size | Content | Notes |
|--------|------|---------|-------|
| +0x00-0x01 | 2B | `00 00` | Padding |
| +0x02-0x05 | 4B | `11 00 00 00` | Type reference marker |
| +0x06-0x09 | 4B | `41 6F 6A 5B` | Type hash 0x5B6A6F41 |
| +0x0A-0x0B | 2B | `00 00` | Flags |
| +0x0C-0x0D | 2B | `00 00` | Property count |
| +0x0E-0x0F | 2B | `0B 00` | Property marker |
| +0x10-0x12 | 3B | `07 00 0B` | Data block start |
| **+0x13-0x16** | **4B** | **[VARIABLE]** | **Entity ID (32-bit LE, unique)** |
| +0x17-0x27 | 17B | Property block 1 | Type references |
| **+0x28** | **1B** | **[VARIABLE]** | **State flag (0x00/0x01)** |
| +0x29-0x67 | 63B | Property blocks 2-3 | Nested containers (0xCEBFA9E3) |
| +0x68-0x103 | 60B | Padding | Alignment zeros |

### Variable Fields

**Entity ID (+0x13-0x16)**
- 4-byte little-endian unique identifier
- Range: 0x000B7F04 to 0xA7539F1F
- All 130 values are distinct
- IDs appear grouped by region with slot indexing

**State Flag (+0x28)**
- 1-byte boolean: `0x00` (inactive) or `0x01` (active)
- Distribution: 100 active (76.9%), 30 inactive (23.1%)

### Type Hashes in Entity Array

| Hash | Count | Purpose |
|------|-------|---------|
| 0x5B6A6F41 | 130 | Entity type (main entry type) |
| 0xCEBFA9E3 | 129 | Property container (nested in most entries) |
| 0x72A56CB6 | 129 | Associated property reference |
| 0xB809DECD | 129 | Associated property reference |
| 0x56321E79 | 129 | Associated property reference |

### Entry Structure (Detailed)

```
+0x00: 00 00                    - Padding
+0x02: 11 00 00 00              - Type reference marker
+0x06: 41 6f 6a 5b              - Type hash 0x5B6A6F41
+0x0A: 00 00                    - Flags
+0x0C: 00 00                    - Property count
+0x0E: 0b 00                    - Property marker
+0x10: 07 00 0b                 - Data block start
+0x13: [4 bytes]                - Entity ID (unique, LE)
+0x17: 0e 00 00 00 b6 6c a5 72  - Property entry (0x72A56CB6)
+0x1F: 00 00 00 00 00 00 00 00  - Property value
+0x27: 0b                       - Property marker
+0x28: [01 or 00]               - State flag (active/inactive)
+0x29: 0e 00 00 00 cd de 09 b8  - Property entry (0xB809DECD)
+0x31: 00 00 00 00 00 00 00 00  - Property value
+0x39: 0b 00                    - Property marker
+0x3B: 11 00 00 00 e3 a9 bf ce  - Nested type (0xCEBFA9E3)
+0x43: 00 00 00 00 00 00 07 00  - Nested flags
+0x4B: 0b 00 00 00 00           - Empty nested property
+0x50: [zeros to 0x67]          - Padding
```

### Game Semantics

Most likely represents **synchronization points** (AC Brotherhood has 133 total sync points, with 3 possibly being tutorial/auto-unlocked). The boolean state flag tracks active/discovered state:
- `0x01` = Active/discovered (100 entries, 76.9%)
- `0x00` = Inactive/undiscovered (30 entries, 23.1%)

### Editing Entity States

To toggle entity N's state:
1. Calculate state flag offset: `0x4B86 + (N x 104) + 0x28`
2. Change 1-byte value from `0x00` to `0x01` (or vice versa)
3. Recompress Block 2 with LZSS
4. Rebuild SAV file

**Note:** Entity IDs are fixed per entry and should not be modified.

---

## Hash Catalog

### Type Hashes (Prefix 0x11)

| Hash | Count | Description |
|------|-------|-------------|
| 0x5B6A6F41 | 130 | Entity/sync point type (entity array main type) |
| 0xCEBFA9E3 | 129 | Property container (nested in entity entries) |
| 0xAF605F1F | 21 | PropertyReference related |
| 0x7ACF45C6 | 2 | World property |
| 0xF44B5195 | 2 | World property |
| 0x5DEBF8DE | 2 | World property |
| 0xD4C878C7 | 2 | World property |
| 0xFBB63E47 | 1 | World |
| 0x5FDACBA0 | 1 | SaveGameDataObject |
| 0x44E5B54C | 1 | Unknown |
| 0xBF4C2013 | 1 | Unknown |
| 0xAC016BC1 | 1 | Unknown |
| 0xE38B5102 | 1 | Unknown |
| 0x2179DAE4 | 1 | Unknown |

### Property Hashes (Prefix 0x0E)

| Hash | Count | Description |
|------|-------|-------------|
| 0x309E9CEF | 157 | Collectibles array element property |
| 0x75758A0E | 157 | Collectibles array element property |
| 0x768CAE23 | 157 | Collectibles array element property |
| 0x72A56CB6 | 129 | Entity array property reference |
| 0xB809DECD | 129 | Entity array property reference |
| 0x56321E79 | 129 | Entity array property reference |
| 0x11854ADA | 2 | World-related |
| 0x11A757F6 | 2 | World-related |
| 0x000C0C40 | 2 | Value property |
| 0x2F4ACE81 | 2 | Value property |

---

## Identified Game Values

### Collectibles (0x03E8 - 0x40D7) - CONFIRMED EDITABLE

The collectibles array stores the collected/uncollected state for 157 items:
- **100 feathers** scattered across Rome
- **57 flags** from various factions

Each entry's state value at offset +0x36 (within its 98-byte structure) determines collection status:
- `0x00000000` = Uncollected
- Non-zero = Collected

### Synchronization Points (0x4B86 - 0x7FFF) - CONFIRMED EDITABLE

The entity array stores state for 130 synchronization points:
- AC Brotherhood has 133 total sync points (3 may be tutorial/auto-unlocked)
- Each entry's state flag at offset +0x28 determines active/inactive status:
  - `0x01` = Active/discovered (100 entries in fresh save)
  - `0x00` = Inactive/undiscovered (30 entries in fresh save)

### Other Potential Value Locations

1. **World Section (0x020E - 0x03E7):** Player position and map state
2. **PropertyReference Array (0x40D8 - 0x460F):** 21 game state bindings

### Note on Value Editing

Direct editing of Block 2 values is complex due to:
- Hash-based type system requiring correct type markers
- Nested structure with cross-references
- Variable-length encodings
- Full format serialization (byte-aligned, not nibble-encoded)

**Collectibles and sync points are the most accessible editable values:**
- Collectibles: fixed 157-entry count with consistent 98-byte structure
- Sync points: fixed 130-entry count with consistent 104-byte structure

For simple value editing (money, health), check Block 4 which may contain more accessible game state data.

---

## Comparison with Other Blocks

| Block | Purpose | Format | Size |
|-------|---------|--------|------|
| Block 1 | Player Profile | LZSS compressed | 283 bytes |
| **Block 2** | **Game State** | **LZSS compressed** | **32,768 bytes** |
| Block 3 | Compact data | Uncompressed | 7,972 bytes |
| Block 4 | Extended state | LZSS compressed | 32,768 bytes |
| Block 5 | Compact data | Uncompressed | 6,266 bytes |

---

## Technical Notes

1. **Double-hash verification:** All type entries use a double-hash pattern where the same 4-byte hash appears twice consecutively, followed by 2 bytes of flags.

2. **Little-endian encoding:** All multi-byte values use little-endian byte order.

3. **Property nesting:** Objects contain nested properties, each prefixed with type/count markers.

4. **Sparse arrays:** Most array slots contain zeros, indicating uninitialized state (early game save).

5. **Fixed entry sizes:** PropertyReference entries are exactly 65 bytes; collectible entries are 98 bytes; entity/sync point entries are exactly 104 bytes.

---

## File Generation

This document was generated by analyzing:
- File: `/tmp/block2_analysis/sav_block2_decompressed.bin`
- Original: `ACBROTHERHOODSAVEGAME0.SAV`
- Block 2 compressed size: 1,854 bytes
- Block 2 decompressed size: 32,768 bytes
