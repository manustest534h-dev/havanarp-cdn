import struct
import unittest

from vfs_archive import (
    HEADER,
    MAGIC,
    parse_declared,
    repair_sizes,
    replace_payloads,
)


def record(name: bytes, payload: bytes, declared_size: int | None = None) -> bytes:
    size = len(payload) if declared_size is None else declared_size
    return (
        HEADER.pack(MAGIC, 1, b"ABCDEF", 2, size, size, len(name))
        + name
        + payload
    )


class VfsArchiveTest(unittest.TestCase):
    def test_repair_grown_record(self) -> None:
        base = record(b"one", b"abc") + record(b"two", b"def") + record(b"three", b"g")
        modified = (
            record(b"one", b"abc")
            + record(b"two", b"def-extra", declared_size=3)
            + record(b"three", b"g")
        )

        with self.assertRaisesRegex(ValueError, "invalid record magic"):
            parse_declared(modified)

        repaired, changes = repair_sizes(base, modified)

        self.assertEqual(changes, [(1, 3, 9)])
        self.assertEqual(len(parse_declared(repaired)), 3)
        second_offset = len(record(b"one", b"abc"))
        self.assertEqual(struct.unpack_from("<I", repaired, second_offset + 18)[0], 9)
        self.assertEqual(struct.unpack_from("<I", repaired, second_offset + 22)[0], 9)

    def test_one_byte_archive_trailer(self) -> None:
        archive = record(b"one", b"abc") + b"\xff"

        self.assertEqual(len(parse_declared(archive)), 1)

    def test_replace_payloads(self) -> None:
        archive = record(b"one", b"abc") + record(b"two", b"def") + b"\xff"

        replaced = replace_payloads(archive, {0: b"longer", 1: b"x"})
        records = parse_declared(replaced)

        self.assertEqual(replaced[records[0].content_offset : records[0].end_offset], b"longer")
        self.assertEqual(replaced[records[1].content_offset : records[1].end_offset], b"x")
        self.assertEqual(replaced[-1:], b"\xff")


if __name__ == "__main__":
    unittest.main()
