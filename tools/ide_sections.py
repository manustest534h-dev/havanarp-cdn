#!/usr/bin/env python3

import argparse
from pathlib import Path

from texture_thumbnails import decode_name
from vfs_archive import parse_declared, replace_payloads


MARKER = b"# Havana country flag accessories"


def object_names(payload: bytes, marker: bytes = MARKER) -> list[str]:
    marker_offset = payload.find(marker)
    if marker_offset < 0:
        raise ValueError("objects marker not found")

    names = []
    for line in payload[marker_offset:].splitlines()[1:]:
        value = line.strip()
        if value.lower() == b"end":
            break
        if not value or value.startswith(b"#"):
            continue
        fields = [field.strip() for field in value.split(b",")]
        if len(fields) != 5:
            raise ValueError(f"invalid object definition: {value!r}")
        names.append(fields[1].decode())
    if not names:
        raise ValueError("objects block is empty")
    return names


def collision_records(data: bytes) -> list[tuple[int, int, str]]:
    records = []
    offset = 0
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError(f"truncated collision record at offset {offset}")
        if bytes(data[offset : offset + 4]) not in {
            b"COL2",
            b"COL3",
            b"COL4",
            b"COLL",
        }:
            raise ValueError(f"invalid collision record at offset {offset}")
        size = int.from_bytes(data[offset + 4 : offset + 8], "little") + 8
        end_offset = offset + size
        if end_offset > len(data):
            raise ValueError(f"collision record at offset {offset} exceeds file size")
        name = data[offset + 8 : offset + 28].split(b"\0", 1)[0].decode()
        records.append((offset, end_offset, name))
        offset = end_offset
    return records


def add_placeholder_collisions(data: bytes, names: list[str]) -> bytes:
    records = collision_records(data)
    existing = {name for _, _, name in records}
    additions = [name for name in names if name not in existing]
    if not additions:
        return data

    candidates = [
        data[offset:end_offset]
        for offset, end_offset, _ in records
        if end_offset - offset > 120
    ]
    if not candidates:
        raise ValueError("collision template not found")
    template = min(candidates, key=len)

    output = bytearray(data)
    for name in additions:
        encoded = name.encode()
        if len(encoded) > 20:
            raise ValueError(f"collision name is too long: {name}")
        record = bytearray(template)
        record[8:28] = encoded.ljust(20, b"\0")
        output.extend(record)
    collision_records(output)
    return bytes(output)


def relocate_appended_objects(payload: bytes, marker: bytes = MARKER) -> bytes:
    marker_offset = payload.find(marker)
    if marker_offset < 0:
        raise ValueError("objects marker not found")
    if payload.find(marker, marker_offset + 1) >= 0:
        raise ValueError("objects marker is not unique")

    newline = b"\r\n" if b"\r\n" in payload else b"\n"
    block_offset = marker_offset
    if payload[marker_offset - len(newline) : marker_offset] == newline:
        block_offset -= len(newline)

    block = payload[marker_offset:]
    payload = payload[:block_offset]
    lines = payload.splitlines(keepends=True)

    section = None
    insert_offset = 0
    for line in lines:
        value = line.strip().lower()
        if value in {b"objs", b"anim"}:
            section = value
        elif value == b"end":
            if section == b"objs":
                return (
                    payload[:insert_offset]
                    + marker
                    + newline
                    + block[len(marker) :]
                    + newline
                    + payload[insert_offset:]
                )
            section = None
        insert_offset += len(line)

    raise ValueError("objs section terminator not found")


def repair_archive(data: bytes) -> tuple[bytes, int]:
    replacements = {}
    names = None
    for index, record in enumerate(parse_declared(data)):
        payload = data[record.content_offset : record.end_offset]
        if MARKER in payload:
            relocated = relocate_appended_objects(payload)
            replacements[index] = relocated
            names = object_names(relocated)

    if len(replacements) != 1:
        raise ValueError(f"expected one IDE record, found {len(replacements)}")
    if names is None:
        raise ValueError("IDE object names not found")

    for index, record in enumerate(parse_declared(data)):
        if decode_name(record.name).endswith("/orp_objects.col"):
            payload = data[record.content_offset : record.end_offset]
            replacements[index] = add_placeholder_collisions(payload, names)
            break
    else:
        raise ValueError("orp_objects.col record not found")

    index = next(iter(replacements))
    return replace_payloads(data, replacements), index


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Move appended IDE object definitions into the objs section."
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    repaired, index = repair_archive(args.archive.read_bytes())
    args.output.write_bytes(repaired)
    parse_declared(repaired)
    print(f"{args.output}: relocated IDE objects in record {index}")


if __name__ == "__main__":
    main()
