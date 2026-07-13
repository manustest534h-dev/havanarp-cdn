import tempfile
import unittest
import zipfile
from pathlib import Path

from build_multipart import build_zip


class BuildMultipartTest(unittest.TestCase):
    def test_marker_is_written_after_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / ".custom3"
            destination = root / "default.custom3.zip"
            source.write_bytes(b"archive")

            build_zip(
                source,
                ".custom3",
                destination,
                ".live_russia_skins_17515",
            )

            with zipfile.ZipFile(destination) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [".custom3", ".live_russia_skins_17515"],
                )
                self.assertEqual(archive.read(".custom3"), b"archive")
                self.assertEqual(
                    archive.read(".live_russia_skins_17515"),
                    b"installed\n",
                )


if __name__ == "__main__":
    unittest.main()
