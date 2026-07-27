#!/usr/bin/env python3
"""Patch and validate HavanaRP multipart game containers.

This fixes the v763 corruption where bytes inserted into record 77 were left
outside the record payload size fields, causing the native sequential parser to
stop before AMERICAN.GXT. It also repairs the same class of corruption across
the v763 ``.custom3`` archives, where truncated ``orp_objects_03`` records hide
the texture database index and produce launcher loading error 002.
"""

from __future__ import annotations

import argparse
import binascii
import hashlib
import io
import json
import mmap
import shutil
import struct
import subprocess
import tempfile
import urllib.parse
import zipfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BAD_RECORD_OFFSET = 13_400_056
BAD_GAP_OFFSET = 13_413_226
BAD_PAYLOAD_SIZE = 13_100
GOOD_PAYLOAD_SIZE = 16_477
GAP_PREFIX = b"\r\n\r\n# Havana country flag accessories"
EXPECTED_RECORDS = 515
EXPECTED_FINAL_TRAILER = 1
EXPECTED_GXT_INDEX = 504
EXPECTED_GXT_PATH = "!client/text/american.gxt"
EXPECTED_GXT_SIZE = 1_339_116
SPLIT_SIZE = 18_000_000
ZIP_TIMESTAMP = (2026, 7, 27, 18, 30, 0)

CUSTOM3_REPAIRS = {
    ".custom3": (
        (8_579_213, "!client/texdb/orp_objects_03.img", 71_159_808, 73_551_872),
    ),
    ".custom3_etc": (
        (
            42_479_427,
            "!client/texdb/orp_objects_03/orp_objects_03.etc.dat",
            131_405_606,
            134_160_766,
        ),
        (
            176_719_651,
            "!client/texdb/orp_objects_03/orp_objects_03.etc.toc",
            5_316,
            5_648,
        ),
        (
            176_725_380,
            "!client/texdb/orp_objects_03/orp_objects_03.txt",
            70_461,
            74_736,
        ),
    ),
    ".custom3_dxt": (
        (
            37_577_091,
            "!client/texdb/orp_objects_03/orp_objects_03.dxt.dat",
            112_787_784,
            115_542_944,
        ),
        (
            153_188_293,
            "!client/texdb/orp_objects_03/orp_objects_03.dxt.toc",
            5_316,
            5_648,
        ),
        (
            153_194_022,
            "!client/texdb/orp_objects_03/orp_objects_03.txt",
            70_461,
            74_740,
        ),
    ),
    ".custom3_pvr": (
        (
            31_614_675,
            "!client/texdb/orp_objects_03/orp_objects_03.pvr.dat",
            98_755_296,
            101_517_072,
        ),
        (
            133_194_405,
            "!client/texdb/orp_objects_03/orp_objects_03.pvr.toc",
            5_316,
            5_648,
        ),
        (
            133_200_134,
            "!client/texdb/orp_objects_03/orp_objects_03.txt",
            70_461,
            74_731,
        ),
    ),
}
CUSTOM3_EXPECTED_RECORD_COUNTS = {
    ".custom3": 7,
    ".custom3_etc": 22,
    ".custom3_dxt": 22,
    ".custom3_pvr": 22,
}
CUSTOM3_EXPECTED_PARTS = {
    ".custom3": 4,
    ".custom3_etc": 6,
    ".custom3_dxt": 7,
    ".custom3_pvr": 6,
}


@dataclass(frozen=True)
class Record:
    index: int
    offset: int
    header_size: int
    payload_offset: int
    payload_size_a: int
    payload_size_b: int
    path: str

    @property
    def payload_size(self) -> int:
        if self.payload_size_a != self.payload_size_b:
            raise ValueError(f"record {self.index} has mismatched size fields")
        return self.payload_size_a

    @property
    def end(self) -> int:
        return self.payload_offset + self.payload_size


def crc32(data: bytes) -> str:
    return f"{binascii.crc32(data) & 0xFFFFFFFF:08X}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_path(encoded: bytes) -> str:
    candidates = []
    for key in range(256):
        try:
            decoded = bytes(b ^ key for b in encoded).decode("utf-8")
        except UnicodeDecodeError:
            continue
        if decoded and all(32 <= ord(ch) < 127 for ch in decoded):
            candidates.append(decoded)
    if not candidates:
        raise UnicodeDecodeError("xor-path", encoded, 0, len(encoded), "no printable path")
    for decoded in candidates:
        if decoded.startswith("!client/"):
            return decoded
    return candidates[0]


def parse_records(data: bytes, *, strict: bool) -> tuple[list[Record], bytes]:
    records: list[Record] = []
    offset = 0
    while offset + 30 <= len(data):
        name_len = struct.unpack_from("<I", data, offset + 26)[0]
        if name_len <= 0 or name_len > 512:
            break
        header_size = 30 + name_len
        if offset + header_size > len(data):
            break
        try:
            path = decode_path(data[offset + 30 : offset + header_size])
        except UnicodeDecodeError:
            break
        size_a = struct.unpack_from("<I", data, offset + 18)[0]
        size_b = struct.unpack_from("<I", data, offset + 22)[0]
        rec = Record(
            index=len(records),
            offset=offset,
            header_size=header_size,
            payload_offset=offset + header_size,
            payload_size_a=size_a,
            payload_size_b=size_b,
            path=path.lower(),
        )
        if strict and rec.payload_size_a != rec.payload_size_b:
            raise AssertionError(
                f"record {rec.index} has mismatched payload sizes "
                f"{rec.payload_size_a} != {rec.payload_size_b}"
            )
        records.append(rec)
        offset = rec.end
    trailer = data[offset:]
    if strict:
        if len(records) != EXPECTED_RECORDS:
            raise AssertionError(f"expected {EXPECTED_RECORDS} records, got {len(records)}")
        if len(trailer) != EXPECTED_FINAL_TRAILER:
            raise AssertionError(f"expected one-byte final trailer, got {len(trailer)} bytes")
        gxt = records[EXPECTED_GXT_INDEX]
        if gxt.path != EXPECTED_GXT_PATH or gxt.payload_size != EXPECTED_GXT_SIZE:
            raise AssertionError(
                f"record {EXPECTED_GXT_INDEX} is {gxt.path} size {gxt.payload_size}, "
                f"expected {EXPECTED_GXT_PATH} size {EXPECTED_GXT_SIZE}"
            )
    return records, trailer


def read_joined_zip(parts_dir: Path) -> bytes:
    chunks = []
    for part in sorted(parts_dir.glob("part-*")):
        chunks.append(part.read_bytes())
    if not chunks:
        raise FileNotFoundError(f"no part-* files found in {parts_dir}")
    return b"".join(chunks)


def extract_member(zip_bytes: bytes, target: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if names != [target]:
            raise AssertionError(f"expected ZIP to contain only {target}, got {names}")
        return zf.read(target)


def extract_data(zip_bytes: bytes) -> bytes:
    return extract_member(zip_bytes, ".data")


def assert_known_v763_corruption(data: bytes) -> None:
    if data[BAD_GAP_OFFSET : BAD_GAP_OFFSET + len(GAP_PREFIX)] != GAP_PREFIX:
        raise AssertionError("expected illegal gap prefix was not found")
    size_a = struct.unpack_from("<I", data, BAD_RECORD_OFFSET + 18)[0]
    size_b = struct.unpack_from("<I", data, BAD_RECORD_OFFSET + 22)[0]
    if (size_a, size_b) != (BAD_PAYLOAD_SIZE, BAD_PAYLOAD_SIZE):
        raise AssertionError(f"expected bad sizes 13100/13100, got {size_a}/{size_b}")
    records, trailer = parse_records(data, strict=False)
    if len(records) < 78:
        raise AssertionError("non-strict parse failed before record 78")
    rec = records[77]
    if rec.offset != BAD_RECORD_OFFSET:
        raise AssertionError(f"record 77 offset {rec.offset}, expected {BAD_RECORD_OFFSET}")
    if rec.path != "!client/data/maps/orp/orp_objects_03.ide":
        raise AssertionError(f"record 77 path mismatch: {rec.path}")
    if rec.end != BAD_GAP_OFFSET:
        raise AssertionError(f"record 77 end {rec.end}, expected bad gap at {BAD_GAP_OFFSET}")
    if any(r.path == EXPECTED_GXT_PATH for r in records):
        raise AssertionError("bad sequential parse unexpectedly reached american.gxt")
    if not trailer.startswith(GAP_PREFIX):
        raise AssertionError("bad parse trailer does not begin with the inserted gap")


def patch_data(data: bytes) -> bytes:
    patched = bytearray(data)
    struct.pack_into("<I", patched, BAD_RECORD_OFFSET + 18, GOOD_PAYLOAD_SIZE)
    struct.pack_into("<I", patched, BAD_RECORD_OFFSET + 22, GOOD_PAYLOAD_SIZE)
    return bytes(patched)


def encoded_record_path(data: bytes | bytearray | mmap.mmap, offset: int) -> str:
    name_len = struct.unpack_from("<I", data, offset + 26)[0]
    return decode_path(data[offset + 30 : offset + 30 + name_len]).lower()


def apply_custom3_repairs(data: bytearray | mmap.mmap, target: str) -> None:
    for offset, expected_path, bad_size, good_size in CUSTOM3_REPAIRS[target]:
        size_a, size_b = struct.unpack_from("<II", data, offset + 18)
        if (size_a, size_b) != (bad_size, bad_size):
            raise AssertionError(
                f"{target} record at {offset} has sizes {size_a}/{size_b}, "
                f"expected {bad_size}/{bad_size}"
            )
        actual_path = encoded_record_path(data, offset)
        if actual_path != expected_path:
            raise AssertionError(
                f"{target} record at {offset} is {actual_path}, expected {expected_path}"
            )
        struct.pack_into("<II", data, offset + 18, good_size, good_size)


def validate_custom3_records(
    data: bytes | bytearray | mmap.mmap, target: str
) -> tuple[list[Record], bytes]:
    records, trailer = parse_records(data, strict=False)
    expected_count = CUSTOM3_EXPECTED_RECORD_COUNTS[target]
    if len(records) != expected_count:
        raise AssertionError(
            f"{target} expected {expected_count} records, got {len(records)}"
        )
    if len(trailer) != EXPECTED_FINAL_TRAILER:
        raise AssertionError(
            f"expected one-byte {target} final trailer, got {len(trailer)} bytes"
        )
    by_offset = {record.offset: record for record in records}
    for offset, expected_path, _bad_size, good_size in CUSTOM3_REPAIRS[target]:
        record = by_offset.get(offset)
        if record is None:
            raise AssertionError(f"{target} has no record at repaired offset {offset}")
        if record.path != expected_path or record.payload_size != good_size:
            raise AssertionError(
                f"{target} repaired record is {record.path} size {record.payload_size}, "
                f"expected {expected_path} size {good_size}"
            )
    if target == ".custom3":
        required = {
            4: "!client/texdb/orp_skins_02.img",
            5: "!client/texdb/orp_vehicles_02.img",
        }
    else:
        required = {
            11: "!client/texdb/orp_objects_03/orp_objects_03.txt",
            12: "!client/texdb/orp_skins_02/",
            17: "!client/texdb/orp_vehicles_02/",
            21: "!client/texdb/orp_vehicles_02/orp_vehicles_02.txt",
        }
    for index, expected_path in required.items():
        if records[index].path != expected_path:
            raise AssertionError(
                f"{target} record {index} is {records[index].path}, "
                f"expected {expected_path}"
            )
    return records, trailer


def make_zip(data: bytes | bytearray, target: str) -> bytes:
    buf = io.BytesIO()
    info = zipfile.ZipInfo(target, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(info, data)
    return buf.getvalue()


def write_v764(zip_bytes: bytes, data: bytes) -> dict[str, str | int]:
    out_dir = ROOT / "files/764/multipart/764/data"
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = [zip_bytes[i : i + SPLIT_SIZE] for i in range(0, len(zip_bytes), SPLIT_SIZE)]
    if len(parts) != 2:
        raise AssertionError(f"expected 2 parts, got {len(parts)}")
    meta: dict[str, str | int] = {
        "target": ".data",
        "parts": len(parts),
        "joined_size": len(zip_bytes),
        "joined_sha256": sha256(zip_bytes),
        "output_size": len(data),
        "output_crc32": crc32(data),
    }
    for i, part in enumerate(parts):
        (out_dir / f"part-{i:03d}").write_bytes(part)
        meta[f"part_{i:03d}_size"] = len(part)
        meta[f"part_{i:03d}_sha256"] = sha256(part)
    lines = [f"{key}={value}" for key, value in meta.items()]
    (out_dir / "manifest.properties").write_text("\n".join(lines) + "\n")
    return meta


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as src:
        while chunk := src.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def crc32_file(path: Path) -> str:
    checksum = 0
    with path.open("rb") as src:
        while chunk := src.read(1024 * 1024):
            checksum = binascii.crc32(chunk, checksum)
    return f"{checksum & 0xFFFFFFFF:08X}"


def join_parts_to_path(parts_dir: Path, output: Path) -> None:
    parts = sorted(parts_dir.glob("part-*"))
    if not parts:
        raise FileNotFoundError(f"no part-* files found in {parts_dir}")
    with output.open("wb") as dst:
        for part in parts:
            with part.open("rb") as src:
                shutil.copyfileobj(src, dst, 1024 * 1024)


def extract_member_to_path(zip_path: Path, target: str, output: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if names != [target]:
            raise AssertionError(f"expected ZIP to contain only {target}, got {names}")
        with zf.open(target) as src, output.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)


def make_zip_from_path(data_path: Path, target: str, output: Path) -> None:
    info = zipfile.ZipInfo(target, ZIP_TIMESTAMP)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zf:
        with data_path.open("rb") as src, zf.open(info, "w") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)


def write_v765_custom3(
    zip_path: Path, data_path: Path, target: str
) -> dict[str, str | int]:
    kind = target.removeprefix(".")
    out_dir = ROOT / f"files/765/multipart/765/{kind}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old_part in out_dir.glob("part-*"):
        old_part.unlink()
    parts: list[Path] = []
    with zip_path.open("rb") as src:
        index = 0
        while chunk := src.read(SPLIT_SIZE):
            part = out_dir / f"part-{index:03d}"
            part.write_bytes(chunk)
            parts.append(part)
            index += 1
    if len(parts) != CUSTOM3_EXPECTED_PARTS[target]:
        raise AssertionError(
            f"expected {CUSTOM3_EXPECTED_PARTS[target]} {kind} parts, got {len(parts)}"
        )
    meta: dict[str, str | int] = {
        "target": target,
        "parts": len(parts),
        "joined_size": zip_path.stat().st_size,
        "joined_sha256": sha256_file(zip_path),
        "output_size": data_path.stat().st_size,
        "output_crc32": crc32_file(data_path),
    }
    for i, part in enumerate(parts):
        meta[f"part_{i:03d}_size"] = part.stat().st_size
        meta[f"part_{i:03d}_sha256"] = sha256_file(part)
    lines = [f"{key}={value}" for key, value in meta.items()]
    (out_dir / "manifest.properties").write_text("\n".join(lines) + "\n")
    return meta


def update_manifest(meta: dict[str, str | int]) -> None:
    path = ROOT / "api/update/705/update_705.json"
    doc = json.loads(path.read_text())
    files = doc["files"]
    replacements = {
        "data-part-000": ("multipart/764/data/part-000", int(meta["part_000_size"])),
        "data-part-001": ("multipart/764/data/part-001", int(meta["part_001_size"])),
        "data-manifest": ("multipart/764/data/manifest.properties", None),
    }
    for entry in files:
        if entry["name"] not in replacements:
            continue
        rel, explicit_size = replacements[entry["name"]]
        # The APK builds raw GitHub URLs as files/<version>/<path>, so this
        # resolves to files/764/multipart/764/data/...
        full = ROOT / "files/764" / rel
        if not full.exists():
            raise FileNotFoundError(full)
        data = full.read_bytes()
        size = explicit_size if explicit_size is not None else len(data)
        entry["path"] = rel
        entry["version"] = 764
        entry["size"] = size
        entry["load_size"] = size
        entry["hash"] = crc32(data)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def update_custom3_manifest(
    metas: dict[str, dict[str, str | int]]
) -> None:
    path = ROOT / "api/update/705/update_705.json"
    doc = json.loads(path.read_text())
    replacements: dict[str, tuple[str, int | None]] = {}
    for target, meta in metas.items():
        kind = target.removeprefix(".")
        for i in range(int(meta["parts"])):
            replacements[f"{kind}-part-{i:03d}"] = (
                f"multipart/765/{kind}/part-{i:03d}",
                int(meta[f"part_{i:03d}_size"]),
            )
        replacements[f"{kind}-manifest"] = (
            f"multipart/765/{kind}/manifest.properties",
            None,
        )
    updated = set()
    for entry in doc["files"]:
        if entry["name"] not in replacements:
            continue
        rel, explicit_size = replacements[entry["name"]]
        full = ROOT / "files/765" / rel
        if not full.exists():
            raise FileNotFoundError(full)
        size = explicit_size if explicit_size is not None else full.stat().st_size
        entry["path"] = rel
        entry["version"] = 765
        entry["size"] = size
        entry["load_size"] = size
        entry["hash"] = crc32_file(full)
        updated.add(entry["name"])
    if updated != set(replacements):
        raise AssertionError(
            f"custom3 update entries mismatch: updated {sorted(updated)}, "
            f"expected {sorted(replacements)}"
        )
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")


def validate_v764() -> None:
    parts_dir = ROOT / "files/764/multipart/764/data"
    zip_bytes = read_joined_zip(parts_dir)
    data = extract_data(zip_bytes)
    records, trailer = parse_records(data, strict=True)
    manifest = dict(
        line.split("=", 1)
        for line in (parts_dir / "manifest.properties").read_text().splitlines()
        if line and not line.startswith("#")
    )
    checks = {
        "joined_size": str(len(zip_bytes)),
        "joined_sha256": sha256(zip_bytes),
        "output_size": str(len(data)),
        "output_crc32": crc32(data),
    }
    for i, part in enumerate(sorted(parts_dir.glob("part-*"))):
        b = part.read_bytes()
        checks[f"part_{i:03d}_size"] = str(len(b))
        checks[f"part_{i:03d}_sha256"] = sha256(b)
    for key, value in checks.items():
        if manifest.get(key) != value:
            raise AssertionError(f"manifest {key}={manifest.get(key)!r}, expected {value!r}")
    if len(trailer) != EXPECTED_FINAL_TRAILER:
        raise AssertionError(f"unexpected final trailer: {trailer!r}")
    print(
        f"validated {len(records)} records; {EXPECTED_GXT_PATH} index "
        f"{EXPECTED_GXT_INDEX} size {records[EXPECTED_GXT_INDEX].payload_size}"
    )
    print(
        f"output .data size {len(data)} CRC32 {crc32(data)} SHA256 {sha256(data)}"
    )
    print(f"joined ZIP size {len(zip_bytes)} SHA256 {sha256(zip_bytes)}")
    for i, part in enumerate(sorted(parts_dir.glob("part-*"))):
        b = part.read_bytes()
        print(f"{part.name} size {len(b)} SHA256 {sha256(b)} CRC32 {crc32(b)}")


def validate_v765_custom3() -> None:
    for target in CUSTOM3_REPAIRS:
        kind = target.removeprefix(".")
        parts_dir = ROOT / f"files/765/multipart/765/{kind}"
        parts = sorted(parts_dir.glob("part-*"))
        with tempfile.TemporaryDirectory(prefix=f"validate-{kind}-") as temp:
            joined = Path(temp) / "joined.zip"
            output = Path(temp) / "output"
            join_parts_to_path(parts_dir, joined)
            extract_member_to_path(joined, target, output)
            with output.open("rb") as src, mmap.mmap(
                src.fileno(), 0, access=mmap.ACCESS_READ
            ) as data:
                records, trailer = validate_custom3_records(data, target)
            manifest = dict(
                line.split("=", 1)
                for line in (parts_dir / "manifest.properties").read_text().splitlines()
                if line and not line.startswith("#")
            )
            checks = {
                "target": target,
                "parts": str(len(parts)),
                "joined_size": str(joined.stat().st_size),
                "joined_sha256": sha256_file(joined),
                "output_size": str(output.stat().st_size),
                "output_crc32": crc32_file(output),
            }
            for i, part in enumerate(parts):
                checks[f"part_{i:03d}_size"] = str(part.stat().st_size)
                checks[f"part_{i:03d}_sha256"] = sha256_file(part)
            for key, value in checks.items():
                if manifest.get(key) != value:
                    raise AssertionError(
                        f"{kind} manifest {key}={manifest.get(key)!r}, "
                        f"expected {value!r}"
                    )
            if len(trailer) != EXPECTED_FINAL_TRAILER:
                raise AssertionError(f"unexpected {kind} final trailer: {trailer!r}")
            repaired = CUSTOM3_REPAIRS[target][0]
            print(
                f"validated {len(records)} {kind} records; "
                f"{repaired[1]} size {repaired[3]}"
            )
            print(
                f"{kind} output size {output.stat().st_size} "
                f"CRC32 {crc32_file(output)} SHA256 {sha256_file(output)}"
            )
            print(
                f"{kind} joined ZIP size {joined.stat().st_size} "
                f"SHA256 {sha256_file(joined)}"
            )
            for part in parts:
                print(
                    f"{part.name} size {part.stat().st_size} "
                    f"SHA256 {sha256_file(part)} CRC32 {crc32_file(part)}"
                )

    update = json.loads((ROOT / "api/update/705/update_705.json").read_text())
    entries = {entry["name"]: entry for entry in update["files"]}
    for target in CUSTOM3_REPAIRS:
        kind = target.removeprefix(".")
        parts_dir = ROOT / f"files/765/multipart/765/{kind}"
        files = sorted(parts_dir.glob("part-*")) + [parts_dir / "manifest.properties"]
        for file in files:
            suffix = file.name if file.name.startswith("part-") else "manifest"
            entry = entries[f"{kind}-{suffix}"]
            expected_path = f"multipart/765/{kind}/{file.name}"
            if (
                entry["version"] != 765
                or entry["path"] != expected_path
                or entry["size"] != file.stat().st_size
                or entry["load_size"] != file.stat().st_size
                or entry["hash"] != crc32_file(file)
            ):
                raise AssertionError(f"update entry {entry['name']} does not match {file}")


def validate_update_manifest_urls(*, head: bool) -> None:
    runtime = json.loads((ROOT / "api/runtime/config.json").read_text())
    update = json.loads((ROOT / "api/update/705/update_705.json").read_text())
    if len(update["files"]) != 148:
        raise AssertionError(f"expected 148 update entries, got {len(update['files'])}")
    url_host = runtime["urls"]["URL_HOST"].rstrip("/")
    for entry in update["files"]:
        version = entry["version"]
        rel = entry["path"]
        archive = entry["archive"]
        if rel.startswith("multipart/"):
            url = (
                "https://raw.githubusercontent.com/manustest534h-dev/havanarp-cdn/main/"
                f"files/{version}/{quote_path(rel)}"
            )
        elif version == 707:
            # Launcher 4.17.17 routes v707 through its dedicated GitHub
            # release instead of URL_HOST (FileData.j in the APK).
            url = (
                "https://github.com/manustest534h-dev/havanarp-cdn/releases/"
                f"download/data-flags-707-test/default{quote_path(rel)}{archive}"
            )
        else:
            url = f"{url_host}/files/{version}/{quote_path(rel)}{archive}"
        if head:
            code, length = head_url(url)
            if code != 200:
                raise AssertionError(f"{url} returned HTTP {code}")
            if length is not None and length != entry["load_size"]:
                raise AssertionError(
                    f"{url} length {length}, expected {entry['load_size']}"
                )
        else:
            print(f"{entry['name']}: {url}")


def quote_path(path: str) -> str:
    return "/".join(urllib.parse.quote(part, safe="") for part in path.split("/"))


def head_url(url: str) -> tuple[int, int | None]:
    proc = subprocess.run(
        ["curl", "-sSIL", "--max-time", "45", url],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise AssertionError(f"curl failed for {url}: {proc.stderr.strip()}")
    statuses: list[int] = []
    lengths: list[int] = []
    for line in proc.stdout.splitlines():
        if line.startswith("HTTP/"):
            statuses.append(int(line.split()[1]))
        elif line.lower().startswith("content-length:"):
            lengths.append(int(line.split(":", 1)[1].strip()))
    if not statuses:
        raise AssertionError(f"no HTTP status for {url}")
    return statuses[-1], (lengths[-1] if lengths else None)


def build() -> None:
    zip_bytes = read_joined_zip(ROOT / "files/763/multipart/763/data")
    data = extract_data(zip_bytes)
    assert_known_v763_corruption(data)
    patched = patch_data(data)
    parse_records(patched, strict=True)
    out_zip = make_zip(patched, ".data")
    meta = write_v764(out_zip, patched)
    update_manifest(meta)
    validate_v764()


def build_custom3() -> None:
    metas: dict[str, dict[str, str | int]] = {}
    for target in CUSTOM3_REPAIRS:
        kind = target.removeprefix(".")
        source_dir = ROOT / f"files/763/multipart/763/{kind}"
        with tempfile.TemporaryDirectory(prefix=f"repair-{kind}-") as temp:
            joined = Path(temp) / "source.zip"
            output = Path(temp) / target
            repaired_zip = Path(temp) / "repaired.zip"
            join_parts_to_path(source_dir, joined)
            extract_member_to_path(joined, target, output)
            with output.open("r+b") as dst, mmap.mmap(
                dst.fileno(), 0, access=mmap.ACCESS_WRITE
            ) as data:
                apply_custom3_repairs(data, target)
                validate_custom3_records(data, target)
                data.flush()
            make_zip_from_path(output, target, repaired_zip)
            metas[target] = write_v765_custom3(
                repaired_zip, output, target
            )
    update_custom3_manifest(metas)
    validate_v765_custom3()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=["build", "build-custom3", "validate", "urls"]
    )
    parser.add_argument("--head", action="store_true", help="HEAD every constructed URL")
    args = parser.parse_args()
    if args.command == "build":
        build()
    elif args.command == "build-custom3":
        build_custom3()
    elif args.command == "validate":
        validate_v764()
        validate_v765_custom3()
    elif args.command == "urls":
        validate_update_manifest_urls(head=args.head)


if __name__ == "__main__":
    main()
