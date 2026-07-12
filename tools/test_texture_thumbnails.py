import struct
import unittest

from texture_thumbnails import parse_thumbnail_records


def thumbnail(identifier: bytes, payload: bytes) -> bytes:
    return (
        identifier
        + b"\x64\x8d\x08\x00\x08\x00"
        + struct.pack("<I", len(payload) + 4)
        + b"\x00\x00\x00\x00"
        + payload
    )


class TextureThumbnailsTest(unittest.TestCase):
    def test_parse_thumbnail_records(self) -> None:
        first = thumbnail(b"\x01\x02", b"a" * 32)
        second = thumbnail(b"\x03\x04", b"b" * 32)

        self.assertEqual(parse_thumbnail_records(first + second), [first, second])

    def test_reject_truncated_thumbnail(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds file size"):
            parse_thumbnail_records(thumbnail(b"\x01\x02", b"a" * 32)[:-1])


if __name__ == "__main__":
    unittest.main()
