#!/usr/bin/env python3

import argparse
import hashlib
import tempfile
import zipfile
from pathlib import Path

from vfs_archive import parse_declared


def properties(path: Path) -> dict[str, str]:
    result = {}
    for line in path.read_text(encoding="ascii").splitlines():
        key, value = line.split("=", 1)
        result[key] = value
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify(bundle_dir: Path) -> None:
    descriptor = properties(bundle_dir / "manifest.properties")
    part_count = int(descriptor["parts"])

    with tempfile.NamedTemporaryFile(suffix=".zip") as joined:
        joined_digest = hashlib.sha256()
        joined_size = 0
        for index in range(part_count):
            part = bundle_dir / f"part-{index:03d}"
            expected_size = int(descriptor[f"part_{index:03d}_size"])
            if part.stat().st_size != expected_size:
                raise ValueError(f"{part}: size mismatch")
            if sha256(part) != descriptor[f"part_{index:03d}_sha256"]:
                raise ValueError(f"{part}: SHA-256 mismatch")
            with part.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    joined.write(chunk)
                    joined_digest.update(chunk)
                    joined_size += len(chunk)

        if joined_size != int(descriptor["joined_size"]):
            raise ValueError(f"{bundle_dir}: joined size mismatch")
        if joined_digest.hexdigest() != descriptor["joined_sha256"]:
            raise ValueError(f"{bundle_dir}: joined SHA-256 mismatch")

        joined.flush()
        with zipfile.ZipFile(joined.name) as archive:
            names = archive.namelist()
            if names != [descriptor["target"]]:
                raise ValueError(f"{bundle_dir}: unexpected ZIP entries: {names}")
            info = archive.getinfo(descriptor["target"])
            if info.file_size != int(descriptor["output_size"]):
                raise ValueError(f"{bundle_dir}: output size mismatch")
            if f"{info.CRC:08X}" != descriptor["output_crc32"]:
                raise ValueError(f"{bundle_dir}: output CRC32 mismatch")
            parse_declared(archive.read(descriptor["target"]))

    print(f"{bundle_dir}: verified")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify multipart hashes, ZIP metadata, and VFS structure."
    )
    parser.add_argument("bundle_dirs", nargs="+", type=Path)
    args = parser.parse_args()
    for bundle_dir in args.bundle_dirs:
        verify(bundle_dir)


if __name__ == "__main__":
    main()
