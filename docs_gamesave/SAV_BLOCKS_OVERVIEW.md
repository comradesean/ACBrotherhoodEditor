# SAV Blocks Overview

Quick reference for the 5-block structure of AC Brotherhood SAV files.

> **⚠ MAJOR CORRECTION (July 2026):** the "5-block" model below describes only
> the small fresh reference save this analysis was based on. The validated
> general structure (checksum-verified across PC and PS3 saves) is:
>
> ```
> [Block 1: 44-byte header + LZSS]  SaveGame root
> [Block 2: 44-byte header + LZSS]  Game state
> [Frame 0..N-1], each:
>   [0x01][comp_size 3B LE][00 00 80 00][1 byte][adler32 4B LE][LZSS data]
> ```
>
> Every frame decompresses to exactly 32 KB, and N grows with progression
> (6 fresh, 14-16 played). What this document calls "Block 3 regions 1-3" are
> frames #0-2, "Block 4" is frame #3, and "Block 5" is frames #4 onward. The
> inventory frame must be located BY CONTENT (decompress and inspect), not by
> position. All statements below about "Blocks 3/5 raw compact data" were
> derived from reading LZSS-COMPRESSED bytes and describe compression
> artifacts, not real structures. Block 1, Block 2, and the decompressed
> Block 4 (inventory) analyses remain valid.

---

## Block Summary

| Block | Format | Header | Compressed | Decompressed | Primary Content |
|-------|--------|--------|------------|--------------|-----------------|
| 1 | Full (LZSS) | 44-byte (0xCD) | ~173 bytes | 283 bytes | SaveGame root object |
| 2 | Full (LZSS) | 44-byte (0xCAFE00) | ~1,854 bytes | 32,768 bytes | Game state, missions, rewards |
| 3 | Compact | None | 7,972 bytes | 7,972 bytes | World compact data |
| **4** | **Full (LZSS)** | **10 zeros only** | **2,150 bytes** | **32,768 bytes** | **Inventory (364 items)** |
| 5 | Compact | None | 6,266 bytes | 6,266 bytes | Additional compact data |

**Block 4 Note:** Uses full format (4-byte type hashes) but uniquely has NO 44-byte header - only 10 zero bytes prefix.

---

## Cross-Block Relationship Diagram

```
+------------------+
|     Block 1      |
|   SaveGame Root  |
| (0xBDBE3B52)     |
+--------+---------+
         |
         | World reference (Object ID 0x8DAC4763)
         v
+------------------+          +------------------+
|     Block 2      |          |     Block 3      |
| Game State       |<-------->| World Compact    |
| (0x94D6F8F1)     |  World   | (0xFBB63E47)     |
| - MissionSaveData|  type    | TABLE_REF 0x5E   |
| - RewardFault    |  hash    +--------+---------+
| - PropertyRefs   |                   |
+--------+---------+                   |
         |                             | Region 4 cross-block reference
         | PhysicalInventoryItem       | (declared size = Block 4 size)
         | type hash                   |
         v                             v
+------------------+          +------------------+
|     Block 4      |<---------| Block 3 Region 4 |
| Inventory Items  |  LINKED  | Reference desc:  |
| (0xA1A85298)     |          | 00 27 a6 62 20   |
| 364 items total  |          +------------------+
+------------------+
         ^
         |          +------------------+
         |          |     Block 5      |
         +----------| PropertyRef Data |
           (refs)   | Region 2: +2049b |
                    | growth buffer    |
                    +------------------+
```

### Block 3 -> Block 4 Relationship (CRITICAL)

Block 3 Region 4 contains a **cross-block reference descriptor** that points to Block 4:

| Property | Value |
|----------|-------|
| Region 4 declared size | 2,150 bytes |
| Block 4 LZSS compressed size | 2,150 bytes |
| Region 4 actual data | 5 bytes: `00 27 a6 62 20` |

This establishes a direct link between:
- **Block 3** (compact format World state metadata)
- **Block 4** (LZSS-compressed inventory items)

The relationship is: Block 3 provides metadata/references for the inventory items stored in Block 4.

---

## Type Hash Cross-Reference

| Hash | Type Name | Block 1 | Block 2 | Block 3 | Block 4 | Block 5 |
|------|-----------|:-------:|:-------:|:-------:|:-------:|:-------:|
| 0xBDBE3B52 | SaveGame | ROOT | - | - | - | - |
| 0x94D6F8F1 | AssassinSaveGameData | - | ROOT | - | - | - |
| 0xFBB63E47 | World | ref | x2 | PRIMARY | - | - |
| 0x5FDACBA0 | SaveGameDataObject | ref | x2 | - | - | - |
| 0xA1A85298 | PhysicalInventoryItem | - | - | - | x364 | x1 |
| 0x0984415E | PropertyReference | - | x21 | - | x182 | - |
| 0x5ED7B213 | MissionSaveData | - | x3 | - | - | - |
| 0x12DE6C4C | RewardFault | - | x2 | - | - | - |
| 0x9BD7FCBE | CollectibleRecord | - | x157 | - | - | - |
| 0x75758A0E | CollectibleClass | - | x157 | - | - | - |
| 0x768CAE23 | CollectibleParent | - | x157 | - | - | - |

---

## Data Flow

```
SAVE OPERATION:

  SaveGame (Block 1)
      |
      +-- World ref -----> World object (Block 2, offset 0x021F)
      |                        |
      +-- DataObject ref       +-- Compact serialization --> Block 3
                               |
  Game State (Block 2)         |
      |                        |
      +-- MissionSaveData      |
      +-- RewardFault          |
      +-- PropertyRefs --------+
      +-- Entity arrays

  Inventory (Block 4) <-- 364 PhysicalInventoryItem entries
      |
      +-- Each item has PropertyReference

  Compact Data (Block 5) <-- Additional serialized state
```

---

## Compression Summary

| Block | Has Header | Header Marker | Compressed Size | Notes |
|-------|------------|---------------|-----------------|-------|
| 1 | Yes (44 bytes) | 0x000000CD | Offset 0x20 | Standard full format |
| 2 | Yes (44 bytes) | 0x00CAFE00 | Offset 0x20 | CAFE00 deserializer |
| 3 | No | N/A | N/A (Raw) | Compact format |
| **4** | **No (10 zeros)** | **N/A** | **2,150 bytes** | **Full format, no header** |
| 5 | No | N/A | N/A (Raw) | Compact format |

**Block 4 Discovery:** The only LZSS-compressed block without a 44-byte header. Uses full format serialization but compressed size (2,150) matches Block 3 Region 4's declared size exactly - establishing a cross-block reference.

---

## Block 4 Item Formats

Block 4 contains 364 PhysicalInventoryItem entries in two interleaved formats:

| Format | Marker at +04 | Count | Size Range | Total Bytes | Purpose |
|--------|---------------|-------|------------|-------------|---------|
| Format 1 | 0x0032 | 182 | 66-71 bytes | 12,381 | Simple stackable items |
| Format 2 | 0x0000 | 182 | 22-1,236 bytes | 20,306 | Complex/variable items |

**Format Detection:** Check 2 bytes at offset +04 after the type hash (0xA1A85298):
- `0x0032` = Format 1 (simple stackable, fixed structure)
- `0x0000` = Format 2 (complex, variable length)

**Key Findings:**
- Items are **interleaved** (72 format transitions), not separated by format type
- All Format 1 items have quantity=42 (max stack size)
- Largest single item: 1,236 bytes (Format 2)
- 1:1 PropertyReference binding for Format 1 items only

---

## Block 2 Collectibles Array (DECODED)

Block 2 contains a 157-entry collectibles array storing the collected/uncollected state for all feathers and flags:

| Property | Value |
|----------|-------|
| Location | 0x03E8 - 0x40D7 |
| Size | 15,600 bytes (47.6% of Block 2) |
| Entry Count | 157 (100 feathers + 57 flags) |
| Entry Size | ~99 bytes each |
| Format | Full format (4-byte hashes, byte-aligned) |

### Entry Structure (98 bytes)

```
+0x00: Field 0 (18 bytes) - Class reference (0x75758A0E)
+0x12: Field 1 (18 bytes) - Parent reference (0x768CAE23 -> World)
+0x24: Field 2 (18 bytes) - Instance reference (0x309E9CEF)
+0x36: Field 3 (18 bytes) - State value (0x00 = uncollected)
+0x48: Footer (26 bytes)  - Record type (0x9BD7FCBE)
```

### State Values

| Value | Count | Meaning |
|-------|-------|---------|
| 0x00 | 156 | Uncollected |
| 0x19 | 1 | Special marker (story-related) |

### World Object Link

All 157 collectible entries link to the World object at offset 0x0212 via the parent reference hash 0x768CAE23.

---

## Compact Format Table IDs (Blocks 3 & 5)

| Table ID | Block 3 Refs | Block 5 Refs | Resolved Type |
|----------|--------------|--------------|---------------|
| 0x5E | 63 | - | CompactType_5E (0x0DEBED19) |
| 0x5B | 4 | - | CompactType_5B (0xC8761736) |
| 0x20 | - | - | World (0xFBB63E47) |
| 0x4F | - | 61 | CompactType_4F (0xF49BFD86) |
| 0x3B | 1 | - | CompactType_3B (0xFC6EDE2A) |

## Compact Format Region Structure

### Block 3 Regions (4 nested headers)

| Region | Offset Range | Content | Notes |
|--------|--------------|---------|-------|
| 1 | 0x0008-0x0E41 | CompactType_5E objects | 72 TABLE_REFs, primary World state |
| 2 | 0x0E4E-0x15A3 | Item references | PhysicalInventoryItem hash 0xA1A85298 |
| 3 | 0x15B0-0x1F12 | Numeric counters | 29.8% VARINT, game statistics |
| 4 | 0x1F1F-0x1F24 | **Block 4 reference** | Declared=2150, Actual=5 bytes |

### Block 5 Regions (2 nested headers)

| Region | Offset Range | Content | Notes |
|--------|--------------|---------|-------|
| 1 | 0x0008-0x075F | PropertyReference data | 5 TABLE_REFs |
| 2 | 0x076C-0x187A | Extended data + buffer | +2,049 bytes growth space |

### Inter-Region Gaps

All gaps between regions use 5-byte format: `[type] [value_16 LE] [0x20 0x00]`

| Gap | Bytes | Purpose |
|-----|-------|---------|
| Block 3: 1->2 | `04 74 62 20 00` | Region separator |
| Block 3: 2->3 | `00 00 28 20 00` | Region separator |
| Block 3: 3->4 | `00 00 a7 20 00` | Region separator |
| Block 5: 1->2 | `00 00 e5 20 00` | Region separator |

---

## Key Object IDs

| Object | ID | Found In |
|--------|-----|----------|
| World instance | 0x8DAC4763 | Block 1 (ref), Block 2 (data) |
| SaveGameDataObject | 0x00000000 | Block 1 (null ref) |

---

## Quick Navigation

| Topic | Document |
|-------|----------|
| SaveGame root structure | [BLOCK1_SAVEGAME_STRUCTURE.md](blocks/BLOCK1_SAVEGAME_STRUCTURE.md) |
| Game state and missions | [BLOCK2_GAME_STATE_STRUCTURE.md](blocks/BLOCK2_GAME_STATE_STRUCTURE.md) |
| Inventory items | [BLOCK4_INVENTORY_STRUCTURE.md](blocks/BLOCK4_INVENTORY_STRUCTURE.md) |
| Compact format spec | [BLOCKS_3_5_COMPACT_FORMAT.md](blocks/BLOCKS_3_5_COMPACT_FORMAT.md) |
| Complete SAV specification | [SAV_FILE_FORMAT_SPECIFICATION.md](SAV_FILE_FORMAT_SPECIFICATION.md) |
| Type system reference | [TYPE_SYSTEM_REFERENCE.md](TYPE_SYSTEM_REFERENCE.md) |

---

## File Layout (Example: 18,503 bytes)

```
Offset      Size        Block
--------    --------    ---------------------------
0x0000      44 + 173    Block 1: SaveGame header + LZSS
0x00D9      44 + 1854   Block 2: GameState header + LZSS
[dynamic]   7,972       Block 3: World compact (raw)
[dynamic]   2,150       Block 4: Inventory LZSS (no header)
[end-6266]  6,266       Block 5: Compact data (raw)
```

---

*Generated from block-specific documentation. See individual files for complete details.*

*Last updated: December 30, 2024 - Added Block 2 collectibles array analysis (157 entries, 100 feathers + 57 flags).*
