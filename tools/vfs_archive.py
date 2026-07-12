#!/usr/bin/env python3

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path


MAGIC = b"\xb8\xd4\x5c\x1f"
HEADER = struct.Struct("<4sI6sIIII")


@dataclass(frozen=True)
class Record:
    offset: int
    packed_size: int
    unpacked_size: int
    name: bytes
    content_offset: int
    end_offset: int


def parse_declared(data: bytes) -> list[Record]:
    records = []
    offset = 0
    while offset < len(data):
        if len(data) - offset == 1:
            break
        if offset + HEADER.size > len(data):
            raise ValueError(f"truncated header at offset {offset}")
        magic, _, _, _, packed_size, unpacked_size, name_size = HEADER.unpack_from(
            data, offset
        )
        if magic != MAGIC:
            raise ValueError(f"invalid record magic at offset {offset}")
        name_offset = offset + HEADER.size
        content_offset = name_offset + name_size
        end_offset = content_offset + packed_size
        if content_offset > len(data) or end_offset > len(data):
            raise ValueError(f"record at offset {offset} exceeds archive size")
        records.append(
            Record(
                offset=offset,
                packed_size=packed_size,
                unpacked_size=unpacked_size,
                name=data[name_offset:content_offset],
                content_offset=content_offset,
                end_offset=end_offset,
            )
        )
        offset = end_offset
    return records


def repair_sizes(base: bytes, modified: bytes) -> tuple[bytes, list[tuple[int, int, int]]]:
    base_records = parse_declared(base)
    trailer_size = len(base) - base_records[-1].end_offset
    if trailer_size not in (0, 1):
        raise ValueError(f"unsupported base archive trailer size: {trailer_size}")
    repaired = bytearray(modified)
    offset = 0
    changes = []

    for index, base_record in enumerate(base_records):
        if offset + HEADER.size > len(modified):
            raise ValueError(f"modified archive ends before record {index}")

        base_header = base[base_record.offset : base_record.content_offset]
        _, _, _, _, packed_size, unpacked_size, name_size = HEADER.unpack_from(
            modified, offset
        )
        content_offset = offset + HEADER.size + name_size
        modified_header = modified[offset:content_offset]

        if modified_header[:18] != base_header[:18]:
            raise ValueError(f"record identity changed at index {index}")
        if modified_header[26:] != base_header[26:]:
            raise ValueError(f"record name changed at index {index}")

        if index + 1 == len(base_records):
            next_offset = len(modified) - trailer_size
        else:
            next_base = base_records[index + 1]
            next_signature = base[next_base.offset : next_base.content_offset]
            matches = []
            search_offset = content_offset
            while True:
                match = modified.find(next_signature, search_offset)
                if match < 0:
                    break
                matches.append(match)
                search_offset = match + 1
            if len(matches) != 1:
                raise ValueError(
                    f"expected one boundary for record {index}, found {len(matches)}"
                )
            next_offset = matches[0]

        actual_size = next_offset - content_offset
        if actual_size != packed_size:
            if packed_size != unpacked_size:
                raise ValueError(
                    f"cannot repair compressed record {index} without recompression"
                )
            struct.pack_into("<I", repaired, offset + 18, actual_size)
            struct.pack_into("<I", repaired, offset + 22, actual_size)
            changes.append((index, packed_size, actual_size))
        offset = next_offset

    if offset + trailer_size != len(modified):
        raise ValueError("modified archive has trailing data")
    return bytes(repaired), changes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate or repair HavanaRP VFS record sizes."
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("--base", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    data = args.archive.read_bytes()
    if args.base is None:
        records = parse_declared(data)
        print(f"{args.archive}: valid ({len(records)} records, {len(data)} bytes)")
        return

    if args.output is None:
        parser.error("--output is required with --base")

    repaired, changes = repair_sizes(args.base.read_bytes(), data)
    if not changes:
        raise SystemExit("no invalid record sizes found")
    args.output.write_bytes(repaired)
    parse_declared(repaired)
    for index, old_size, new_size in changes:
        print(f"record {index}: {old_size} -> {new_size}")
    print(f"{args.output}: repaired and validated")


if __name__ == "__main__":
    main()
