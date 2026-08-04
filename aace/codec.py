"""Reference implementation for AACE-1.

The codec is deliberately self-contained: no third-party dependencies are
required, all integer fields are big-endian, and every encoded data block is
independent so transcription damage is localized to one block.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import math
import struct
import sys
import zlib

ALPHABET = "12689ACEHJKLMNOPQRSTUXYZ"
GROUP = 5
MAGIC = b"AACE"
VERSION = 1
VERSION2_BLOCK_SIZE = 63
_V2_CRC16_POLY = 0x1021
_HEADER = struct.Struct(">4sBBHIQI")
_BLOCK = struct.Struct(">IHHBI")


class AACEError(ValueError):
    """Raised when AACE data is malformed or unrecoverable."""


@dataclass(frozen=True)
class ECCProfile:
    name: str
    code: int
    copies: int
    description: str


ECC_PROFILES = {
    "standard": ECCProfile("standard", 0, 1, "CRC localized detection"),
    "high": ECCProfile("high", 1, 3, "triple modular redundancy"),
    "extreme": ECCProfile("extreme", 2, 5, "quintuple modular redundancy"),
}
V2_ECC_LEVELS = {
    0: (1, 0, "no ECC/checksum; minimum size"),
    1: (1, 2, "CRC-16 localized detection"),
    2: (2, 4, "two copies plus CRC-32; repairs one bad copy"),
    3: (3, 4, "three copies plus CRC-32 majority repair"),
}
_PROFILE_BY_CODE = {p.code: p for p in ECC_PROFILES.values()}
_DECODE = {ch: i for i, ch in enumerate(ALPHABET)}


def _digits_for_bytes(n: int) -> int:
    if n <= 0:
        return 0
    return math.ceil((8 * n) / math.log2(24))


def _b24_encode(raw: bytes) -> str:
    if not raw:
        return ""
    value = int.from_bytes(raw, "big")
    digits = _digits_for_bytes(len(raw))
    out = [ALPHABET[0]] * digits
    for pos in range(digits - 1, -1, -1):
        value, rem = divmod(value, 24)
        out[pos] = ALPHABET[rem]
    if value:
        raise AssertionError("base-24 digit calculation underflow")
    return "".join(out)


def _b24_decode(text: str, byte_len: int) -> bytes:
    value = 0
    for ch in text:
        try:
            digit = _DECODE[ch]
        except KeyError as exc:
            raise AACEError(f"invalid AACSS character: {ch!r}") from exc
        value = value * 24 + digit
    try:
        return value.to_bytes(byte_len, "big")
    except OverflowError as exc:
        raise AACEError("base-24 value exceeds declared byte length") from exc


def _group(s: str) -> str:
    return "-".join(s[i : i + GROUP] for i in range(0, len(s), GROUP))


def _ungroup(s: str) -> str:
    return "".join(ch for ch in s.strip().upper() if ch not in "- \t\r\n")


def _majority_decode(coded: bytes, data_len: int, copies: int) -> bytes:
    if len(coded) != data_len * copies:
        raise AACEError("coded payload length mismatch")
    if copies == 1:
        return coded
    parts = [coded[i * data_len : (i + 1) * data_len] for i in range(copies)]
    recovered = bytearray(data_len)
    for i in range(data_len):
        counts: dict[int, int] = {}
        for part in parts:
            counts[part[i]] = counts.get(part[i], 0) + 1
        value, count = max(counts.items(), key=lambda kv: kv[1])
        if count < (copies // 2 + 1):
            raise AACEError("ECC majority failure in block")
        recovered[i] = value
    return bytes(recovered)


def _header(profile: ECCProfile, block_size: int, length: int, blocks: int) -> bytes:
    without_crc = _HEADER.pack(MAGIC, VERSION, profile.code, block_size, blocks, length, 0)
    crc = zlib.crc32(without_crc[:-4]) & 0xFFFFFFFF
    return _HEADER.pack(MAGIC, VERSION, profile.code, block_size, blocks, length, crc)



def _crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ _V2_CRC16_POLY) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def _v2_checksum(data: bytes, checksum_len: int) -> bytes:
    if checksum_len == 0:
        return b""
    if checksum_len == 2:
        return _crc16_ccitt(data).to_bytes(2, "big")
    if checksum_len == 4:
        return (zlib.crc32(data) & 0xFFFFFFFF).to_bytes(4, "big")
    raise AssertionError("unsupported checksum length")


def _v2_record_encode(chunk: bytes, level: int, index: int) -> str:
    copies, checksum_len, _ = V2_ECC_LEVELS[level]
    header = bytes([((level & 0x03) << 6) | len(chunk), index & 0xFF])
    raw = header + chunk * copies + _v2_checksum(chunk, checksum_len)
    return _group(_b24_encode(raw))


def encode_ascii(text: str, *, ecc_level: int = 1, block_size: int = VERSION2_BLOCK_SIZE) -> str:
    """Encode ASCII text to compact AACE-2.

    AACE-2 intentionally rejects non-ASCII input.  Use AACE-1 for arbitrary
    UTF-8 text.
    """
    try:
        data = text.encode("ascii")
    except UnicodeEncodeError as exc:
        raise AACEError("AACE-2 is ASCII-only; use AACE-1 for UTF-8") from exc
    return encode_ascii_bytes(data, ecc_level=ecc_level, block_size=block_size)


def encode_ascii_bytes(data: bytes, *, ecc_level: int = 1, block_size: int = VERSION2_BLOCK_SIZE) -> str:
    if any(byte > 0x7F for byte in data):
        raise AACEError("AACE-2 bytes must be ASCII only (0x00..0x7F)")
    if ecc_level not in V2_ECC_LEVELS:
        raise AACEError("AACE-2 ecc_level must be 0, 1, 2, or 3")
    if not 1 <= block_size <= VERSION2_BLOCK_SIZE:
        raise AACEError(f"AACE-2 block_size must be in 1..{VERSION2_BLOCK_SIZE}")
    records = [
        _v2_record_encode(data[i : i + block_size], ecc_level, i // block_size)
        for i in range(0, len(data), block_size)
    ]
    if not records:
        records = [_v2_record_encode(b"", ecc_level, 0)]
    return f"AACE2-{ecc_level}:" + ".".join(records)


def _v2_recover(coded: bytes, data_len: int, copies: int, checksum: bytes) -> bytes:
    parts = [coded[i * data_len : (i + 1) * data_len] for i in range(copies)]
    checksum_len = len(checksum)
    if copies == 1:
        candidate = parts[0]
        if checksum and _v2_checksum(candidate, checksum_len) != checksum:
            raise AACEError("AACE-2 block checksum mismatch")
        return candidate
    for part in parts:
        if _v2_checksum(part, checksum_len) == checksum:
            return part
    if copies >= 3:
        candidate = _majority_decode(coded, data_len, copies)
        if _v2_checksum(candidate, checksum_len) == checksum:
            return candidate
    raise AACEError("AACE-2 ECC recovery failed")


def decode_ascii(text: str) -> str:
    return decode_ascii_bytes(text).decode("ascii")


def decode_ascii_bytes(text: str) -> bytes:
    cleaned = text.strip().upper()
    if not cleaned.startswith("AACE2-") or ":" not in cleaned:
        raise AACEError("missing AACE2 prefix")
    level_text, body = cleaned[6:].split(":", 1)
    try:
        prefix_level = int(level_text)
    except ValueError as exc:
        raise AACEError("invalid AACE-2 ECC level") from exc
    if prefix_level not in V2_ECC_LEVELS:
        raise AACEError("AACE-2 ecc_level must be 0, 1, 2, or 3")
    out = []
    pieces = body.split(".") if body else []
    for expected, piece in enumerate(pieces):
        compact = _ungroup(piece)
        # The first byte stores level and data length.  Trial-decode possible
        # byte lengths until the metadata is self-consistent.
        found = None
        for raw_len in range(2, 2 + VERSION2_BLOCK_SIZE * V2_ECC_LEVELS[prefix_level][0] + 4 + 1):
            if _digits_for_bytes(raw_len) != len(compact):
                continue
            try:
                raw = _b24_decode(compact, raw_len)
            except AACEError:
                continue
            header = raw[0]
            level = header >> 6
            data_len = header & 0x3F
            if level != prefix_level or data_len > VERSION2_BLOCK_SIZE or raw[1] != (expected & 0xFF):
                continue
            copies, checksum_len, _ = V2_ECC_LEVELS[level]
            if len(raw) != 2 + data_len * copies + checksum_len:
                continue
            found = raw
            break
        if found is None:
            raise AACEError(f"AACE-2 block metadata mismatch at {expected}")
        level = found[0] >> 6
        data_len = found[0] & 0x3F
        copies, checksum_len, _ = V2_ECC_LEVELS[level]
        coded_start = 2
        coded_end = coded_start + data_len * copies
        chunk = _v2_recover(found[coded_start:coded_end], data_len, copies, found[coded_end:])
        if any(byte > 0x7F for byte in chunk):
            raise AACEError("AACE-2 decoded non-ASCII byte")
        out.append(chunk)
    return b"".join(out)


def encode_bytes(data: bytes, *, profile: str = "standard", block_size: int = 128) -> str:
    """Encode bytes to canonical AACE text."""
    try:
        prof = ECC_PROFILES[profile.lower()]
    except KeyError as exc:
        raise AACEError(f"unknown ECC profile: {profile!r}") from exc
    if not 1 <= block_size <= 65535:
        raise AACEError("block_size must be in 1..65535")
    block_count = (len(data) + block_size - 1) // block_size
    records = [_group(_b24_encode(_header(prof, block_size, len(data), block_count)))]
    for index in range(block_count):
        chunk = data[index * block_size : (index + 1) * block_size]
        coded = chunk * prof.copies
        crc = zlib.crc32(chunk) & 0xFFFFFFFF
        prefix = _BLOCK.pack(index, len(chunk), len(coded) - len(chunk), 0, crc)
        records.append(_group(_b24_encode(prefix + coded)))
    return "AACE1:" + ".".join(records)


def decode_bytes(text: str) -> bytes:
    """Decode canonical or whitespace-reflowed AACE text to bytes."""
    cleaned = text.strip().upper()
    if not cleaned.startswith("AACE1:"):
        raise AACEError("missing AACE1 prefix")
    pieces = cleaned[6:].split(".")
    if not pieces or not pieces[0]:
        raise AACEError("missing header")
    header_raw = _b24_decode(_ungroup(pieces[0]), _HEADER.size)
    magic, version, profile_code, block_size, block_count, length, header_crc = _HEADER.unpack(header_raw)
    if magic != MAGIC or version != VERSION:
        raise AACEError("unsupported AACE container")
    if zlib.crc32(header_raw[:-4]) & 0xFFFFFFFF != header_crc:
        raise AACEError("header checksum mismatch")
    try:
        prof = _PROFILE_BY_CODE[profile_code]
    except KeyError as exc:
        raise AACEError("unsupported ECC profile") from exc
    if len(pieces) - 1 != block_count:
        raise AACEError("block count mismatch")
    out = [b""] * block_count
    for expected, piece in enumerate(pieces[1:]):
        data_len = block_size if expected < block_count - 1 else length - block_size * expected
        if data_len < 0 or data_len > block_size:
            raise AACEError("invalid block length in header")
        coded_len = data_len * prof.copies
        raw = _b24_decode(_ungroup(piece), _BLOCK.size + coded_len)
        index, declared_len, ecc_len, flags, crc = _BLOCK.unpack(raw[: _BLOCK.size])
        if index != expected or declared_len != data_len or ecc_len != coded_len - data_len or flags != 0:
            raise AACEError(f"block metadata mismatch at {expected}")
        chunk = _majority_decode(raw[_BLOCK.size :], data_len, prof.copies)
        if zlib.crc32(chunk) & 0xFFFFFFFF != crc:
            raise AACEError(f"block checksum mismatch at {expected}")
        out[expected] = chunk
    result = b"".join(out)
    if len(result) != length:
        raise AACEError("decoded length mismatch")
    return result


def encode(text: str, *, profile: str = "standard", block_size: int = 128, version: int = 1, ecc_level: int = 1) -> str:
    if version == 1:
        return encode_bytes(text.encode("utf-8"), profile=profile, block_size=block_size)
    if version == 2:
        return encode_ascii(text, ecc_level=ecc_level)
    raise AACEError("unsupported AACE version")


def decode(text: str) -> str:
    cleaned = text.strip().upper()
    if cleaned.startswith("AACE2-"):
        return decode_ascii(cleaned)
    return decode_bytes(text).decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AACE-1 reference codec")
    sub = parser.add_subparsers(dest="cmd", required=True)
    enc = sub.add_parser("encode")
    enc.add_argument("text", nargs="?", help="UTF-8 text; stdin is used when omitted")
    enc.add_argument("--version", type=int, choices=[1, 2], default=1)
    enc.add_argument("--profile", choices=sorted(ECC_PROFILES), default="standard")
    enc.add_argument("--ecc-level", type=int, choices=sorted(V2_ECC_LEVELS), default=1)
    enc.add_argument("--block-size", type=int, default=128)
    dec = sub.add_parser("decode")
    dec.add_argument("text", nargs="?", help="AACE text; stdin is used when omitted")
    args = parser.parse_args(argv)
    src = args.text if args.text is not None else sys.stdin.read()
    try:
        if args.cmd == "encode":
            print(encode(src, profile=args.profile, block_size=args.block_size, version=args.version, ecc_level=args.ecc_level))
        else:
            print(decode(src), end="")
    except (AACEError, UnicodeDecodeError) as exc:
        print(f"aace: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
