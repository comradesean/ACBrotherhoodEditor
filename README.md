# AC Brotherhood Save File Tools

Reverse-engineered tools for Assassin's Creed Brotherhood's OPTIONS and SAV save files, built on an LZSS implementation that achieves **100% byte-for-byte accuracy** with the game's compressor.

## Tools

### Unlock Utilities
| Tool | Description |
|------|-------------|
| `acb_uplay_unlocker.py` | Unlock uPlay rewards in OPTIONS files |
| `acb_facebookcape_unlocker.py` | Unlock the Facebook capes and edit the player name in SAV game saves (PC and PS3, encrypted or decrypted) |

### OPTIONS File Tools
| Tool | Description |
|------|-------------|
| `tools/options_unpack.py` | Extract and decompress sections from OPTIONS files (auto-detects PC/PS3) |
| `tools/options_pack.py` | Rebuild OPTIONS files from decompressed sections (supports PC and PS3) |

### GUI Editor (WIP)
| Tool | Description |
|------|-------------|
| `tools/acb-options-editor/` | Qt6/C++ GUI editor for OPTIONS files (work in progress) |

## Usage

### Unlock Utilities
```bash
# Unlock uPlay rewards (OPTIONS file)
python acb_uplay_unlocker.py OPTIONS

# Unlock Facebook capes / edit player name (SAV game save)
python acb_facebookcape_unlocker.py ACBROTHERHOODSAVEGAME0.SAV   # PC
python acb_facebookcape_unlocker.py AC2_0.SAV                    # PS3
```

For encrypted PS3 saves, `PARAM.PFD` must sit in the same directory as the
SAV; the file is decrypted automatically and re-encrypted on save (requires
`pycryptodome`). Already-decrypted PS3 saves need neither.

### OPTIONS File Tools

#### Unpack an OPTIONS file
```bash
# Auto-detect format, extract all sections
python tools/options_unpack.py OPTIONS.bin

# Extract specific section (1-4)
python tools/options_unpack.py OPTIONS.bin 2

# Force specific format
python tools/options_unpack.py OPTIONS.bin --pc
python tools/options_unpack.py OPTIONS.PS3 --ps3

# Custom output directory
python tools/options_unpack.py OPTIONS.bin -o ./output/
```
Outputs: `section1.bin`, `section2.bin`, `section3.bin`, and optionally `section4.bin`

#### Pack sections into an OPTIONS file
```bash
# PC format (3 sections)
python tools/options_pack.py section1.bin section2.bin section3.bin -o OPTIONS.bin --pc

# PS3 format (4 sections)
python tools/options_pack.py section1.bin section2.bin section3.bin section4.bin -o OPTIONS.PS3 --ps3

# With validation (decompresses and verifies output)
python tools/options_pack.py section1.bin section2.bin section3.bin -o OPTIONS.bin --pc --validate
```

## Section Structure

Each OPTIONS file contains 3 or 4 compressed sections. Section 4 is optional on both PC and PS3.

| Section | Name | Description |
|---------|------|-------------|
| 1 | SaveGame | Core save game data |
| 2 | AssassinGlobalProfileData | Global profile settings |
| 3 | AssassinSingleProfileData | Single-player profile data |
| 4 | AssassinMultiProfileData | Multiplayer profile data (optional) |

## File Structure

### PC OPTIONS File
```
[Section 1: 44-byte header + LZSS compressed data]
[Section 2: 44-byte header + LZSS compressed data]
[Section 3: 44-byte header + LZSS compressed data]
[8-byte gap marker (if Section 4 present)]
[Section 4: 44-byte header + LZSS compressed data (optional)]
[Footer: 01 00 00 00 XX]
```

### PS3 OPTIONS File
```
[8-byte prefix: size (BE) + CRC32 (BE)]
[Section 1: 44-byte header + LZSS compressed data]
[Section 2: 44-byte header + LZSS compressed data]
[Section 3: 44-byte header + LZSS compressed data]
[8-byte gap marker (if Section 4 present)]
[Section 4: 44-byte header + LZSS compressed data (optional)]
[Zero padding to 51,200 bytes]
```

## Documentation

See `docs/` for detailed reverse engineering notes:
- `LZSS_LOGIC_FLOW_ANALYSIS.md` - Compression algorithm details
- `PS3_OPTIONS_FORMAT.md` - PS3 format specification
- `PS3_vs_PC_STRUCTURE_ANALYSIS.md` - PC/PS3 format differences
- `ACB_OPTIONS_Header_Complete_Specification.md` - Complete header specification

## SAV File Structure

Game saves (PC and PS3) share one layout; PS3 adds an 8-byte size+CRC32
prefix and zero-padding to 307,200 bytes, and console saves are encrypted:

```
[Block 1: 44-byte header + LZSS data]   SaveGame root (player name)
[Block 2: 44-byte header + LZSS data]   Game state
[Frame 0..N-1], each:
  [0x01][comp_size 3B LE][00 00 80 00][1 byte][adler32 4B LE][LZSS data]
```

Every frame decompresses to exactly 32 KB. The frame count grows with game
progression (6 on a fresh save, 14-16 on played ones), so the frame holding
the inventory — and the cape ownership records — must be located by content,
not by position. See `docs_gamesave/` for the full format documentation.

## Requirements

- Python 3.6+
- No external dependencies for OPTIONS tools and decrypted saves
- `pycryptodome` (optional) — only for encrypted PS3 SAV saves

## License

This project is for educational and research purposes.
