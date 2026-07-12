#!/usr/bin/env python3

import argparse
import json
import zlib
from pathlib import Path


TARGETS = (".custom3", ".custom3_dxt", ".custom3_etc", ".custom3_pvr", ".data")


def crc32(path: Path) -> str:
    checksum = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum = zlib.crc32(chunk, checksum)
    return f"{checksum & 0xFFFFFFFF:08X}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synchronize update JSON sizes and CRC32 values."
    )
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--fixed-dir", type=Path, required=True)
    parser.add_argument("--zip-dir", type=Path, required=True)
    parser.add_argument("--files-root", type=Path, default=Path("files/707"))
    args = parser.parse_args()

    document = json.loads(args.manifest.read_text(encoding="utf-8"))
    updated = 0
    for entry in document["files"]:
        path = entry["path"]
        if path in TARGETS:
            output = args.fixed_dir / path
            download = (
                output
                if not entry["archive"]
                else args.zip_dir / f"{path.removeprefix('.')}.zip"
            )
            entry["size"] = output.stat().st_size
            entry["load_size"] = download.stat().st_size
            entry["hash"] = crc32(output)
            updated += 1
        elif path.startswith("multipart/707/"):
            artifact = args.files_root / path
            entry["size"] = artifact.stat().st_size
            entry["load_size"] = artifact.stat().st_size
            entry["hash"] = crc32(artifact)
            updated += 1

    args.manifest.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"updated {updated} manifest entries")


if __name__ == "__main__":
    main()
