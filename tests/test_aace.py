import random
import unittest

from aace import AACEError, decode, decode_ascii, decode_bytes, encode, encode_ascii, encode_bytes


class AACETests(unittest.TestCase):
    def round_trip(self, text, profile="standard", block_size=16):
        encoded = encode(text, profile=profile, block_size=block_size)
        self.assertEqual(decode(encoded), text)
        self.assertEqual(encoded, encode(decode(encoded), profile=profile, block_size=block_size))

    def test_vectors(self):
        self.assertEqual(encode(""), "AACE1:981CC-CPM6M-PXUHP-R8SMK-1CLTR-A2ROE-X9CN2-HSKUQ-8J")
        self.assertEqual(decode(encode("hello i am atsh", block_size=128)), "hello i am atsh")
        self.assertEqual(decode(encode("Archive: Καλημέρα 🌍 — こんにちは")), "Archive: Καλημέρα 🌍 — こんにちは")

    def test_aace2_compact_vectors(self):
        self.assertEqual(encode("hello i am atsh", version=2, ecc_level=0), "AACE2-0:1LMUU-8YC2J-EU86Y-P9UK1-TC8NZ-QZLE1")
        self.assertEqual(encode("hello i am atsh", version=2, ecc_level=1), "AACE2-1:1M11A-KNSAL-ZR21N-R26AU-OZKUU-KMKOS-6LRK")
        self.assertEqual(decode_ascii(encode_ascii("hello i am atsh", ecc_level=3)), "hello i am atsh")
        self.assertLess(len(encode("hello i am atsh", version=2, ecc_level=0)), len(encode("hello i am atsh")))

    def test_aace2_rejects_non_ascii(self):
        with self.assertRaises(AACEError):
            encode("Καλημέρα", version=2)

    def test_many_texts_all_profiles(self):
        samples = ["", "hello i am atsh", "ASCII", "Καλημέρα", "こんにちは", "🌍" * 8, "line\nbreak\t tab"]
        for profile in ["standard", "high", "extreme"]:
            for block_size in [1, 2, 7, 16, 128]:
                for sample in samples:
                    with self.subTest(profile=profile, block_size=block_size, sample=sample):
                        self.round_trip(sample, profile, block_size)

    def test_aace2_all_ecc_levels(self):
        samples = ["", "hello i am atsh", "line\nbreak\t tab", "A" * 200]
        for level in range(4):
            for sample in samples:
                with self.subTest(level=level, sample=sample):
                    self.assertEqual(decode(encode(sample, version=2, ecc_level=level)), sample)

    def test_random_bytes(self):
        rng = random.Random(12345)
        for size in list(range(80)) + [128, 129, 255, 256, 300]:
            data = bytes(rng.randrange(256) for _ in range(size))
            encoded = encode_bytes(data, profile="high", block_size=17)
            self.assertEqual(decode_bytes(encoded), data)

    def test_localized_corruption_detected(self):
        encoded = encode("hello i am atsh", block_size=5)
        parts = encoded.split(".")
        parts[2] = parts[2][:-1] + ("1" if parts[2][-1] != "1" else "2")
        damaged = ".".join(parts)
        with self.assertRaises(AACEError):
            decode(damaged)
        self.assertTrue(parts[3].startswith("11111"))

    def test_high_profile_repairs_single_copy_byte(self):
        data = b"abcdefgh"
        encoded = encode_bytes(data, profile="high", block_size=8)
        head, block = encoded.split(".")
        from aace.codec import _b24_decode, _b24_encode, _group, _ungroup, _BLOCK
        raw = bytearray(_b24_decode(_ungroup(block), _BLOCK.size + len(data) * 3))
        raw[_BLOCK.size + 1] ^= 0x01
        repaired = head + "." + _group(_b24_encode(bytes(raw)))
        self.assertEqual(decode_bytes(repaired), data)

    def test_aace2_level2_repairs_one_bad_copy(self):
        encoded = encode_ascii("abcdefgh", ecc_level=2)
        prefix, block = encoded.split(":", 1)
        from aace.codec import _b24_decode, _b24_encode, _digits_for_bytes, _group, _ungroup
        raw_len = 2 + 8 * 2 + 4
        raw = bytearray(_b24_decode(_ungroup(block), raw_len))
        raw[2] ^= 0x01
        repaired = prefix + ":" + _group(_b24_encode(bytes(raw)))
        self.assertEqual(decode_ascii(repaired), "abcdefgh")

    def test_rejects_invalid_character(self):
        with self.assertRaises(AACEError):
            decode("AACE1:00000")


if __name__ == "__main__":
    unittest.main()
