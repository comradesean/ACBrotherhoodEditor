# JSON Data Files Index

This document describes the JSON data files in the `docs/data/` directory and their purposes.

## Active Data Files

### Directory: `docs/data/`

| File | Size | Purpose |
|------|------|---------|
| `cape_mappings.json` | 2 KB | Cape record hashes/IDs and the frame-based unlock method. Used by acb_facebookcape_unlocker.py. |
| `sav_hash_mapping.json` | 268 KB | Cross-reference mapping between SAV file hashes and EXE-known hashes. Essential for validation. The `"block"` provenance labels use the deprecated 5-block naming (the areas after Block 2 are LZSS frames; see SAV_BLOCKS_OVERVIEW.md); the hash values themselves are unaffected. |
| `sav_type_descriptors_found.json` | 44 KB | Hash match locations in ACBSP.exe for key types (SaveGame, Block2_GameState). Required for type resolution. |
| `sav_property_tables_extracted.json` | 20 KB | SaveGame property tables with descriptors, flags, and struct offsets. |
| `sav_descriptors_deep_analysis.json` | 20 KB | Serializer function analysis and property cluster documentation. |
| `type_hash_analysis.json` | 10 KB | **Consolidated type analysis** - combines core types, CommonParent, PropertyReference, ValueBind/LinkBind, and container types. |
| `table_ids/` | 26 MB total | **Split master type table** - complete type descriptor entries organized by table ID ranges. See [Table ID Files](#table-id-files-split-structure) section below. |

---

## File Relationships

```
+-------------------------------------------------------------+
|                    DATA FILE HIERARCHY                       |
+-------------------------------------------------------------+
|                                                              |
|  docs/data/                                                 |
|                                                              |
|  TYPE SYSTEM (CONSOLIDATED):                                |
|  +- type_hash_analysis.json       [Master type reference]   |
|     +- core_types                 [10 key type hashes]      |
|     +- common_parent              [Root class, 745 derived] |
|     +- property_reference         [461 code locations]      |
|     +- value_link_binds           [ValueBind/LinkBind]      |
|     +- container_types            [Container/Collection]    |
|                                                              |
|  COMPACT FORMAT (Blocks 3 & 5):                             |
|  +- table_ids/                   [Split by ID ranges]       |
|     +- table_ids_00-1F.json      [IDs 0x00-0x1F, 4.0 MB]    |
|     +- table_ids_20-3F.json      [IDs 0x20-0x3F, 4.3 MB]    |
|     +- table_ids_40-5F.json      [IDs 0x40-0x5F, 4.3 MB]    |
|     +- table_ids_60-7F.json      [IDs 0x60-0x7F, 4.3 MB]    |
|     +- table_ids_80-FF.json      [IDs 0x80-0xFF, 8.4 MB]    |
|     +- table_ids_shared.json     [Shared data, 28 KB]       |
|     +- table_ids_index.json      [Index file, 2 KB]         |
|     +- type_descriptors.json     [8,208 type descs, 1.0 MB] |
|                                                              |
|  SAV FILE STRUCTURE:                                        |
|  +- sav_descriptors_deep_analysis.json  [Serializer funcs]  |
|  +- sav_property_tables_extracted.json  [SaveGame props]    |
|  +- sav_hash_mapping.json               [SAV<->EXE xref]    |
|  +- sav_type_descriptors_found.json     [EXE hash mappings] |
|                                                              |
|  ITEM MAPPINGS:                                             |
|  +- cape_mappings.json                  [Block 4 capes]     |
|                                                              |
+-------------------------------------------------------------+
```

---

## Consolidated Type Analysis Structure

The `type_hash_analysis.json` file contains the following sections:

| Section | Content |
|---------|---------|
| `metadata` | Source files, generation date, description |
| `core_types` | 10 key type hashes (World, PropertyReference, SaveGame, etc.) |
| `analysis_notes` | Key function addresses (world_serializer, type_lookup, etc.) |
| `common_parent` | Root class analysis with 745 derived types |
| `property_reference` | 461 code locations, call targets, patterns |
| `value_link_binds` | ValueBind (0x18B8C0DE) and LinkBind (0xC0A01091) analysis |
| `container_types` | ContainerType and CollectionType for World objects |

---

## Usage Notes

### For Implementation Work
- **Start with**: `type_hash_analysis.json` for all type hash information
- **Compact format**: `table_ids/` directory contains the authoritative source (split by range)
- **Validation**: Use `sav_hash_mapping.json` to cross-check SAV hashes against EXE

### For Research/Investigation
- **Type hierarchy**: `type_hash_analysis.json` -> `common_parent` section
- **Property system**: `type_hash_analysis.json` -> `property_reference` section
- **Binding types**: `type_hash_analysis.json` -> `value_link_binds` section
- **Serialization**: `sav_descriptors_deep_analysis.json`

### File Size Warning
- `data/table_ids/` split files (4-8 MB each) - Load only the range you need
- `sav_hash_mapping.json` (268 KB) - Moderate size, loads quickly

---

## Table ID Files (Split Structure)

Type table data is organized into range-based files for efficient loading.

### Directory: `docs/data/table_ids/`

| File | Size | Table ID Range | Tables | Entries |
|------|------|----------------|--------|---------|
| `table_ids_00-1F.json` | 4.0 MB | 0x00 - 0x1F | 6,203 | 13,124 |
| `table_ids_20-3F.json` | 4.3 MB | 0x20 - 0x3F | 6,664 | 14,072 |
| `table_ids_40-5F.json` | 4.3 MB | 0x40 - 0x5F | 6,851 | 14,361 |
| `table_ids_60-7F.json` | 4.3 MB | 0x60 - 0x7F | 6,690 | 14,121 |
| `table_ids_80-FF.json` | 8.4 MB | 0x80 - 0xFF | 8,913 | 31,055 |
| `table_ids_shared.json` | 28 KB | N/A | Shared metadata |
| `table_ids_index.json` | 2 KB | N/A | Index of all files |
| `type_descriptors.json` | 1.0 MB | N/A | Complete type descriptor registry (8,208 types) |

### File Structure

Each range file contains:
```json
{
  "_metadata": {
    "description": "Table ID mappings for range 0xNN-0xMM",
    "range_start": "0xNN",
    "range_end": "0xMM",
    "generated_at": "..."
  },
  "type_tables": [...]  // Filtered to entries in this range
}
```

The `table_ids_shared.json` file contains:
- `target_table_ids` - Target table IDs of interest
- `type_descriptors` - 100 type descriptor entries
- `deserializer_analysis` - 5 deserializer function analyses
- `table_id_comparisons` - 40 table ID comparison entries

The `type_descriptors.json` file contains the complete type descriptor registry:
```json
{
  "_metadata": { ... },
  "table_ids_found": ["0x20", "0x21", ...],  // 62 table IDs observed in SAV files
  "type_descriptors": {
    "0xC44BA5AB": {
      "va": "0x027DE630",           // Virtual address in ACBSP.exe
      "flags": "0x02000001",        // Type flags
      "prop_count": 64,             // Property count
      "known_name": null            // Human-readable name (if known)
    },
    // ... 8,208 entries total
  }
}
```

### Usage Example

```python
import json

# Load only the range you need (e.g., for table ID 0x5E)
with open('docs/data/table_ids/table_ids_40-5F.json') as f:
    data = json.load(f)

# Access type tables
for table in data['type_tables']:
    for entry in table['entries']:
        if entry['index'] == 0x5E:
            print(f"Found: {entry['type_hash']}")
```

---

## Generation Scripts

These JSON files were generated by analysis scripts in `analyze/`:

| JSON File | Generated By |
|-----------|--------------|
| `type_hash_analysis.json` | Consolidated from source files (Dec 2025) |
| `table_ids/*.json` | Analysis scripts (Dec 2025) |
| `sav_hash_mapping.json` | `analyze/sav_hash_extractor.py` |

---

*Last updated: December 2025*
