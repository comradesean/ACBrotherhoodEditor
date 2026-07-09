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

Cape structure in Block 4:
  [cape_hash 4B] [8 zeros] [0x0B marker] [ownership_flag 1B] [cape_id 1B] ...

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
# find_cape_in_block4). The hash + cape_id alone are NOT sufficient: the same
# cape_id is reused by many inventory entries, and the raw hash bytes also turn
# up inside compact reference lists (e.g. Block 5) that are not ownership
# records. Requiring the zero-run and the 0x0B marker rejects those impostors.
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
# SHARED PARSING HELPERS
# =============================================================================

def _find_block3_regions(data: bytes, start_offset: int, total_size: int) -> list:
    """
    Find all 4 region headers in Block 3.

    Returns list of (offset, size) tuples for each region.
    """
    regions = []
    search_pos = start_offset
    for region_num in range(4):
        while search_pos < total_size - 8:
            if (data[search_pos] == 0x01 and
                data[search_pos+4:search_pos+8] == b'\x00\x00\x80\x00'):
                region_size = struct.unpack('<I', data[search_pos+1:search_pos+4] + b'\x00')[0]
                if 0 < region_size < 50000:
                    regions.append((search_pos, region_size))
                    search_pos = search_pos + 8 + region_size + 5
                    break
            search_pos += 1
    return regions


def _patch_block4_in_block3(block3_raw: bytearray, region4_offset: int,
                            block4_recompressed: bytes) -> None:
    """
    Patch Block 3's Region 4 header with new Block 4 size and checksum.

    Modifies block3_raw in place.
    """
    # Update size
    old_b4_size = struct.unpack('<I', bytes(block3_raw[region4_offset+1:region4_offset+4]) + b'\x00')[0]
    new_b4_size = len(block4_recompressed)
    if old_b4_size != new_b4_size:
        size_bytes = struct.pack('<I', new_b4_size)[:3]
        block3_raw[region4_offset+1:region4_offset+4] = size_bytes

    # Update checksum
    old_checksum = struct.unpack('<I', bytes(block3_raw[region4_offset+9:region4_offset+13]))[0]
    new_checksum = adler32_zero_seed(block4_recompressed)
    if old_checksum != new_checksum:
        block3_raw[region4_offset+9:region4_offset+13] = struct.pack('<I', new_checksum)


# =============================================================================
# PC SAV PARSING
# =============================================================================

def parse_pc_sav_blocks(data: bytes) -> dict:
    """Parse PC SAV file and extract all 5 blocks."""
    total_size = len(data)

    # Block 1: 44-byte header at offset 0, then compressed data
    block1_compressed_size = struct.unpack('<I', data[0x20:0x24])[0]
    block1_compressed = data[0x2C:0x2C + block1_compressed_size]

    # Block 2: 44-byte header immediately after Block 1
    block2_header_offset = 0x2C + block1_compressed_size
    block2_compressed_size = struct.unpack('<I', data[block2_header_offset + 0x20:block2_header_offset + 0x24])[0]
    block2_data_offset = block2_header_offset + 44
    block2_compressed = data[block2_data_offset:block2_data_offset + block2_compressed_size]

    # Block 3: Raw data with 4 regions
    block3_offset = block2_data_offset + block2_compressed_size

    # Find all 4 region headers in Block 3
    block3_regions = _find_block3_regions(data, block3_offset, total_size)

    # Region 4's declared size equals Block 4's compressed size
    if len(block3_regions) >= 4:
        region4_offset, block4_compressed_size = block3_regions[3]
        # Block 3 ends after Region 4 header (8 bytes) + 5-byte local data
        block3_end = region4_offset + 8 + 5
        block3_size = block3_end - block3_offset
    else:
        raise ValueError(f"Could not parse Block 3 headers, found {len(block3_regions)} regions")

    block3_raw = data[block3_offset:block3_offset + block3_size]

    # Calculate Region 4's offset within Block 3 (for later patching)
    region4_offset_in_block3 = region4_offset - block3_offset

    # Block 4: LZSS compressed, size from Region 4's declared value
    block4_offset = block3_offset + block3_size
    block4_compressed = data[block4_offset:block4_offset + block4_compressed_size]

    # Block 5: Rest of file
    block5_offset = block4_offset + block4_compressed_size
    block5_raw = data[block5_offset:]

    return {
        'block1_header': data[0:0x2C],
        'block1_compressed': block1_compressed,
        'block2_header_offset': block2_header_offset,
        'block2_header': data[block2_header_offset:block2_header_offset + 44],
        'block2_compressed': block2_compressed,
        'block3_raw': block3_raw,
        'block4_compressed': block4_compressed,
        'block5_raw': block5_raw,
        'region4_offset_in_block3': region4_offset_in_block3,
    }


# =============================================================================
# PS3 SAV PARSING
# =============================================================================

def parse_ps3_sav_blocks(data: bytes) -> dict:
    """Parse PS3 SAV file and extract all 5 blocks."""
    # Verify PS3 prefix
    if len(data) < 8:
        raise ValueError("File too small for PS3 SAV format")

    ps3_size = struct.unpack('>I', data[0:4])[0]
    ps3_checksum = struct.unpack('>I', data[4:8])[0]

    # SAV data starts after 8-byte prefix
    sav_data = data[8:]
    total_size = len(sav_data)

    # Block 1: 44-byte header, sizes at offset 0x20 (LE)
    b1_comp_size = struct.unpack('<I', sav_data[0x20:0x24])[0]
    b1_uncomp_size = struct.unpack('<I', sav_data[0x24:0x28])[0]
    b1_checksum = struct.unpack('<I', sav_data[0x28:0x2C])[0]
    b1_compressed = sav_data[44:44 + b1_comp_size]

    # Block 2: 44-byte header immediately after Block 1
    b2_header_offset = 44 + b1_comp_size
    b2_comp_size = struct.unpack('<I', sav_data[b2_header_offset + 0x20:b2_header_offset + 0x24])[0]
    b2_uncomp_size = struct.unpack('<I', sav_data[b2_header_offset + 0x24:b2_header_offset + 0x28])[0]
    b2_checksum = struct.unpack('<I', sav_data[b2_header_offset + 0x28:b2_header_offset + 0x2C])[0]
    b2_data_offset = b2_header_offset + 44
    b2_compressed = sav_data[b2_data_offset:b2_data_offset + b2_comp_size]

    # Block 3: Raw data with 4 regions
    b3_offset = b2_data_offset + b2_comp_size

    # Find all 4 region headers in Block 3
    block3_regions = _find_block3_regions(sav_data, b3_offset, total_size)

    if len(block3_regions) < 4:
        raise ValueError(f"Could not parse Block 3 headers, found {len(block3_regions)} regions")

    # Region 4's declared size equals Block 4's compressed size
    region4_offset, b4_comp_size = block3_regions[3]
    b3_end = region4_offset + 8 + 5
    b3_size = b3_end - b3_offset
    b3_raw = sav_data[b3_offset:b3_offset + b3_size]

    region4_offset_in_block3 = region4_offset - b3_offset

    # Block 4: LZSS compressed
    b4_offset = b3_offset + b3_size
    b4_compressed = sav_data[b4_offset:b4_offset + b4_comp_size]

    # Block 5: Rest of actual data (before padding)
    b5_offset = b4_offset + b4_comp_size
    actual_end = ps3_size
    b5_raw = sav_data[b5_offset:actual_end]

    return {
        'ps3_size': ps3_size,
        'ps3_checksum': ps3_checksum,
        'block1_header': sav_data[0:44],
        'block1_compressed': b1_compressed,
        'block2_header_offset': b2_header_offset,
        'block2_header': sav_data[b2_header_offset:b2_header_offset + 44],
        'block2_compressed': b2_compressed,
        'block3_raw': b3_raw,
        'block4_compressed': b4_compressed,
        'block5_raw': b5_raw,
        'region4_offset_in_block3': region4_offset_in_block3,
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

def find_cape_in_block4(data: bytes, cape_hash: int, expected_id: int) -> int:
    """
    Find a cape ownership record in Block 4 by searching for its hash.

    Cape record: [hash 4B] [8 zeros] [0x0B marker] [flag 1B] [cape_id 1B]

    Returns the offset of the ownership flag, or -1 if not found.

    The whole fixed structure is validated, not just the hash: the 8-byte zero
    run, the 0x0B marker, and the cape_id must all line up. Matching on the hash
    (and even the cape_id) alone produces false positives, because the cape_id is
    shared across many inventory entries and the hash bytes also appear inside
    Block 5 compact reference lists that are not ownership records.
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
    offset = find_cape_in_block4(data, cape_hash, expected_id)
    if offset == -1 or offset >= len(data):
        return False
    return data[offset] != 0


def set_cape_state(data: bytearray, cape_hash: int, expected_id: int, unlocked: bool):
    """Set cape unlock state."""
    offset = find_cape_in_block4(data, cape_hash, expected_id)
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


def _recompress_blocks(blocks: dict, block1_data: bytearray, block4_data: bytearray,
                       block1_modified: bool, block4_modified: bool, is_ps3: bool) -> tuple:
    """
    Recompress modified blocks and patch Block 3.

    Returns (block1_header, block1_compressed, block4_compressed, block3_raw, total_size_diff)
    """
    block3_raw = bytearray(blocks['block3_raw'])
    region4_offset = blocks['region4_offset_in_block3']
    total_size_diff = 0

    # Handle Block 1
    if block1_modified:
        block1_compressed = compress(bytes(block1_data))
        block1_header = _build_block1_header(block1_compressed, len(block1_data), is_ps3)
        total_size_diff += len(block1_compressed) - len(blocks['block1_compressed'])
    else:
        block1_header = blocks['block1_header']
        block1_compressed = blocks['block1_compressed']

    # Handle Block 4
    if block4_modified:
        block4_compressed = compress(bytes(block4_data))
        _patch_block4_in_block3(block3_raw, region4_offset, block4_compressed)
        total_size_diff += len(block4_compressed) - len(blocks['block4_compressed'])
    else:
        block4_compressed = blocks['block4_compressed']

    return block1_header, block1_compressed, block4_compressed, block3_raw, total_size_diff


def save_pc_sav(filepath: str, blocks: dict, block1_data: bytearray,
                block4_data: bytearray, block1_modified: bool, block4_modified: bool):
    """Save modified PC SAV file."""
    block1_header, block1_compressed, block4_compressed, block3_raw, total_size_diff = \
        _recompress_blocks(blocks, block1_data, block4_data, block1_modified, block4_modified, is_ps3=False)

    # Get Block 2 header+data and patch Field1 if size changed
    block2_header_and_data = bytearray(blocks['block2_header'] + blocks['block2_compressed'])
    if total_size_diff != 0:
        old_field1 = struct.unpack('<I', block2_header_and_data[0:4])[0]
        block2_header_and_data[0:4] = struct.pack('<I', old_field1 + total_size_diff)

    # Assemble output file
    output = bytearray()
    output.extend(block1_header)
    output.extend(block1_compressed)
    output.extend(block2_header_and_data)
    output.extend(block3_raw)
    output.extend(block4_compressed)
    output.extend(blocks['block5_raw'])

    with open(filepath, 'wb') as f:
        f.write(output)


def save_ps3_sav(filepath: str, blocks: dict, block1_data: bytearray,
                 block4_data: bytearray, block1_modified: bool, block4_modified: bool,
                 was_encrypted: bool = False):
    """
    Save PS3 SAV. If was_encrypted is True, re-encrypts the output using
    PARAM.PFD from the same directory as filepath.
    """
    block1_header, block1_compressed, block4_compressed, block3_raw, total_size_diff = \
        _recompress_blocks(blocks, block1_data, block4_data, block1_modified, block4_modified, is_ps3=True)

    # Get Block 2 header and patch Field1 if size changed (BE for PS3)
    block2_header = bytearray(blocks['block2_header'])
    if total_size_diff != 0:
        old_field1 = struct.unpack('>I', block2_header[0:4])[0]
        block2_header[0:4] = struct.pack('>I', old_field1 + total_size_diff)

    # Assemble SAV payload
    sav_payload = bytearray()
    sav_payload.extend(block1_header)
    sav_payload.extend(block1_compressed)
    sav_payload.extend(block2_header)
    sav_payload.extend(blocks['block2_compressed'])
    sav_payload.extend(block3_raw)
    sav_payload.extend(block4_compressed)
    sav_payload.extend(blocks['block5_raw'])

    # Build final output with PS3 prefix and padding
    output = bytearray()
    output.extend(struct.pack('>I', len(sav_payload)))
    output.extend(struct.pack('>I', crc32_ps3(bytes(sav_payload))))
    output.extend(sav_payload)

    if len(output) < PS3_FILE_SIZE:
        output.extend(b'\x00' * (PS3_FILE_SIZE - len(output)))

    if was_encrypted:
        print("  Re-encrypting modified SAV...")
        output = bytearray(ps3_encrypt_file(bytes(output), filepath))

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


def load_unlock_states(items: list, block1_data: bytes, block4_data: bytes):
    """Load current states from decompressed block data."""
    for item in items:
        if item.is_name:
            _, _, name = find_name_in_block1(block1_data)
            item.name_value = name if name else "Unknown"
        else:
            item.checked = get_cape_state(block4_data, item.hash_value, item.expected_id)


def apply_unlock_states(items: list, block1_data: bytearray, block4_data: bytearray) -> None:
    """Apply unlock states to block data."""
    for item in items:
        if item.is_name:
            continue  # Name handled separately
        old_state = get_cape_state(block4_data, item.hash_value, item.expected_id)
        if old_state != item.checked:
            set_cape_state(block4_data, item.hash_value, item.expected_id, item.checked)


# =============================================================================
# CURSES UI
# =============================================================================

def run_ui(stdscr, filepath: str, platform: str, blocks: dict,
           block1_data: bytearray, block4_data: bytearray) -> tuple:
    """Run the curses UI. Returns (should_save, new_name or None)."""
    curses.curs_set(0)
    curses.use_default_colors()

    if curses.has_colors():
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_GREEN, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)

    items = build_unlock_items()
    load_unlock_states(items, block1_data, block4_data)

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
            apply_unlock_states(items, block1_data, block4_data)
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
                block1_data: bytearray, block4_data: bytearray) -> tuple:
    """Run simple text-based UI. Returns (should_save, new_name or None)."""
    items = build_unlock_items()
    load_unlock_states(items, block1_data, block4_data)
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
            apply_unlock_states(items, block1_data, block4_data)
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
        if platform == 'PC':
            blocks = parse_pc_sav_blocks(data)
        else:
            blocks = parse_ps3_sav_blocks(data)
    except Exception as e:
        print(f"Error parsing SAV file: {e}")
        return 1

    # Decompress Block 1 and Block 4
    print("Decompressing blocks...")
    block1_data = bytearray(decompress(blocks['block1_compressed']))
    block4_data = bytearray(decompress(blocks['block4_compressed']))

    print(f"Block 1: {len(block1_data)} bytes")
    print(f"Block 4: {len(block4_data)} bytes")

    # ── Run UI ────────────────────────────────────────────────────────────────
    if HAS_CURSES:
        try:
            should_save, new_name = curses.wrapper(
                lambda stdscr: run_ui(stdscr, filepath, platform, blocks,
                                      block1_data, block4_data))
        except KeyboardInterrupt:
            print("\nCancelled.")
            return 0
    else:
        should_save, new_name = run_text_ui(filepath, platform, blocks,
                                            block1_data, block4_data)

    if should_save:
        # Check what was modified
        block1_modified = False
        block4_modified = False

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
        orig_block4 = decompress(blocks['block4_compressed'])
        for hash_val, expected_id, name in CAPE_DEFINITIONS:
            orig_state = get_cape_state(orig_block4, hash_val, expected_id)
            new_state = get_cape_state(block4_data, hash_val, expected_id)
            if orig_state != new_state:
                block4_modified = True
                status = "UNLOCKED" if new_state else "LOCKED"
                print(f"{name}: {status}")

        if not block1_modified and not block4_modified:
            print("\nNo changes to save.")
        else:
            enc_note = " (will re-encrypt)" if was_encrypted else ""
            print(f"\nSaving to {filepath}{enc_note}...")
            if platform == 'PC':
                save_pc_sav(filepath, blocks, block1_data, block4_data,
                            block1_modified, block4_modified)
            else:
                save_ps3_sav(filepath, blocks, block1_data, block4_data,
                             block1_modified, block4_modified,
                             was_encrypted=was_encrypted)
            print("Done!")
    else:
        print("\nNo changes saved.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
