# Ascandane Archival Character Encoding (AACE-1)

## Status

This document defines AACE-1, the first reference version of the Ascandane
Archival Character Encoding for the Ascandane Archival Character Set Standard
(AACSS).  The allowed textual alphabet is exactly:

```text
1 2 6 8 9 A C E H J K L M N O P Q R S T U X Y Z
```

## Goals

AACE-1 is a reversible UTF-8 archival transport.  It is deterministic, block
localized, checksummed, and designed so damage in one transcribed block does not
shift or corrupt all following blocks.

## Binary container

All integer fields are unsigned big-endian.  The fixed 24-byte header is:

| Field | Size | Meaning |
| --- | ---: | --- |
| magic | 4 | ASCII `AACE` |
| version | 1 | `1` |
| ecc_profile | 1 | `0` Standard, `1` High, `2` Extreme |
| block_size | 2 | Original bytes per block, 1..65535 |
| block_count | 4 | Number of independent block records |
| original_length | 8 | Original byte length |
| header_crc32 | 4 | CRC-32 over all previous header fields |

Each block record has a fixed 13-byte prefix followed by coded payload bytes:

| Field | Size | Meaning |
| --- | ---: | --- |
| index | 4 | Zero-based block index |
| data_length | 2 | Original bytes in this block |
| ecc_length | 2 | Extra ECC bytes after the primary copy |
| flags | 1 | Reserved, MUST be zero |
| data_crc32 | 4 | CRC-32 of recovered original block bytes |
| coded_payload | variable | Profile-specific coded bytes |

## ECC profiles

* **Standard** (`0`) stores one payload copy and provides localized CRC failure
  detection.
* **High** (`1`) stores three identical payload copies and recovers each byte by
  majority vote, correcting one damaged copy at a byte position.
* **Extreme** (`2`) stores five identical payload copies and recovers each byte
  by majority vote, correcting two damaged copies at a byte position.

Future versions may add Reed-Solomon or other erasure codes.  AACE-1 decoders
MUST reject unsupported profile codes rather than guessing.

## Canonical textual encoding

The textual form starts with `AACE1:`.  The header and every block record are
converted independently to base-24 using the AACSS alphabet in the order shown
above.  Encoded records are split into groups of five characters with hyphens,
and records are separated by periods.  Decoders MAY ignore whitespace and
hyphens inside records, but MUST NOT ignore periods because periods are the
block resynchronization boundary.

Because each block is base-24 encoded independently, insertion, deletion, or
loss inside one printed record does not change the interpretation of the next
record.  A decoder can reject the damaged block and resynchronize at the next
period.

## UTF-8 mapping

Text is encoded as canonical UTF-8 bytes before containerization.  Decoding is
successful only if recovered bytes are valid UTF-8 when the text API is used.
The byte API is reversible for arbitrary bytes.

## Version negotiation

Implementations MUST check magic, version, profile, block size, block count, and
header CRC before block decoding.  AACE-1 readers MUST reject any version other
than `1`.  Future standards should use a new `AACE<version>:` textual prefix and
binary version value.

## Security and hardening requirements

Implementations MUST bound allocations from the header, verify every CRC before
returning decoded data, reject non-AACSS characters, reject reordered or missing
blocks, and avoid heuristic repair that could silently change archived content.
AACE provides integrity checking and limited error correction; it is not
encryption and does not authenticate malicious modification.

## Official test vectors

### Empty string

UTF-8 input: empty string

```text
AACE1:981CC-CPM6M-PXUHP-R8SMK-1CLTR-A2ROE-X9CN2-HSKUQ-8J
```

### `hello i am atsh`

UTF-8 input: `hello i am atsh`

```text
AACE1:981CC-CPM6M-PXUHP-R8SMK-269TU-C6KNL-LXHL8-N9XET-H8.11111-11116-8A19H-LNSOX-QSNMN-ZUERP-19UZP-QMPXE-LSEMN-XZRQ
```

### Unicode sample

UTF-8 input: `Archive: Καλημέρα 🌍 — こんにちは`

```text
AACE1:981CC-CPM6M-PXUHP-R8SMK-269TU-C6KNL-LXHMM-MSK1L-HS.11111-1111H-UQK2L-ZPU2K-NA6EK-CLK22-COTUK-2TN9C-62LAU-CKMPE-RU1EO-6KZS6-N1U9U-RSP61-ZE82U-NSYCX-RYS1X-QAZJ2-ZOMEY-XUZHA-QC6XU-YK6MP
```

# Ascandane Compact ASCII Encoding (AACE-2)

## Status

AACE-2 is a compact ASCII-only companion profile.  It is intended for small
plain-ASCII archival strings where the fixed AACE-1 binary container overhead is
too large.  Non-ASCII text MUST use AACE-1.

## Textual form

AACE-2 starts with `AACE2-<level>:` where `<level>` is `0`, `1`, `2`, or `3`.
The body is one or more period-delimited records.  Each record is independently
base-24 encoded with the same AACSS alphabet and five-character hyphen grouping
as AACE-1.  Periods remain block resynchronization boundaries.

## Compact record container

AACE-2 records are at most 63 ASCII bytes before ECC expansion.  The first byte
stores the ECC level in the high two bits and the original data length in the
low six bits.  The second byte stores the block index modulo 256.  The remaining
bytes are the ECC-coded ASCII payload followed by the selected checksum.

## AACE-2 ECC levels

* **Level 0** stores one payload copy and no checksum, minimizing size.
* **Level 1** stores one payload copy plus CRC-16/CCITT localized detection.
* **Level 2** stores two payload copies plus CRC-32, allowing recovery when one
  copy still matches the checksum.
* **Level 3** stores three payload copies plus CRC-32 majority recovery.

## AACE-2 compact test vectors

UTF-8/ASCII input: `hello i am atsh`

```text
AACE2-0:1LMUU-8YC2J-EU86Y-P9UK1-TC8NZ-QZLE1
```

```text
AACE2-1:1M11A-KNSAL-ZR21N-R26AU-OZKUU-KMKOS-6LRK
```

The level-0 vector is 43 characters including prefix and separators, compared
with 114 characters for the default AACE-1 encoding of the same string.
