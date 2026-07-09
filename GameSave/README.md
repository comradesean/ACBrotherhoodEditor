# AC Brotherhood Save File Tools

Reverse-engineered LZSS compression/decompression tools for Assassin's Creed Brotherhood's OPTIONS and SAV save files. Developed through WinDbg time-travel debugging and Ghidra decompilation.

**Accuracy**: 100% byte-for-byte match with the game's original compressor.

## Requirements

- Python 3.6+
- No external dependencies

## Tools

| Script | Description |
|--------|-------------|
| `lzss_compressor_final.py` | LZSS compressor (lazy matching algorithm) |
| `lzss_decompressor_final.py` | LZSS decompressor |
| `options_serializer.py` | Rebuild OPTIONS files from decompressed sections |
| `sav_parser.py` | Parse SAV files and extract blocks |
| `sav_serializer.py` | Rebuild SAV files from extracted blocks |

## Usage

### OPTIONS Files

OPTIONS files store game settings (graphics, audio, controls). They contain 3 LZSS-compressed sections.

```bash
# Decompress all 3 sections
python lzss_decompressor_final.py OPTIONS

# Output: game_uncompressed_1.bin, game_uncompressed_2.bin, game_uncompressed_3.bin

# Rebuild OPTIONS file
python options_serializer.py game_uncompressed_1.bin game_uncompressed_2.bin game_uncompressed_3.bin -o OPTIONS_NEW

# Rebuild with validation
python options_serializer.py game_uncompressed_1.bin game_uncompressed_2.bin game_uncompressed_3.bin -o OPTIONS_NEW --validate
```

### SAV Files

> **⚠ SUPERSEDED (July 2026):** `sav_parser.py` and `sav_serializer.py` assume
> the fixed "5-block" layout below, which is only what a small fresh save looks
> like. Real saves hold 6-16 LZSS frames after Blocks 1-2, so these scripts
> extract the wrong data on played saves. Use `../acb_facebookcape_unlocker.py`
> (which locates content by decompressing every frame) or see the corrected
> structure in the root README.

SAV files store game saves.

```bash
# Parse and extract all blocks
python sav_parser.py ACBROTHERHOODSAVEGAME0.SAV

# Output: sav_block{1,2,4}_decompressed.bin, sav_block{3,5}_raw.bin

# Rebuild SAV file
python sav_serializer.py \
  --block1 sav_block1_decompressed.bin \
  --block2 sav_block2_decompressed.bin \
  --block3 sav_block3_raw.bin \
  --block4 sav_block4_decompressed.bin \
  --block5 sav_block5_raw.bin \
  -o SAVEGAME_NEW.SAV

# Rebuild with comparison to original
python sav_serializer.py --block1 ... --block5 ... -o NEW.SAV --compare ORIGINAL.SAV
```

### Standalone Compression

```bash
# Compress any file
python lzss_compressor_final.py input.bin output.bin

# Decompress raw LZSS data
python lzss_decompressor_final.py compressed.bin
```

## File Formats

### OPTIONS Structure

```
[Section 1: 44-byte header + LZSS data]  <- Game settings
[Section 2: 44-byte header + LZSS data]  <- Profile data
[Section 3: 44-byte header + LZSS data]  <- Additional config
[Footer: 01 00 00 00 54]
```

### SAV Structure

> **⚠ CORRECTED (July 2026):** the "5-block" table below described a fresh
> 6-frame save; the "Raw" rows were actually LZSS-compressed frames read as raw
> bytes. The real layout is Blocks 1-2 followed by N self-contained frames
> (`[0x01][comp_size 3B LE][00 00 80 00][1 byte][adler32 4B LE][LZSS data]`),
> each decompressing to exactly 32 KB, where N grows with game progression
> (6 fresh, 14-16 played). Content such as the inventory must be located by
> decompressing frames and inspecting them, not by position.

Historical (incorrect) model kept for reference:

| Block | Format | Size | Content |
|-------|--------|------|---------|
| 1 | LZSS | 283 B | SaveGame root object |
| 2 | LZSS | 32 KB | Game state, missions, rewards |
| 3 | Raw | ~8 KB | Compact format type data |
| 4 | LZSS | 32 KB | Inventory (364 items) |
| 5 | Raw | ~6 KB | Compact format type data |

### LZSS Encoding

The game uses an LZSS variant with three encoding types:

| Type | Bits | Description |
|------|------|-------------|
| Literal | 9 | Flag 0 + 8-bit byte |
| Short match | 12 | Length 2-5, offset 1-256 |
| Long match | 18+ | Length 2-2048, offset 1-8191 |

## Documentation

Detailed specifications are in the `docs/` directory:

- [SAV File Format Specification](docs/SAV_FILE_FORMAT_SPECIFICATION.md) - Complete format spec
- [Type System Reference](docs/TYPE_SYSTEM_REFERENCE.md) - Scimitar engine type system
- [SAV Blocks Overview](docs/SAV_BLOCKS_OVERVIEW.md) - Cross-block relationships
- [JSON Data Index](docs/JSON_DATA_INDEX.md) - Extracted type descriptor data

Block-specific documentation:
- [Block 1: SaveGame Structure](docs/blocks/BLOCK1_SAVEGAME_STRUCTURE.md)
- [Block 2: Game State Structure](docs/blocks/BLOCK2_GAME_STATE_STRUCTURE.md)
- [Block 4: Inventory Structure](docs/blocks/BLOCK4_INVENTORY_STRUCTURE.md)
- [Blocks 3 & 5: Compact Format](docs/blocks/BLOCKS_3_5_COMPACT_FORMAT.md)

## Directory Structure

```
├── lzss_compressor_final.py     # Production compressor
├── lzss_decompressor_final.py   # Decompressor
├── options_serializer.py        # OPTIONS file rebuilder
├── sav_parser.py                # SAV file parser
├── sav_serializer.py            # SAV file rebuilder
├── analyze/                     # Ghidra and binary analysis scripts
├── debug_scripts/               # WinDbg, x64dbg, Cheat Engine scripts
├── docs/                        # Format specifications
│   ├── blocks/                  # Block structure docs
│   └── data/                    # Extracted JSON data
└── references/                  # Test files
```

## License

This project is for educational and research purposes. Assassin's Creed Brotherhood is a trademark of Ubisoft.
