# Block 4 Inventory Structure Analysis

> **Note (July 2026):** the decompressed-content analysis in this document is
> valid — it was performed on correctly decompressed data. What changed is the
> framing: "Block 4" is simply one of N self-contained LZSS frames that follow
> Block 2 (frame #3 on the fresh reference save analyzed here), and its
> position varies with game progression (frame #9-#15 on played PS3 saves).
> The "compressed size matching Block 3 Region 4's declared size" is just the
> frame's own header declaring its data size; the byte before the adler32 plus
> the checksum are the "5-byte local data" of the old model. Locate this frame
> by decompressing frames and looking for its content, not by position.

## Overview

Block 4 contains the player's physical inventory items. It uses **full format** (4-byte type hashes) with LZSS compression but uniquely has **NO 44-byte header** - only 10 zero bytes.

**Key Statistics:**
- **Decompressed size:** 32,768 bytes (exactly 32 KB)
- **Compressed size:** 2,150 bytes (matches Block 3 Region 4's declared size)
- **Header:** 10 bytes (all zeros) - NO 44-byte header (unique among full-format blocks)
- **Format:** Full format (4-byte type hashes) - NOT compact format
- **PhysicalInventoryItem entries:** 364
- **PropertyReference entries:** 364 (Format 1 items only)
- **Format 1 (Simple) items:** 182 (66-71 bytes each)
- **Format 2 (Container) items:** 182 (22-1,402 bytes each)

### Total Byte Distribution

| Format | Count | Total Bytes | Percentage |
|--------|-------|-------------|------------|
| Format 1 | 182 | 12,381 | 37.8% |
| Format 2 | 182 | 20,306 | 62.0% (containers) |
| Header | 1 | 10 | 0.0% |
| Padding | - | 71 | 0.2% |
| **Total** | **364** | **32,768** | **100%** |

## Block Structure

```
Offset    | Size    | Description
----------|---------|------------------------------------------
0x0000    | 10      | Header (all zeros - no count field, NO 44-byte header)
0x000A    | varies  | PhysicalInventoryItem array (364 entries, interleaved formats)
          |         | Items end at 0x7FFF (block boundary)
```

**Key Discovery:** Block 4 is the only full-format block without a 44-byte header. Unlike Blocks 1 and 2 which have headers with Field3 markers (0xCD and 0xCAFE00 respectively), Block 4 has only the standard 10-byte null prefix before item data.

## Item Formats

Block 4 contains two distinct item formats, identified by bytes 4-5 after the type hash:

### Format 1: Simple Stackable Items (0x32 marker)

Used for stackable items with PropertyReference binding. Size ranges from 66-71 bytes.

**Format Detection:** Check 2 bytes at offset +04 from type hash:
- `0x0032` = Format 1 (simple stackable)

```
Offset | Size | Description
-------|------|-----------------------------------------------------
+0x00  | 4    | Type Hash: 0xA1A85298 (PhysicalInventoryItem)
+0x04  | 2    | Format marker: 0x0032 (50 decimal)
+0x06  | 2    | Padding: 0x0000
+0x08  | 4    | Quantity: 0x0000002A (always 42 - max stack size)
+0x0C  | 4    | Field marker: 0x00000011
+0x10  | 4    | Property hash 1: 0xBF298A20
+0x14  | 4    | Property hash 2: 0xC69075AB
+0x18  | 2    | Padding: 0x0000
+0x1A  | 1    | Prefix: 0x12
+0x1B  | 2    | Padding + TYPE_REF marker: 0x00 0x0B
+0x1D  | 4    | Item ID Hash (VARIES - identifies specific game item)
+0x21  | 4    | Field marker: 0x00000011
+0x25  | 4    | PropertyReference hash: 0x0984415E
+0x29  | 4    | PropertyReference hash (repeated): 0x0984415E
+0x2D  | 2    | Padding: 0x0000
+0x2F  | 1    | Prefix: 0x12
+0x30  | 2    | Padding + TYPE_REF marker: 0x00 0x0B
+0x32  | var  | Trailing zeros (padding to size boundary)
```

**Size Distribution:**
- 69 bytes: 145 items (most common)
- 66 bytes: 36 items
- 71 bytes: 1 item

**Total Format 1 bytes:** 12,381 bytes across 182 items

### Format 2: Container Objects (0x00 marker)

**Key Discovery:** Format 2 items are **CONTAINER/COLLECTION objects** that hold nested PhysicalInventoryItem entries, not simple inventory items like Format 1. They represent equipped weapons, armor sets, quest items, and crafting bundles.

**Format Detection:** Check 2 bytes at offset +04 from type hash:
- `0x0000` = Format 2 (container/collection)

#### Base Structure (22-byte minimum)

```
Offset | Size | Description
-------|------|-----------------------------------------------------
+0x00  | 4    | Type Hash: 0xA1A85298 (PhysicalInventoryItem)
+0x04  | 2    | Format Marker: 0x0000 (identifies Format 2)
+0x06  | 2    | Capacity Field: 0x0A1D (constant = 2589)
+0x08  | 2    | Flags/Version: 0x010B (constant)
+0x0A  | 2    | Reserved: 0x0000
+0x0C  | 4    | Container type marker (0x41004867 or 0x90776BBF)
+0x10  | 4    | Metadata/Count field
+0x14  | 2    | Padding/reserved
```

Extended Format 2 items (>22 bytes) contain nested PhysicalInventoryItem entries after the 22-byte header.

#### Container Type Markers

| Hash | Location | Meaning |
|------|----------|---------|
| 0x41004867 | +0x0C (22-byte items) | Empty container type |
| 0x90776BBF | +0x0C (158+ byte items) | Complex item type (weapons/armor) |

#### Item Count Field Discovery

Byte at offset +0x10 correlates with nested item count:

| Value | Meaning |
|-------|---------|
| 0x00 | Empty container |
| 0x01 | 1 item variant |
| 0x03 | 3 nested items |
| 0x04 | 4 nested items |
| 0x0E | 14 nested items |
| 0x14 | 20 nested items |

#### Size Distribution (182 Format 2 items)

| Size | Count | Content |
|------|-------|---------|
| 22 bytes | 55 | Empty containers - header only |
| 25 bytes | 36 | Minimal containers with 3 bytes metadata |
| 91 bytes | 15 | ~1 nested item |
| 158 bytes | 84 | 1-2 nested items |
| 160 bytes | 4 | Variant of 158-byte format |
| 229 bytes | 2 | Larger containers |
| 298 bytes | 3 | Multi-item containers |
| 367-1,402 bytes | 13 | Complex containers with multiple nested items |

**Total Format 2 bytes:** 20,306 bytes across 182 items

#### Largest Container Analysis (1,402 bytes at offset 0x12BD)

The largest container demonstrates the nested structure:

- **Size:** 1,402 bytes
- **Contains:** 21 nested PhysicalInventoryItem entries
- **Entry 0:** Format 2 wrapper (marker 0x0000)
- **Entries 1-20:** Format 1 items (marker 0x0032)
- **All 20 Format 1 items share ITEM_ID_HASH:** 0xAFD4F6F3 (Florins currency)
- **Spacing:** 69-byte intervals between Format 1 entries
- **Pattern:** 20 items x 69 bytes + 22-byte wrapper = 1,402 bytes

This container represents a "stack bundle" - a single container holding 20 Florin stacks (each stack = 42 Florins, total = 840 Florins).

#### Why Format 2 Items Lack PropertyReference

| Format | PropertyReference Binding | Mechanism |
|--------|---------------------------|-----------|
| Format 1 | 1:1 per-item (182 total) | Direct embedded binding |
| Format 2 | Category-level only (3 in Block 5) | Container-level binding |

Nested Format 1 items within Format 2 containers have their own individual PropertyReference bindings. The Format 2 container itself only needs category-level bindings.

#### Game Item Categories by Format

**Format 2 containers likely represent:**
- Equipped weapons (complex objects with stats)
- Armor sets (multiple properties)
- Quest items (internal state tracking)
- Crafting bundles (multiple nested items)
- Currency bundles (Florin stacks)

**Format 1 items (simple stackable):**
- Currency (individual Florin stacks)
- Consumables
- Ammunition
- Throwables

## Item Identification System

**Primary Identifier:** ITEM_ID_HASH - 4-byte little-endian value at offset +0x1D from each Format 1 item's start.

This hash uniquely identifies the specific game item type (e.g., Florins, Smoke Bombs, Throwing Knives).

### Inventory Composition Summary

- **Total items:** 364 (182 Format 1 + 182 Format 2)
- **Unique item ID hashes:** 30 distinct values
- **Most common:** 0xAFD4F6F3 (68 occurrences) - likely Florins (currency)

## Complete Item ID Hash Reference

All 30 unique item ID hashes found in Block 4:

| Item ID Hash | Count | Likely Category |
|--------------|-------|-----------------|
| 0xAFD4F6F3 | 68 | Currency (Florins) |
| 0x1BE2AFD6 | 6 | Weapon variant 1 |
| 0x1BE2AFD7 | 6 | Weapon variant 2 |
| 0x1BE2AFD8 | 6 | Weapon variant 3 |
| 0x55308E7F | 5 | Consumable type 1 |
| 0x55308E80 | 4 | Consumable type 2 |
| 0x55308E81 | 4 | Consumable type 3 |
| 0x55308E82 | 4 | Consumable type 4 |
| 0x55308E83 | 6 | Consumable type 5 |
| 0x55308EA5 | 4 | Consumable type 6 |
| 0x55308EA6 | 4 | Consumable type 7 |
| 0x55308EA7 | 4 | Consumable type 8 |
| 0x55308EA8 | 3 | Consumable type 9 |
| 0x55308EA9 | 4 | Consumable type 10 |
| 0x6621BE50 | 6 | Equipment item 1 |
| 0x6621BE58 | 6 | Equipment item 2 |
| 0x77AB5B4C | 5 | Equipment item 3 |
| 0x784EC410 | 4 | Equipment item 4 |
| 0x784ECD82 | 2 | Equipment item 5 |
| 0x7F3D48A7 | 4 | Special item 1 |
| 0xBF4D4478 | 4 | Special item 2 |
| 0x9F836382 | 6 | Special item pair 1 |
| 0x9F836387 | 3 | Special item pair 2 |
| 0x61D961DE | 3 | Quest item pair 1 |
| 0x61D961DF | 3 | Quest item pair 2 |
| 0x26740BA6 | 4 | Unknown/Craft item |
| 0x2E0957F8 | 1 | Ammunition type 1 |
| 0x2E095807 | 1 | Ammunition type 2 |
| 0x2E095821 | 1 | Ammunition type 3 |
| 0x2E095837 | 1 | Ammunition type 4 |

## Item Categories by Hash Pattern

| Category | Hash Pattern | Count | Examples |
|----------|--------------|-------|----------|
| Currency | 0xAFD4F6F3 | 68 | Florins (68 x 42 = 2,856 total) |
| Consumables | 0x55308E7F-EA9 | 10 types | Smoke Bombs, Medicine, Throwing Knives |
| Weapons | 0x1BE2AFD6-8 | 3 variants | Sword/weapon variants |
| Equipment | 0x6621BE50/58 | 2 types | Armor pieces |
| Ammunition | 0x2E0957F8-837 | 4 types | Crossbow bolts, throwing knives |

### Hash Pattern Analysis

| Prefix | Item IDs | Likely Category |
|--------|----------|-----------------|
| 0x1B | 0x1BE2AFD6, 0x1BE2AFD7, 0x1BE2AFD8 | 3 weapon variants (sequential hashes) |
| 0x2E | 0x2E0957F8, 0x2E095807, 0x2E095821, 0x2E095837 | 4 ammunition types (sequential) |
| 0x55 | 0x55308E7F-0x55308EA9 (10 items) | Consumables cluster |
| 0x61 | 0x61D961DE, 0x61D961DF | Related pair (quest items?) |
| 0x66 | 0x6621BE50, 0x6621BE58 | Related pair (equipment) |
| 0x77 | 0x77AB5B4C | Weapon/armor (single) |
| 0x78 | 0x784EC410, 0x784ECD82 | Weapons/armor pair |
| 0x7F | 0x7F3D48A7 | Special item (single) |
| 0x9F | 0x9F836382, 0x9F836387 | Related pair (special) |
| 0xAF | 0xAFD4F6F3 | Currency (68 occurrences - highest count) |
| 0xBF | 0xBF4D4478 | Special item (single) |

### Top Item IDs by Frequency

| Item ID | Count | Notes |
|---------|-------|-------|
| 0xAFD4F6F3 | 68 | Most common - currency (Florins) |
| 0x9F836382 | 6 | Special item pair 1 |
| 0x1BE2AFD6 | 6 | Weapon variant 1 |
| 0x1BE2AFD7 | 6 | Weapon variant 2 |
| 0x1BE2AFD8 | 6 | Weapon variant 3 |
| 0x6621BE58 | 6 | Equipment item 2 |
| 0x6621BE50 | 6 | Equipment item 1 |
| 0x55308E83 | 6 | Consumable type 5 |

## Item Interleaving Pattern

**Critical Discovery:** Format 1 and Format 2 items are **interleaved throughout the block**, not stored in separate regions. Analysis shows 72 format transitions with varying run lengths:

- Format 1 runs: 1-20 items
- Format 2 runs: 2-18 items

This interleaving is likely based on item acquisition order or internal categorization, not format type.

## TYPE_REF Pattern

The marker byte `0x0B` appears 369 times in Block 4 data, indicating object references in the deserialization stream.

**Pattern:** `12 00 0B [4-byte hash]`

This is consistent with the TYPE_REF dispatcher (FUN_01af6a40) which routes based on prefix bytes.

## Type Hashes Used

| Hash | Type Name | Count | Usage |
|------|-----------|-------|-------|
| 0xA1A85298 | PhysicalInventoryItem | 364 | Item entry marker |
| 0x0984415E | PropertyReference | 182 | Property binding (Format 1 only) |
| 0xBF298A20 | Unknown | 182 | Property hash 1 (Format 1) |
| 0xC69075AB | Unknown | 182 | Property hash 2 (Format 1) |

## Hex Dump Examples

### Format 1 Item (69 bytes)
```
000a: 98 52 a8 a1 32 00 00 00 2a 00 00 00 11 00 00 00
001a: 20 8a 29 bf ab 75 90 c6 00 00 12 00 0b f3 f6 d4
002a: af 11 00 00 00 5e 41 84 09 5e 41 84 09 00 00 12
003a: 00 0b 00 00 00 00 00 00 00 00 00 00 00 00 00 00
004a: 00 00 00 00 00
```

### Format 2 Item (22 bytes - minimal)
```
02b2: 98 52 a8 a1 00 00 1d 0a 0b 01 00 00 00 00 12 00
02c2: 00 00 67 48 00 41
```

### Format 2 Item (158 bytes - complex)
```
00d6: 98 52 a8 a1 00 00 1d 0a 0b 01 00 00 00 00 11 00
00e6: 00 00 bf 6b 77 90 00 00 00 00 00 00 07 00 0b 00
00f6: 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
0106: 00 00 91 75 8b 6d 2b 01 00 00 23 01 00 00 15 00
0116: 00 00 97 7b 3a ff af cc 99 25 00 00 19 00 0b 02
0126: 00 00 00 a8 6a 4b 04 11 00 00 00 4f d4 f7 6a 00
0136: 00 00 00 00 00 07 00 0b 00 00 00 00 11 00 00 00
0146: 12 99 7b f7 00 00 00 00 00 00 07 00 0b 00 00 00
0156: 00 11 00 00 00 24 c9 7e c8 00 00 00 00 00 00 07
0166: 00 0b d7 71 d6 5f 9c 00 00 00 b8 57 f2 b7
```

## Cross-Block Reference (Block 3 -> Block 4)

Block 3 Region 4 serves as a **cross-block reference descriptor** that points to Block 4:

| Field | Block 3 Region 4 | Block 4 |
|-------|------------------|---------|
| Declared size | 2,150 bytes | N/A |
| Compressed size | N/A | **2,150 bytes** (exact match) |
| Actual region data | 5 bytes | 32,768 bytes |
| Descriptor bytes | `00 27 a6 62 20` | Full inventory data |

**Key insight:** Block 3 doesn't duplicate inventory data - it references Block 4. The declared size field encodes the external block's compressed size.

## PropertyReference Binding Pattern - DECODED

### Double-Hash Pattern

Block 4 Format 1 items exhibit a **double-hash pattern** where hash 0x0984415E (PropertyReference) appears twice consecutively:

```
+0x25  | 4    | PropertyReference hash: 0x0984415E
+0x29  | 4    | PropertyReference hash (repeated): 0x0984415E
```

This double-hash pattern appears in **all 182 Format 1 items** and serves as a binding marker.

### Distribution Summary

| Format | Item Count | PropertyRef Count | Binding Ratio |
|--------|------------|-------------------|---------------|
| Format 1 | 182 | 182 | 1:1 (every item) |
| Format 2 | 182 | 0 | No bindings |
| **Total** | **364** | **182** | 50% |

### Property Hashes in Binding

Each Format 1 PropertyReference entry contains two property hashes:

| Hash | Purpose |
|------|---------|
| 0xBF298A20 | Property hash 1 (item category?) |
| 0xC69075AB | Property hash 2 (item state?) |

These hashes appear at offsets +0x10 and +0x14 within every Format 1 item.

### Cross-Block Architecture

Block 4's 182 PropertyReferences connect to Block 5:

| Block | Count | Format | Purpose |
|-------|-------|--------|---------|
| Block 2 | 21 | 65-byte entries | Game state bindings |
| **Block 4** | **182** | **Double-hash pairs** | **1:1 Format 1 item binding** |
| Block 5 | 3 | Judy Array embedded | Compact format bindings |
| **Total** | **206** | | |

**Key Finding:** Block 5 stores the PropertyReference bindings for Block 4 inventory items. The 3 PropertyReferences in Block 5 may represent category-level bindings, while Block 4 stores per-item bindings.

---

## Notes

1. **1:1 PropertyReference Binding**: Each Format 1 PhysicalInventoryItem has exactly one PropertyReference (double-hash pattern). Format 2 items do not have PropertyReferences in their base structure.

2. **Block Boundary**: The last item ends exactly at the 32KB boundary. The final bytes `98 52` are the start of what would be another PhysicalInventoryItem hash, but the block is truncated.

3. **Full Format Without 44-Byte Header**: Block 4 is unique - it uses full format (type hashes) but only has 10 zero bytes header, not the 44-byte header seen in Blocks 1 and 2.

4. **Quantity Field**: All Format 1 items have quantity=42 (0x2A), likely the maximum stack size or a default value.

5. **Format 2 Container Structure**: Format 2 items are container objects that hold nested PhysicalInventoryItem entries. The largest container (1,402 bytes) holds 20 nested Format 1 Florin stacks. Container type markers (0x41004867 for empty, 0x90776BBF for complex) identify container category.

6. **Field Markers**: The value 0x11 (17 decimal) appears frequently as a field marker/delimiter in both formats.

7. **Largest Container**: The 1,402-byte Format 2 container holds 20 nested Format 1 Florin stacks (21 total PhysicalInventoryItem entries including the wrapper).

8. **Reference ID = 0x00000000**: All PropertyReferences in Block 4 use zero reference IDs, matching the embedded metadata pattern seen in Blocks 2 and 5.

## Related Files

- Source: `ACBROTHERHOODSAVEGAME0.SAV` (Block 4)
- Decompressed: `/tmp/block4_analysis/sav_block4_decompressed.bin`
- Parser: `/mnt/f/ClaudeHole/assassinscreedsave/sav_parser.py`

## Block Format Comparison

| Block | Format | Header | Compression | Size (decomp.) | Content |
|-------|--------|--------|-------------|----------------|---------|
| 1 | Full | 44-byte (0xCD) | LZSS | 283 bytes | SaveGame root |
| 2 | Full | 44-byte (0xCAFE00) | LZSS | 32 KB | Game state |
| 3 | Compact | None | None | 7.9 KB | World metadata |
| **4** | **Full** | **10 zeros only** | **LZSS** | **32 KB** | **Inventory (364 items)** |
| 5 | Compact | None | None | 6.3 KB | PropertyReference data |

## Key Discoveries Summary

1. **Full format without 44-byte header** - Block 4 uses full format (type hashes) but only has 10 zero bytes header (unique among full-format blocks)
2. **Interleaved item formats** - Format 1 and Format 2 items are mixed throughout, not separated into regions
3. **Quantity=42 for all Format 1 items** - Likely max stack size or default value
4. **Format 2 = Container objects** - Hold nested PhysicalInventoryItem entries (weapons, armor, currency bundles)
5. **Largest container: 1,402 bytes** - Holds 20 nested Florin stacks (21 total entries)
6. **1:1 PropertyReference binding** - Each Format 1 item has exactly one PropertyReference
7. **Cross-block size encoding** - Block 3 Region 4's declared size (2,150) matches Block 4's compressed size exactly

## Item ID Hash to Game Item Mapping Status

**Current Status: PARTIAL** - Structure decoded, exact item names require empirical testing

### What We Know

- **30 unique item ID hashes** have been extracted and categorized
- **Categories identified** by hash pattern analysis (currency, consumables, weapons, etc.)
- **ITEM_ID_HASH location:** Offset +0x1D in Format 1 items (within TYPE_REF pattern)

### Methods to Complete Mapping (Future Work)

1. **Cheat Engine In-Game Testing**
   - Edit quantity values at known offsets
   - Observe UI changes to identify item types
   - Match hash to displayed item name

2. **ACBSP.exe String Analysis**
   - Extract item name strings from executable
   - Compute hashes using game's algorithm
   - Match computed hashes to extracted values

3. **Ghidra Item Factory Analysis**
   - Trace `FUN_01AEB020` (object creator by type hash)
   - Follow item initialization code paths
   - Extract item metadata from static data tables

4. **Multiple Save File Comparison**
   - Create saves at different game progress points
   - Compare item hash populations
   - Correlate with known inventory changes

## Future Research

1. ~~Map Item ID hashes to actual AC Brotherhood inventory items~~ **PARTIAL** - 30 hashes extracted, names need empirical mapping
2. ~~Decode Format 2 embedded object structure~~ **COMPLETE** - Container objects with nested PhysicalInventoryItem entries
3. Understand the relationship between quantity and item stacking
4. Investigate the continuation reference in Block 5 (contains 1 PhysicalInventoryItem)
5. Map container type markers (0x41004867, 0x90776BBF) to specific game item categories
6. Decode the 158-byte complex item internal structure (weapons/armor properties)
