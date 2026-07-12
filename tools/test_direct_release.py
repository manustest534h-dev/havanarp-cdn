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

    def test_published_manifest_uses_direct_release_fallback(self) -> None:
        manifest = (
            Path(__file__).parents[1] / "api/update/705/update_705.json"
        )
        document = json.loads(manifest.read_text(encoding="utf-8"))
        rewritten, removed = rewrite_manifest(document)
        entries = {entry["path"]: entry for entry in document["files"]}

        self.assertEqual(rewritten, document)
        self.assertEqual(removed, 0)
        self.assertTrue(TARGETS.issubset(entries))
        self.assertTrue(
            all(entries[target]["update_type"] == "strong" for target in TARGETS)
        )
        self.assertFalse(
            any(path.startswith(MULTIPART_PREFIX) for path in entries)
        )


if __name__ == "__main__":
    unittest.main()
