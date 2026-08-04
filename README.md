# Ascandane Archival Standard

This repository contains the draft AACE-1 specification and a hardened Python
reference implementation for the Ascandane Archival Character Set Standard
(AACSS) alphabet:

```text
1 2 6 8 9 A C E H J K L M N O P Q R S T U X Y Z
```

## Usage

```bash
python -m aace encode "hello i am atsh" --profile high --block-size 128
python -m aace decode 'AACE1:...'
```

The public Python API exposes `encode(str) -> str`, `decode(str) -> str`,
`encode_bytes(bytes) -> str`, and `decode_bytes(str) -> bytes`.

See [docs/AACE-1.md](docs/AACE-1.md) for the RFC-style standard, binary
container, canonical text form, ECC profiles, security notes, and test vectors.
