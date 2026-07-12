#!/usr/bin/env python3

import argparse
import copy
import json
from pathlib import Path


TARGETS = frozenset(
    (".custom3", ".custom3_dxt", ".custom3_etc", ".custom3_pvr", ".data")
)
MULTIPART_PREFIX = "multipart/707/"
RELEASE_VERSION = 707


def rewrite_manifest(document: dict) -> tuple[dict, int]:
    rewritten = copy.deepcopy(document)
    files = []
    found_targets = set()
    removed_multipart = 0

    for entry in rewritten["files"]:
        path = entry["path"]
        if path.startswith(MULTIPART_PREFIX):
            removed_multipart += 1
            continue
        if path in TARGETS:
            if entry["version"] != RELEASE_VERSION:
                raise ValueError(
                    f"{path} must remain version {RELEASE_VERSION} for launcher routing"
                )
            entry["update_type"] = "strong"
            found_targets.add(path)
        files.append(entry)

    missing = TARGETS - found_targets
    if missing:
        raise ValueError(f"missing release targets: {', '.join(sorted(missing))}")

    rewritten["files"] = files
    return rewritten, removed_multipart


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Route update 707 through the launcher's direct release fallback."
    )
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    document = json.loads(args.manifest.read_text(encoding="utf-8"))
    rewritten, removed_multipart = rewrite_manifest(document)
    args.manifest.write_text(
        json.dumps(rewritten, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"set {len(TARGETS)} release targets to strong and removed "
        f"{removed_multipart} multipart entries"
    )


if __name__ == "__main__":
    main()
