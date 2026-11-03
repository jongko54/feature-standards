"""Refuse incomplete release metadata and bundle corruption before publication."""

import hashlib
import http.client
import http.server
import sys
import tempfile
import threading
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from check_maven_release import (
    UploadTrap,
    coordinates,
    fixture_environment,
    inspect_bundle,
    overlay,
    q,
)

SOURCE = ROOT / "implementations/java-spring"
EXPECTED = ("io.github.jongko54", "java-spring-auth", "1.0.0")


class MavenReleaseTests(unittest.TestCase):
    def test_upload_trap_counts_head_and_post_without_printing_request_data(self):
        UploadTrap.requests = 0
        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), UploadTrap) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                for method in ("HEAD", "POST"):
                    connection = http.client.HTTPConnection(
                        "127.0.0.1", server.server_port, timeout=2
                    )
                    try:
                        connection.request(method, "/forbidden")
                        response = connection.getresponse()
                        self.assertEqual(response.status, 403)
                        response.read()
                    finally:
                        connection.close()
            finally:
                server.shutdown()
                thread.join(timeout=2)
        self.assertEqual(UploadTrap.requests, 2)

    def test_fixture_does_not_inherit_maven_rc_credentials_or_signer_overrides(self):
        work = Path("/fixture/work")
        inherited = {
            "HOME": "/existing-home",
            "PATH": "/tools",
            "JAVA_HOME": "/jdk",
            "MAVEN_USER_HOME": "/existing-maven-cache",
            "MAVEN_OPTS": "-Dunexpected=true",
            "MAVEN_ARGS": "--settings real-settings.xml",
            "MAVEN_SKIP_RC": "",
            "MVNW_PASSWORD": "synthetic-test-secret",
            "GPG_PASSPHRASE": "synthetic-test-secret",
            "OPENAI_API_KEY": "synthetic-test-secret",
            "JAVA_TOOL_OPTIONS": "-Dunexpected=true",
        }
        env = fixture_environment(work, inherited)
        self.assertEqual(env["HOME"], inherited["HOME"])
        self.assertEqual(env["MAVEN_USER_HOME"], str(work / "maven-user"))
        self.assertEqual(env["MAVEN_SKIP_RC"], "true")
        self.assertEqual(env["GNUPGHOME"], str(work / "gpg"))
        for key in (
            "MAVEN_OPTS",
            "MAVEN_ARGS",
            "MVNW_PASSWORD",
            "GPG_PASSPHRASE",
            "OPENAI_API_KEY",
            "JAVA_TOOL_OPTIONS",
        ):
            self.assertNotIn(key, env)

    def test_current_pom_has_required_publication_metadata(self):
        self.assertEqual(coordinates(ET.parse(SOURCE / "pom.xml").getroot()), EXPECTED)

    def test_overlay_enforces_no_upload_and_isolated_source_build(self):
        original = (SOURCE / "pom.xml").read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            pom = ET.fromstring(
                overlay(SOURCE, work, "http://127.0.0.1:12345/forbidden", "/test/gpg")
            )
            plugins = pom.findall(
                q("profiles")
                + "/"
                + q("profile")
                + "/"
                + q("build")
                + "/"
                + q("plugins")
                + "/"
                + q("plugin")
            )
            central = next(
                plugin
                for plugin in plugins
                if plugin.findtext(q("artifactId")) == "central-publishing-maven-plugin"
            )
            config = central.find(q("configuration"))
            self.assertEqual(config.findtext(q("skipUpload")), "true")
            self.assertEqual(config.findtext(q("ignorePublishedComponents")), "false")
            self.assertEqual(
                config.findtext(q("centralBaseUrl")), "http://127.0.0.1:12345/forbidden"
            )
            self.assertEqual(
                pom.find(q("build")).findtext(q("sourceDirectory")),
                str(SOURCE / "src/main/java"),
            )
        self.assertEqual((SOURCE / "pom.xml").read_bytes(), original)

    def test_rejects_a_public_central_endpoint_in_fixture(self):
        with self.assertRaisesRegex(ValueError, "loopback-trap-required"):
            overlay(SOURCE, Path("/tmp/fixture"), "https://central.sonatype.com", "gpg")

    def test_overlay_replaces_signer_and_publisher_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            pom = ET.parse(SOURCE / "pom.xml").getroot()
            plugins = pom.findall(
                q("profiles")
                + "/"
                + q("profile")
                + "/"
                + q("build")
                + "/"
                + q("plugins")
                + "/"
                + q("plugin")
            )
            for plugin in plugins:
                config = plugin.find(q("configuration"))
                if config is None:
                    config = ET.SubElement(plugin, q("configuration"))
                ET.SubElement(config, q("keyFilePath")).text = "/unused/private.key"
                ET.SubElement(config, q("skipUpload")).text = "false"
            ET.ElementTree(pom).write(source / "pom.xml")
            result = overlay(
                source, source / "work", "http://127.0.0.1:12345/forbidden", "gpg"
            )
            self.assertNotIn(b"/unused/private.key", result)
            self.assertNotIn(b"<skipUpload>false</skipUpload>", result)

    def test_requires_the_verified_bundle_only_plugin_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            pom = ET.parse(SOURCE / "pom.xml").getroot()
            for plugin in pom.iter(q("plugin")):
                if (
                    plugin.findtext(q("artifactId"))
                    == "central-publishing-maven-plugin"
                ):
                    plugin.find(q("version")).text = "0.11.0"
            ET.ElementTree(pom).write(source / "pom.xml")
            with self.assertRaisesRegex(
                ValueError, "verified-central-plugin-version-required"
            ):
                overlay(
                    source, source / "work", "http://127.0.0.1:12345/forbidden", "gpg"
                )

    def test_rejects_missing_required_metadata_or_snapshot(self):
        pom = ET.parse(SOURCE / "pom.xml").getroot()
        pom.remove(pom.find(q("licenses")))
        with self.assertRaisesRegex(ValueError, "missing-central-pom-metadata"):
            coordinates(pom)
        pom = ET.parse(SOURCE / "pom.xml").getroot()
        pom.find(q("version")).text = "1.0.0-SNAPSHOT"
        with self.assertRaisesRegex(ValueError, "release-version-required"):
            coordinates(pom)

    def test_rejects_missing_signature_before_calling_gpg(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            bundle = work / "bundle.zip"
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr(
                    "io/github/jongko54/java-spring-auth/1.0.0/java-spring-auth-1.0.0.pom",
                    b"pom",
                )
            with self.assertRaisesRegex(ValueError, "missing-artifact-or-signature"):
                inspect_bundle(bundle, EXPECTED, work / "gpg", "unavailable-gpg", {})

    def test_rejects_unexpected_unsigned_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            bundle = work / "bundle.zip"
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr(
                    "io/github/jongko54/java-spring-auth/1.0.0/unexpected.jar", b"jar"
                )
            with self.assertRaisesRegex(ValueError, "unexpected-bundle-artifact"):
                inspect_bundle(bundle, EXPECTED, work / "gpg", "unavailable-gpg", {})

    def test_rejects_checksum_corruption_before_calling_gpg(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            bundle = work / "bundle.zip"
            name = (
                "io/github/jongko54/java-spring-auth/1.0.0/java-spring-auth-1.0.0.pom"
            )
            with zipfile.ZipFile(bundle, "w") as archive:
                archive.writestr(name, b"pom")
                archive.writestr(name + ".asc", b"signature")
                for algorithm in ("md5", "sha1", "sha256", "sha512"):
                    value = (
                        "bad"
                        if algorithm == "sha1"
                        else hashlib.new(algorithm, b"pom").hexdigest()
                    )
                    archive.writestr(name + "." + algorithm, value)
            with self.assertRaisesRegex(ValueError, "invalid-bundle-checksum"):
                inspect_bundle(bundle, EXPECTED, work / "gpg", "unavailable-gpg", {})
