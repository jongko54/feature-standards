"""Scanner installation verifies every pinned native engine before execution."""

import hashlib
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import install_security_tools


class NativeScannerInstallationTests(unittest.TestCase):
    def fixtures(self, root):
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as output:
            member = tarfile.TarInfo("gitleaks")
            member.size = len(b"secret engine")
            output.addfile(member, io.BytesIO(b"secret engine"))
        contents = {
            "osv-scanner": b"dependency engine",
            "gitleaks": archive.getvalue(),
            "opengrep": b"native static engine",
        }
        tools = {
            name: {
                "version": "2.0.0",
                "repository": "example/" + name,
                "assets": {
                    "Linux-x86_64": {
                        "name": name,
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                },
            }
            for name, data in contents.items()
        }
        (root / "security").mkdir()
        (root / "security/tools.json").write_text(json.dumps({"tools": tools}))
        return contents

    def test_every_engine_is_checksum_verified_and_installed_privately(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contents = self.fixtures(root)
            downloaded = []

            def download(url, timeout):
                name = url.rsplit("/", 1)[-1]
                downloaded.append(name)
                return io.BytesIO(contents[name])

            destination = root / "installed"
            with (
                patch.object(install_security_tools, "ROOT", root),
                patch.object(
                    install_security_tools.platform, "system", return_value="Linux"
                ),
                patch.object(
                    install_security_tools.platform, "machine", return_value="x86_64"
                ),
                patch.object(
                    install_security_tools.urllib.request,
                    "urlopen",
                    side_effect=download,
                ),
            ):
                install_security_tools.install(destination)
            self.assertEqual(set(downloaded), set(contents))
            self.assertEqual(
                (destination / "opengrep").read_bytes(), contents["opengrep"]
            )
            self.assertEqual((destination / "gitleaks").read_bytes(), b"secret engine")
            for path in [destination, *destination.iterdir()]:
                self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_checksum_failure_never_installs_the_unverified_engine(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixtures(root)
            destination = root / "installed"
            with (
                patch.object(install_security_tools, "ROOT", root),
                patch.object(
                    install_security_tools.platform, "system", return_value="Linux"
                ),
                patch.object(
                    install_security_tools.platform, "machine", return_value="x86_64"
                ),
                patch.object(
                    install_security_tools.urllib.request,
                    "urlopen",
                    return_value=io.BytesIO(b"modified download"),
                ),
                self.assertRaisesRegex(ValueError, "checksum mismatch"),
            ):
                install_security_tools.install(destination)
            self.assertEqual(list(destination.iterdir()), [])

    def test_oversized_verified_download_is_rejected_before_installing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            contents = self.fixtures(root)
            destination = root / "installed"
            with (
                patch.object(install_security_tools, "ROOT", root),
                patch.object(install_security_tools, "MAX_DOWNLOAD_BYTES", 4),
                patch.object(
                    install_security_tools.platform, "system", return_value="Linux"
                ),
                patch.object(
                    install_security_tools.platform, "machine", return_value="x86_64"
                ),
                patch.object(
                    install_security_tools.urllib.request,
                    "urlopen",
                    return_value=io.BytesIO(contents["osv-scanner"]),
                ),
                self.assertRaisesRegex(ValueError, "checksum mismatch"),
            ):
                install_security_tools.install(destination)
            self.assertEqual(list(destination.iterdir()), [])

    def test_existing_destination_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            existing = destination / "opengrep"
            existing.write_bytes(b"existing file")
            with self.assertRaises(FileExistsError):
                install_security_tools.install(destination)
            self.assertEqual(existing.read_bytes(), b"existing file")


if __name__ == "__main__":
    unittest.main()
