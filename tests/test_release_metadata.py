"""Publishing must refuse a tag for a different artifact version."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from release_metadata import TARGETS, metadata


class ReleaseMetadataTests(unittest.TestCase):
    def test_current_packages_and_exact_tags(self):
        for target in TARGETS:
            with self.subTest(target=target):
                result = metadata(target)
                self.assertEqual(result, metadata(target, result["tag"]))
                with self.assertRaises(ValueError):
                    metadata(target, result["tag"] + "-wrong")

    def test_rejects_nonstable_or_injected_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            location = root / TARGETS["npm-react-auth"][0]
            location.mkdir(parents=True)
            for version in ("1.2.3\nname=other", "1.0.0-beta.1", "latest", None):
                (location / "package.json").write_text(
                    json.dumps({"name": "safe", "version": version})
                )
                with self.assertRaises(ValueError):
                    metadata("npm-react-auth", root=root)

    def test_rejects_output_injection_in_name(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            location = root / TARGETS["npm-react-auth"][0]
            location.mkdir(parents=True)
            (location / "package.json").write_text(
                json.dumps({"name": "other\nx=y", "version": "1.2.3"})
            )
            with self.assertRaises(ValueError):
                metadata("npm-react-auth", root=root)
