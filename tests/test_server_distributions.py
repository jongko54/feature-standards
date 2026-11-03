"""Reject wrong identities or non-library artifacts before consumer checks."""

import io
import os
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_server_distributions import (
    archive_members,
    check_distributions,
    fixture_environment,
    inspect_library_jar,
    inspect_wheel,
)


class DistributionArtifactTests(unittest.TestCase):
    def test_wheel_with_a_different_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "auth.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "feature_standards_python_auth-9.9.9.dist-info/METADATA",
                    "Name: feature-standards-python-auth\nVersion: 9.9.9\n",
                )
                archive.writestr("feature_auth/__init__.py", "")
            with self.assertRaisesRegex(ValueError, "wheel-identity-mismatch"):
                inspect_wheel(wheel, ("feature-standards-python-auth", "0.2.0"))

    def test_wheel_requires_public_package_and_matches_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "auth.whl"
            for include_api in (False, True):
                with zipfile.ZipFile(wheel, "w") as archive:
                    archive.writestr(
                        "feature_standards_python_auth-0.2.0.dist-info/METADATA",
                        "Name: feature-standards-python-auth\nVersion: 0.2.0\n",
                    )
                    if include_api:
                        archive.writestr("feature_auth/__init__.py", "")
                if include_api:
                    result = inspect_wheel(
                        wheel, ("feature-standards-python-auth", "0.2.0")
                    )
                    self.assertEqual(result["version"], "0.2.0")
                    self.assertRegex(result["sha256"], "^[0-9a-f]{64}$")
                else:
                    with self.assertRaisesRegex(
                        ValueError, "wheel-public-package-missing"
                    ):
                        inspect_wheel(wheel, ("feature-standards-python-auth", "0.2.0"))

    def test_executable_or_reference_application_jar_cannot_pass_as_library(self):
        with tempfile.TemporaryDirectory() as directory:
            jar = Path(directory) / "auth.jar"
            for bad in (
                "BOOT-INF/classes/example.class",
                "application.properties",
                "dev/featurestandards/auth/AuthApplication.class",
            ):
                with self.subTest(bad=bad), zipfile.ZipFile(jar, "w") as archive:
                    archive.writestr(
                        "dev/featurestandards/auth/AuthService.class", b"fixture"
                    )
                    archive.writestr(bad, b"fixture")
                with self.assertRaises(ValueError):
                    inspect_library_jar(jar)
            with zipfile.ZipFile(jar, "w") as archive:
                archive.writestr(
                    "dev/featurestandards/auth/AuthService.class", b"fixture"
                )
            self.assertTrue(inspect_library_jar(jar)["plainLibraryJar"])

    def test_archive_extraction_refuses_escape_paths_links_and_wrong_crate_prefix(self):
        for name, kind in (
            ("../escape", tarfile.REGTYPE),
            ("/absolute", tarfile.REGTYPE),
            ("auth-0.1.0/link", tarfile.SYMTYPE),
            ("wrong-0.1.0/Cargo.toml", tarfile.REGTYPE),
        ):
            with self.subTest(name=name):
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode="w") as archive:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    archive.addfile(member)
                stream.seek(0)
                with (
                    tarfile.open(fileobj=stream, mode="r:") as archive,
                    self.assertRaisesRegex(ValueError, "unsafe-archive-member"),
                ):
                    archive_members(archive, "auth-0.1.0")

    def test_duplicate_archive_members_are_rejected(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as archive:
            archive.addfile(tarfile.TarInfo("auth-0.1.0/Cargo.toml"))
            archive.addfile(tarfile.TarInfo("auth-0.1.0/Cargo.toml"))
        stream.seek(0)
        with (
            tarfile.open(fileobj=stream, mode="r:") as archive,
            self.assertRaisesRegex(ValueError, "duplicate-archive-path"),
        ):
            archive_members(archive, "auth-0.1.0")

    def test_fixture_environment_does_not_inherit_runtime_or_publish_credentials(self):
        with patch.dict(
            os.environ,
            {
                "AUTH_DATABASE_URL": "synthetic",
                "PGPASSWORD": "synthetic",
                "SMTP_PASSWORD": "synthetic",
                "TWINE_PASSWORD": "synthetic",
                "CARGO_REGISTRY_TOKEN": "synthetic",
                "HOME": "/existing-user-home",
            },
            clear=True,
        ):
            environment = fixture_environment(Path("/private/fixture"))
        self.assertEqual(environment["HOME"], "/existing-user-home")
        self.assertEqual(environment["MAVEN_SKIP_RC"], "true")
        self.assertFalse(
            any(
                key.startswith(("AUTH_", "PG", "SMTP_", "TWINE_"))
                for key in environment
            )
        )
        self.assertNotIn("CARGO_REGISTRY_TOKEN", environment)

    def test_invalid_stack_is_rejected_before_invoking_any_build(self):
        for stacks in ([], ["unsupported"]):
            with self.assertRaisesRegex(ValueError, "unsupported-stack"):
                check_distributions(Path("/does-not-exist"), stacks)
