# Block 1: SaveGame Root Structure

> **Note (July 2026):** the Block 1 analysis in this document is valid. Any
> mentions of "Block 3"/"Block 5" use the deprecated 5-block naming — those
> are LZSS-compressed frames, and claims about their raw "compact format"
> content were compression artifacts. See SAV_BLOCKS_OVERVIEW.md.

## Overview

Block 1 is the root/entry point block for Assassin's Creed Brotherhood save files. It contains the top-level `SaveGame` object which references all other save data.

| Property | Value |
|----------|-------|
| **Compressed Size** | ~173 bytes |
| **Decompressed Size** | 283 bytes (0x11B) |
| **Compression** | LZSS (standard SAV format) |
| **Root Object** | SaveGame (0xBDBE3B52) |

## Block Layout

```
Block 1 (283 bytes):
+----------+----------+-------------------------------------------+
| Offset   | Size     | Description                               |
+----------+----------+-------------------------------------------+
| 0x00     | 10 bytes | Header (zero padding)                     |
| 0x0A     | 12 bytes | Type Descriptor (SaveGame entry)          |
| 0x16     | 261 bytes| SaveGame Properties                       |
| 0x117    | 4 bytes  | Footer (trailing zeros)                   |
+----------+----------+-------------------------------------------+
```

## Complete Field Map

### Header (0x00-0x09) - 10 bytes

```
Offset  Bytes                      Description
------  -------------------------  ---------------------------------
0x00    00 00 00 00 00 00 00 00   Block alignment padding
0x08    00 00                      Continued padding
```

All 10 bytes are zeros. This appears to be standard block initialization/alignment.

### Type Descriptor (0x0A-0x15) - 12 bytes

```
Offset  Bytes        Field              Value/Description
------  -----------  -----------------  ----------------------------------
0x0A    52 3B BE BD  Type Hash          0xBDBE3B52 (SaveGame)
0x0E    09 01 00 00  Object ID          265 (0x00000109)
0x12    01 01 00 00  Flags/Version      0x00000101
```

| Field | Size | Value | Description |
|-------|------|-------|-------------|
| Type Hash | 4 bytes | 0xBDBE3B52 | Identifies this as a SaveGame object |
| Object ID | 4 bytes | 265 | Unique identifier for this object instance |
| Flags | 4 bytes | 0x00000101 | Version or capability flags (binary: 00000001 00000001) |

### Properties (0x16-0x116)

SaveGame has 12 documented properties. This block contains serialized values for 10+ properties with various data types.

#### Property Encoding Format

**Standard uint32 Property (21 bytes):**
```
11 00 00 00           Property marker
[prop_hash:4]         Property hash (little-endian)
00 00 00 00 00 00     6-byte padding
07 00 0b              Type marker (0x07 = uint32)
[value:4]             Value (little-endian)
```

**Object Reference Property (17 bytes):**
```
11 00 00 00           Property marker
[prop_hash:4]         Property hash
[type_hash:4]         Expected type hash (e.g., World)
00 00                 2-byte padding
12 00 0b              Type marker (0x12 = object_ref)
[object_id:4]         Referenced object ID (0 = null)
```

**String Property (variable length):**
```
[prop_hash:4]         Property hash
00 00 00 00 00 00     6-byte padding
1a 00 0b              Type marker (0x1a = string)
[length:4]            String length including null terminator
[string_data]         UTF-8 string with null terminator
```

### Property List

| # | Offset | Property Hash | Type | Value | Notes |
|---|--------|---------------|------|-------|-------|
| 0 | 0x16 | 0x70A1EA5F | uint32 | 22 | Unknown purpose |
| 1 | 0x2B | 0x2578300E | uint32 | 0x00FEDBAC (16702380) | Unknown (magic number?) |
| 2 | 0x40 | 0xF5C71F6B | uint32 | 6 | Unknown |
| 3 | 0x55 | 0xBB6621D2 | uint32 | 0x00055E0F (351759) | Unknown |
| 4 | 0x6A | 0x28550876 | uint32 | 0 | Unknown |
| 5 | 0x7F | 0x34032BE4 | embedded | 14 | Embedded object data |
| 6 | 0x95 | 0x78BD5067 | string | "Desmond" | Player name |
| 7 | 0xAE | 0x7111FCC2 | object_ref | 0x8DAC4763 | World reference |
| 8 | 0xC3 | 0x6C448E95 | object_ref | 0x00000000 | SaveGameDataObject (null) |
| 9 | 0xD8 | 0xEB76C432 | uint32 | 1 | Unknown |
| 10 | 0xED | 0x28F5132B | uint32 | 0 | Unknown |
| 11 | 0x102 | 0x8C00191B | uint32 | 0x64B82027 | Unknown (possible timestamp/hash) |

### Footer (0x117-0x11A) - 4 bytes

```
Offset  Bytes        Description
------  -----------  ---------------------------------
0x117   00 00 00 00  Trailing zero padding
```

## Cross-Block References

### World Reference (Property 7)

| Field | Value |
|-------|-------|
| Property Hash | 0x7111FCC2 |
| Expected Type | World (0xFBB63E47) |
| Object ID | 0x8DAC4763 |

The Object ID 0x8DAC4763 references the World object which contains:
- Level/mission state
- Player position
- Environment data

**Verified location**: The World object is serialized in **Block 2** at offset 0x021F, where the object ID 0x8DAC4763 appears with the World type hash nearby at offsets 0x0212 and 0x0216.

### SaveGameDataObject Reference (Property 8)

| Field | Value |
|-------|-------|
| Property Hash | 0x6C448E95 |
| Expected Type | SaveGameDataObject (0x5FDACBA0) |
| Object ID | 0x00000000 |

This is a **null reference** - no SaveGameDataObject is currently linked. When populated, this would contain:
- Mission save data
- Checkpoint information
- Progress markers

## Type System

### Type Codes

| Code | Type | Description |
|------|------|-------------|
| 0x07 | uint32 | 32-bit unsigned integer |
| 0x0B | marker | Part of type encoding sequence |
| 0x11 | property_marker | Indicates start of property |
| 0x12 | object_ref | Object reference/pointer |
| 0x1A | string | UTF-8 string with length prefix |

### Known Type Hashes in Block 1

| Hash | Type Name | Occurrence |
|------|-----------|------------|
| 0xBDBE3B52 | SaveGame | Root object (offset 0x0A) |
| 0xFBB63E47 | World | Reference type (offset 0xB6) |
| 0x5FDACBA0 | SaveGameDataObject | Reference type (offset 0xCB) |

## Hex Dump

```
0000: 00 00 00 00 00 00 00 00 00 00 52 3b be bd 09 01  |..........R;....|
0010: 00 00 01 01 00 00 11 00 00 00 5f ea a1 70 00 00  |.........._..p..|
0020: 00 00 00 00 07 00 0b 16 00 00 00 11 00 00 00 0e  |................|
0030: 30 78 25 00 00 00 00 00 00 07 00 0b ac db fe 00  |0x%.............|
0040: 11 00 00 00 6b 1f c7 f5 00 00 00 00 00 00 07 00  |....k...........|
0050: 0b 06 00 00 00 11 00 00 00 d2 21 66 bb 00 00 00  |..........!f....|
0060: 00 00 00 07 00 0b 0f 5e 05 00 11 00 00 00 76 08  |.......^......v.|
0070: 55 28 00 00 00 00 00 00 07 00 0b 00 00 00 00 0e  |U(..............|
0080: 00 00 00 e4 2b 03 34 00 00 00 00 00 00 00 00 0b  |....+.4.........|
0090: 00 19 00 00 00 67 50 bd 78 00 00 00 00 00 00 1a  |.....gP.x.......|
00a0: 00 0b 07 00 00 00 44 65 73 6d 6f 6e 64 00 11 00  |......Desmond...|
00b0: 00 00 c2 fc 11 71 47 3e b6 fb 00 00 12 00 0b 63  |.....qG>.......c|
00c0: 47 ac 8d 11 00 00 00 95 8e 44 6c a0 cb da 5f 00  |G........Dl..._.|
00d0: 00 12 00 0b 00 00 00 00 11 00 00 00 32 c4 76 eb  |............2.v.|
00e0: 00 00 00 00 00 00 07 00 0b 01 00 00 00 11 00 00  |................|
00f0: 00 2b 13 f5 28 00 00 00 00 00 00 07 00 0b 00 00  |.+..(...........|
0100: 00 00 11 00 00 00 1b 19 00 8c 00 00 00 00 00 00  |................|
0110: 07 00 0b 27 20 b8 64 00 00 00 00                 |...' .d....|
```

## Notable Findings

### Player Name Storage

The player name "Desmond" is stored at offset 0xA6 as a 7-character UTF-8 string with null terminator. This appears to be hardcoded for the Assassin's Creed Brotherhood storyline character.

**String encoding:**
- Property hash: 0x78BD5067
- Length prefix: 7 (including null? or 8 with null)
- Data: `44 65 73 6d 6f 6e 64 00` = "Desmond\0"

### Embedded Object (0x7F-0x94)

Between properties 4 and 6, there's an embedded structure at offset 0x7F:
```
0x7F: 0e 00 00 00        Value: 14
0x83: e4 2b 03 34        Type hash: 0x34032BE4
0x87: 00 00 00 00 00...  Padding/data
```

This appears to be an inline object serialization with type hash 0x34032BE4 (unknown type).

### Null References

The SaveGameDataObject reference (property 8) is null (Object ID = 0x00000000), indicating this data structure is not populated in this save file.

## Relationship to Other Blocks

| Block | Relationship |
|-------|--------------|
| Block 2 | **Contains World object** data at offset 0x021F (verified) |
| Block 3 | Compact format - may contain additional type metadata |
| Block 4 | May contain additional World/SaveGameDataObject data |
| Block 5 | Compact format - may contain type references |

### Block 2 World Object Reference

The World object ID 0x8DAC4763 from Block 1 property 7 is found in Block 2:
```
Block 2 offset 0x021F: 63 47 ac 8d (object ID in little-endian)
Block 2 offset 0x0212: World type hash 0xFBB63E47
Block 2 offset 0x0216: World type hash 0xFBB63E47 (repeated)
```

Context around the reference:
```
0212: 3e b6 fb 00 00 12 00 0b 63 47 ac 8d de 00 00 00  |>.......cG......|
      ^^^^^^^^^^                ^^^^^^^^^^^
      World hash                Object ID
```

## Size Fields (Must Update When Name Changes)

When modifying the player name, three internal size fields must be adjusted by the difference in name length:

| Offset | Size | Description | Example (7→4 char) |
|--------|------|-------------|-------------------|
| 0x0E | 1 byte | Object size field | 0x09 → 0x06 (-3) |
| 0x12 | 2 bytes (LE) | Block size field | 257 → 254 (-3) |
| 0x91 | 1 byte | Nested size field | 0x19 → 0x16 (-3) |

**Critical**: Failure to update these fields causes the game to crash on load.

### Size Field Adjustment Formula

```python
length_diff = new_name_length - old_name_length

# Single-byte fields
block1[0x0E] += length_diff
block1[0x91] += length_diff

# 2-byte field (little-endian)
old_val = struct.unpack('<H', block1[0x12:0x14])[0]
block1[0x12:0x14] = struct.pack('<H', old_val + length_diff)
```

### Field Details

| Field | Offset | Fresh Value | Notes |
|-------|--------|-------------|-------|
| Object Size | 0x0E | 9 (for "Desmond") | Part of type descriptor |
| Block Size | 0x12-0x13 | 257 (0x0101) | 2-byte LE cumulative size |
| Nested Size | 0x91 | 25 (0x19) | Size of name container |

**Verification**: These fields were identified by comparing working saves with different name lengths. All three change by exactly the name length difference.

## Implementation Notes

1. **Property Marker**: All standard properties begin with `11 00 00 00`
2. **Type Markers**: Format is `TT 00 0B` where TT is the type code
3. **Object References**: Include the expected type hash before the object ID
4. **Byte Order**: All multi-byte values are little-endian
5. **String Encoding**: UTF-8 with 4-byte length prefix and null terminator
6. **Name Changes**: Must update size fields at 0x0E, 0x12, and 0x91

## Property Hash Reference

### Resolved Properties (December 2024)

Hash algorithm confirmed as **CRC32 (zlib.crc32)**. Only 2 of 12 SaveGame properties resolved via string extraction:

| Hash | Field Name | Type | Value | Verified |
|------|-----------|------|-------|----------|
| `0x70A1EA5F` | **Version** | uint32 | 22 | CRC32("Version") |
| `0x78BD5067` | **PlayerName** | string | "Desmond" | CRC32("PlayerName") |

### Unmapped Properties (10 of 12)

Property names are stripped at compile time and cannot be resolved via string matching:

| Hash | Type | Value | Notes |
|------|------|-------|-------|
| `0x2578300E` | uint32 | 0x00FEDBAC | Magic number pattern |
| `0x28550876` | uint32 | 0 | Zero value |
| `0x28F5132B` | uint32 | 0 | Zero value |
| `0x34032BE4` | embedded | 14 | Embedded object type hash |
| `0x6C448E95` | object_ref | 0x00000000 | SaveGameDataObject (null ref) |
| `0x7111FCC2` | object_ref | 0x8DAC4763 | World reference (cross-block) |
| `0x8C00191B` | uint32 | 0x64B82027 | Possible timestamp/hash |
| `0xBB6621D2` | uint32 | 0x00055E0F | Unknown (351759 decimal) |
| `0xEB76C432` | uint32 | 1 | Boolean/flag value |
| `0xF5C71F6B` | uint32 | 6 | Small counter/enum |

### Cross-Block References

Two properties link to other blocks:

| Hash | Target | Block | Object ID |
|------|--------|-------|-----------|
| `0x7111FCC2` | World | Block 2 | 0x8DAC4763 |
| `0x6C448E95` | SaveGameDataObject | Block 2 | 0x00000000 (null) |

### Future Resolution

Property names require alternative discovery methods:
- Type Descriptor Table at Ghidra VA `0x027E0638`
- Dynamic analysis via Cheat Engine value modification
- Type lookup function `FUN_01AEAD60`
