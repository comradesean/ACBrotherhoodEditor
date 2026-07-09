# Assassin's Creed Brotherhood Type System Reference

This document provides a comprehensive reference to the Scimitar Engine type system used in Assassin's Creed Brotherhood's save files (SAV and OPTIONS). The information was reverse-engineered from ACBSP.exe through Ghidra decompilation and WinDbg time-travel debugging.

> **Note (July 2026):** the executable-derived type system documented here is
> valid. Any mentions of SAV "Block 3"/"Block 5" use the deprecated 5-block
> naming — those are LZSS-compressed frames, and byte-level claims about their
> raw content were compression artifacts. See SAV_BLOCKS_OVERVIEW.md.

## Table of Contents

1. [Overview](#overview)
2. [Type Hierarchy Diagram](#type-hierarchy-diagram)
3. [Type Hash Quick Reference](#type-hash-quick-reference)
4. [Detailed Type Specifications](#detailed-type-specifications)
5. [Key Functions Reference](#key-functions-reference)
   - [Type System Functions](#type-system-functions)
   - [Serializer Helper Functions](#serializer-helper-functions)
   - [Object Serializers](#object-serializers)
   - [PropertyReference Functions](#propertyreference-functions)
   - [Type Table Lookup (FUN_01AEAF70) - Detailed Analysis](#type-table-lookup-fun_01aeaf70---detailed-analysis)
6. [Key Addresses Reference](#key-addresses-reference)
7. [Serialization Formats](#serialization-formats)
8. [Usage in SAV/OPTIONS Files](#usage-in-savoptions-files)

---

## Overview

### Type System Architecture

The Scimitar/AnvilNext engine uses a reflection-based type system with the following characteristics:

- **Hash-Based Identification**: Types are identified by 32-bit hashes rather than string names
- **Hierarchical Inheritance**: Types form an inheritance tree rooted at CommonParent
- **Property Descriptors**: Each type has a list of properties with their own hashes and types
- **Runtime Registration**: Types register themselves during game initialization
- **Dual Descriptor Formats**: Standard type descriptors (marker 0x02000201) and registration tables (name pointer format)

### Engine Context

- **Engine**: Scimitar Engine (evolved into AnvilNext for later AC games)
- **Executable**: ACBSP.exe (main game executable)
- **Type Count**: 900+ total types in the type system
  - 700+ types derive directly from CommonParent
  - 192 types derive from ManagedObject
  - Remaining types are specialized/inline types

---

## Type Hierarchy Diagram

```
CommonParent (0x7E42F87F) - ROOT (0 properties, 786 code refs)
    |
    +-- ManagedObject (0xBB96607D) - Base for managed objects (16-byte base, 31 refs)
    |       |
    |       +-- SaveGame (0xBDBE3B52) - Save file root (12 properties)
    |       |       |
    |       |       +-- World (0xFBB63E47) [property 7, offset 0x28]
    |       |       |       |
    |       |       |       +-- 9x World references (0x130-0x1B0)
    |       |       |       +-- PropertyReference (0x0984415E) [property 9]
    |       |       |       +-- ContainerType (0xA9E0C685) [property 10]
    |       |       |       +-- 3x CollectionType (0x11598A66) [properties 11-13]
    |       |       |
    |       |       +-- SaveGameDataObject (0x5FDACBA0) [property 8, offset 0x2C]
    |       |               |
    |       |               +-- MissionSaveData (0x5ED7B213)
    |       |                       |
    |       |                       +-- SaveGameDataObject [property, offset 0x04]
    |       |                       +-- RewardFault[] (0x12DE6C4C) [array]
    |       |
    |       +-- 192 other managed types
    |
    +-- PropertyReference (0x0984415E) - Property accessor (461 code refs)
    |       |
    |       +-- ValueBind (0x18B8C0DE) - Value binding (26 refs, always paired)
    |       |
    |       +-- LinkBind (0xC0A01091) - Link binding (15 refs, optional)
    |
    +-- SubObject (0xF8206AF7) - Embedded object marker (42 refs)
    |
    +-- AbstractElementBase (0xE9DDD041) - Abstract, no registration
    |       |
    |       +-- PlayerOptionsElement (0x2DAD13E3) - 48 bytes, Table ID 22
    |
    +-- CollectionType (0x11598A66) - Self-referential root (Havok physics)
    |
    +-- ContainerType (0xA9E0C685) - Container/array storage
    |
    +-- 700+ compact serialization types (22 properties each)
        (used in SAV blocks 3 and 5)
```

### Property Types vs Inheritance Types

| Category | Description | Examples |
|----------|-------------|----------|
| **Inheritance Types** | Types in class hierarchy | CommonParent, ManagedObject, SaveGame |
| **Property Types** | Types used in property descriptors | SubObject, PropertyReference, ValueBind |
| **Container Types** | Types for collections/arrays | ContainerType, CollectionType |
| **Primitive Types** | Basic value types | Type hash 0x00000000 = primitive |

---

## Type Hash Quick Reference

### Root/Base Types

| Hash | Name | Refs | Parent | Size | Table ID |
|------|------|------|--------|------|----------|
| `0x7E42F87F` | CommonParent | 786 | SELF (root) | 0 | - |
| `0xBB96607D` | ManagedObject | 31 | CommonParent | 16 bytes | - |

### Save Game Types

| Hash | Name | Refs | Parent | Size | Table ID |
|------|------|------|--------|------|----------|
| `0xBDBE3B52` | SaveGame | 1 | ManagedObject | ~80 bytes | - |
| `0x94D6F8F1` | AssassinSaveGameData | 1 | - | 32 KB | - |
| `0x5FDACBA0` | SaveGameDataObject | 5 | ManagedObject | Variable | - |
| `0x5ED7B213` | MissionSaveData | 3 | - | Variable | - |
| `0x12DE6C4C` | RewardFault | 2 | - | ~16 bytes | - |

### World Types

| Hash | Name | Refs | Parent | Size | Table ID |
|------|------|------|--------|------|----------|
| `0xFBB63E47` | World | 88 | ManagedObject | >848 bytes | 0x20 |

### Inventory Types

| Hash | Name | Refs | Parent | Size | Table ID |
|------|------|------|--------|------|----------|
| `0xA1A85298` | PhysicalInventoryItem | 364 | - | 22-1236 bytes | - |

### Collectible Types

| Hash | Name | Refs | Parent | Size | Table ID |
|------|------|------|--------|------|----------|
| `0x9BD7FCBE` | CollectibleRecord | 157 | - | ~98 bytes | - |
| `0x75758A0E` | CollectibleClass | 157 | - | 18 bytes | - |
| `0x768CAE23` | CollectibleParent | 157 | World | 18 bytes | - |

### Property System Types

| Hash | Name | Refs | Parent | Size | Table ID |
|------|------|------|--------|------|----------|
| `0x0984415E` | PropertyReference | 461 | - | Variable | - |
| `0x18B8C0DE` | ValueBind | 26 | - | Variable | - |
| `0xC0A01091` | LinkBind | 15 | - | Variable | - |
| `0xF8206AF7` | SubObject | 42 | - | 16 bytes | - |

### Container Types

| Hash | Name | Refs | Parent | Size | Table ID |
|------|------|------|--------|------|----------|
| `0xA9E0C685` | ContainerType | 1 | - | Variable | - |
| `0x11598A66` | CollectionType | 0 | SELF (root) | 128 bytes | - |

### OPTIONS Types

| Hash | Name | Refs | Parent | Size | Table ID |
|------|------|------|--------|------|----------|
| `0x1C0637AB` | OPTIONS | 2 | - | 112 bytes | - |
| `0xDCCBD617` | LanguageSettings | - | - | 16 bytes (inline) | - |
| `0x569CD276` | AudioSettings | - | - | 16 bytes (inline) | - |
| `0x9E293373` | VideoSettings | - | - | 16 bytes (inline) | - |

### Player Options Types

| Hash | Name | Refs | Parent | Size | Table ID |
|------|------|------|--------|------|----------|
| `0xCAC5F9B3` | PlayerOptions | 4 | - | 48 bytes | - |
| `0x7879288E` | PlayerOptionsSaveData | 5 | - | 76 bytes | - |
| `0x2DAD13E3` | PlayerOptionsElement | 20 | AbstractElementBase | 48 bytes | 22 |
| `0xE9DDD041` | AbstractElementBase | 0 | CommonParent | - (abstract) | - |

### Compact Format Types (Blocks 3 & 5)

| Hash | Name | Refs | Parent | Size | Table ID |
|------|------|------|--------|------|----------|
| `0x0DEBED19` | CompactType_5E | 63 | CommonParent | 22 props | 0x5E |
| `0xC8761736` | CompactType_5B | 4 | CommonParent | 22 props | 0x5B |
| `0xF49BFD86` | CompactType_4F | 61 | CommonParent | 22 props | 0x4F |
| `0xFC6EDE2A` | CompactType_3B | 1 | CommonParent | 22 props | 0x3B |

### PropertyDataObject Structure

Runtime structure used by PropertyData handlers (16 bytes):

```c
struct PropertyDataObject {
    void* vtable;      // +0x00: 0x025561ec -> 0x01b71d70
    byte  flags;       // +0x04: (param << 2) | 1
    uint  PackedInfo;  // +0x08
    uint  ObjectID;    // +0x0C
};
```

---

## Detailed Type Specifications

### CommonParent (0x7E42F87F)

**The fundamental root type of the Scimitar Engine type system.**

| Field | Value |
|-------|-------|
| Type Hash | `0x7E42F87F` |
| Type Name | Unknown (likely "Object" or "Base") |
| Parent Hash | `0x7E42F87F` (SELF - indicates root) |
| Property Count | 0 (pure base class) |
| Code References | 786 PUSH instructions |
| Direct Derivatives | 700+ types |

**Descriptor Locations:**
- Primary: `0x027E655C` (VA)
- Secondary: `0x0285B504` (contains ManagedObject link at +0x30)

**Key Functions:**
| Function VA | Refs | Purpose |
|-------------|------|---------|
| `0x00CAFCC0` | 131 | Bulk type registration |
| `0x00CAF050` | 104 | Type registration with properties |
| `0x00CADEC0` | 74 | Type registration |
| `0x00CB22B0` | 73 | Type registration |
| `0x00D8ECE0` | 28 | Serialization with type checking |

**Purpose:**
- Universal base type for all game objects
- Provides type identity through hash
- Foundation for serialization framework
- Root of reflection/property system

---

### ManagedObject (0xBB96607D)

**Root base class for all serializable game objects.**

| Field | Value |
|-------|-------|
| Type Hash | `0xBB96607D` |
| Type Name | "ManagedObject" |
| Name String VA | `0x02554AAC` |
| Parent Hash | CommonParent |
| Base Size | 16 bytes |
| Code References | 31 PUSH instructions |
| Data References | 277 type descriptors |
| Derived Types | 192 unique types |

**Base Class Layout:**
| Offset | Size | Purpose |
|--------|------|---------|
| 0x00 | 4 | VTable pointer |
| 0x04 | 4 | Reference count |
| 0x08 | 4 | Object ID |
| 0x0C | 4 | Flags/State |

**Inheritance Registration Function: `FUN_01b17f90`**
```asm
01717390: PUSH EBP
01717391: MOV EBP, ESP
...
017173C5: PUSH 0xBB96607D    ; ManagedObject type hash
017173CA: PUSH 0x00
017173CC: PUSH 0x025556AC    ; Type descriptor pointer
```

**Derived Type Pattern:**
All types deriving from ManagedObject:
1. Call `FUN_01b09e20` to register type name and hash
2. Call `FUN_01b17f90` to register ManagedObject as parent
3. Base class fields (0x00-0x0F) handled by parent serializer
4. Derived properties start at offset 0x10+

---

### SaveGame (0xBDBE3B52)

**Top-level container for game save data.**

| Field | Value |
|-------|-------|
| Type Hash | `0xBDBE3B52` |
| Type Name | "SaveGame" |
| Name String VA | `0x023F0808` |
| Parent Hash | ManagedObject |
| Property Count | 12 |
| Size | ~80 bytes |
| Serializer | `0x005E3560` |
| Deserializer | `0x005E3870` |

**Property Table (0x027ECF54 - 0x027ECF80):**
| Index | Ptr Address | Offset | Serializer | Type | Purpose |
|-------|-------------|--------|------------|------|---------|
| 0 | 0x027ECF54 | 0x10 | FUN_01b0a1f0 | - | uint32 field |
| 1 | 0x027ECF58 | 0x14 | FUN_01b0a1f0 | - | uint32 field |
| 2 | 0x027ECF5C | 0x18 | FUN_01b0a1f0 | - | uint32 field |
| 3 | 0x027ECF60 | 0x1C | FUN_01b0a1f0 | - | uint32 field |
| 4 | 0x027ECF64 | 0x20 | FUN_01b0a1f0 | - | uint32 field |
| 5 | 0x027ECF68 | 0x49 | FUN_01b09650 | - | Boolean (1 byte) |
| 6 | 0x027ECF6C | 0x24 | FUN_01b09980 | - | Special field |
| 7 | 0x027ECF70 | 0x28 | FUN_01b099a0 | 0xFBB63E47 | World reference |
| 8 | 0x027ECF74 | 0x2C | FUN_01b099a0 | 0x5FDACBA0 | SaveGameDataObject |
| 9 | 0x027ECF78 | 0x30 | FUN_01b0a1f0 | - | uint32 field |
| 10 | 0x027ECF7C | 0x34 | FUN_01b0a1f0 | - | uint32 field |
| 11 | 0x027ECF80 | 0x38 | FUN_01b0a1f0 | - | uint32 field |

**Struct Layout:**
```c
struct SaveGame {
    ManagedObject base;         // 0x00-0x0F (16 bytes)
    uint32_t property0;         // 0x10
    uint32_t property1;         // 0x14
    uint32_t property2;         // 0x18
    uint32_t property3;         // 0x1C
    uint32_t property4;         // 0x20
    uint32_t property6_special; // 0x24
    World* world;               // 0x28 - Property 7
    SaveGameDataObject* data;   // 0x2C - Property 8
    uint32_t property9;         // 0x30
    uint32_t property10;        // 0x34
    uint32_t property11;        // 0x38
    uint8_t padding[13];        // 0x3C-0x48
    uint8_t property5_bool;     // 0x49
    uint8_t padding2[2];        // 0x4A-0x4B
    DynamicProps dynamic;       // 0x4C+
};
```

---

### SaveGameDataObject (0x5FDACBA0)

**Mission and save data container.**

| Field | Value |
|-------|-------|
| Type Hash | `0x5FDACBA0` |
| Type Name | "SaveGameDataObject" |
| Name String VA | `0x023F13F4` |
| Parent Hash | ManagedObject |
| Functions Using | 26 unique functions |
| Property Table | `0x027ED428` |

**Struct Offsets Used:**
| Offset | Context | Functions |
|--------|---------|-----------|
| 0x04 | MissionSaveData child | Multiple serializers |
| 0x08 | Nested reference | 0x0097B900, 0x0097BF70 |
| 0x10 | Property reference | 0x00BA88F0, 0x016DB2A0 |
| 0x14 | Property reference | 0x00BA88F0, 0x00CF0BE0 |
| 0x24 | Property reference | 0x005E9F60, 0x00A62260 |
| 0x28 | SaveGame child | 0x0080C020 |
| 0x2C | SaveGame property 8 | 0x005E2960, 0x005E2C70 |
| 0x50 | Array/collection | 0x005E9F60 |
| 0x68 | Property reference | 0x00F893E0, 0x01305870 |

**Purpose:**
- Primary container for mission-related save data
- Contains nested SaveGameDataObject references (hierarchical)
- Stores MissionSaveData objects

---

### MissionSaveData (0x5ED7B213)

**Mission-specific save data storage.**

| Field | Value |
|-------|-------|
| Type Hash | `0x5ED7B213` |
| Type Name | "MissionSaveData" |
| Name String VA | `0x023F0EBC` |
| Property Table | `0x027EE1BC` |
| Serializer | `0x005FCE60` |
| Deserializer | `0x005FD0E0` |

**Property Pointer Addresses:**
- `0x027EE1BC` - SaveGameDataObject reference
- `0x027EE1C0` - Property 1
- `0x027EE1C4` - Property 2
- `0x027EE1C8` - Property 3
- `0x027EE1CC` - Property 4
- `0x027EE1D4` - RewardFault (0x12DE6C4C) array

**Serialization:**
```c
void MissionSaveData_Serialize(MissionSaveData* this, Context* ctx) {
    FUN_01b09e20("MissionSaveData", 0, 0x5ed7b213, ...);
    FUN_01b099a0(0x5fdacba0, this + 0x04, PTR_DAT_027ee1bc);  // SaveGameDataObject
    // Serialize RewardFault array...
}
```

---

### RewardFault (0x12DE6C4C)

**Ubisoft Connect reward/action fault tracking.**

| Field | Value |
|-------|-------|
| Type Hash | `0x12DE6C4C` |
| Type Name | "RewardFault" |
| Name String VA | `0x023F1AE0` |
| Type Descriptor | `0x027ED298` |
| Serializer | `0x005FCB30` |
| Deserializer | `0x005FD0E0` |
| Element Copy | `0x005FD730` |

**Struct Layout:**
```c
struct RewardFault {
    int32_t fault_id;           // +0x00 - Fault condition identifier
    uint8_t fault_data[6];      // +0x04 - Variable fault-specific data
    uint16_t data_count;        // +0x0A - Element count (& 0x3FFF, max 16383)
    uint8_t flag1;              // +0x0C - Status flag
    uint8_t flag2;              // +0x0D - Status flag
    uint8_t flag3;              // +0x0E - Status flag
    uint8_t padding;            // +0x0F
    // Total: ~16 bytes base + variable array
};
```

**Property Descriptor Pointers:**
| Address | Offset | Purpose |
|---------|--------|---------|
| 0x027EE094 | +0x00 | fault_id |
| 0x027EE098 | +0x0C | flag1 |
| 0x027EE09C | +0x0D | flag2 |
| 0x027EE0A0 | +0x0E | flag3 |
| 0x027EE0A4 | +0x04 | array elements |

**Related Fault Types (from .rdata strings):**
- InsufficientTokensToPurchaseRewardFault
- ActionAlreadyCompletedFault
- RewardAlreadyBoughtFault
- InactiveRewardFault
- ServiceFault

**Purpose:**
Part of Ubisoft Connect (formerly Uplay) integration for tracking:
- Reward purchases
- Action completions
- Service faults

---

### World (0xFBB63E47)

**Main world object type for game state.**

| Field | Value |
|-------|-------|
| Type Hash | `0xFBB63E47` |
| Type Name | "World" |
| Name String VA | `0x023E5A68` |
| Parent Hash | ManagedObject |
| Property Count | 14 |
| Table ID | 0x20 |
| Property Table | `0x027E2068` |
| Serializer | `0x004976D0` |

**Property Table:**
| Index | Property Hash | Type Hash | Type Name | Offset | Flags |
|-------|---------------|-----------|-----------|--------|-------|
| 0 | 0x7CABB367 | 0xFBB63E47 | World | 0x0130 | 0x12 |
| 1 | 0xDF921C7A | 0xFBB63E47 | World | 0x0140 | 0x12 |
| 2 | 0xC165012B | 0xFBB63E47 | World | 0x0150 | 0x12 |
| 3 | 0x7EB9BD46 | 0xFBB63E47 | World | 0x0160 | 0x12 |
| 4 | 0xEF15DC37 | 0xFBB63E47 | World | 0x0170 | 0x12 |
| 5 | 0xEAD0AF88 | 0xFBB63E47 | World | 0x0180 | 0x12 |
| 6 | 0xA5C3E279 | 0xFBB63E47 | World | 0x0190 | 0x12 |
| 7 | 0x5CCB24CA | 0xFBB63E47 | World | 0x01A0 | 0x12 |
| 8 | 0x4B5E1234 | 0xFBB63E47 | World | 0x01B0 | 0x12 |
| 9 | 0xE74CB43D | 0x0984415E | PropertyReference | 0x01C0 | 0x12 |
| 10 | 0x86755862 | 0xA9E0C685 | ContainerType | 0x0350 | 0x1D0B |
| 11 | 0xF62F1895 | 0x11598A66 | CollectionType | 0x01D0 | 0x13 |
| 12 | 0xF29FD531 | 0x11598A66 | CollectionType | 0x0250 | 0x13 |
| 13 | 0xF2BCAC14 | 0x11598A66 | CollectionType | 0x02D0 | 0x13 |

**Property Categories:**
- **World References (0-8)**: Self-referential pointers to other World objects (parent, children, linked worlds)
- **PropertyReference (9)**: Property sheet accessor at offset 0x1C0
- **ContainerType (10)**: Dynamic array/container at offset 0x0350
- **CollectionType (11-13)**: Havok physics collision shape collections at 0x80-byte intervals

---

### PropertyReference (0x0984415E)

**Property accessor/reference wrapper.**

| Field | Value |
|-------|-------|
| Type Hash | `0x0984415E` |
| Type Name | Unknown (likely "PropertyRef") |
| Code References | 461 PUSH instructions |
| Property Usages | 72 properties |
| Primary Serializer | `0x00426930` (391 calls) |

**Call Targets:**
| Target | Count | Purpose |
|--------|-------|---------|
| 0x00426930 | 391 | Primary serialization |
| 0x00449360 | 41 | Secondary serialization |
| 0x016F5E40 | 26 | PropertyRef-specific |
| 0x004274A0 | 3 | Type-aware serialization |

**Serialization Pattern:**
```asm
MOV EDX, [property_desc_ptr]    ; Load descriptor
PUSH EDX
LEA EAX, [struct_base + offset] ; Calculate offset
PUSH EAX
PUSH 0x0984415E                 ; PropertyReference hash
MOV ECX, serialize_context
CALL 0x00426930                 ; Main serializer
```

**Purpose:**
- Property access wrapper for reflection
- Enables runtime property access by hash
- Stores reference to property sheets
- Provides type-safe serialization bridge

---

### ValueBind (0x18B8C0DE)

**Property value binding type (always paired with PropertyReference).**

| Field | Value |
|-------|-------|
| Type Hash | `0x18B8C0DE` |
| Type Name | Unknown (likely "ValueBind") |
| Code References | 26 PUSH instructions |
| Always Paired With | PropertyReference |
| Type Descriptor | `0x02866AF0` (self-referential) |

**All 26 uses are paired with PropertyReference:**
- Primary call target: `0x00427530` (24/26 calls)
- Secondary: `0x01B099A0` (2 calls)

**Properties Using ValueBind (14 with hash 0x91737F59):**
| Property Hash | Occurrences | Example Pointer |
|---------------|-------------|-----------------|
| 0x91737F59 | 14 | 0x027DF238 |
| 0x13919750 | 1 | 0x027F880C |
| 0x94C075F4 | 1 | 0x027F8814 |
| (9 others) | 1 each | Various |

**Purpose:**
- Binds property value to PropertyReference
- Type marker for serialization
- Part of tri-type property system

---

### LinkBind (0xC0A01091)

**Property link type (pairs PropertyReference + ValueBind + LinkBind).**

| Field | Value |
|-------|-------|
| Type Hash | `0xC0A01091` |
| Type Name | Unknown (likely "LinkBind") |
| Code References | 15 PUSH instructions |
| Always Paired With | ValueBind |
| Type Descriptor | `0x02804474` (self-referential) |

**All 15 uses also use ValueBind:**
- Call target: `0x00427530` (most calls)
- Always appears after PropertyReference and ValueBind

**Property System Architecture:**
```
PropertyReference (0x0984415E) - Main accessor
    |
    +-- ValueBind (0x18B8C0DE) - Value binding (ALWAYS present)
    |
    +-- LinkBind (0xC0A01091) - Link binding (present in ~60% of cases)
```

---

### SubObject (0xF8206AF7)

**Embedded object marker (property type, not standalone).**

| Field | Value |
|-------|-------|
| Type Hash | `0xF8206AF7` |
| Type Name | SubObject (from CameraTransformableSubObject) |
| Code References | 42 PUSH instructions |
| Property Usages | 38 properties |
| Serializer | `0x004268A0` |
| Default Callback | `0x01BEF950` (16-byte SSE copy) |

**NOT a Standalone Type:**
- No type descriptor with marker 0x02000201
- Used as property type hash in property descriptors
- Indicates property contains inline embedded data

**Property Descriptor Pattern:**
```
+0x00: 0x02000001     - Property marker
+0x04: [prop_hash]    - Property identifier
+0x08: 0xF8206AF7     - SubObject type hash
+0x10: [struct_offset]- Offset in containing struct
+0x14: [flags]        - Serialization flags
```

**Binary Format:**
```
[Type Marker]   - 4 bytes: Type hash of nested object (0 = null)
[Object Data]   - Variable: Handled by callback (typically 16 bytes)
```

**Functions Using SubObject:**
| Function VA | Category | Refs | Purpose |
|-------------|----------|------|---------|
| 0x01BDDBC0 | OPTIONS | 12 | OPTIONS content handler |
| 0x0079F1A0 | World/Entity | 11 | Entity serialization |
| 0x01C15BF0 | Save/Load | 4 | Save serialization |

---

### ContainerType (0xA9E0C685)

**Container/array storage type.**

| Field | Value |
|-------|-------|
| Type Hash | `0xA9E0C685` |
| Type Name | Unknown |
| Usage | World property 10 |
| Code Reference | 1 PUSH at 0x00096E25 |
| Property Descriptor | `0x023E1508` |
| Type Descriptor | `0x023E15E0` |

**World Property 10 Details:**
| Field | Value |
|-------|-------|
| Property Hash | 0x86755862 |
| Struct Offset | 0x0350 (848 bytes) |
| Flags | 0x1D0B (special handling) |

**Type Descriptor (0x023E15DC):**
```
01 00 00 00  ; Marker
85 c6 e0 a9  ; Type Hash
08 00 00 00  ; Size/flags
...
ff 7f ff 7f  ; Sentinel
a0 71 49 00  ; Function pointer
```

---

### CollectionType (0x11598A66)

**Havok physics collection type.**

| Field | Value |
|-------|-------|
| Type Hash | `0x11598A66` |
| Type Name | "CollectionType" |
| Name String VA | `0x021C5EBC` |
| Usage | World properties 11, 12, 13 |
| Type Descriptor | `0x024252D4` (self-referential root) |

**World Properties:**
| Property | Hash | Offset | Size Per Instance |
|----------|------|--------|-------------------|
| 11 | 0xF62F1895 | 0x01D0 | 128 bytes |
| 12 | 0xF29FD531 | 0x0250 | 128 bytes |
| 13 | 0xF2BCAC14 | 0x02D0 | 128 bytes |

**Related Strings (Havok context):**
- COLLECTION_MAX
- COLLECTION_COMPRESSED_MESH
- COLLECTION_MESH_SHAPE
- COLLECTION_SIMPLE_MESH
- COLLECTION_USER

---

### OPTIONS (0x1C0637AB)

**Global game settings type.**

| Field | Value |
|-------|-------|
| Type Hash | `0x1C0637AB` |
| Type Name | OPTIONS |
| Type Descriptor | `0x02991180` |
| Property Count | 21 |
| Fixed Size | 112 bytes (0x70) |
| Serializer | `0x01BE02F0` |
| Deserializer | `0x01BE0370` |

**Property Table (21 Properties):**
| Idx | Property Hash | Type Hash | Offset | Type |
|-----|---------------|-----------|--------|------|
| 0 | 0x3F903A58 | 0xDCCBD617 | 0x0000 | LanguageSettings (16 bytes) |
| 1 | 0x88C1CCB4 | 0x569CD276 | 0x0010 | AudioSettings (16 bytes) |
| 2 | 0xA1B67FD1 | 0x9E293373 | 0x0020 | VideoSettings (16 bytes) |
| 3 | 0xF5E77D32 | 0x00000000 | 0x0030 | uint32 |
| 4 | 0x9244D6CC | 0x00000000 | 0x0034 | uint32 |
| 5 | 0xA4EAD3A8 | 0x00000000 | 0x0038 | uint32 |
| 6 | 0xB165100B | 0x00000000 | 0x003C | uint32 |
| 7 | 0xE618520B | 0x00000000 | 0x0040 | uint32 |
| 8 | 0xC728336B | 0x00000000 | 0x0044 | uint32 |
| 9 | 0x9F59A628 | 0x00000000 | 0x0048 | uint32 |
| 10 | 0x07008481 | 0x00000000 | 0x004C | uint32 |
| 11 | 0x742D7A7F | 0x00000000 | 0x0050 | uint32 |
| 12 | 0xF755EAD7 | 0x00000000 | 0x0054 | uint32 |
| 13 | 0xCA322414 | 0x00000000 | 0x0058 | uint32 |
| 14 | 0x06488902 | 0x00000000 | 0x005C | uint32 (DLC flags at 0x5E bit 2) |
| 15 | 0x21872634 | 0x00000000 | 0x0060 | uint32 |
| 16 | 0x1C314CD7 | 0x00000000 | 0x0064 | uint32 |
| 17 | 0xC193C469 | 0x00000000 | 0x0068 | uint32 |
| 18 | 0x0464997C | 0x00000000 | 0x006C | uint32 |
| 19 | 0xD44391CF | 0x00000000 | 0x0000 | Dynamic |
| 20 | 0x0BA3AD02 | 0x00000000 | 0x0000 | Dynamic |

**Struct Layout:**
```c
struct OPTIONS {
    LanguageSettings property0;    // +0x00 - Type 0xDCCBD617 (16 bytes)
    AudioSettings property1;       // +0x10 - Type 0x569CD276 (16 bytes)
    VideoSettings property2;       // +0x20 - Type 0x9E293373 (16 bytes)
    uint32_t property3;            // +0x30
    // ... properties 4-18 at 4-byte intervals
    uint32_t property14;           // +0x5C - DLC unlock flags
    // ...
    // Dynamic properties 19-20 handled separately
};
```

---

### LanguageSettings (0xDCCBD617)

**Inline type for OPTIONS property 0.**

| Field | Value |
|-------|-------|
| Type Hash | `0xDCCBD617` |
| Parent Type | OPTIONS |
| Offset in OPTIONS | 0x00 |
| Size | 16 bytes |
| String Reference | "Language" at 0x023E17E4 |

**Layout:**
| Offset | Size | Notes |
|--------|------|-------|
| +0x00 | 4 | Unknown (always 0) |
| +0x04 | 4 | Unknown (always 0) |
| +0x08 | 4 | Flags/Settings |
| +0x0C | 4 | Version/Marker (0x0109BDBE typical) |

---

### AudioSettings (0x569CD276)

**Inline type for OPTIONS property 1.**

| Field | Value |
|-------|-------|
| Type Hash | `0x569CD276` |
| Parent Type | OPTIONS |
| Offset in OPTIONS | 0x10 |
| Size | 16 bytes |
| String References | "Audio", "Volume" in .rdata |

**Layout:**
| Offset | Size | Notes |
|--------|------|-------|
| +0x00 | 4 | Volume settings (packed) |
| +0x04 | 4 | Audio flags (boolean options) |
| +0x08 | 4 | Unknown |
| +0x0C | 4 | Unknown |

---

### VideoSettings (0x9E293373)

**Inline type for OPTIONS property 2.**

| Field | Value |
|-------|-------|
| Type Hash | `0x9E293373` |
| Parent Type | OPTIONS |
| Offset in OPTIONS | 0x20 |
| Size | 16 bytes |
| String References | "Video", "Graphics", "Brightness", "ControlSettings" |

**Layout:**
| Offset | Size | Notes |
|--------|------|-------|
| +0x00 | 4 | Unknown |
| +0x04 | 4 | Settings flags |
| +0x08 | 4 | Unknown |
| +0x0C | 4 | Unknown |

---

### PlayerOptions (0xCAC5F9B3)

**Per-save player options (stored in SAV, not OPTIONS file).**

| Field | Value |
|-------|-------|
| Type Hash | `0xCAC5F9B3` |
| Type Name | "PlayerOptions" |
| Name String VA | `0x024C6880` |
| Registration Table | `0x02842600` |
| Size | 48 bytes (0x30) |
| Serializer | `0x00BCA460` |

**Registration Structure:**
```
+0x00: 024C6880  Name pointer -> "PlayerOptions"
+0x04: 00000002  Flags
+0x08: CAC5F9B3  Type hash
+0x0C: 00000030  Size (48 bytes)
+0x20: 7FFF7FFF  Sentinel
+0x24: 00BCA460  Serializer
```

**Property:**
| Index | Hash | Type | Marker | Flags |
|-------|------|------|--------|-------|
| 0 | 0xBF3E20BD | 0x00000000 | Normal | 0x0010 |

**Comparison with OPTIONS:**
| Aspect | OPTIONS | PlayerOptions |
|--------|---------|---------------|
| File | OPTIONS file | SAV file |
| Scope | Global | Per-save |
| Properties | 21 | 1 |
| Size | 112 bytes | 48 bytes |

---

### PlayerOptionsSaveData (0x7879288E)

**Container for player-specific save data options.**

| Field | Value |
|-------|-------|
| Type Hash | `0x7879288E` |
| Type Name | "PlayerOptionsSaveData" |
| Name String VA | `0x024C6890` |
| Registration Table | `0x02842070` |
| Size | 76 bytes (0x4C) |
| Property Count | 10 |
| Serializer | `0x00BC9080` |
| Registration Function | `0x00BC8B00` |

**Property Table:**
| Index | Property Hash | Type Hash | Marker | Flags | Purpose |
|-------|---------------|-----------|--------|-------|---------|
| 0 | 0x2688EEE2 | 0x00000000 | Normal | 0x0010 | Primitive |
| 1 | 0x7BDDD016 | 0x00000000 | Dynamic | 0x0000 | Collection |
| 2 | 0xE8A93814 | 0x2DAD13E3 | Dynamic | 0x0019 | PlayerOptionsElement[] |
| 3 | 0x2EAD62FF | 0x2DAD13E3 | Dynamic | 0x0019 | PlayerOptionsElement[] |
| 4 | 0xD51BD06B | 0x00000000 | Dynamic | 0x000A | Collection |
| 5 | 0xA3BE63D8 | 0x00000000 | Dynamic | 0x000A | Collection |
| 6 | 0x501AF16F | 0x00000000 | Dynamic | 0x000A | Collection |
| 7 | 0x3D40C46A | 0x00000000 | Dynamic | 0x0000 | Collection |
| 8 | 0xC00434A6 | 0x00000000 | Dynamic | 0x000A | Collection |
| 9 | 0x53E72FE6 | 0x00000000 | Dynamic | 0x000A | Collection |

---

### PlayerOptionsElement (0x2DAD13E3)

**Element type for PlayerOptionsSaveData collections.**

| Field | Value |
|-------|-------|
| Type Hash | `0x2DAD13E3` |
| Type Name | PlayerOptionsElement (inferred) |
| Table Index | 22 (0x16) |
| Parent Type | AbstractElementBase (0xE9DDD041) |
| Code References | 20 PUSH instructions |
| Serialized Size | 48 bytes (0x30) |
| In-Memory Size | 88 bytes (0x58) |
| Alignment | 16 bytes |

**Type Descriptor (0x023E0540):**
```
+0x00: 0x02000001  Marker
+0x04: 0x2DAD13E3  Type hash
+0x08: 0x2DAD13E3  Self hash
+0x0C: 0x00190000  Flags
+0x10: 0x00300000  Size = 48 bytes
```

**Registration Entry (0x023E2EE0):**
```
+0x00: 0x0000001C  Marker
+0x04: 0x2DAD13E3  Type hash
+0x08: 0xE9DDD041  Parent (AbstractElementBase)
+0x14: 0x005196D0  Serialize function
+0x18: 0x005196E0  Deserialize function
```

**Serialization Functions:**
| Function | Address | Purpose |
|----------|---------|---------|
| Element Serialize | 0x005196A0 | Single element (allocates 88 bytes) |
| Element Deserialize | 0x005196E0 | Single element |
| Collection Serialize (Prop2) | 0x00BCA690 | Property 2 collection |
| Collection Serialize (Prop3) | 0x00BCA6C0 | Property 3 collection |

---

### AbstractElementBase (0xE9DDD041)

**Abstract parent type for PlayerOptionsElement.**

| Field | Value |
|-------|-------|
| Type Hash | `0xE9DDD041` |
| Type Name | AbstractElementBase (inferred) |
| Self-Registration | NONE (abstract type) |
| Child Types | 1 (PlayerOptionsElement) |
| Code References | 0 |

**Evidence of Abstract Nature:**
- No registration entry where 0xE9DDD041 is the type hash
- No self-referential entries
- Only appears as parent hash for PlayerOptionsElement

**Only 3 occurrences in binary:**
| Location | Context |
|----------|---------|
| 0x023E2EE8 | Parent hash for PlayerOptionsElement |
| 0x023E96BE | Hash table data (false positive) |
| 0x023E97A0 | Parent hash in alternate descriptor |

---

## Key Functions Reference

### Type System Functions

| Address | Name | Description |
|---------|------|-------------|
| `0x01AEAF70` | Type Table Lookup | Looks up type descriptor by table ID |
| `0x00427530` | Serialize Type Reference | Deserializes a typed reference (dual-mode: direct/indirect) |
| `0x004274a0` | Serialize With Custom Func | Serializes with custom function pointer |
| `0x004268A0` | SubObject Serializer | Dispatches SubObject serialization |
| `0x01AF6420` | TYPE_REF Indirect Handler | Wrapper for indirect type resolution via descriptor chain |
| `0x01AE9390` | Type Resolution with Lookup | Resolves type through descriptor chain lookup |
| `0x01B1EEB0` | Tree Map Lookup | Looks up entry by key in tree map structure |
| `0x004253E0` | Assignment Helper | Helper function for type assignment |
| `0x0041DC10` | Cleanup/Destructor | Cleanup function for type handles |

### Serializer Helper Functions

| Address | Name | Description |
|---------|------|-------------|
| `0x01B0A1F0` | Serialize Basic Value | Serializes 4-byte basic types |
| `0x01B09650` | Serialize Boolean | Serializes 1-byte boolean with normalization |
| `0x01B09980` | Serialize Special | Serializes special field type |
| `0x01B099A0` | Serialize Typed Ref | Serializes with type hash (complex objects) |
| `0x01B09620` | Serialize Dynamic | Handles dynamic/variable properties |
| `0x01B0D0C0` | End Serialization | Finalizes object serialization |
| `0x01B17F90` | Register Base Class | Registers parent type (ManagedObject) |
| `0x01B09E20` | Register Type Name | Registers type with name and hash |
| `0x01B09C10` | Serialize Typed Collection | Serializes typed collection |
| `0x01B097A0` | Serialize Dynamic Property | Handles dynamic properties |

### Object Serializers

| Address | Object | Description |
|---------|--------|-------------|
| `0x004976D0` | World | Serializes World objects (9 property refs) |
| `0x005E3560` | SaveGame | Serializes SaveGame (12 properties) |
| `0x005E3870` | SaveGame | Deserializes SaveGame |
| `0x005FCE60` | MissionSaveData | Serializes mission data |
| `0x005FD0E0` | MissionSaveData | Deserializes mission data |
| `0x005FCB30` | RewardFault | Serializes RewardFault |
| `0x005FD730` | RewardFault | Element copy routine |
| `0x01BE02F0` | OPTIONS | Serializes OPTIONS struct |
| `0x01BE0370` | OPTIONS | Deserializes OPTIONS struct |
| `0x00BCA460` | PlayerOptions | Serializes PlayerOptions |
| `0x00BC9080` | PlayerOptionsSaveData | Serializes PlayerOptionsSaveData |
| `0x005196A0` | PlayerOptionsElement | Serializes single element |

### PropertyReference Functions

| Address | Refs | Description |
|---------|------|-------------|
| `0x00426930` | 391 | Primary PropertyReference serializer |
| `0x00449360` | 41 | Secondary PropertyReference serialization |
| `0x016F5E40` | 26 | PropertyReference-specific handler |

### SaveGame I/O System

These functions handle the file-level operations for reading/writing SAV and OPTIONS files. They are separate from content deserialization.

#### SaveGame I/O Address Table

| Function | Ghidra VA | Purpose |
|----------|-----------|---------|
| FUN_0046dcc0 | 0x0046dcc0 | SaveGameManager constructor |
| FUN_0046dea0 | 0x0046dea0 | SaveGameManager caller 1 |
| FUN_0046df80 | 0x0046df80 | SaveGameManager caller 2 |
| FUN_0046f6b0 | 0x0046f6b0 | SaveGameManager caller 3 |
| FUN_005e49d0 | 0x005e49d0 | SaveGame I/O factory |
| FUN_009ca3e0 | 0x009ca3e0 | SaveGame I/O constructor |
| FUN_005e4b10 | 0x005e4b10 | SaveGameWriter::ReadFile (raw I/O) |
| FUN_005e4860 | 0x005e4860 | SaveGameWriter::WriteFile (raw I/O) |

#### SaveGame I/O Vtable Methods (0x02411f30)

| Slot | Address | Method |
|------|---------|--------|
| 0 | 0x009ca550 | **Destructor** - cleans up array, frees memory |
| 1 | 0x009ca250 | **WriteSavegame** - writes ACBROTHERHOODSAVEGAME{slot}. |
| 2 | 0x009ca290 | **ReadSavegame** - reads ACBROTHERHOODSAVEGAME{slot}. |
| 3 | 0x009ca2d0 | **WriteOptions** - writes OPTIONS file |
| 4 | 0x009ca2f0 | **ReadOptions** - reads OPTIONS file |
| 5 | 0x009ca430 | Stub - returns false |
| 6 | 0x009ca440 | Stub - returns true |
| 7 | 0x009ca450 | Stub - empty |
| 8 | 0x009ca310 | **DeleteSavegame** - deletes save file + cleanup |
| 9 | 0x005e4990 | **CheckAssassinSav** - checks if assassin.sav exists |
| 10 | 0x009ca460 | Stub - returns true |
| 11 | 0x009ca470 | Stub - returns 0 |
| 12-15 | 0x009ca480-4b0 | Stubs - empty |

**Important:** `FUN_005e4b10` (ReadFile) is a pure I/O function that reads raw bytes from disk. It is NOT a deserializer. The actual block parsing and content deserialization happens in separate functions after the file is loaded.

---

### Deserialization System Functions

These functions were identified through WinDbg time-travel debugging during SAV file loading. They form the core deserialization pipeline for both full format (Blocks 2/4) and compact format (Blocks 3/5).

#### Address Mapping

**CRITICAL:** WinDbg runtime addresses must be converted to Ghidra static addresses:

| Base | Description | Value |
|------|-------------|-------|
| WinDbg runtime | Module base (varies with ASLR) | Example: `0x00F30000` |
| Ghidra static | Default analysis base | `0x00400000` |

**Conversion formula:** `Ghidra VA = 0x400000 + WinDbg offset`

**Example:** WinDbg `ACBSP+0x1711ab0` = Ghidra `0x01B11AB0`

#### Parsing Pipeline Functions

These functions form the main SAV parsing pipeline (discovered via TTD tracing):

| Function (Ghidra) | Size | Purpose |
|-------------------|------|---------|
| `FUN_01B7A1D0` | - | Detects OPTIONS magic (`0x57FBAA33`, `0x1004FA99`) |
| `FUN_01B7B190` | - | Decompresses OPTIONS-style headers (32KB chunks) |
| `FUN_01B6F730` | 0x38 | Creates stream reader object |
| `FUN_01B49250` | 0x1058 | Creates parser object (vtable at `0x02555C60`) |
| `FUN_01AEDD90` | 0x12d8 | Pushes parser state onto stack |
| `FUN_01AFD600` | - | **Main deserializer orchestrator** |
| `FUN_01B0A740` | - | Object extraction/deserialization |
| `FUN_01B08CE0` | - | **ObjectInfo metadata parser** |

#### CAFE00 Deserializer (FUN_01B11AB0)

The Block 2 format deserializer at Ghidra VA `0x01B11AB0`:

**Validation:**
- Checks: `type == 1 && magic == 0x00CAFE00`
- Skips 8-byte header (`piVar1 + 2`)

**Processing:**
1. Calls `FUN_00425360` to set up buffer descriptor
2. Calls `FUN_01AFD600` for parsing
3. Returns deserialized object via `FUN_01AFD600`

**Note:** `FUN_00425360` is a buffer descriptor setter, NOT a parser.

#### Parser Vtable at 0x02555C60 (Updated December 2024)

The parser object created by `FUN_01B49250` uses this vtable:

| Offset | Slot | Function | Purpose |
|--------|------|----------|---------|
| 0x00 | 0 | `FUN_01B49B10` | Constructor/base |
| 0x08 | 2 | `LAB_01B48770` | BeginElement |
| 0x10 | 4 | `LAB_01B487A0` | EndElement |
| 0x50 | 20 | `FUN_01B48FB0` | Read type hash ("T") |
| 0x54 | 21 | `FUN_01B48E90` | Read ObjectName |
| 0x84 | 33 | `FUN_01B48C10` | Read ClassID / PropertyID |
| 0x8c | 35 | `FUN_01B48C00` | Read Version |
| 0x98 | 38 | `FUN_01B48B70` | Read PackedInfo (→ FUN_01B49430) |
| 0x9c | 39 | `FUN_01B48E70` | Read ObjectID |

**Vtable Dispatch Pattern (December 2024 discovery):**
```c
// FUN_01B48B70 - Slot 38 dispatcher
// Resolves parser→stream_reader chain and calls stream reader methods
if (parser[5] != 0) {
    stream_reader = parser[6];  // parser+0x18 = stream reader pointer
    result = (*stream_reader->vtable[9])();  // Read method
}
```

#### Stream Reader Architecture (December 2024)

The parser object delegates actual byte reading to a Stream Reader object.

**Stream Reader Factory:** `FUN_01B6F730`
**Stream Reader Constructor:** `FUN_01B6F590`
**Stream Reader Size:** 0x38 bytes

**Stream Reader Vtable (0x02556168):**

| Offset | Slot | Function | Purpose |
|--------|------|----------|---------|
| 0x00 | 0 | `FUN_01B6F500` | Destructor |
| 0x04 | 1 | `FUN_01B6F3B0` | Read bytes (buffer, count) |
| 0x08 | 2 | `FUN_01B6F2F0` | Read with callback |
| 0x0C | 3 | `FUN_01B6F2E0` | Stub |
| 0x10 | 4 | `FUN_01B6F290` | Read N bytes |
| 0x14 | 5 | `FUN_01B6F220` | Skip bytes |
| 0x18 | 6 | `FUN_01B6F210` | Get remaining |
| 0x1C | 7 | `FUN_01B6F200` | Check EOF |
| 0x20 | 8 | `FUN_01B6F1F0` | Stub |
| 0x24 | 9 | `FUN_01B6F150` | **Read single byte** |
| 0x28 | 10 | `FUN_01B6F140` | Stub |
| 0x38 | 14 | `FUN_01B6F5E0` | Init/Reset |
| 0x3C | 15 | `FUN_01B6F370` | **Write byte** |

**Key Read Function (FUN_01B6F150):**
```c
// Returns single byte from buffer
if (read_pos < end_pos) {
    byte = *read_pos;
    read_pos++;
    return byte;
}
return -1;  // EOF
```

**Object Layout:**
```
Offset  Field
0x00    vtable pointer (→ 0x02556168)
0x04    field_04
0x08    buffer_start
0x0C    buffer_end
0x10    current_pos
...
0x38    total size
```

#### ObjectInfo Fields (FUN_01B08CE0)

The ObjectInfo metadata parser extracts these fields in order:

1. **SerializerVersion** - Serializer format version
2. **ClassVersion** - Class schema version
3. **NbClassVersionsInfo** - Count of version entries
4. **VersionClassID + Version pairs** - Per-class versions
5. **ObjectName** - Object instance name (string)
6. **ObjectID** - Unique object identifier
7. **InstancingMode** - How object is stored:
   - `0x01` = child object
   - `0x02` = embedded object
8. **FatherID** - Parent object ID
9. **Type hash ("T")** - Object type hash

---

#### Address Conversion Table

| Function | Ghidra VA | Runtime VA (Base=0xF30000) | WinDbg Offset |
|----------|-----------|----------------------------|---------------|
| FUN_01AEAF70 | 0x01AEAF70 | 0x0261AF70 | ACBSP+0x16EAF70 |
| FUN_01AEB020 | 0x01AEB020 | 0x0261B020 | ACBSP+0x16EB020 |
| FUN_01AEF890 | 0x01AEF890 | 0x0261F890 | ACBSP+0x16EF890 |
| FUN_01AEF9D0 | 0x01AEF9D0 | 0x0261F9D0 | ACBSP+0x16EF9D0 |
| FUN_01AF0490 | 0x01AF0490 | 0x02620490 | ACBSP+0x16F0490 |
| FUN_01AF2BB0 | 0x01AF2BB0 | 0x02622BB0 | ACBSP+0x16F2BB0 |
| FUN_01AF6A40 | 0x01AF6A40 | 0x02626A40 | ACBSP+0x16F6A40 |
| FUN_00421110 | 0x00421110 | 0x00F51110 | ACBSP+0x21110 |
| FUN_00427530 | 0x00427530 | 0x00F57530 | ACBSP+0x27530 |

**Note:** Runtime VA = Ghidra VA + 0x00B30000 (when module base is 0x00F30000)

---

#### FUN_01AF6A40 - TYPE_REF Dispatcher (Updated December 2024)

**Address:** `0x01AF6A40` (Ghidra VA)

**Purpose:** The central TYPE_REF dispatcher for reading typed object references from serialized data. Reads a prefix byte and dispatches to appropriate handler based on the reference type.

**IMPORTANT:** This function uses **4-byte TYPE HASHES**, NOT nibble-encoded table IDs. It is used by the "full format" deserialization path (Blocks 1, 2, 4), not the compact format (Blocks 3, 5).

**Signature:**
```c
void __thiscall FUN_01af6a40(int param_1, undefined4 expected_type_hash, int* output_ptr, undefined4 callback_ptr);
```

**Parameters:**
- `param_1` (ECX): Context object with buffer state
  - `param_1[5]` = Current read position pointer
  - `param_1[6]` = End of buffer position
- `expected_type_hash`: Expected type hash for validation
- `output_ptr`: Where to store the result pointer
- `callback_ptr`: Callback function pointer for post-processing

**Dispatch Logic (TTD-verified):**
```c
prefix = read_byte();         // Read prefix byte
switch (prefix) {
    case 0x00:  // Full object with nested deserialization
        type_hash = read_uint32();       // Read 4-byte TYPE HASH
        object = FUN_01aeb020(type_hash, 0);  // Create/get object by hash
        // ... invoke callback for nested deserialization
        break;

    case 0x01:  // Type reference with validation
        sub_type = read_byte();          // Read 1-byte sub-type
        type_hash = read_uint32();       // Read 4-byte TYPE HASH
        FUN_01af6420(param_1, type_hash, output_ptr);  // Indirect lookup
        break;

    default:    // >= 0x02: Simple object reference
        type_hash = read_uint32();       // Read 4-byte TYPE HASH
        // Direct value handling
        break;
}
```

**Cross-References:** 400+ callers throughout the codebase

**Prefix Byte Semantics:**
| Prefix | Meaning | Data Following | Handler |
|--------|---------|----------------|---------|
| `0x00` | Full object | 4-byte type hash | FUN_01AEB020 + nested deser |
| `0x01` | Type reference | 1-byte sub-type + 4-byte hash | FUN_01AF6420 |
| `≥0x02` | Simple reference | 4-byte type hash | Direct assignment |

**Key Insight:** This dispatcher is the entry point for all typed object references in the full format serialization used by Blocks 1, 2, and 4. The compact format (Blocks 3, 5) uses a completely different code path that has NOT been traced yet.

---

#### FUN_01AEB020 - Type Hash Object Creator/Retriever (Updated December 2024)

**Address:** `0x01AEB020` (Ghidra VA)

**Purpose:** Creates or retrieves an object instance by its **TYPE HASH** (not table ID). This is a wrapper around FUN_01AEAD60, which performs the actual type lookup.

**IMPORTANT CORRECTION:** Previous documentation incorrectly stated this takes a "table_id". It actually takes a **4-byte type hash**. This function is called by the TYPE_REF dispatcher (FUN_01AF6A40) with type hashes read from the data stream.

**Signature:**
```c
int __thiscall FUN_01aeb020(int this, uint32_t type_hash, int flags);
```

**Parameters:**
- `type_hash`: 4-byte type hash (e.g., `0xBDBE3B52` for SaveGame)
- `flags`: Usually 0

**Return Value:** Pointer to the object instance

**Call Chain:**
```
FUN_01AEB020 (wrapper)
    → FUN_01AEAD60 (core lookup function)
        → Type registry lookup by hash
        → Object instantiation
```

**Cross-References:** 400+ callers, including:
- TYPE_REF dispatcher (FUN_01AF6A40) for full format deserialization
- Graphics initialization (FUN_01C50A00)
- Save deserialization
- World object creation

**Contrast with FUN_01AEAF70:**
| Function | Input | Used By |
|----------|-------|---------|
| FUN_01AEB020 | 4-byte type hash | Full format (Blocks 1, 2, 4) |
| FUN_01AEAF70 | Nibble-encoded table ID | Compact format (Blocks 3, 5) |

**Observed Type Hashes (from WinDbg trace):**
These are full 32-bit type hashes, NOT small table IDs:
```
0xBDBE3B52 (SaveGame), 0x94D6F8F1 (AssassinSaveGameData),
0xFBB63E47 (World), 0xA1A85298 (PhysicalInventoryItem), etc.
```

---

#### FUN_01AF2BB0 - Object Initialization with Table ID Lookup

**Address:** `0x01AF2BB0` (Ghidra VA)

**Purpose:** Initializes an object using type table lookup. Directly calls FUN_01AEAF70 to resolve the type descriptor.

**Key Call:**
```asm
PUSH 0                      ; param_3 = 0
PUSH dword ptr [EBP+0x14]   ; param_2 = table_id
CALL FUN_01aeaf70           ; Type table lookup
```

**Called From:**
- `FUN_01AEF890`
- `FUN_01AEF9D0`

**Observed Table IDs (from WinDbg trace):**
```
9, 8, 20, 21, 26, 4a, 4b, 4c, 4d, 4e, 4f, 2f, 30, 32, 31, 48, 46, 24, 25
```

---

#### FUN_01AEF890 - Caller Chain Entry Point

**Address:** `0x01AEF890` (Ghidra VA)

**Purpose:** Higher-level caller that invokes FUN_01AF2BB0 with table ID parameters.

**Stack Parameters (at call site):**
- `[ESP+0x14]`: Large hash values (0x034ba988, 0x073ef8c8, 0x088ef728, etc.)
- These appear to be runtime object addresses, not type hashes

**Call Chain:**
```
FUN_01AEF890
    → FUN_01AF2BB0
        → FUN_01AEAF70 (type table lookup)
```

---

#### FUN_01AEF9D0 - Alternative Caller Path

**Address:** `0x01AEF9D0` (Ghidra VA)

**Purpose:** Alternative entry point that also calls FUN_01AF2BB0. Used for different initialization contexts.

---

#### FUN_01AF0490 - Pass-Through Wrapper

**Address:** `0x01AF0490` (Ghidra VA)

**Purpose:** Simple wrapper/forwarding function in the deserialization chain.

---

#### FUN_00421110 - Generated Full Format Deserializer

**Address:** `0x00421110` (Ghidra VA)

**Purpose:** Deserializer for full format types (Blocks 2/4). Contains hardcoded type hashes and calls multiple serialization helpers.

**Hardcoded Type Hashes:**
```c
FUN_01af6a40(0xC76018E2, *(int *)(param_1 + 0x2c) + uVar8 * 4, PTR_DAT_027de5a4);
FUN_00427530(0xC69A7F31, param_1 + 0x44, PTR_DAT_027de5bc);  // TYPE_REF
FUN_004274a0(0xF0734B6A, FUN_00519350, ...);                  // Custom serializer
```

**Type Hashes Used:**
| Hash | Purpose |
|------|---------|
| `0xC76018E2` | Property type 1 |
| `0x97FCF21E` | Property type 2 |
| `0x7C00F6AF` | Property type 3 |
| `0xC69A7F31` | TYPE_REF property |
| `0xF0734B6A` | Custom serialized property |

**Function Calls:**
- `FUN_01af6a40` - Buffer deserializer
- `FUN_00427530` - TYPE_REF serializer
- `FUN_004274a0` - Custom function serializer
- `FUN_01af6d30` - Additional deserializer

**Note:** This is a FULL FORMAT deserializer for Blocks 2/4, NOT the compact format deserializer (08 03 prefix) for Blocks 3/5.

---

### Deserialization Call Chain Summary

```
                    Full Format (Blocks 2/4)
                    ========================

FUN_00421110 (Generated Deserializer)
    |
    +-- FUN_01af6a40 (Buffer Deserializer)
    |       |
    |       +-- Case 0x00: FUN_01aeb020 (Object by ID)
    |       |       |
    |       |       +-- FUN_01aeaf70 (Type Table Lookup)
    |       |
    |       +-- Case 0x01: FUN_01af6420 (Indirect)
    |               |
    |               +-- FUN_01ae9390 (Type Resolution)
    |                       |
    |                       +-- FUN_01aeaf70 (Type Table Lookup)
    |
    +-- FUN_00427530 (TYPE_REF Serializer)
    |       |
    |       +-- Direct: FUN_01aeaf70
    |       +-- Indirect: FUN_01af6420
    |
    +-- FUN_004274a0 (Custom Function Serializer)


                    Object Initialization Path
                    ==========================

FUN_01AEF890 / FUN_01AEF9D0 (Entry Points)
    |
    +-- FUN_01AF2BB0 (Object Init)
            |
            +-- FUN_01AEAF70 (Type Table Lookup)


                    Compact Format (Blocks 3/5)
                    ===========================

[NOT YET IDENTIFIED]
    |
    +-- Reads 08 03 prefix
    +-- Reads table_id (1 byte)
    +-- Reads property_index (1 byte)
    +-- FUN_01AEAF70 (Type Table Lookup)
    +-- Property dispatch
```

---

### TYPE_REF Helper Functions

The TYPE_REF serialization system uses multiple helper functions for indirect type resolution. These functions form a chain that resolves type references through descriptor lookups.

#### FUN_01AF6420 - TYPE_REF Indirect Handler

**Address:** `0x01AF6420` (ACBSP+0x1AF6420)

**Purpose:** Wrapper function for indirect type resolution via descriptor chain lookup

**Called From:**
- `FUN_00427530` (TYPE_REF serializer) at `0x004275FF`
- `FUN_00449F60` at `0x0044A040`

**Implementation:**
```c
void __thiscall FUN_01af6420(int param_1, undefined4 param_2, undefined4 param_3)
{
  // Calls FUN_01ae9390 with parameters from descriptor chain
  FUN_01ae9390(param_3, param_2, *(int *)(param_1 + 4) + 0x2c, &DAT_02a62454, 0);
  return;
}
```

**Parameters:**
- `param_1` (ECX): Context pointer with descriptor chain reference
- `param_2`: Secondary identifier
- `param_3`: Type identifier

**Key Data:**
- `DAT_02a62454`: Global data reference used in lookup

---

#### FUN_01AE9390 - Type Resolution with Lookup

**Address:** `0x01AE9390` (ACBSP+0x1AE9390)

**Purpose:** Resolves type by looking up in descriptor chain, then calls type table lookup

**Called From:**
- `FUN_01af61d0`
- `FUN_01af6420` (TYPE_REF indirect handler)

**Key Function Calls:**
- `FUN_01b1eeb0` - Lookup by key in tree map
- `FUN_01aeaf70` - Type table lookup (called at `0x01ae942c`)
- `FUN_004253e0` - Assignment helper
- `FUN_0041dc10` - Cleanup/destructor

**Call Flow:**
```
FUN_01ae9390
    |
    +-> FUN_01b1eeb0  (tree map lookup by key)
    |
    +-> FUN_01aeaf70  (type table lookup - at 0x01ae942c)
    |
    +-> FUN_004253e0  (assignment helper)
    |
    +-> FUN_0041dc10  (cleanup)
```

---

#### TYPE_REF Dual Encoding Mode

The TYPE_REF function (`FUN_00427530` at `0x00427530`) has **TWO encoding modes** based on the first byte in the stream:

| First Byte | Path | Function Chain |
|------------|------|----------------|
| `0x00` | Direct lookup | `FUN_01aeaf70` directly |
| `!= 0x00` | Indirect lookup | `FUN_01af6420` → `FUN_01ae9390` → `FUN_01aeaf70` |

**Binary Format in Stream:**
```
Direct Mode:
  [00] [4-byte type hash]  -> Direct type hash lookup via FUN_01aeaf70

Indirect Mode:
  [XX] [4-byte hash] (where XX != 0)  -> Indirect lookup via descriptor chain
```

**Example:**
```
Stream: 00 47 3E B6 FB
  -> Mode: 0x00 (direct)
  -> Hash: 0xFBB63E47 (World type)
  -> Calls: FUN_01aeaf70(0xFBB63E47, 0)

Stream: 01 19 ED EB 0D
  -> Mode: 0x01 (indirect)
  -> Hash: 0x0DEBED19 (CompactType_5E)
  -> Calls: FUN_01af6420(...) -> FUN_01ae9390(...) -> FUN_01aeaf70(...)
```

---

### Type Table Lookup (FUN_01AEAF70) - Detailed Analysis

`FUN_01AEAF70` is the primary function for looking up type descriptors in Assassin's Creed Brotherhood's serialization system. It takes a type identifier and returns a pointer to the type descriptor structure used during SAV file serialization.

#### Function Signature

```c
undefined4* __thiscall FUN_01aeaf70(int this, int param_2, int param_3);
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `this` (ECX) | int | HandleManager context pointer |
| `param_2` | int | Type identifier (table ID or type hash) |
| `param_3` | int | Secondary identifier (usually 0) |

**Return Value:**
- Pointer to type descriptor structure (16-byte aligned handle object)
- Returns `&DAT_02A621A4` if both params are 0 (null/default handle)

#### Decompiled Code

```c
undefined4* __thiscall FUN_01aeaf70(int param_1, int param_2, int param_3)
{
    undefined4* puVar1;
    void* local_10;
    undefined1* puStack_c;
    undefined4 local_8;

    local_8 = 0xffffffff;
    puStack_c = &LAB_023c0a4e;  // Exception handler
    local_10 = ExceptionList;

    // Special case: both params zero returns null handle
    if ((param_2 == 0) && (param_3 == 0)) {
        LOCK();
        DAT_02a621a8 = DAT_02a621a8 + 1;  // Increment ref count
        UNLOCK();
        return &DAT_02a621a4;  // Return null handle singleton
    }

    ExceptionList = &local_10;
    FUN_01aba8b0();  // Enter critical section (mutex lock)
    local_8 = 0;

    // Call inner lookup function
    puVar1 = (undefined4*)FUN_01aead60(param_2, param_3);

    // Increment reference count atomically
    LOCK();
    puVar1[1] = puVar1[1] + 1;
    UNLOCK();

    local_8 = 0xffffffff;
    if (param_1 != -0x7c) {
        FUN_01aba8c0();  // Leave critical section (mutex unlock)
    }
    ExceptionList = local_10;
    return puVar1;
}
```

#### Inner Lookup Function: FUN_01AEAD60

The actual table lookup happens in `FUN_01aead60`:

```c
int* __thiscall FUN_01aead60(int this, int param_2, int param_3)
{
    // First, try fast path via hash lookup
    piVar2 = (int*)FUN_01aea0b0(&local_14, &param_3);

    if (piVar2 == NULL) {
        // Create new handle from pool
        // Uses pool at this+0x98, indexed by (this+0x9E) & 0x3FFF

        iVar3 = local_14;
        if (local_14 == 0) {
            iVar3 = FUN_01afb960();  // Get next sequence ID
        }

        // Iterate pool slots
        piVar5 = *(int**)(this + 0x98);
        piVar2 = piVar5 + (*(ushort*)(this + 0x9e) & 0x3fff) * 3;

        for (; piVar5 != piVar2; piVar5 = piVar5 + 3) {
            if (piVar5[2] != -1) {
                // Found free slot
                piVar2 = (int*)(piVar5[2] * 0x10 + *piVar5);
                iVar1 = piVar2[1];
                *piVar2 = 0;         // Handle field 0
                piVar2[1] = 0;       // Handle field 1 (ref count)
                piVar2[2] = 0;       // Handle field 2 (flags)
                piVar2[3] = iVar3;   // Handle field 3 (type ID)
                piVar5[2] = iVar1;   // Update free list
                goto LAB_01aeaef4;
            }
        }

        // Need to grow pool
        FUN_01aec2f0((*(ushort*)(this + 0x9e) & 0x3fff) + 1, DAT_02a622bc);
        // ... allocate new slot
    }

    // Register in type->handle map
    FUN_01aeabc0(piVar2, param_3);

    return piVar2;
}
```

#### Hash Lookup Function: FUN_01AEA0B0

```c
int __thiscall FUN_01aea0b0(int this, int* param_2, int* param_3)
{
    if (*param_3 == 0) {
        // Resolve type hash to type info
        iVar1 = FUN_01afbe80(*param_2);  // Hash lookup in global table
        *param_3 = iVar1;
    }

    iVar1 = *param_3;
    if (iVar1 != 0) {
        // Extract slot info from type info
        uVar2 = (*(uint*)(iVar1 + 4) & 0xc3ffffff) - 1;
        if (uVar2 != 0xffffffff) {
            // Calculate slot address:
            // Pool base: *(int*)(this + 0x98)
            // Pool index: (uVar2 >> 14) * 12
            // Slot index: (uVar2 & 0x3fff) * 16
            iVar3 = (uVar2 & 0x3fff) * 0x10 +
                    *(int*)(*(int*)(this + 0x98) + (uVar2 >> 0xe) * 0xc);
            if (iVar3 != 0) {
                return iVar3;
            }
        }
    }

    // Fallback: search in tree map
    piVar4 = (int*)FUN_01b1eeb0(*(undefined4*)(this + 0xa4), *param_2, 0);
    if (piVar4 != NULL) {
        return *piVar4;
    }
    return 0;
}
```

#### Table ID Encoding Formula

The Table ID is extracted from the type descriptor at offset `+0x04`:

```c
raw_value = type_desc[+4] & 0xC3FFFFFF;  // Mask out upper 2 bits (0x3C000000)
table_id = raw_value - 1;                 // Subtract 1 for 0-based index
bucket_index = table_id >> 14;            // Upper bits = bucket (pool index)
entry_index = table_id & 0x3FFF;          // Lower 14 bits = entry (max 16383)
address = table[bucket * 12] + entry * 16;  // Final address calculation
```

**Key constraints:**
- Maximum 16383 entries per bucket (14 bits)
- Each bucket entry is 12 bytes
- Each type handle is 16 bytes

#### Handle Structure (16 bytes)

Type handles are 16-byte structures stored in pools:

```
Offset  Size  Field
------  ----  -----
+0x00   4     Type pointer or 0
+0x04   4     Reference count
+0x08   4     Flags (low 24 bits: status, high 8 bits: tag)
+0x0C   4     Type ID (sequence number or hash)
```

#### Global Data Addresses

| Address | Purpose |
|---------|---------|
| `0x02A621A4` | Null handle singleton |
| `0x02A621A8` | Null handle reference count |
| `0x02A6247C` | Type hash lookup manager |
| `0x02A622BC` | Allocator context |
| `0x02989F60` | Debug mode flag (2 = debug enabled) |
| `0x02A5E0F4` | Debug output interface |

#### HandleManager Structure

The `this` pointer (HandleManager) has the following layout:

```
Offset   Size  Field
------   ----  -----
+0x7C    var   Mutex/lock object
+0x98    4     Pointer to pool array
+0x9E    2     Pool index mask (& 0x3FFF)
+0xA4    4     Tree map for hash->handle lookup
```

#### Cross-References

30+ functions call `FUN_01AEAF70`. Key callers include:

| Address | Function | Purpose |
|---------|----------|---------|
| `0x01B04640` | FUN_01b04640 | Type system initialization |
| `0x00C61510` | FUN_00c61510 | Object creation |
| `0x0040D5D0` | FUN_0040d5d0 | Serialization setup |
| `0x00434160` | FUN_00434160 | Type registration |
| `0x004625B0` | FUN_004625b0 | Property access |
| `0x005F1F50` | FUN_005f1f50 | World object handling |

#### Serialization Integration

The type lookup integrates with the serialization system through:

**FUN_00427530 - Serialize Type Reference:**

```c
void __thiscall FUN_00427530(int this, undefined4 param_2, int* param_3)
{
    // Read 1-byte flag + 4-byte type ID from stream
    cVar5 = *pcVar6++;
    uVar7 = *(undefined4*)pcVar6;
    pcVar6 += 4;

    if (cVar5 == '\0') {
        // Type by ID
        iVar8 = FUN_01aeaf70(uVar7, 0);  // Look up type
        // Swap handles with refcount management
        *param_3 = iVar8;
    } else {
        // Type by hash
        FUN_01af6420(uVar7, param_3);
    }
}
```

#### Common Type Hashes Used

From caller analysis, these type hashes are frequently passed:

| Hash | Usage Context |
|------|---------------|
| `0xFBB63E47` | World object (most common - 8+ calls in World serializer) |
| `0x984415E` | Property reference |
| `0x18B8C0DE` | Unknown |
| `0xC0A01091` | Unknown |
| `0x1756B2BA` | Unknown |
| `0xC69A7F31` | Unknown |
| `0x4DB4B1FE` | Unknown |

#### Thread Safety

The function implements thread-safe access through:
1. Atomic LOCK/UNLOCK for reference counting
2. Critical section via `FUN_01aba8b0`/`FUN_01aba8c0`
3. Structured exception handling (SEH)

#### Table ID to Type Mapping

The `param_2` value can be either:
1. A **Table ID** (small integer like 0x5E, 0x4F) - used with pool lookup
2. A **Type Hash** (32-bit hash like 0xFBB63E47) - used with hash table lookup

The function handles both cases through `FUN_01aea0b0` which:
1. Tries pool-based lookup if `param_3` has valid slot info
2. Falls back to tree map lookup by type hash

#### Pool Layout

Type handles are stored in pools structured as:
- Array of 12-byte pool entries at `this+0x98`
- Each pool entry: `[base_ptr(4)] [capacity(4)] [free_list_head(4)]`
- Handles are 16-byte structures: `[type_ptr] [refcount] [flags] [type_id]`
- Maximum 0x4000 (16384) handles per pool

#### Relationship to SAV Compact Format

When deserializing SAV Block 3 and 5 data:
1. Stream contains `[prefix] [table_id] [property_index]` sequences
2. `table_id` is passed to `FUN_01aeaf70` to get type descriptor
3. Type descriptor contains property array
4. `property_index` selects the property to read

Example from SAV data:
```
08 03 5E 01  -> TABLE_REF_FIXED, Table ID 0x5E, Property 0x01
```

#### Summary

`FUN_01AEAF70` is the central type resolution function in the game's reflection/serialization system. It:
1. Manages reference-counted type handles
2. Supports both hash-based and ID-based lookup
3. Uses pooled allocation for performance
4. Is thread-safe with atomic operations
5. Integrates with the SAV compact format decoder

---

## Key Addresses Reference

### Deserialization Function Addresses

| Address | Function | Purpose |
|---------|----------|---------|
| `0x01AEAF70` | FUN_01AEAF70 | Type table lookup (primary) |
| `0x01AEB020` | FUN_01AEB020 | Object creator by table ID |
| `0x01AEF890` | FUN_01AEF890 | Deserialization entry point |
| `0x01AEF9D0` | FUN_01AEF9D0 | Alternative entry point |
| `0x01AF0490` | FUN_01AF0490 | Pass-through wrapper |
| `0x01AF2BB0` | FUN_01AF2BB0 | Object init with type lookup |
| `0x01AF6A40` | FUN_01AF6A40 | Buffer deserializer (prefix dispatch) |
| `0x01AF6420` | FUN_01AF6420 | TYPE_REF indirect handler |
| `0x01AE9390` | FUN_01AE9390 | Type resolution with lookup |
| `0x00421110` | FUN_00421110 | Generated full format deserializer |
| `0x00427530` | FUN_00427530 | TYPE_REF serializer |
| `0x004274A0` | FUN_004274A0 | Custom function serializer |
| `0x01B11AB0` | FUN_01B11AB0 | **CAFE00 deserializer** (Block 2) |
| `0x01B7A1D0` | FUN_01B7A1D0 | OPTIONS magic detector |
| `0x01B7B190` | FUN_01B7B190 | OPTIONS header decompressor |
| `0x01AFD600` | FUN_01AFD600 | **Main deserializer orchestrator** |
| `0x01B0A740` | FUN_01B0A740 | Object extraction/deserialization |
| `0x01B08CE0` | FUN_01B08CE0 | **ObjectInfo metadata parser** |
| `0x01B6F730` | FUN_01B6F730 | Stream reader object creator (0x38 bytes) |
| `0x01B49250` | FUN_01B49250 | Parser object creator (0x1058 bytes) |
| `0x01AEDD90` | FUN_01AEDD90 | Parser state pusher (0x12d8 bytes) |
| `0x01B6F170` | FUN_01B6F170 | **Block 2 Field4 Calculator** - `sub edx, eax` at +0x1B (CONFIRMED TTD) |
| `0x01B7B050` | FUN_01B7B050 | Block serialization wrapper - receives Field4 as param_2 |

### Functions That Are NOT Deserializers

**IMPORTANT:** These functions are often encountered during debugging but are utility functions, not parsers:

| Address | Function | Actual Purpose |
|---------|----------|----------------|
| `0x01ADCC30` | FUN_01ADCC30 | Custom heap `free()` - memory deallocation |
| `0x01AE44F0` | FUN_01AE44F0 | Simple initializer - zeros two dwords |
| `0x00425360` | FUN_00425360 | Buffer descriptor setter - NOT a parser |
| `0x005E4B10` | FUN_005E4B10 | SaveGameWriter::ReadFile - raw disk I/O only |

Avoid confusing these with deserializers when tracing.

### Type Descriptor Locations

| Address (VA) | Type | Description |
|--------------|------|-------------|
| `0x027E655C` | CommonParent | Primary descriptor |
| `0x0285B504` | CommonParent | Secondary (with ManagedObject link) |
| `0x025556AC` | ManagedObject | Type descriptor pointer |
| `0x02991180` | OPTIONS | Type descriptor |
| `0x027ECFC8` | SaveGame | Type descriptor (runtime) |
| `0x027ED298` | RewardFault | Type descriptor |
| `0x023E0540` | PlayerOptionsElement | Primary descriptor |
| `0x023E2EE0` | PlayerOptionsElement | Registration entry |
| `0x024252D4` | CollectionType | Self-referential descriptor |
| `0x023E15E0` | ContainerType | Type descriptor |

### Registration Tables

| Address (VA) | Type | Description |
|--------------|------|-------------|
| `0x02842600` | PlayerOptions | Registration table |
| `0x02842070` | PlayerOptionsSaveData | Registration table |
| `0x02589830` | PlayerOptionsElement | Hash table entry |

### Property Pointer Tables

| Address Range | Type | Entries |
|---------------|------|---------|
| `0x027ECF54-0x027ECF8C` | SaveGame | 13 properties |
| `0x027ED428-0x027ED520+` | SaveGameDataObject | 5+ properties |
| `0x027EE1BC-0x027EE230+` | MissionSaveData | 6+ properties |
| `0x027E2068-0x027E20A0` | World | 14 properties |

### String Locations

| Address (VA) | String |
|--------------|--------|
| `0x023E5A68` | World |
| `0x023F0808` | SaveGame |
| `0x023F13F4` | SaveGameDataObject |
| `0x023F0EBC` | MissionSaveData |
| `0x023F1AE0` | RewardFault |
| `0x02554AAC` | ManagedObject |
| `0x024C6880` | PlayerOptions |
| `0x024C6890` | PlayerOptionsSaveData |
| `0x021C5EBC` | CollectionType |
| `0x023FDC60` | PropertySheet |
| `0x02554ABA` | PropertyBuffer |
| `0x02554AEA` | DynamicPropertiesSet |

---

## Serialization Formats

### Standard Type Descriptor (Marker: 0x02000201)

289 descriptors found with this pattern in .data section.

```
Offset  Size  Field
------  ----  -----
+0x00   4     Marker (0x02000201 for types)
+0x04   4     Type hash (unique identifier)
+0x08   4     Self hash (repeated, or parent hash)
+0x0C   2     Property count (low byte)
+0x0E   2     Flags
+0x10   4     Base offset / size
+0x14   12    Reserved/padding
+0x20   4     Pointer to self descriptor
+0x24   4     Pointer to property table
+0x28+  var   Property entries (32 bytes each)
```

### Property Descriptor (Marker: 0x01000002 or 0x02000001)

Each property is 32 bytes:

```
Offset  Size  Field
------  ----  -----
+0x00   4     Marker (0x01000002 or 0x02000001)
+0x04   4     Property hash (unique identifier)
+0x08   4     Type hash (type of this property)
+0x0C   2     Unknown field
+0x0E   2     Unknown field
+0x10   2     Struct offset
+0x12   2     Flags
+0x14   12    Reserved/additional data
```

**Property Markers:**
- `0x02000001` = Normal property
- `0x0200001D` = Dynamic/Array property

### Registration Table Format

Used by types registered at runtime (PlayerOptions, PlayerOptionsSaveData):

```
Offset  Size  Field
------  ----  -----
+0x00   4     Name pointer (-> string)
+0x04   4     Flags
+0x08   4     Type hash
+0x0C   4     Size
+0x10   4     Reserved
+0x20   4     Sentinel (0x7FFF7FFF)
+0x24   4     Vtable/Serializer pointer
+0x3C   4     Function 1
+0x40   4     Function 2
+0x48+  var   Property entries
```

### Inline Types

Types like LanguageSettings, AudioSettings, VideoSettings:
- No standalone type descriptor
- Serialized as raw byte streams (16 bytes)
- Type hashes are descriptor markers for reflection system

---

## Usage in SAV/OPTIONS Files

### OPTIONS File

The OPTIONS file contains 3 compressed sections plus footer.

**Types Used:**
| Type | Section | Purpose |
|------|---------|---------|
| OPTIONS (0x1C0637AB) | Section 1 | Main settings structure |
| LanguageSettings (0xDCCBD617) | Section 1 | Language (inline at 0x00) |
| AudioSettings (0x569CD276) | Section 1 | Audio (inline at 0x10) |
| VideoSettings (0x9E293373) | Section 1 | Video (inline at 0x20) |
| SubObject (0xF8206AF7) | Section 1 | 11 embedded objects |

**Key Offsets:**
| File Offset | Property | Description |
|-------------|----------|-------------|
| 0x28-0x2B | In header | Block1 Hash |
| 0x5E bit 2 | Property 14 | DLC unlock flag |
| 0xD1-0xD2 | Variable | Size D1 |
| 0xF1-0xF2 | Variable | Size F1 |
| 0xF9-0xFC | Variable | User Hash |

### SAV File

SAV files contain multiple blocks with different serialization formats.

**Block Mapping:**
| Block | Format | Primary Types |
|-------|--------|---------------|
| 1 | Header | - |
| 2 | Standard | SaveGame, World |
| 3 | Compact | CommonParent derivatives (700+ types) |
| 4 | Standard | SaveGameDataObject, MissionSaveData |
| 5 | Compact | CommonParent derivatives |

**Types in SAV:**
| Type | Block | Purpose |
|------|-------|---------|
| SaveGame (0xBDBE3B52) | 2 | Root save container |
| World (0xFBB63E47) | 2 | World state |
| SaveGameDataObject (0x5FDACBA0) | 4 | Mission data container |
| MissionSaveData (0x5ED7B213) | 4 | Mission-specific data |
| RewardFault (0x12DE6C4C) | 4 | Uplay service faults |
| PlayerOptions (0xCAC5F9B3) | - | Per-save options |
| PlayerOptionsSaveData (0x7879288E) | - | Player option collections |
| PlayerOptionsElement (0x2DAD13E3) | - | Collection elements |

### Compact Format (Blocks 3, 5)

Uses 4-byte patterns: `[prefix] [type_indicator] [table_id] [property_index]`

**Common Prefixes:**
| Prefix | Name | Description |
|--------|------|-------------|
| 0x0803 | TABLE_REF_FIXED | Fixed property reference |
| 0x0502 | FIXED32 | 4-byte fixed value |
| 0x1405 | VARINT | Variable-length integer |
| 0x0C18 | EXTENDED | Extended format with modifier |

**Table ID Distribution:**
| Table ID | References | Property Range |
|----------|------------|----------------|
| 0x5E | 73 | 0x01-0xD9 |
| 0x3B | 43 | 0x08-0xFE |
| 0x0B | 27 | 0x03-0xFC |
| 0x38 | 11 | 0x03-0xDF |
| 0x08 | 12 | 0x00-0xF6 |
| 0x20 | - | World type |
| 0x16 (22) | - | PlayerOptionsElement |

---

## Appendix: Analysis Limitations

### Hash Algorithm Discovery (December 2024)

**CONFIRMED: CRC32 (zlib.crc32)** is the hash function used for type and property hashes.

**Verification Method:**
- Extracted 199,399 unique strings from ACBSP.exe
- Computed CRC32 hash for each string
- Compared against known hashes from SAV files

**Results:**
- 7 type hash matches found (type names exist as debug strings)
- 0 property name matches (property names stripped at compile time)

#### Successfully Resolved Hashes (7 total)

| Hash | Field Name | Location | Verified |
|------|-----------|----------|----------|
| `0x70A1EA5F` | Version | Block 1 | CRC32("Version") |
| `0x78BD5067` | PlayerName | Block 1 | CRC32("PlayerName") |
| `0x84A80CC2` | MissionHistory | Block 2 | CRC32("MissionHistory") |
| `0x94D6F8F1` | AssassinSaveGameData | Block 2 (root type) | CRC32("AssassinSaveGameData") |
| `0xA1A85298` | PhysicalInventoryItem | Block 4 | CRC32("PhysicalInventoryItem") |
| `0xBB96607D` | ManagedObject | System base type | CRC32("ManagedObject") |
| `0xFBB63E47` | World | Block 1, 2, 3 | CRC32("World") |

#### Property Hash Statistics

| Metric | Value |
|--------|-------|
| Total unique hashes in SAV | 53 |
| Successfully resolved | 7 (13%) |
| Block 1 unmapped properties | 10 of 12 |
| Item ID hashes (Block 4) | 30 unique |

### Why Property Names Cannot Be Resolved

Property hashes cannot be reversed to string names because:
1. **Property names are stripped at compile time** - the game only stores hashes at runtime
2. Type names (like "SaveGame", "World") exist as debug strings
3. Property names (like "Health", "Money") do NOT appear in the executable
4. Hashes are 32-bit CRC32 values with no collision-resistant reversal

**Hash constants found in binary (unused for type system):**
- FNV prime `0x01000193` at `0x01D8D058`
- FNV offset `0x811c9dc5` at `0x01D8D0A3`

### Future Resolution Methods

| Method | Source | Effort |
|--------|--------|--------|
| Type Descriptor Table | Ghidra VA `0x027E0638` | Medium |
| Type lookup function | `FUN_01AEAD60` | High |
| Dynamic analysis | Cheat Engine value modification | Low |
| SDK/Debug symbols | Ubisoft proprietary | N/A |

### Unknown Type Names

Some types have no name string in the binary:
- CommonParent (0x7E42F87F) - likely "Object" or "Base"
- PropertyReference (0x0984415E) - likely "PropertyRef"
- ValueBind (0x18B8C0DE) - likely "ValueBind"
- LinkBind (0xC0A01091) - likely "LinkBind"
- ContainerType (0xA9E0C685) - no string found

---

## Appendix B: Binary Analysis Details

*Merged from type_descriptor_table.md - detailed binary-level analysis.*

### OPTIONS Type Descriptor Binary Breakdown (0x02991180)

```
+0x00: 01 02 00 02 ab 37 06 1c ab 37 06 1c 00 00 15 00
       [Marker]    [TypeHash]  [SelfHash]  [PropCnt]
+0x10: 00 00 20 00 00 00 00 00 00 00 00 00 00 00 00 00
       [BaseOffset][Reserved]
+0x20: 80 11 99 02 88 3b 99 02 01 00 00 02 58 3a 90 3f
       [SelfPtr]   [PropTable] [PropEntry...........
```

**Key Header Fields:**
| Field | Value | Description |
|-------|-------|-------------|
| Marker | `0x02000201` | Type descriptor marker |
| Type Hash | `0x1C0637AB` | OPTIONS type identifier |
| Property Count | 21 (0x15) | Total number of properties |
| Self Pointer | `0x02991180` | Pointer back to this descriptor |
| Property Table | `0x02993B88` | Secondary property table |

### Hash-to-Index Table (0x023E1040)

**Format:** `[hash(4)] [table_id(4)] [0xFFFFFFFF(4)]`

| Address | Type Hash | Table ID | Type Name |
|---------|-----------|----------|-----------|
| 0x023E1040 | 0x90C6FB96 | 0x20 | (Unknown) |
| 0x023E11A0 | 0xFBB63E47 | 0x20 | World |
| 0x023E11AC | 0x24687531 | 0x20 | (Unknown) |
| 0x023E22DC | 0xEDCA05DB | 0x3C | (Unknown) |

### Type Pointer Tables (Compact Format)

**Table at 0x028558AC region:**

| Table ID | Type Hash | Parent Hash | Props |
|----------|-----------|-------------|-------|
| 0x08 | 0xC9A5839D | 0x7E42F87F | 22 |
| 0x0B | 0x82A2AEE0 | 0x7E42F87F | 22 |
| 0x13 | 0x9464A1DF | 0x7E42F87F | 22 |
| 0x1F | 0xD17B9E84 | 0x7E42F87F | 22 |
| 0x20 | 0x1B2159BE | 0x7E42F87F | 22 |
| 0x38 | 0xFA1AA549 | 0x7E42F87F | 22 |
| 0x3B | 0xFC6EDE2A | 0x7E42F87F | 22 |
| 0x4F | 0xF49BFD86 | 0x7E42F87F | 22 |
| 0x5B | 0xC8761736 | 0x7E42F87F | 22 |
| 0x5E | 0x0DEBED19 | 0x7E42F87F | 22 |

### CompactType_5E Analysis (Table ID 0x5E)

| Field | Value |
|-------|-------|
| Table ID | `0x5E` (94 decimal) |
| Type Hash | `0x0DEBED19` |
| Parent Hash | `0x7E42F87F` (CommonParent) |
| Property Count | 22 |
| Block 3 References | 63 |
| Property Index Range | 0x01 - 0xD9 |

**Type Descriptor at VA 0x02855778:**
```
+0x00: 01 00 00 02          Marker (0x02000001)
+0x04: 19 ed eb 0d          Type Hash (0x0DEBED19)
+0x08: 7f f8 42 7e          Parent Hash (0x7E42F87F - CommonParent)
+0x0C: 00 00                Field 0x0C (0)
+0x0E: 16 00                Property Count (22)
```

### Property System Three-Type Architecture

```
+----------------------+
| PropertyReference    |  <- Main accessor (461 refs)
| (0x0984415E)        |
+----------+-----------+
           |
    +------+------+
    |             |
+---v---+   +-----v-----+
|ValueBind|  | LinkBind  |
|(0x18B8C0DE)| |(0xC0A01091)|
+---+---+   +-----+-----+
    |             |
    v             v
 Property      Linked
 Value         Reference
```

### Additional Type Hashes from Descriptors

Found 262 unique type hashes in type descriptors. Notable ones:

| Hash | Occurrences | Notes |
|------|-------------|-------|
| `0x11598A66` | 30 | CollectionType |
| `0xA9E0C685` | 4 | ContainerType |
| `0x21C2D472` | - | Referenced in serialization |

### Extended String Locations (.rdata)

| Address | String |
|---------|--------|
| 0x023E5A68 | World |
| 0x023F0808 | SaveGame |
| 0x023F13F4 | SaveGameDataObject |
| 0x023F0EBC | MissionSaveData |
| 0x023F1AE0 | RewardFault |
| 0x02554AAC | ManagedObject |
| 0x02554A9A | ObjectIDPair |
| 0x02554ABA | PropertyBuffer |
| 0x02554ACA | PersistenceManager |
| 0x02554ADA | PersistenceObject |
| 0x02554AEA | DynamicPropertiesSet |
| 0x024C6880 | PlayerOptions |
| 0x024C6890 | PlayerOptionsSaveData |
| 0x021C5EBC | CollectionType |
| 0x023FDC60 | PropertySheet |
| 0x024DFFAC | PhysicalInventoryItem |
| 0x023EC1F8 | Entity |
| 0x023E6A88 | Player |

---

*Document generated from ACBSP.exe binary analysis, December 2025*
