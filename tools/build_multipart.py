#!/usr/bin/env python3

import argparse
import hashlib
import os
import tempfile
import zipfile
import zlib
from pathlib import Path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def build_zip(
    source: Path,
    archive_name: str,
    destination: Path,
    marker: str | None = None,
) -> None:
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        archive.writestr(zip_info(archive_name), source.read_bytes())
        if marker is not None:
            archive.writestr(zip_info(marker), b"installed\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a deterministic multipart ZIP and descriptor."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("bundle_dir", type=Path)
    parser.add_argument("--target", required=True)
    parser.add_argument("--part-size", type=int, default=18_000_000)
    parser.add_argument("--zip-output", type=Path)
    parser.add_argument("--marker")
    args = parser.parse_args()

    args.bundle_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=args.bundle_dir.parent, suffix=".zip", delete=False
    ) as temporary:
        zip_path = Path(temporary.name)
    try:
        build_zip(args.source, args.target, zip_path, args.marker)
        joined = zip_path.read_bytes()
        parts = [
            joined[offset : offset + args.part_size]
            for offset in range(0, len(joined), args.part_size)
        ]

        for old_part in args.bundle_dir.glob("part-*"):
            old_part.unlink()
        for index, part in enumerate(parts):
            (args.bundle_dir / f"part-{index:03d}").write_bytes(part)

        output = args.source.read_bytes()
        lines = [
            f"target={args.target}",
            f"parts={len(parts)}",
            f"joined_size={len(joined)}",
            f"joined_sha256={sha256(joined)}",
            f"output_size={len(output)}",
            f"output_crc32={zlib.crc32(output) & 0xFFFFFFFF:08X}",
        ]
        for index, part in enumerate(parts):
            lines.extend(
                [
                    f"part_{index:03d}_size={len(part)}",
                    f"part_{index:03d}_sha256={sha256(part)}",
                ]
            )
        (args.bundle_dir / "manifest.properties").write_text(
            "\n".join(lines) + "\n", encoding="ascii"
        )

        if args.zip_output is not None:
            args.zip_output.parent.mkdir(parents=True, exist_ok=True)
            os.replace(zip_path, args.zip_output)
            zip_path = None
    finally:
        if zip_path is not None:
            zip_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
