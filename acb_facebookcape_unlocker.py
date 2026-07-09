#!/usr/bin/env python3
"""
ACB Brotherhood Facebook Cape Unlocker
=======================================

A self-contained tool for unlocking Facebook-exclusive capes and changing
player name in AC Brotherhood SAV files.
Supports both PC and PS3 formats (encrypted or decrypted) with a console UI.

If a PS3 SAV is encrypted, PARAM.PFD must be present in the same directory.
The file will be decrypted automatically before editing and re-encrypted after
saving. Already-decrypted files are left in their existing state.

File structure (PC and PS3 share it; PS3 adds an 8-byte size+CRC32 prefix and
zero-padding to 307200 bytes):
  Block 1: LZSS, 44-byte header — SaveGame root (player name lives here)
  Block 2: LZSS, 44-byte header — game state
  Then N self-contained frames, each:
    [0x01][comp_size 3B LE][00 00 80 00][1 byte][adler32 4B LE][LZSS data]
  Each frame decompresses to 32 KB. N grows with game progression (6 on a
  fresh save, 14-16 on played saves), and the frame holding the inventory --
  and with it the cape ownership records -- moves accordingly, so it must be
  located by content, not position.

Cape record (inside the decompressed inventory frame):
  [cape_hash 4B] [8 zeros] [0x0B marker] [ownership_flag 1B] [cape_id 1B]

Cape identification:
  Venetian Cape: Hash 0x4470F39F, ID 0x0E
  Medici Cape:   Hash 0xDD79A225, ID 0x11

Ownership flag is at hash_offset + 13, followed by cape_id at hash_offset + 14.

Name structure in Block 1:
  [1A] [00 0B] [length 4B LE] [string bytes]
  Default name is "Desmond" (7 bytes)

Usage:
    python acb_facebookcape_unlocker.py save.SAV
    python acb_facebookcape_unlocker.py AC2_0.SAV
"""

import sys
import os
import struct

try:
    import curses
    HAS_CURSES = True
except ImportError:
    HAS_CURSES = False

try:
    from Crypto.Cipher import AES
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# Import LZSS compression/decompression
from lzss import compress, decompress

# =============================================================================
# CONSTANTS
# =============================================================================

# Cape definitions: (hash, expected_id, name)
# The cape_id appears at hash+14 and is used for validation
CAPE_DEFINITIONS = [
    (0x4470F39F, 0x0E, "Venetian Cape"),
    (0xDD79A225, 0x11, "Medici Cape"),
]

# Ownership record layout, measured from the start of the 4-byte cape hash:
#   [hash 4B] [8 zero bytes] [0x0B marker] [ownership_flag 1B] [cape_id 1B]
#    +0..+3    +4..+11        +12           +13                 +14
# All four fixed fields are validated together when locating a cape (see
# find_cape_record). The hash + cape_id alone are NOT sufficient: the same
# cape_id is reused by many inventory entries, and 4-byte hash look-alikes
# occur elsewhere in the 32 KB frames being scanned. Requiring the zero-run
# and the 0x0B marker rejects those impostors.
CAPE_ZERO_RUN_OFFSET = 4
CAPE_ZERO_RUN_LENGTH = 8
CAPE_MARKER_OFFSET = 12
CAPE_MARKER = 0x0B
OWNERSHIP_FLAG_OFFSET = 13
CAPE_ID_OFFSET = 14

# Name string marker pattern in Block 1: [1A] [00 0B] [length 4B] [string]
NAME_MARKER = bytes([0x1A, 0x00, 0x0B])
MAX_NAME_LENGTH = 17  # Game limit

# PS3 file size (padded)
PS3_FILE_SIZE = 307200  # 0x4B000

# =============================================================================
# PS3 CRYPTO  (ported from pfd_util.c / bucanero/pfd_sfo_tools)
# =============================================================================
#
# Keys from games.conf for BLES00909 (Assassin's Creed Brotherhood):
#   syscon_manager_key  = D413B89663E1FE9F75143D3BB4565274
#   secure_file_id:*    = 0D0E0A0D0B0E0E0F0A0A0A0A0A0A0A0A
#
# Crypto chain for decryption:
#   1. Parse PARAM.PFD  → 64-byte encrypted entry_key + file_size (BE u64)
#   2. Derive iv_hash_key from secure_file_id (hardcoded bytes at i=1,2,5,8)
#   3. AES-128-CBC decrypt entry_key (key=syscon_manager_key, iv=iv_hash_key)
#   4. entry_key[:16]  →  file AES-128 key
#   5. Per 16-byte block i:
#        counter  = pack('>QQ', i, 0)            # PS3 big-endian
#        enc_ctr  = AES_ECB_encrypt(key, counter)
#        dec_blk  = AES_ECB_decrypt(key, block)
#        plain    = dec_blk XOR enc_ctr
# Encryption reverses steps 5: XOR first, then ECB-encrypt.

_SYSCON_MANAGER_KEY = bytes.fromhex("D413B89663E1FE9F75143D3BB4565274")
_SECURE_FILE_ID     = bytes.fromhex("0D0E0A0D0B0E0E0F0A0A0A0A0A0A0A0A")

_PFD_ENTRY_TABLE_OFFSET = 0x240
_PFD_ENTRY_SIZE         = 0x110
_PFD_ENTRY_NAME_OFF     = 0x08
_PFD_ENTRY_NAME_LEN     = 65
_PFD_ENTRY_KEY_OFF      = 0x50
_PFD_ENTRY_KEY_LEN      = 64
_PFD_ENTRY_FSIZE_OFF    = 0x108
_PFD_MAX_ENTRIES        = 0x72
_AES_BLOCK              = 16


def _find_pfd_entry(pfd_data: bytes, filename: str):
    """Find entry in PARAM.PFD and return (enc_key_64b, file_size_be)."""
    for i in range(_PFD_MAX_ENTRIES):
        off = _PFD_ENTRY_TABLE_OFFSET + i * _PFD_ENTRY_SIZE
        if off + _PFD_ENTRY_SIZE > len(pfd_data):
            break
        raw = pfd_data[off + _PFD_ENTRY_NAME_OFF : off + _PFD_ENTRY_NAME_OFF + _PFD_ENTRY_NAME_LEN]
        name = raw.split(b'\x00')[0].decode('ascii', errors='replace')
        if name == filename:
            enc_key = pfd_data[off + _PFD_ENTRY_KEY_OFF : off + _PFD_ENTRY_KEY_OFF + _PFD_ENTRY_KEY_LEN]
            fsize   = struct.unpack_from('>Q', pfd_data, off + _PFD_ENTRY_FSIZE_OFF)[0]
            return enc_key, fsize
    return None, None


def _derive_iv_hash_key(secure_key: bytes) -> bytes:
    """Build iv_hash_key from secure_file_id (mirrors _get_aes_details_pfd)."""
    iv = bytearray(16)
    j = 0
    for i in range(16):
        if   i == 1: iv[i] = 11
        elif i == 2: iv[i] = 15
        elif i == 5: iv[i] = 14
        elif i == 8: iv[i] = 10
        else:
            iv[i] = secure_key[j]; j += 1
    return bytes(iv)


def _get_file_aes_key(enc_entry_key: bytes) -> bytes:
    """AES-128-CBC decrypt the 64-byte entry key; return first 16 bytes."""
    iv  = _derive_iv_hash_key(_SECURE_FILE_ID)
    dec = AES.new(_SYSCON_MANAGER_KEY, AES.MODE_CBC, iv=iv).decrypt(enc_entry_key)
    return dec[:16]


def _ps3_decrypt_data(enc_data: bytes, file_key: bytes, file_size: int) -> bytes:
    """Decrypt PS3 save data (ECB-decrypt then XOR counter, per block)."""
    aligned = ((file_size + _AES_BLOCK - 1) // _AES_BLOCK) * _AES_BLOCK
    if len(enc_data) < aligned:
        enc_data = enc_data + b'\x00' * (aligned - len(enc_data))
    aes_enc = AES.new(file_key, AES.MODE_ECB)
    aes_dec = AES.new(file_key, AES.MODE_ECB)
    result  = bytearray(aligned)
    for i in range(aligned // _AES_BLOCK):
        off     = i * _AES_BLOCK
        ctr     = aes_enc.encrypt(struct.pack('>QQ', i, 0))
        dec_blk = aes_dec.decrypt(enc_data[off:off + _AES_BLOCK])
        for j in range(_AES_BLOCK):
            result[off + j] = dec_blk[j] ^ ctr[j]
    return bytes(result[:file_size])


def _ps3_encrypt_data(plain_data: bytes, file_key: bytes, file_size: int) -> bytes:
    """Encrypt PS3 save data (XOR counter then ECB-encrypt, per block)."""
    aligned = ((file_size + _AES_BLOCK - 1) // _AES_BLOCK) * _AES_BLOCK
    work    = bytearray(plain_data[:file_size].ljust(aligned, b'\x00'))
    aes_ctr = AES.new(file_key, AES.MODE_ECB)
    aes_blk = AES.new(file_key, AES.MODE_ECB)
    for i in range(aligned // _AES_BLOCK):
        off = i * _AES_BLOCK
        ctr = aes_ctr.encrypt(struct.pack('>QQ', i, 0))
        for j in range(_AES_BLOCK):
            work[off + j] ^= ctr[j]
        enc = aes_blk.encrypt(bytes(work[off:off + _AES_BLOCK]))
        work[off:off + _AES_BLOCK] = enc
    return bytes(work)  # full aligned size


def ps3_decrypt_file(sav_path: str) -> bytes:
    """
    Decrypt a PS3 SAV using PARAM.PFD from the same directory.
    Returns the decrypted file bytes.
    """
    sav_dir  = os.path.dirname(os.path.abspath(sav_path))
    filename = os.path.basename(sav_path)
    pfd_path = os.path.join(sav_dir, 'PARAM.PFD')

    if not os.path.isfile(pfd_path):
        raise FileNotFoundError(
            f"PARAM.PFD not found in {sav_dir}\n"
            "  It must be present alongside the encrypted SAV for decryption."
        )

    with open(pfd_path, 'rb') as f:
        pfd_data = f.read()
    with open(sav_path, 'rb') as f:
        enc_data = f.read()

    enc_key, file_size = _find_pfd_entry(pfd_data, filename)
    if enc_key is None:
        raise ValueError(f"'{filename}' not found in PARAM.PFD")

    file_key  = _get_file_aes_key(enc_key)
    decrypted = _ps3_decrypt_data(enc_data, file_key, file_size)
    print(f"  Decrypted '{filename}' ({file_size} bytes) using PARAM.PFD")
    return decrypted


def ps3_encrypt_file(plain_bytes: bytes, sav_path: str) -> bytes:
    """
    Encrypt plain SAV bytes back to PS3 format using PARAM.PFD.
    Returns the encrypted file bytes (padded to PS3_FILE_SIZE).
    """
    sav_dir  = os.path.dirname(os.path.abspath(sav_path))
    filename = os.path.basename(sav_path)
    pfd_path = os.path.join(sav_dir, 'PARAM.PFD')

    with open(pfd_path, 'rb') as f:
        pfd_data = f.read()

    enc_key, pfd_size = _find_pfd_entry(pfd_data, filename)
    if enc_key is None:
        raise ValueError(f"'{filename}' not found in PARAM.PFD")

    file_key  = _get_file_aes_key(enc_key)
    file_size = len(plain_bytes)
    encrypted = _ps3_encrypt_data(plain_bytes, file_key, file_size)

    # Pad to PS3_FILE_SIZE
    if len(encrypted) < PS3_FILE_SIZE:
        encrypted = encrypted + b'\x00' * (PS3_FILE_SIZE - len(encrypted))

    print(f"  Re-encrypted '{filename}' ({file_size} bytes)")
    return encrypted


# =============================================================================
# CHECKSUMS
# =============================================================================

def adler32_zero_seed(data: bytes) -> int:
    """Adler-32 with zero seed (AC Brotherhood variant)."""
    MOD_ADLER = 65521
    s1 = 0
    s2 = 0
    for byte in data:
        s1 = (s1 + byte) % MOD_ADLER
        s2 = (s2 + s1) % MOD_ADLER
    return (s2 << 16) | s1


def crc32_ps3(data: bytes) -> int:
    """CRC32 with PS3 parameters."""
    crc = 0xBAE23CD0
    for byte in data:
        byte = int('{:08b}'.format(byte)[::-1], 2)
        crc ^= (byte << 24)
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    crc = int('{:032b}'.format(crc)[::-1], 2)
    return (crc ^ 0xFFFFFFFF) & 0xFFFFFFFF




# =============================================================================
# FORMAT DETECTION
# =============================================================================

def detect_format(data: bytes) -> str:
    """
    Detect PC, PS3 (decrypted), PS3-encrypted, or unknown format.

    Detection is driven by structural signatures first and file size only as a
    last-resort fallback. File size is a poor discriminator: a corrupt or
    foreign file padded to the PS3 length should not be assumed encrypted, and a
    decrypted PS3 save should be recognised by its header rather than by being
    exactly PS3_FILE_SIZE bytes.

    Returns one of: 'PC', 'PS3', 'PS3-encrypted', 'unknown'
    """
    # 1. PS3 decrypted — positive signature: the 8-byte prefix (payload size BE +
    #    CRC32 BE) verifies against the payload. This is the strong signal, so it
    #    leads regardless of total file size.
    if len(data) >= 8:
        prefix_size = struct.unpack('>I', data[0:4])[0]
        prefix_crc  = struct.unpack('>I', data[4:8])[0]
        if 0 < prefix_size <= len(data) - 8:
            if crc32_ps3(data[8:8 + prefix_size]) == prefix_crc:
                return 'PS3'

    # 2. PC — positive signature: the GUID-low magic in the Block 1 header.
    if len(data) > 0x14 and data[0x10:0x14] == b'\x33\xAA\xFB\x57':
        return 'PC'

    # 3. No plaintext signature matched. A file padded to the PS3 save size is
    #    almost certainly an encrypted PS3 save (ciphertext is effectively random,
    #    so neither signature above can match). Anything else is unrecognised.
    if len(data) == PS3_FILE_SIZE:
        return 'PS3-encrypted'

    return 'unknown'


# =============================================================================
# SAV PARSING (shared PC/PS3)
# =============================================================================

# Frame header: [0x01][comp_size 3B LE][00 00 80 00][1 byte][adler32 4B LE]
_FRAME_HEADER_SIZE = 13


def _scan_frames(payload: bytes, start: int) -> list:
    """
    Enumerate the LZSS frames that follow Block 2.

    A candidate header is accepted only if the adler32 it stores matches the
    data span it declares, so stale frame-shaped bytes in growth space cannot
    produce phantom frames.

    Returns a list of (header_offset, comp_size) tuples.
    """
    frames = []
    pos = start
    while pos < len(payload) - _FRAME_HEADER_SIZE:
        if payload[pos] == 0x01 and payload[pos+4:pos+8] == b'\x00\x00\x80\x00':
            comp_size = struct.unpack('<I', payload[pos+1:pos+4] + b'\x00')[0]
            data_start = pos + _FRAME_HEADER_SIZE
            if 0 < comp_size <= len(payload) - data_start:
                stored_checksum = struct.unpack('<I', payload[pos+9:pos+13])[0]
                if adler32_zero_seed(payload[data_start:data_start + comp_size]) == stored_checksum:
                    frames.append((pos, comp_size))
                    pos = data_start + comp_size
                    continue
        pos += 1
    return frames


def _patch_frame_header(payload: bytearray, header_offset: int, comp_size: int,
                        checksum: int) -> None:
    """Write a frame's compressed size and adler32 into its 13-byte header."""
    payload[header_offset+1:header_offset+4] = struct.pack('<I', comp_size)[:3]
    payload[header_offset+9:header_offset+13] = struct.pack('<I', checksum)


def parse_sav_blocks(data: bytes, is_ps3: bool) -> dict:
    """
    Parse a decrypted SAV file: blocks 1-2, then the frame sequence.

    The frame holding the cape records is located by content — decompress
    every frame and look for both cape records — because its position varies
    with game progression. A save may carry the cape records in more than one
    frame; all of them are returned so edits can be applied consistently.
    """
    if is_ps3:
        if len(data) < 8:
            raise ValueError("File too small for PS3 SAV format")
        ps3_size = struct.unpack('>I', data[0:4])[0]
        if ps3_size > len(data) - 8:
            raise ValueError("PS3 prefix declares more data than the file holds")
        payload = data[8:8 + ps3_size]
    else:
        payload = data

    if len(payload) < 88:
        raise ValueError("File too small for SAV block structure")

    # Block 1: 44-byte header, compressed size at +0x20 (LE)
    b1_comp_size = struct.unpack('<I', payload[0x20:0x24])[0]

    # Block 2: 44-byte header immediately after Block 1
    b2_header_offset = 44 + b1_comp_size
    if b2_header_offset + 44 > len(payload):
        raise ValueError("Block 2 header lies beyond end of file")
    b2_comp_size = struct.unpack('<I', payload[b2_header_offset + 0x20:b2_header_offset + 0x24])[0]

    # Everything after Block 2 is a sequence of self-contained LZSS frames
    frame_area_offset = b2_header_offset + 44 + b2_comp_size
    frames = _scan_frames(payload, frame_area_offset)
    if not frames:
        raise ValueError("No valid LZSS frames found after Block 2")

    # Select the frame(s) holding the cape ownership records by content
    cape_frames = []
    for header_offset, comp_size in frames:
        frame_data = decompress(payload[header_offset + _FRAME_HEADER_SIZE:
                                         header_offset + _FRAME_HEADER_SIZE + comp_size])
        if all(find_cape_record(frame_data, cape_hash, cape_id) != -1
               for cape_hash, cape_id, _ in CAPE_DEFINITIONS):
            cape_frames.append((header_offset, comp_size))

    if cape_frames:
        primary_offset, primary_size = cape_frames[0]
        cape_frame_compressed = payload[primary_offset + _FRAME_HEADER_SIZE:
                                    primary_offset + _FRAME_HEADER_SIZE + primary_size]
    else:
        cape_frame_compressed = b''

    return {
        'is_ps3': is_ps3,
        'payload': bytes(payload),
        'block1_comp_size': b1_comp_size,
        'block1_compressed': payload[44:44 + b1_comp_size],
        'block2_header_offset': b2_header_offset,
        'frames': frames,
        'cape_frames': cape_frames,
        'cape_frame_compressed': cape_frame_compressed,
    }


# =============================================================================
# NAME HANDLING
# =============================================================================

def find_name_in_block1(data: bytes) -> tuple:
    """
    Find the player name in Block 1.
    Returns (offset, length, name) where offset is the start of the length field.
    Returns (None, None, None) if not found.
    """
    pos = 0
    while True:
        pos = data.find(NAME_MARKER, pos)
        if pos == -1:
            return None, None, None

        length_offset = pos + 3
        if length_offset + 4 > len(data):
            pos += 1
            continue

        name_length = struct.unpack('<I', data[length_offset:length_offset + 4])[0]

        if 1 <= name_length <= 64:
            name_offset = length_offset + 4
            if name_offset + name_length <= len(data):
                name = data[name_offset:name_offset + name_length].decode('utf-8', errors='replace')
                return length_offset, name_length, name

        pos += 1

    return None, None, None


def change_name_in_block1(data: bytearray, new_name: str) -> bytearray:
    """
    Change the player name in Block 1.

    Block 1 contains internal size fields at offsets 0x0E and 0x91 that must be
    adjusted when the name length changes. These are cumulative size fields that
    include the name string in their calculation.
    """
    length_offset, old_length, old_name = find_name_in_block1(data)

    if length_offset is None:
        raise ValueError("Could not find name in Block 1")

    new_name_bytes = new_name.encode('utf-8')

    # Enforce max length
    if len(new_name_bytes) > MAX_NAME_LENGTH:
        new_name_bytes = new_name_bytes[:MAX_NAME_LENGTH]
        print(f"WARNING: Name truncated to {MAX_NAME_LENGTH} characters")

    new_length = len(new_name_bytes)
    length_diff = new_length - old_length
    print(f"Name: \"{old_name}\" -> \"{new_name_bytes.decode('utf-8')}\" (length: {old_length} -> {new_length})")

    # Build new Block 1 data with name replaced
    name_offset = length_offset + 4

    result = bytearray()
    result.extend(data[:length_offset])  # Everything before length field
    result.extend(struct.pack('<I', new_length))  # New length
    result.extend(new_name_bytes)  # New name
    result.extend(data[name_offset + old_length:])  # Everything after old name

    # Adjust internal size fields by the length difference
    # These fields are cumulative sizes that include the name string
    # Single-byte size fields
    SIZE_FIELD_OFFSETS_1BYTE = [0x0E, 0x91]
    for offset in SIZE_FIELD_OFFSETS_1BYTE:
        if offset < len(result):
            old_val = result[offset]
            new_val = old_val + length_diff
            if 0 <= new_val <= 255:
                result[offset] = new_val
                print(f"  Size field at 0x{offset:02X}: 0x{old_val:02X} -> 0x{new_val:02X}")

    # 2-byte size field at 0x12
    if 0x14 <= len(result):
        old_val = struct.unpack('<H', result[0x12:0x14])[0]
        new_val = old_val + length_diff
        if 0 <= new_val <= 65535:
            result[0x12:0x14] = struct.pack('<H', new_val)
            print(f"  Size field at 0x12 (2-byte): {old_val} -> {new_val}")

    return result


# =============================================================================
# CAPE ACCESS
# =============================================================================

def find_cape_record(data: bytes, cape_hash: int, expected_id: int) -> int:
    """
    Find a cape ownership record in a decompressed inventory frame by
    searching for its hash.

    Cape record: [hash 4B] [8 zeros] [0x0B marker] [flag 1B] [cape_id 1B]

    Returns the offset of the ownership flag, or -1 if not found.

    The whole fixed structure is validated, not just the hash: the 8-byte zero
    run, the 0x0B marker, and the cape_id must all line up. Matching on the hash
    (and even the cape_id) alone produces false positives, because the cape_id
    is shared across many inventory entries and 4-byte hash look-alikes occur
    elsewhere in the 32 KB frames being scanned.
    """
    hash_bytes = struct.pack('<I', cape_hash)
    pos = 0

    while True:
        pos = data.find(hash_bytes, pos)
        if pos == -1:
            return -1

        id_offset = pos + CAPE_ID_OFFSET
        zero_run_end = pos + CAPE_ZERO_RUN_OFFSET + CAPE_ZERO_RUN_LENGTH
        if id_offset < len(data):
            is_record = (
                data[pos + CAPE_ZERO_RUN_OFFSET:zero_run_end] == b'\x00' * CAPE_ZERO_RUN_LENGTH
                and data[pos + CAPE_MARKER_OFFSET] == CAPE_MARKER
                and data[id_offset] == expected_id
            )
            if is_record:
                return pos + OWNERSHIP_FLAG_OFFSET

        pos += 1


def get_cape_state(data: bytes, cape_hash: int, expected_id: int) -> bool:
    """Get cape unlock state (True = unlocked)."""
    offset = find_cape_record(data, cape_hash, expected_id)
    if offset == -1 or offset >= len(data):
        return False
    return data[offset] != 0


def set_cape_state(data: bytearray, cape_hash: int, expected_id: int, unlocked: bool):
    """Set cape unlock state."""
    offset = find_cape_record(data, cape_hash, expected_id)
    if offset != -1 and offset < len(data):
        data[offset] = 0x01 if unlocked else 0x00


# =============================================================================
# FILE SERIALIZATION
# =============================================================================

def _build_block1_header(compressed_data: bytes, uncompressed_size: int, is_ps3: bool) -> bytes:
    """Build 44-byte Block 1 header with correct endianness."""
    checksum = adler32_zero_seed(compressed_data)
    comp_size = len(compressed_data)

    if is_ps3:
        # PS3: first 3 fields big-endian, rest little-endian
        header = bytearray()
        header.extend(struct.pack('>I', 0x00000016))
        header.extend(struct.pack('>I', 0x00FEDBAC))
        header.extend(struct.pack('>I', comp_size + 32))
        header.extend(struct.pack('<I', uncompressed_size))
        header.extend(struct.pack('<I', 0x57FBAA33))
        header.extend(struct.pack('<I', 0x1004FA99))
        header.extend(struct.pack('<I', 0x00020001))
        header.extend(struct.pack('<I', 0x01000080))
        header.extend(struct.pack('<I', comp_size))
        header.extend(struct.pack('<I', uncompressed_size))
        header.extend(struct.pack('<I', checksum))
        return bytes(header)
    else:
        # PC: all little-endian
        return struct.pack('<11I',
            0x00000016, 0x00FEDBAC, comp_size + 32, uncompressed_size,
            0x57FBAA33, 0x1004FA99, 0x00020001, 0x01000080,
            comp_size, uncompressed_size, checksum)


def save_sav(filepath: str, blocks: dict, block1_data: bytearray,
             cape_frame_data: bytearray, block1_modified: bool, capes_modified: bool,
             was_encrypted: bool = False):
    """
    Save a modified SAV (PC or PS3) by splicing changed pieces into the
    original payload, leaving every untouched byte identical.

    Cape changes are applied to EVERY frame that holds the cape records (a
    save can carry more than one copy), each recompressed with its header's
    size and adler32 updated. If was_encrypted is True the PS3 output is
    re-encrypted using PARAM.PFD from the same directory as filepath.
    """
    is_ps3 = blocks['is_ps3']
    payload = bytearray(blocks['payload'])
    frames_size_diff = 0

    if capes_modified:
        # Splice back-to-front so earlier frame offsets stay valid
        for header_offset, comp_size in sorted(blocks['cape_frames'], reverse=True):
            data_start = header_offset + _FRAME_HEADER_SIZE
            frame_data = bytearray(decompress(bytes(payload[data_start:data_start + comp_size])))
            for cape_hash, cape_id, _ in CAPE_DEFINITIONS:
                set_cape_state(frame_data, cape_hash, cape_id,
                               get_cape_state(cape_frame_data, cape_hash, cape_id))
            new_compressed = compress(bytes(frame_data))
            _patch_frame_header(payload, header_offset, len(new_compressed),
                                adler32_zero_seed(new_compressed))
            payload[data_start:data_start + comp_size] = new_compressed
            frames_size_diff += len(new_compressed) - comp_size

    # Block 2's Field1 counts the bytes that follow it, so only size changes
    # in the frame area affect it (Block 1 sits before it and does not).
    if frames_size_diff != 0:
        b2h = blocks['block2_header_offset']
        field1_fmt = '>I' if is_ps3 else '<I'
        old_field1 = struct.unpack(field1_fmt, payload[b2h:b2h+4])[0]
        payload[b2h:b2h+4] = struct.pack(field1_fmt, old_field1 + frames_size_diff)

    if block1_modified:
        block1_compressed = compress(bytes(block1_data))
        block1_header = _build_block1_header(block1_compressed, len(block1_data), is_ps3)
        payload[0:44 + blocks['block1_comp_size']] = block1_header + block1_compressed

    if is_ps3:
        output = bytearray()
        output.extend(struct.pack('>I', len(payload)))
        output.extend(struct.pack('>I', crc32_ps3(bytes(payload))))
        output.extend(payload)
        if len(output) < PS3_FILE_SIZE:
            output.extend(b'\x00' * (PS3_FILE_SIZE - len(output)))
        if was_encrypted:
            print("  Re-encrypting modified SAV...")
            output = bytearray(ps3_encrypt_file(bytes(output), filepath))
    else:
        output = payload

    with open(filepath, 'wb') as f:
        f.write(output)


# =============================================================================
# UI HELPERS
# =============================================================================

class UnlockItem:
    def __init__(self, name: str, category: str, item_type: str,
                 hash_value: int = None, expected_id: int = None, is_name: bool = False):
        self.name = name
        self.category = category
        self.item_type = item_type
        self.hash_value = hash_value
        self.expected_id = expected_id
        self.is_name = is_name
        self.checked = False
        self.name_value = ""  # For name field


def build_unlock_items() -> list:
    items = []
    # Name item
    items.append(UnlockItem("Player Name", "PLAYER", "name", is_name=True))
    # Cape items
    for hash_val, expected_id, name in CAPE_DEFINITIONS:
        items.append(UnlockItem(name, "FACEBOOK CAPES", "cape",
                                hash_value=hash_val, expected_id=expected_id))
    return items


def load_unlock_states(items: list, block1_data: bytes, cape_frame_data: bytes):
    """Load current states from decompressed block data."""
    for item in items:
        if item.is_name:
            _, _, name = find_name_in_block1(block1_data)
            item.name_value = name if name else "Unknown"
        else:
            item.checked = get_cape_state(cape_frame_data, item.hash_value, item.expected_id)


def apply_unlock_states(items: list, block1_data: bytearray, cape_frame_data: bytearray) -> None:
    """Apply unlock states to block data."""
    for item in items:
        if item.is_name:
            continue  # Name handled separately
        old_state = get_cape_state(cape_frame_data, item.hash_value, item.expected_id)
        if old_state != item.checked:
            set_cape_state(cape_frame_data, item.hash_value, item.expected_id, item.checked)


# =============================================================================
# CURSES UI
# =============================================================================

def run_ui(stdscr, filepath: str, platform: str, blocks: dict,
           block1_data: bytearray, cape_frame_data: bytearray) -> tuple:
    """Run the curses UI. Returns (should_save, new_name or None)."""
    curses.curs_set(0)
    curses.use_default_colors()

    if curses.has_colors():
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)

    items = build_unlock_items()
    load_unlock_states(items, block1_data, cape_frame_data)

    selected = 0
    modified = False
    new_name = None

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Title
        title = " ACB Brotherhood Facebook Cape Unlocker "
        stdscr.addstr(0, max(0, (width - len(title)) // 2), title,
                      curses.A_BOLD | curses.A_REVERSE)

        # File info
        filename = os.path.basename(filepath)
        info = f" File: {filename} ({platform} format) "
        stdscr.addstr(2, 2, info, curses.color_pair(1) if curses.has_colors() else 0)

        if modified:
            stdscr.addstr(2, 2 + len(info) + 1, "[MODIFIED]",
                          curses.color_pair(3) if curses.has_colors() else curses.A_BOLD)

        # Items
        row = 4
        current_category = None

        for i, item in enumerate(items):
            if row >= height - 4:
                break

            # Category header
            if item.category != current_category:
                current_category = item.category
                if row > 4:
                    row += 1
                stdscr.addstr(row, 2, current_category,
                              curses.A_BOLD | (curses.color_pair(2) if curses.has_colors() else 0))
                row += 1

            attr = curses.A_REVERSE if i == selected else 0

            if item.is_name:
                # Name display
                display_name = new_name if new_name else item.name_value
                stdscr.addstr(row, 4, f"{item.name}: ", attr)
                stdscr.addstr(row, 4 + len(item.name) + 2, display_name, attr | curses.A_BOLD)
                stdscr.addstr(row, 4 + len(item.name) + 2 + len(display_name) + 1,
                              "[Enter to edit]", curses.A_DIM)
            else:
                # Checkbox
                checkbox = "[x]" if item.checked else "[ ]"
                stdscr.addstr(row, 4, checkbox, attr)
                stdscr.addstr(row, 8, item.name, attr)
            row += 1

        # Footer
        footer_row = height - 2
        footer = " [Space] Toggle  [Enter] Edit Name  [A] All On  [N] All Off  [S] Save  [Q] Quit "
        stdscr.addstr(footer_row, max(0, (width - len(footer)) // 2), footer, curses.A_REVERSE)

        stdscr.refresh()

        # Input
        key = stdscr.getch()

        if key in (ord('q'), ord('Q'), 27):  # Q or Escape
            if modified:
                stdscr.addstr(height - 3, 2, "Discard changes? (y/n) ", curses.A_BOLD)
                stdscr.refresh()
                confirm = stdscr.getch()
                if confirm not in (ord('y'), ord('Y')):
                    continue
            return (False, None)

        elif key in (ord('s'), ord('S')):
            # Apply changes to block data
            apply_unlock_states(items, block1_data, cape_frame_data)
            return (True, new_name)

        elif key in (curses.KEY_UP, ord('k')):
            selected = max(0, selected - 1)

        elif key in (curses.KEY_DOWN, ord('j')):
            selected = min(len(items) - 1, selected + 1)

        elif key in (ord(' '),):
            if not items[selected].is_name:
                items[selected].checked = not items[selected].checked
                modified = True

        elif key in (curses.KEY_ENTER, 10):
            if items[selected].is_name:
                # Edit name
                curses.echo()
                curses.curs_set(1)
                stdscr.addstr(height - 3, 2, "Enter new name (max 17 chars): ")
                stdscr.clrtoeol()
                stdscr.refresh()
                try:
                    input_bytes = stdscr.getstr(height - 3, 33, MAX_NAME_LENGTH)
                    input_str = input_bytes.decode('utf-8', errors='replace').strip()
                    if input_str:
                        new_name = input_str
                        modified = True
                except curses.error:
                    pass
                curses.noecho()
                curses.curs_set(0)
            else:
                items[selected].checked = not items[selected].checked
                modified = True

        elif key in (ord('a'), ord('A')):
            for item in items:
                if not item.is_name:
                    item.checked = True
            modified = True

        elif key in (ord('n'), ord('N')):
            for item in items:
                if not item.is_name:
                    item.checked = False
            modified = True

    return (False, None)


# =============================================================================
# TEXT UI (fallback)
# =============================================================================

def clear_screen():
    """Clear the console screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def run_text_ui(filepath: str, platform: str, blocks: dict,
                block1_data: bytearray, cape_frame_data: bytearray) -> tuple:
    """Run simple text-based UI. Returns (should_save, new_name or None)."""
    items = build_unlock_items()
    load_unlock_states(items, block1_data, cape_frame_data)
    new_name = None

    while True:
        clear_screen()
        print("=" * 60)
        print(" ACB Brotherhood Facebook Cape Unlocker")
        print("=" * 60)
        print(f" File: {os.path.basename(filepath)} ({platform} format)")
        print("=" * 60)
        print()

        # Display items grouped by category
        current_category = None
        item_num = 1

        for item in items:
            if item.category != current_category:
                current_category = item.category
                print(f"\n  {current_category}")
                print("  " + "-" * 40)

            if item.is_name:
                display_name = new_name if new_name else item.name_value
                print(f"  {item_num:2d}. {item.name}: {display_name}")
            else:
                checkbox = "[x]" if item.checked else "[ ]"
                print(f"  {item_num:2d}. {checkbox} {item.name}")
            item_num += 1

        print()
        print("=" * 60)
        print(" Commands: 1-{} toggle/edit | A=all on | N=all off | S=save | Q=quit".format(len(items)))
        print("=" * 60)

        try:
            choice = input("\n> ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return (False, None)

        if choice == 'Q':
            return (False, None)
        elif choice == 'S':
            apply_unlock_states(items, block1_data, cape_frame_data)
            return (True, new_name)
        elif choice == 'A':
            for item in items:
                if not item.is_name:
                    item.checked = True
        elif choice == 'N':
            for item in items:
                if not item.is_name:
                    item.checked = False
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(items):
                if items[idx].is_name:
                    try:
                        new_input = input(f"  Enter new name (max {MAX_NAME_LENGTH} chars): ").strip()
                        if new_input:
                            new_name = new_input[:MAX_NAME_LENGTH]
                    except EOFError:
                        pass
                else:
                    items[idx].checked = not items[idx].checked

    return (False, None)


# =============================================================================
# MAIN
# =============================================================================

def main():
    if len(sys.argv) < 2:
        print("ACB Brotherhood Facebook Cape Unlocker")
        print()
        print("Usage: python acb_facebookcape_unlocker.py <SAV_FILE>")
        print()
        print("Examples:")
        print("  python acb_facebookcape_unlocker.py save.SAV")
        print("  python acb_facebookcape_unlocker.py AC2_0.SAV")
        return 1

    filepath = sys.argv[1]

    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        return 1

    print(f"Loading {filepath}...")

    with open(filepath, 'rb') as f:
        raw_data = f.read()

    # ── Encryption detection ──────────────────────────────────────────────────
    fmt = detect_format(raw_data)

    if fmt == 'PS3-encrypted':
        print("Detected format: PS3 (encrypted)")
        if not HAS_CRYPTO:
            print("Error: pycryptodome is required to decrypt PS3 saves.")
            print("  Install it with:  pip install pycryptodome")
            return 1
        print("  PARAM.PFD found — decrypting before editing...")
        try:
            data          = ps3_decrypt_file(filepath)
            was_encrypted = True
        except (FileNotFoundError, ValueError) as e:
            print(f"Error: {e}")
            return 1
        # Re-detect on the decrypted bytes to confirm it parsed correctly
        fmt = detect_format(data)
        if fmt != 'PS3':
            print("Error: Decrypted data did not produce a valid PS3 SAV structure.")
            return 1
        platform = 'PS3'

    elif fmt == 'PS3':
        print("Detected format: PS3 (decrypted)")
        data          = raw_data
        was_encrypted = False
        platform      = 'PS3'

    elif fmt == 'PC':
        print("Detected format: PC")
        data          = raw_data
        was_encrypted = False
        platform      = 'PC'

    else:
        print("Error: Could not detect file format (PC or PS3)")
        return 1

    # ── Parse blocks ──────────────────────────────────────────────────────────
    try:
        blocks = parse_sav_blocks(data, is_ps3=(platform == 'PS3'))
    except Exception as e:
        print(f"Error parsing SAV file: {e}")
        return 1

    frame_index_by_offset = {off: i for i, (off, _) in enumerate(blocks['frames'])}
    cape_frame_indices = [frame_index_by_offset[off] for off, _ in blocks['cape_frames']]
    print(f"Found {len(blocks['frames'])} data frames; "
          f"cape records in frame(s): {cape_frame_indices if cape_frame_indices else 'NONE'}")

    if not blocks['cape_frames']:
        print("WARNING: No frame contains the cape records.")
        print("  Cape unlocking is unavailable for this file; name editing still works.")

    block1_data = bytearray(decompress(blocks['block1_compressed']))
    cape_frame_data = bytearray(decompress(blocks['cape_frame_compressed']))

    # ── Run UI ────────────────────────────────────────────────────────────────
    if HAS_CURSES:
        try:
            should_save, new_name = curses.wrapper(
                lambda stdscr: run_ui(stdscr, filepath, platform, blocks,
                                      block1_data, cape_frame_data))
        except KeyboardInterrupt:
            print("\nCancelled.")
            return 0
    else:
        should_save, new_name = run_text_ui(filepath, platform, blocks,
                                            block1_data, cape_frame_data)

    if should_save:
        # Check what was modified
        block1_modified = False
        capes_modified = False

        # Check if name was actually changed (compare to original)
        if new_name:
            orig_block1 = decompress(blocks['block1_compressed'])
            _, _, orig_name = find_name_in_block1(orig_block1)
            if new_name != orig_name:
                block1_data = change_name_in_block1(block1_data, new_name)
                block1_modified = True
            else:
                print(f"Name unchanged: {new_name}")

        # Check if any capes were modified
        orig_cape_frame = decompress(blocks['cape_frame_compressed'])
        for hash_val, expected_id, name in CAPE_DEFINITIONS:
            orig_state = get_cape_state(orig_cape_frame, hash_val, expected_id)
            new_state = get_cape_state(cape_frame_data, hash_val, expected_id)
            if orig_state != new_state:
                capes_modified = True
                status = "UNLOCKED" if new_state else "LOCKED"
                print(f"{name}: {status}")

        if not block1_modified and not capes_modified:
            print("\nNo changes to save.")
        else:
            enc_note = " (will re-encrypt)" if was_encrypted else ""
            print(f"\nSaving to {filepath}{enc_note}...")
            save_sav(filepath, blocks, block1_data, cape_frame_data,
                     block1_modified, capes_modified,
                     was_encrypted=was_encrypted)
            print("Done!")
    else:
        print("\nNo changes saved.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
