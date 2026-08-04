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


def encode(text: str, *, profile: str = "standard", block_size: int = 128) -> str:
    return encode_bytes(text.encode("utf-8"), profile=profile, block_size=block_size)


def decode(text: str) -> str:
    return decode_bytes(text).decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AACE-1 reference codec")
    sub = parser.add_subparsers(dest="cmd", required=True)
    enc = sub.add_parser("encode")
    enc.add_argument("text", nargs="?", help="UTF-8 text; stdin is used when omitted")
    enc.add_argument("--profile", choices=sorted(ECC_PROFILES), default="standard")
    enc.add_argument("--block-size", type=int, default=128)
    dec = sub.add_parser("decode")
    dec.add_argument("text", nargs="?", help="AACE text; stdin is used when omitted")
    args = parser.parse_args(argv)
    src = args.text if args.text is not None else sys.stdin.read()
    try:
        if args.cmd == "encode":
            print(encode(src, profile=args.profile, block_size=args.block_size))
        else:
            print(decode(src), end="")
    except (AACEError, UnicodeDecodeError) as exc:
        print(f"aace: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
