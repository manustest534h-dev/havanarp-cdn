import tempfile
import unittest
from pathlib import Path

from build_live_russia_skins import (
    DATA_REGISTRATIONS,
    RESERVED_MODEL_ID,
    add_data_registrations,
    add_vfs_records,
    model_mapping,
    set_ped_model_limit,
    validate_data_registrations,
)
from texture_thumbnails import decode_name
from vfs_archive import HEADER, MAGIC, parse_declared


def record(name: bytes, payload: bytes) -> bytes:
    encoded = bytes(value ^ len(name) for value in name)
    return (
        HEADER.pack(
            MAGIC,
            1,
            b"ABCDEF",
            2,
            len(payload),
            len(payload),
            len(encoded),
        )
        + encoded
        + payload
    )


class LiveRussiaSkinBuilderTest(unittest.TestCase):
    def test_model_mapping_skips_reserved_object_id(self) -> None:
        models = [
            {
                "modelName": "null",
            }
        ] + [
            {
                "id": index,
                "modelName": f"lr_skin{index}",
            }
            for index in range(1, 433)
        ]

        mapping = model_mapping(models)
        ids = [model_id for model_id, _ in mapping]

        self.assertEqual(len(ids), 432)
        self.assertEqual(ids[0], 17083)
        self.assertEqual(ids[-1], 17515)
        self.assertNotIn(RESERVED_MODEL_ID, ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_add_vfs_records_inserts_before_archive_trailer(self) -> None:
        archive = (
            record(b"!client/texdb/base/", b"")
            + record(b"!client/texdb/base/base.dat", b"base")
            + b"\xff"
        )

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = Path(directory) / "destination"
            source.write_bytes(archive)

            add_vfs_records(
                source,
                destination,
                [("!client/texdb/new.dat", b"new")],
            )

            result = destination.read_bytes()
            records = parse_declared(result)
            names = [decode_name(item.name) for item in records]
            self.assertEqual(
                names,
                [
                    "!client/texdb/base/",
                    "!client/texdb/base/base.dat",
                    "!client/texdb/new.dat",
                ],
            )
            self.assertEqual(result[-1:], b"\xff")

    def test_added_record_name_uses_its_own_length_as_key(self) -> None:
        archive = (
            record(b"!client/texdb/base/", b"")
            + record(b"!client/texdb/base/base.dat", b"base")
            + b"\xff"
        )
        added_name = "!client/texdb/lr_skins/lr_skins.txt"

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = Path(directory) / "destination"
            source.write_bytes(archive)

            add_vfs_records(source, destination, [(added_name, b"descriptor")])

            added = parse_declared(destination.read_bytes())[-1]
            self.assertEqual(added.name[0] ^ ord("!"), len(added_name))
            self.assertEqual(decode_name(added.name), added_name)

    def test_add_vfs_records_inserts_before_declared_sentinel(self) -> None:
        archive = (
            record(b"!client/texdb/base/", b"")
            + record(b"!client/texdb/base/base.dat", b"base")
            + record(b"sentinel", b"")
            + b"\xff"
        )

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            destination = Path(directory) / "destination"
            source.write_bytes(archive)

            add_vfs_records(
                source,
                destination,
                [("!client/texdb/new.dat", b"new")],
            )

            names = [
                decode_name(item.name)
                for item in parse_declared(destination.read_bytes())
            ]
            self.assertEqual(names[2], "!client/texdb/new.dat")
            self.assertNotEqual(names[-1], "!client/texdb/new.dat")

    def test_add_data_registrations_updates_loader_files(self) -> None:
        archive = b"".join(
            record(name.encode("ascii"), anchor + b"\r\n")
            for name, (anchor, _) in DATA_REGISTRATIONS.items()
        )

        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / ".data"
            archive_path.write_bytes(archive)

            add_data_registrations(archive_path)
            validate_data_registrations(archive_path)

            data = archive_path.read_bytes()
            payloads = {
                decode_name(item.name): data[item.content_offset : item.end_offset]
                for item in parse_declared(data)
            }
            for name, (anchor, registration) in DATA_REGISTRATIONS.items():
                self.assertEqual(
                    payloads[name],
                    anchor + b"\r\n" + registration + b"\r\n",
                )

    def test_set_ped_model_limit_updates_limit_adjuster(self) -> None:
        archive = record(
            b"!client/limit_adjuster.ini",
            b"[IDE LIMITS]\r\nPed Models = 1000\r\n",
        )

        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / ".data"
            archive_path.write_bytes(archive)

            set_ped_model_limit(archive_path)

            data = archive_path.read_bytes()
            item = parse_declared(data)[0]
            payload = data[item.content_offset : item.end_offset]
            self.assertIn(b"Ped Models = 2000\r\n", payload)
            self.assertNotIn(b"Ped Models = 1000", payload)


if __name__ == "__main__":
    unittest.main()
