import json
import unittest
from pathlib import Path

from direct_release import MULTIPART_PREFIX, TARGETS, rewrite_manifest


class DirectReleaseTest(unittest.TestCase):
    def test_rewrites_targets_and_removes_multipart_entries(self) -> None:
        document = {
            "files": [
                {
                    "path": target,
                    "version": 707,
                    "update_type": "exists",
                }
                for target in sorted(TARGETS)
            ]
            + [
                {
                    "path": "multipart/707/data/part-000",
                    "version": 707,
                    "update_type": "exists",
                },
                {
                    "path": ".default",
                    "version": 420,
                    "update_type": "strong",
                },
            ]
        }

        rewritten, removed = rewrite_manifest(document)

        self.assertEqual(removed, 1)
        self.assertFalse(
            any(
                entry["path"].startswith(MULTIPART_PREFIX)
                for entry in rewritten["files"]
            )
        )
        self.assertTrue(
            all(
                entry["update_type"] == "strong"
                for entry in rewritten["files"]
                if entry["path"] in TARGETS
            )
        )
        self.assertEqual(document["files"][0]["update_type"], "exists")

    def test_published_manifest_uses_multipart_delivery(self) -> None:
        manifest = (
            Path(__file__).parents[1] / "api/update/705/update_705.json"
        )
        document = json.loads(manifest.read_text(encoding="utf-8"))
        entries = {entry["path"]: entry for entry in document["files"]}

        self.assertTrue(TARGETS.isdisjoint(entries))
        self.assertTrue(
            {
                f"{MULTIPART_PREFIX}{bundle}/manifest.properties"
                for bundle in (
                    "custom3",
                    "custom3_dxt",
                    "custom3_etc",
                    "custom3_pvr",
                    "data",
                )
            }.issubset(entries)
        )
        self.assertTrue(
            all(
                entry["update_type"] == "exists"
                for path, entry in entries.items()
                if path.startswith(MULTIPART_PREFIX)
            )
        )


if __name__ == "__main__":
    unittest.main()
