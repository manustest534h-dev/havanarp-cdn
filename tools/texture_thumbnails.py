#!/usr/bin/env python3

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path

from vfs_archive import Record, parse_declared, replace_payloads


@dataclass(frozen=True)
class ThumbnailRecord:
    data: bytes
    alpha: bool


def decode_name(name: bytes) -> str:
    key = name[0] ^ 0x21
    return bytes(value ^ key for value in name).decode()


def parse_thumbnail_records(data: bytes) -> list[bytes]:
    records = []
    offset = 0
    while offset < len(data):
        if offset + 12 > len(data):
            raise ValueError(f"truncated thumbnail record at offset {offset}")
        payload_size = struct.unpack_from("<I", data, offset + 8)[0]
        end_offset = offset + 12 + payload_size
        if end_offset > len(data):
            raise ValueError(f"thumbnail record at offset {offset} exceeds file size")
        records.append(data[offset:end_offset])
        offset = end_offset
    return records


def is_affiliate(line: str) -> bool:
    return "affiliate=" in line


def is_alpha(line: str) -> bool:
    return " alphamode=" in line


def companion_records(
    records: list[Record], text_record: Record
) -> tuple[int, int, int]:
    text_name = decode_name(text_record.name)
    if not text_name.endswith(".txt"):
        raise ValueError(f"not a texture database descriptor: {text_name}")
    stem = text_name[:-4]
    matches = {}
    for index, record in enumerate(records):
        name = decode_name(record.name)
        for suffix in (".dat", ".tmb", ".toc"):
            if name.startswith(stem + ".") and name.endswith(suffix):
                matches[suffix] = index
    missing = {".dat", ".tmb", ".toc"} - matches.keys()
    if missing:
        raise ValueError(f"{stem} missing companion files: {sorted(missing)}")
    return matches[".dat"], matches[".tmb"], matches[".toc"]


def select_templates(lines: list[str], thumbnails: list[bytes]) -> dict[bool, bytes]:
    templates = {}
    thumbnail_index = 0
    for line in lines:
        if is_affiliate(line):
            continue
        if thumbnail_index == len(thumbnails):
            break
        record = thumbnails[thumbnail_index]
        thumbnail_index += 1
        alpha = is_alpha(line)
        if "flag" in line.lower():
            templates.setdefault(alpha, record)
        if len(templates) == 2:
            break
    for alpha in (False, True):
        if alpha not in templates:
            thumbnail_index = 0
            for line in lines:
                if is_affiliate(line):
                    continue
                if thumbnail_index == len(thumbnails):
                    break
                record = thumbnails[thumbnail_index]
                thumbnail_index += 1
                if is_alpha(line) == alpha:
                    templates[alpha] = record
                    break
    return templates


def repair_database(
    archive: bytes,
    records: list[Record],
    text_index: int,
) -> tuple[int, bytes] | None:
    text_record = records[text_index]
    lines = archive[text_record.content_offset : text_record.end_offset].decode().splitlines()
    entries = lines[1:]
    dat_index, tmb_index, toc_index = companion_records(records, text_record)
    dat_record = records[dat_index]
    tmb_record = records[tmb_index]
    toc_record = records[toc_index]
    dat = archive[dat_record.content_offset : dat_record.end_offset]
    tmb = archive[tmb_record.content_offset : tmb_record.end_offset]
    toc_data = archive[toc_record.content_offset : toc_record.end_offset]
    if len(toc_data) % 4:
        raise ValueError(f"{decode_name(toc_record.name)} size is not divisible by 4")
    offsets = struct.unpack(f"<{len(toc_data) // 4}I", toc_data)
    if len(offsets) != len(entries) + 1:
        raise ValueError(
            f"{decode_name(toc_record.name)} has {len(offsets) - 1} entries; "
            f"descriptor has {len(entries)}"
        )
    if offsets[0] != len(dat):
        raise ValueError(
            f"{decode_name(toc_record.name)} declares DAT size {offsets[0]}; "
            f"actual size is {len(dat)}"
        )

    thumbnails = parse_thumbnail_records(tmb)
    texture_entries = [
        (entry_index, line)
        for entry_index, line in enumerate(entries)
        if not is_affiliate(line)
    ]
    if len(thumbnails) == len(texture_entries):
        return None
    if len(thumbnails) > len(texture_entries):
        raise ValueError(
            f"{decode_name(tmb_record.name)} has more thumbnails than textures"
        )

    templates = select_templates(entries, thumbnails)
    additions = bytearray()
    for entry_index, line in texture_entries[len(thumbnails) :]:
        alpha = is_alpha(line)
        if alpha not in templates:
            raise ValueError(f"no {'alpha' if alpha else 'opaque'} template available")
        dat_offset = offsets[entry_index + 1]
        if dat_offset + 2 > len(dat):
            raise ValueError(f"DAT offset for entry {entry_index} exceeds file size")
        template = templates[alpha]
        additions.extend(dat[dat_offset : dat_offset + 2])
        additions.extend(template[2:])

    repaired = tmb + additions
    if len(parse_thumbnail_records(repaired)) != len(texture_entries):
        raise ValueError("thumbnail repair did not produce the expected record count")
    return tmb_index, repaired


def repair_archive(data: bytes) -> tuple[bytes, list[tuple[str, int, int]]]:
    records = parse_declared(data)
    replacements = {}
    changes = []
    for index, record in enumerate(records):
        if not decode_name(record.name).endswith(".txt"):
            continue
        repaired = repair_database(data, records, index)
        if repaired is None:
            continue
        tmb_index, payload = repaired
        old_size = records[tmb_index].packed_size
        replacements[tmb_index] = payload
        changes.append((decode_name(records[tmb_index].name), old_size, len(payload)))
    if not replacements:
        return data, []
    repaired_archive = replace_payloads(data, replacements)
    parse_declared(repaired_archive)
    return repaired_archive, changes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add missing texture thumbnails to HavanaRP VFS databases."
    )
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    repaired, changes = repair_archive(args.archive.read_bytes())
    if not changes:
        raise SystemExit("no missing texture thumbnails found")
    args.output.write_bytes(repaired)
    for name, old_size, new_size in changes:
        print(f"{name}: {old_size} -> {new_size}")
    print(f"{args.output}: repaired and validated")


if __name__ == "__main__":
    main()
